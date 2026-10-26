# 前导零计数 CLZ / LZD（Count / Detect Leading Zeros）

- **类别**：优先级与编码
- **一句话**：从最高位往下数有几个 0 —— 可以当成 MSB 优先的优先编码器来做，
  但有一个更好的**递归合并树**（LZD）；浮点加法里还有个更狠的做法：
  在加法算完之前就把它预测出来（LZA）。
- **典型用途**：浮点加法/减法的规格化移位量、定点归一化、
  `floor(log2 x)`、除法的商位对齐、稀疏数据的游程处理。

## 结构

约定：`CLZ(x)` = 从 bit N-1 往下的连续 0 的个数。`x == 0` 是特例（见坑）。
`CTZ`（trailing zeros）= 把位序倒过来的同一个问题，或者
`popcount((x & -x) - 1)`（popcount 即 n 个 1 位数求和，见 [`../arith/csa-accumulation.md`](../arith/csa-accumulation.md)）。

### 写法 A：优先编码器 + 减法

`idx = ` MSB 优先的 first-one 下标（见
[`find-first-one.md`](find-first-one.md)），then `CLZ = N-1-idx`。
因为 N-1 是常数，那个"减法"其实是**按位取反**（当 N 是 2 的幂时
`N-1-idx == ~idx`），一分钱不花。

所以写法 A 的真实成本 = 一个 MSB 优先的前缀 OR 网络 + 一棵编码树。**够用**。

### 写法 B：递归合并的 LZD 树（Oklobdzija 结构）

把问题定义成"返回 (valid, count)"，然后自底向上两两合并。
2 位的叶子单元：

```
x = 00 -> (v=0, c=x)   // 全零，count 无意义
x = 01 -> (v=1, c=1)
x = 1_ -> (v=1, c=0)
```

合并两个各产生 w 位 count 的半边（hi 在高位）：

```
v = v_hi | v_lo
c = v_hi ? {1'b0, c_hi} : {1'b1, c_lo}
```

读法：**如果高半边有 1，答案就在高半边、最高位补 0；否则跳过整个高半边
（这正好是 count 的最高位置 1），答案在低半边。** 每合并一级，count 宽一位。

- 级数：log2(N)，每级一个 2:1 mux + 一个 OR。
- 面积：第 k 级有 N/2^k 个单元、每个 mux 宽 k 位，总和 Σ (N/2^k)·k = **O(N)**。
  不是 O(N log N) —— 因为 mux 变宽的同时单元数在减半。

这个结构比写法 A **更规整**：没有全局扇出很大的前缀节点，
每一级都是纯局部的两两合并，连线是标准的二叉树。

### 写法 D：进位先行式（Dimitrakopoulos 等 2008）

记 s^0 = x，s^k 是把 s^{k-1} 相邻两位相或得到的半长串（二叉 OR 树的第 k 层）。
论文证明：**count 的第 k 位 = 「s^k 的前导零个数为奇数」**，而「为偶数」正好是一条
进位先行方程 —— 两位一组，g = 高位、p = ~低位，E = G(最高组 ∘ … ∘ 最低组)。
于是每一位 count 用一棵**独立的进位合并树**并行算出，扇出 <= 2。

- 直接版：每棵树各自维护 (G, P)。论文 64 位最小延时比写法 B 低 4%，同延时能量低 10–49%。
- **共享传播版**：组的 P 就是「这组全零」= OR 树上现成的节点，各棵树只算 G。
  门数最少（是写法 B 的化简），共享节点扇出大所以稍慢。

另有两种常见写法，本仓实测过（见「本地实测」）：**4 位分组并行 + 选择**
（Milenković 等 2015：组内 count 先算好，高位出来后只剩一级选择）；
**逐次折半**（Bruguera & Lang：count 从高位逐位定，高位先出，适合直接喂给规格化
移位器的粗移位级）。

### 写法 C：LZA（前导零预测，浮点专用）

浮点加减的关键路径是 `加法 → CLZ → 规格化移位`，三段串行。LZA
的思路是：**从两个操作数直接估算前导零数，与加法并行进行**，
把 CLZ 从关键路径上摘掉。

代价：估算值可能差 1（因为进位的影响没完全建模），
所以后面要跟一级"错 1 修正"（一位移位 + 指数 ±1）。
面积换关键路径的典型案例，**只在浮点加法器里值得**。

## 关键路径

- 写法 A：前缀 OR **O(log N)** + 编码树 **O(log N)**。
- 写法 B：**O(log N)** 级，每级只有 1 个 mux + 1 个 OR，**常数比 A 小**。
- 写法 C：与加法器并行，对整条路径的贡献 ≈ 0，代价是多一级修正移位。
- CTZ 若用 `popcount((x&-x)-1)`：一条进位链 + 一棵压缩树，
  **比直接倒位序做 LZD 贵**，不要这么写硬件（那是软件写法）。

## PPA 权衡

