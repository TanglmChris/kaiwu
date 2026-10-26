# round-robin 仲裁（Round-Robin Arbiter）

- **类别**：优先级与编码
- **一句话**：把"固定优先级的起点"每次轮转一格 —— 经典实现是
  **掩码 + 两棵固定优先级树 + 一个 mux**，按结构数面积上界约是固定优先级仲裁的两倍（实际多少要量）。
- **典型用途**：多主设备总线、NoC 路由器的输出端口分配、
  多队列调度（VOQ）、cache bank 争用、
  任何"多个对等请求者争带宽且不能饿死"的地方。

## 结构

### 写法 A：掩码 + 双优先级树（**经典实现，首选**）

```verilog
wire [N-1:0] masked_req = req & mask;              // mask: 上次 grant 之后的那些位
wire [N-1:0] g_hi = fixed_prio(masked_req);        // 从指针往后找
wire [N-1:0] g_lo = fixed_prio(req);               // 绕回队头再找
wire         wrap = ~|masked_req;
wire [N-1:0] grant = wrap ? g_lo : g_hi;
```

读法：**先从上次服务过的下一个位置往后找；找不到就绕回 0 再找一遍。**
两棵树可以**并行**算，所以延时只比固定优先级多一级 mux。

掩码更新（严格高于本次 grant 的位全置 1）：

```verilog
always @(posedge clk or negedge rst_n)
    if (!rst_n)              mask <= {N{1'b1}};
    else if (|grant)         mask <= ~((grant << 1) - 1'b1);
```

`(grant << 1) - 1` 把"grant 位及以下"全变成 1，取反就得到"严格更高的位"。
**这个 `-1` 是一条进位链**；N 小的时候无所谓，N 大可以改用
thermometer 的写法（见
[`onehot-binary-thermometer.md`](onehot-binary-thermometer.md)：
one-hot → thermometer 就是一次前缀 OR）。

### 写法 B：旋转—仲裁—转回

```
rot_req  = rotate(req, ptr)
rot_gr   = fixed_prio(rot_req)
grant    = rotate_back(rot_gr, ptr)
```

概念上最干净，但要**两个桶形移位器**。查
[`barrel-shifter.md`](barrel-shifter.md)：一个 N 位旋转器是 N·log₂N 个 mux，
两个就是 2N·log₂N，而写法 A 的两棵优先级树只有 O(N)。
**所以写法 B 一般更贵** —— 除非数据通路上本来就有个桶形移位器可以复用。

### 写法 C：矩阵仲裁器（matrix arbiter，最近最少服务）

维护一个 N×N 的优先级位矩阵 `pri[i][j]` = "i 的优先级高于 j"。
授权给"没有任何人优先于它"的请求者，然后把被服务者那一行清零、那一列置一
（它变成最低优先级）。

- 面积 **O(N²)** 的触发器 —— N=4/8 完全可以接受，N=32 不行。
- **公平性比 round-robin 更强**：它实现的是"最近最少服务"（LRS），
  而 round-robin 只是固定轮转。
- 延时：一级 AND-OR，**比双树更浅**。

**小 N（≤8）而且卡时序时，矩阵仲裁器是被低估的选项。**

## 关键路径

- 写法 A：`固定优先级树 O(log N)` + `1 级 mux`。
  两棵树并行，所以**不是 2×**。
- 写法 B：`旋转 O(log N)` + `树 O(log N)` + `转回 O(log N)` = 三段串行，
  **常数是 A 的三倍左右**。
- 写法 C：**O(1) 逻辑级**（一行 AND 归约），代价是 O(N²) 面积。
- **掩码更新在关键路径上。** 下一拍的掩码由本拍的 grant 算出来，
  所以「`mask` 寄存器 → `req & mask` → 树 → mux → grant → `~((grant<<1)-1)` → `mask` 寄存器」
  是一条寄存器到寄存器的状态环，一拍内要走完。输入、输出都打拍的设计里，最长路径一般就是它，
  上面三段只是它的前半截（2026-10-25 内部#421 改正：原文说掩码更新「不在关键路径上」，不对）。
  所以写法 A 那条 `-1` 进位链在 N 大时值得换成 thermometer 写法；停顿保持的授权寄存器也在同一个环上。

## PPA 权衡

- **相对固定优先级的增量**：+1 棵优先级树、+N 个掩码触发器、+1 级 mux。
  这是按结构数出来的上界：面积不超过约 **2 倍**，`req → grant` 的组合段 **+1 级**。
  综合后两棵树可能共享部分逻辑，面积未必到 2 倍；而延时要看的是上一节的状态环，
  它比 `req → grant` 多了掩码更新那一段。两个数都以记录为准。
  这个"公平性的价钱"是本类最值得实测的一组数。
- A vs B：写法 B 的面积随 N 增长得快得多（N·log N 项 ×2）。
  **只有在能复用已有移位器时才考虑 B。**
- C 在 N ≤ 8 时面积可能反而不比 A 大多少（N²=64 个触发器 vs
  两棵树 + N 个触发器），而延时更好。**N 是这里唯一的决定变量。**
- 功耗：掩码寄存器每次 grant 都翻转，但只有 N 位，可以忽略；
  真正的功耗在下游那个被 grant 选中的宽数据 mux 上。

## 什么时候选它 / 什么时候别用

- **对等请求者争带宽** → 就是这张卡。
- **优先级有真实语义差别**（中断、异常、刷新）→ 用
  [`fixed-priority-arbiter.md`](fixed-priority-arbiter.md)，
  轮转在这里是**错的**，不是"更公平"。
- **N ≤ 8 且时序紧** → 先算算矩阵仲裁器（写法 C）。
- **需要加权**（有的请求者该拿更多带宽）→ round-robin 给不了，
  要 WRR / deficit round-robin，那是把"轮转"换成"配额"，
  逻辑上是个计数器问题而不是优先级问题。
- **需要严格的延迟上界** → round-robin 给的上界是 N-1 拍**当且仅当
  每次 grant 都被接受**；有 ready 反压时这个界不成立，要单独论证。
- **只有 2 个请求者** → 一个触发器做乒乓，别铺这套逻辑。

## 实现要点与坑

- **掩码必须是严格高于本次 grant（`~((grant<<1)-1)`），写成含自己（`~(grant-1)`）就不是轮转了。**
  含自己时 `masked_req` 里总有被授权者本身，只要它还在请求就一直赢，
  全员持续请求时授权序列是 `0,0,0,…`，其他人饿死 —— 是「粘住直到撤请求」，不是「能连赢」。
  严格掩码本来就不会让唯一的请求者空转：别人都不请求时 `masked_req` 为空、走绕回分支，
  它每拍都赢。所以「含不含自己」不是一个可选的语义，`~(grant-1)` 就是这张卡最常见的 off-by-one。
  （2026-10-25 内部#421 改正：原文说含自己是「没有别人请求时可以连续拿」的有意选择，不对。）
- **指针推进的时机：应当是 `grant & 被接受`，不是 `grant`。**
  如果被授权者当拍因为下游 `ready` 为低没能发出去，
  指针就不该推进 —— 否则这次 grant 白给，
  而且在持续反压下会退化成"轮流空转"。
  接反压的设计里这条几乎一定要处理，和
  [`../storage-flow/credit-flow-control.md`](../storage-flow/credit-flow-control.md)
  的语义要对齐。
- **只管推进时机还不够：停顿期间授权要保持不变。** 掩码没推进，但 `req` 在停顿时可以变；
  掩码下有更靠前的新请求进来，组合 grant 就会换人。
  例：上拍只有 3 号请求、`ready` 为低，授权 3；这拍 0 号也来了，掩码仍是复位值，授权变成 0 ——
  下游看到 valid 一直为高，选择却变了，违反 valid/ready 握手「valid 拉高后内容不变」的规则。
  做法：`o_any_grant & ~i_rdy` 时把本拍 grant 打一拍存起来，下一拍只要该请求者还在请求就直接输出它。
  接 valid/ready 下游的仲裁器都要这样做（内部#421）。
- **复位后的 mask 应当是全 1**（等价于指针在 0），不是全 0 ——
  全 0 会让第一拍 `masked_req` 恒为空、永远走 wrap 分支，
  功能上还是对的但第一次仲裁的行为和预期不符，测试里很难看出来。