- A 和 B 渐进同阶，但**常数差得远**：Dimitrakopoulos 2008 在静态 CMOS 下实测写法 A 的最小延时约是 B / D 的两倍（本仓实测 64 位差 4.6 倍，见「本地实测」）；B 结构更规整、fanout 更均匀；
  A 的好处是**如果你本来就需要 one-hot 或 idx**（比如同时要做仲裁），
  那 CLZ 是白送的。**先看还需要什么，再选。**
- LZA 是纯粹的"面积 + 复杂度换关键路径"，而且它只对浮点加法有意义 ——
  别的场合没有那个"和加法并行"的窗口可占。
- 位宽 ≤ 16 时综合工具做得不差，手写收益小；32/64 位才值得上 LZD 树。

## 什么时候选它 / 什么时候别用

- **浮点加减的规格化** → LZD 树；关键路径卡死了再上 LZA。
- **只要 `floor(log2 x)`（取整的对数）** → `N-1-CLZ(x)`，就是同一个电路。
- **只要"最高位是不是 1"** → 别用 CLZ，直接看那一位。
- **同时还要仲裁/one-hot** → 用写法 A，复用优先编码器。
- **数的是末尾零（CTZ）** → 倒位序 + 同一棵树，不要走 popcount。

## 实现要点与坑

- **`x == 0` 必须定义。** 数学上 CLZ(0) = N，但 count 只有 log2(N) 位，
  **装不下 N**。三种常见处理：
  (a) 输出 `valid`，count 在无效时是 don't care（推荐，也是 LZD 树的天然输出）；
  (b) count 加一位；
  (c) 饱和成 N-1（会和"最低位是 1"的合法输入撞车，**不要用**）。
  这是这张卡最容易翻车的地方，也是必测点。
- **要比较写法 A/B 就必须保层级（`params.yaml` 的 `keep_hierarchy:`）。** 两者功能完全等价，
  不设边界的话 ABC 的 `&dch` 会把它们收敛成同一个网表
  （`docs/pitfalls.md` 的 P-3）。
- **LZD 树写成递归 generate 时，count 位宽要跟着级数长**，
  用 `$clog2` 算错一位就会在某个位宽上悄悄截断。写参数化时对
  N = 8/16/32/64 全部跑一遍 elaborate（`./scripts/fast_check.sh` 就是干这个的）。
- **LZA 的"错 1"修正不能省。** 它不是精度问题，是正确性问题：
  漏掉修正的浮点加法器会在特定操作数下给出未规格化的结果。
  实现 LZA 必须配一组针对性激励（接近相消的减法）。
- **别拿 CLZ 当"位宽压缩"用而忘了它是纯组合的。** 64 位 LZD 是
  6 级 mux，接在一个已经很长的路径后面很容易变成关键路径。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module LZD #(
    parameter DAT_W  = 32,
    parameter SCHEME = 1        // 0 OKLOBDZIJA | 1 CLA | 2 CLA_SHARED | 3 NIBBLE | 4 HALVING | 5 PRIENC | 6 TOOL
)(
    input  [DAT_W-1:0]           i_dat,
    output [$clog2(DAT_W)-1:0]   o_cnt,
    output                       o_zero  // i_dat == 0
);
    localparam SCHEME_OKLOBDZIJA = 0;
    localparam SCHEME_CLA        = 1;
    localparam SCHEME_CLA_SHARED = 2;
    localparam SCHEME_NIBBLE     = 3;
    localparam SCHEME_HALVING    = 4;
    localparam SCHEME_PRIENC     = 5;
    localparam SCHEME_TOOL       = 6;
```

`o_zero` 放在接口里而不是把 `o_cnt` 加宽，是有意的选择：
它把"全零"这个特例逼到调用方面前，而不是藏在一个宽出来的位里。
叫 `o_zero`（全零时为 1）而不是 `o_vld`：`vld` 只用于握手语义。
本仓曾按这个接口实现 `cbb/lzd/`（2026-10-02 已删，只留单文件的 `CBB_LZD`，见 `cbb/cbb_lzd/`）。

## 出处

- Oklobdzija, V.G., "An algorithmic and novel design of a leading zero detector
  circuit: comparison with logic synthesis," *IEEE Transactions on VLSI Systems*,
  vol. 2, no. 1, pp. 124–128, 1994 —— 写法 B 的合并树出处。
- Ercegovac, M.D. & Lang, T., *Digital Arithmetic*, Morgan Kaufmann, 2004 ——
  规格化、LZD/LZA 在浮点加法器中的位置。
- Schmookler, M.S. & Nowka, K.J., "Leading zero anticipation and detection —
  a comparison of methods," *IEEE Symposium on Computer Arithmetic (ARITH-15)*,
  2001 —— LZA 各种方法的对比。**未逐行核实，引用前自行确认。**
- Dimitrakopoulos, G., Galanopoulos, K., Mavrokefalidis, C. & Nikolos, D.,
  "Low-Power Leading-Zero Counting and Anticipation Logic for High-Speed Floating
  Point Units," *IEEE Transactions on VLSI Systems*, vol. 16, no. 7, pp. 837–850, 2008
  —— 写法 D 的推导、各结构在 130 nm 下的能量-延时对比。**已读原文**
  （作者主页 PDF，2026-09-27）。
- Milenković, N.Z., Stanković, V.V. & Milić, M.Lj., "Modular Design Of Fast Leading
  Zeros Counting Circuit," *Journal of Electrical Engineering*, vol. 66, no. 1, 2015
  —— 4 位分组结构。**只核到摘要，原文未取到**，卷期与门级细节引用前自行确认。

## 本地实测

`cbb/lzd`（本仓第一个 cbb 构件，内部#62）（该设计根 2026-10-02 已删，源码按记录的 `git_commit` 取，见 `docs/data-credibility.md` 的 D-29）：七种结构 × 位宽 8/16/32/64 共 28 个组合（下面引用的这批记录里位宽键还叫 `WIDTH`，2026-09-28 起改名 `DAT_W`、全零标志改为 `o_zero`，读法见 `docs/data-credibility.md` 的 D-26），
flow 指纹 `211a545d`、`git_commit 476a974`，报告见该提交下的 `cbb/lzd/REPORT.LZD.md`。
`SCHEME` 与本卡的对应：`PRIENC` = 写法 A，`OKLOBDZIJA` = 写法 B，`CLA` / `CLA_SHARED` =
写法 D 的两个版本，`NIBBLE` / `HALVING` = 写法 D 之后提到的两种，`TOOL` = 行为级对照。
64 位代表记录：`LZD-CLA-64-6c17f75f`、`LZD-OKLOBDZIJA-64-3c9fa395`、`LZD-TOOL-64-65c1eab4`、
`LZD-CLA_SHARED-64-9448d078`、`LZD-PRIENC-64-0bfd9da2`；其余按 `params` 检索。

关键路径延时（ps，TT）与它对位宽的 log-log 斜率：

| SCHEME | 8 | 16 | 32 | 64 | 斜率 | 64 位面积 µm² |
|---|---|---|---|---|---|---|
| `CLA` | 75 | **97** | **123** | **143** | **0.31** | 16.6 |
| `OKLOBDZIJA` | 79 | 110 | 144 | 189 | 0.42 | 18.4 |
| `CLA_SHARED` | 84 | 135 | 228 | 264 | 0.55 | 11.3 |
| `NIBBLE` | 77 | 156 | 238 | 398 | 0.79 | 11.3 |
| `HALVING` | 142 | 284 | 609 | 700 | 0.77 | 11.6 |
| `PRIENC` | 143 | 289 | 568 | 873 | 0.87 | 15.3 |
| `TOOL` | **51** | 103 | 190 | 389 | 0.97 | **9.0** |

四个结论：

1. **「<= 16 位交给工具、32/64 位才值得手写」被证实，分界很清楚。** `TOOL` 在 8 位
   最快（51 ps，比最好的手写快 32%），16 位与 `CLA` 打平，32 位起落后（190 vs 123），
   64 位慢到 2.7 倍 —— 延时斜率 0.97，**工具把 for 循环综合成了近似线性的链**。
   各档的面积-延时 Pareto 前沿：8 位 {`NIBBLE`, `TOOL`}，16 / 32 位 {`CLA`, `TOOL`}，
   64 位 {`CLA`, `CLA_SHARED`, `TOOL`}。
2. **时序首选写法 D 的直接版（`CLA`）**：16 位起每档都最快，斜率 0.31 最接近 log。
   64 位比写法 B 快 **24%**，远大于论文的 4%。差异来源未查清：可能是本仓的门尺寸
   只由 ABC 做，也可能是保层级的节点粒度对两种结构的惩罚不同。**先当作「方向对、
   幅度存疑」。**
3. **写法 A（`PRIENC`）与逐次折半在静态标准单元下是反例**：64 位分别是 `CLA` 的
   6.1 倍与 4.9 倍；论文给的是约 2 倍，方向一致、幅度更大。`PRIENC` 比写法 B
   又慢又大，没有任何一档进 Pareto 前沿。
4. **面积**：手写结构里 `CLA_SHARED` / `NIBBLE` / `HALVING` 在 64 位同为约 11.3 µm²，
   比 `CLA` 小 32%；`CLA_SHARED` 用这 32% 换来了 85% 的延时（论文说「稍慢」，本仓慢得多）。
   `TOOL` 每档面积都最小 —— 但这里有方法上的偏置：手写结构保住了节点层级，每个
   节点边界都挡住了跨节点的复合门合并，`TOOL` 只保外壳、没有这份代价。

⚠️ **动态功耗暂不下结论。** 活动率只反标到端口，内部节点靠概率传播，没有毛刺
（内部#65）。本批 64 位里 `PRIENC` 的动态功耗最低（5.1 µW，`CLA` 10.2 µW），与文献方向
相反，很可能是传播模型造成的。`HALVING` 的「count 高位先出」在记录里也看不到
（记录只有最差路径）。

⚠️ 测量边界同全库：无 LEF / 无布局布线 / 连线代价为零；`fmax` 是 setup-only、
单角 TT 的理想值，用于横向比结构。