- **两棵树在功能上是"同一个函数的两次调用"，综合工具有动机去合并/重构它们。**
  它们的输入不同（`req` vs `req & mask`）所以不会被直接合并，
  但 `-flatten` + ABC 的 `&dch` 仍然会跨模块重组逻辑，
  把写法 A/B/C 的结构差异抹平。**要比较 SCHEME 就必须在
  `fixed_prio_arb` 和顶层都在 `params.yaml` 的 `keep_hierarchy:` 里声明保层级**
  （`docs/pitfalls.md` 的 P-3）。
- **公平性不是能靠随机激励测出来的。** 要写定向用例：
  (a) 全部请求者持续拉高 → 检查 N 拍内每人恰好一次；
  (b) 只有一个请求者 → 检查它每拍都能拿到（不能因为轮转而空转）；
  (c) 请求者集合动态变化 → 检查不丢不重；
  (d) `ready` 为低时加入更靠前的请求 → 检查授权不换人，`ready` 拉高那拍才推进。
  这四条应当写进设计的 `verify.md`。
- **`$onehot0(grant)` 断言照样要有**，理由同固定优先级。
- **别把 mask 暴露到模块外**。见过的错误用法是外面拿 mask 去做别的判断，
  于是掩码语义（含不含自己）变成了跨模块的隐式契约。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module RR_ARB #(
    parameter REQ_N        = 8,
    parameter SCHEME       = 0         // 0 MASK（双树） | 1 ROTATE（双移位器） | 2 MATRIX
)(
    input                  clk,
    input                  rst_n,
    input  [REQ_N-1:0]     i_req,
    input                  i_rdy,       // 下游接受；没有反压的场合接 1
    output [REQ_N-1:0]     o_grant,     // one-hot
    output                 o_any_grant
);
    localparam SCHEME_MASK   = 0;
    localparam SCHEME_ROTATE = 1;
    localparam SCHEME_MATRIX = 2;
```

语义定死：严格轮转、只在 `o_any_grant & i_rdy` 时推进、停顿期间保持授权（见「实现要点与坑」）。
原来建议的两个语义参数都去掉了（内部#421）：`INCLUSIVE_EN=1` 会饿死别人，不是可选语义；
`USE_RDY_EN=0`（按 grant 推进）和把 `i_rdy` 接 1 逐拍等价，没有单独存在的意义。
扫 PPA 的维度是 `REQ_N` 和 `SCHEME`。

## 出处

- Dally, W.J. & Towles, B., *Principles and Practices of Interconnection
  Networks*, Morgan Kaufmann, 2004 —— Arbitration 一章给出了
  掩码双树、matrix arbiter 和 wavefront allocator 的完整推导，
  是这张卡的主要依据。
- Weste, N. & Harris, D., *CMOS VLSI Design*, 4th ed., Addison-Wesley, 2010 ——
  仲裁器的电路级实现。
- 内部构件见 [`fixed-priority-arbiter.md`](fixed-priority-arbiter.md)、
  [`barrel-shifter.md`](barrel-shifter.md)、
  [`onehot-binary-thermometer.md`](onehot-binary-thermometer.md)。

## 本地实测

暂无。**本类里 PPA 实验价值最高的一张卡**，因为它能回答一个具体的工程问题：

> **公平性到底要花多少面积和多少延时？**

对照组很干净：同一个 N，`fixed_prio_arb` vs `rr_arb(SCHEME=0)`（MASK）
vs `rr_arb(SCHEME=1)`（ROTATE） vs `rr_arb(SCHEME=2)`（MATRIX），
扫 N = 4/8/16/32。预期结论（尚未验证）：

- MASK 的面积 ≈ 2× 固定优先级，延时 +1 级；
- ROTATE 的面积随 N 涨得最快，N=32 时明显劣于 MASK；
- MATRIX 在 N=4/8 时延时最好，N=16 起面积失控。

**但这个设计需要时钟和多拍激励**（掩码是状态），
不像本类其他卡那样纯组合 —— 记录里 `cycles` 的语义、
以及带 `ready` 的握手激励，正是 内部#7 里那条
"仿真驱动要先支持 valid-ready"所指的前提。
`SCHEME=2`（MATRIX）和 `USE_READY=1` 尤其依赖它。
