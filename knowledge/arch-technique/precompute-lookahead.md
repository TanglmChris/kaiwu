# 预计算与前瞻（Precomputation / Speculation / Look-Ahead）

- **类别**：架构范式与技巧
- **一句话**：**两条路都算，最后用晚到的信号选一条** —— 用面积买掉一整段串行依赖；
  look-ahead 是它作用在递归上的形态，能真正压低 iteration bound。
- **典型用途**：carry-select 加法器、浮点加法的双路径（近/远）、
  分支预测与投机执行、CRC 一拍算多位、
  比较-选择-累加（Viterbi 的 ACS）、任何"要等一个晚到的选择信号"的地方。

## 结构

### 预计算（speculation）：把串行依赖变成并行 + mux

原始形态：

```
result = f( g(x), sel )      // 必须先算 g，再等 sel
```

预计算形态：

```
r0 = f( g(x), 0 )   ┐
r1 = f( g(x), 1 )   ┘  并行算
result = sel ? r1 : r0     // sel 只穿过一级 mux
```

**代价 2× 面积，收益是把 `sel` 的到达时间从"路径起点"挪到"路径终点"。**
所以它值不值，完全取决于 `sel` 有多晚 —— 这直接连到
[`late-arriving-signal.md`](late-arriving-signal.md)。

### 本库里现成的例子：carry-select 加法器

每个块用 0 和 1 两个进位入各算一遍和，块间进位到了之后只做一次 mux 选择：

```
进位链的延时从 O(块内延时 × 块数) 变成 O(块内延时 + 块数 × mux)
```

见 [`../arith/prefix-adders.md`](../arith/prefix-adders.md)，
本仓库 `designs/adder32` 的 `CARRY_STRUCT = CSEL` 就是它，**已有实测数据**（见下）。

### 投机的指数墙

对 1 位信号投机 = 2 份硬件；2 位 = 4 份；k 位 = 2^k 份。
**面积指数涨、收益线性降**，所以实践中几乎只投机 1 位、偶尔 2 位。
carry-select 的"分块"正是在控制这个爆炸：不对整条进位链投机，
只对每个块的 1 位进位入投机。**块宽是这个权衡的旋钮。**

### look-ahead：作用在递归上的预计算

对 `y[n] = f(y[n-1], x[n])`，把递归代入自身：

```
y[n] = f( f(y[n-2], x[n-1]), x[n] ) = F( y[n-2], x[n-1], x[n] )
```

如果 `F` 能被化简得比 `f∘f` 浅（线性递归、常数系数、GF(2) 运算时通常能），
那么**一拍处理两个样本，环上的每样本延时减半** ——
这是突破 iteration bound 的正规途径（见
[`retiming.md`](retiming.md)、
[`parallel-unroll-cslow.md`](parallel-unroll-cslow.md)）。

典型实例：

- **carry-lookahead**：进位的递归 `c[i+1] = g[i] | p[i]&c[i]` 展开若干步再化简，
  这就是 CLA 名字的由来 —— **前缀加法器整族都是 look-ahead**。
- **CRC 一拍 N 位**：CRC 是 GF(2) 上的线性递归，展开 N 步后
  化简成一个常数矩阵乘（一堆 XOR 树），所以能一拍吃 8/32/64 位。
- **IIR look-ahead**：把 k 步递归合并，代价是系数变多、精度问题。

**look-ahead 和预计算的关系**：预计算是"两个答案都算"，
look-ahead 是"把两步合并成一步再化简"。**后者更强，但要求递归有可化简的代数结构。**
没有结构可利用时就退化成前者。

### 另一个意思的"预计算"：低功耗预判

先用一个**便宜的**函数判断"这次计算的结果会不会被用到"，
不会用到就把昂贵的模块关掉（不给使能/不给数据）。
这是功耗技巧不是速度技巧，属于
[`operand-isolation-clock-gating.md`](operand-isolation-clock-gating.md)。
**两件事同名，别搞混。**

## 关键路径

- 预计算：`max(两条路径) + 1 级 mux`。**注意是 max，不是"变快了"** ——
  如果两条路本来就都要等 `sel` 之外的输入，预计算一分钱都省不下。
- look-ahead：把每样本的环延时从 `D` 降到 `D_k / k`（`D_k` 是化简后 k 步的延时）。
  化简效果好时接近 `D/k`，不好时可能连 `D` 都不如。
- carry-select 的经典结论：块宽相等时延时 O(√n) 最优（块内 ripple、块间 mux 链），
  **块宽递增**（后面的块更宽，因为它们的进位到得更晚）还能再好一点。

## PPA 权衡

- 预计算的面积代价是**成倍**的，不是百分比级的。
  本仓库实测 carry-select 相对 ripple 是 **2.6× 面积换 2.2× 延时**（见下）。
  **接近 1:1 的兑换比** —— 值不值要看你是 area-limited 还是 timing-limited。
- 功耗：两条路都在翻转，**动态功耗涨得比面积还快**（多算的那一路是纯浪费）。
  ⚠️ 本仓库测不了（`docs/data-credibility.md` D-1）。这是预计算最大的隐性成本，
  **也是本仓库目前完全看不到的那一面** —— 只看面积和延时会让预计算显得比实际好。
- look-ahead 的面积代价取决于化简效果，**可能很小**（CRC 展开后还是一堆 XOR），
  也可能爆炸（IIR 展开后系数位宽暴涨）。没有通用答案。

## 什么时候选它 / 什么时候别用

- **有一个明确的、晚到的选择信号** → 预计算。先确认它真的晚，
  见 [`late-arriving-signal.md`](late-arriving-signal.md)。
- **递归有代数结构可化简**（线性、GF(2)、常系数）→ look-ahead，
  收益远大于预计算。
- **选择信号和数据一样早到** → **别用**，纯亏 2× 面积。
- **要投机的位数 ≥ 3** → 面积 8×，几乎一定不划算，换思路。
- **功耗敏感** → 预计算是**反功耗**的（多算的那份全是浪费），
  慎用；或者配上操作数隔离让没选中的那路不翻转 ——
  但那又会把延时收益吃掉一部分。
- **被 iteration bound 卡住** → look-ahead 是唯一不需要多路数据的出路
  （C-slow 需要多路独立数据）。

## 实现要点与坑

- **"两条路都算"很容易被综合工具合并回去。** `r0` 和 `r1` 共享
  `g(x)` 这个子表达式，ABC 会做公共子表达式提取 ——
  这是**对的**（那部分本来就该共享）。但如果工具进一步把
  `sel ? f(g,1) : f(g,0)` 重新推导回 `f(g, sel)`，
  投机结构就白写了。**这正是本仓库踩过的坑**：`&dch` 会从布尔功能
  重新推导电路，把 ripple / CLA / carry-select 收敛成同一个映射结果。
  **必须保层级（`params.yaml` 的 `keep_hierarchy:`）且不 `-flatten`**（`docs/pitfalls.md` 的 P-3）。
  本仓库的 `carry_select_adder.v` 已经这么做了。
- **投机的两路必须真正功能等价于原式。** 边界条件（溢出、饱和、
  符号扩展）在 `sel=0` 和 `sel=1` 两路里容易写得不一致，
  而随机激励只会走到常见的那一路。**两路各自定向测。**
- **look-ahead 的化简是纸上工作，不是 RTL 工作。** 直接把 `f(f(...))`
  写进 RTL 而不做代数化简，得到的就是两倍深的组合逻辑，比原来更慢。
  **化简做不出来就不要做 look-ahead。**
- **CRC/线性递归的 look-ahead 要注意位序和多项式约定**（反射、初值、
  最终异或）。展开矩阵算错一位，表现是"大部分数据对、特定长度错"。
- **别忘了 mux 本身的成本。** 投机省下的级数如果只有 2~3 级，
  而 mux 加上选择信号的扇出又要 1~2 级，净收益可能接近零。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module ADDER #(
    parameter DAT_W       = 32,
    parameter SCHEME      = 2,       // 0 RIPPLE | 1 CLA | 2 CSEL
    parameter CSEL_BLK_W  = 8,       // CSEL 的块宽 —— 投机粒度
    parameter BLK_GROW_EN = 0        // 1 = 块宽递增（后块更宽）
)(...);
    localparam SCHEME_RIPPLE = 0;
    localparam SCHEME_CLA    = 1;
    localparam SCHEME_CSEL   = 2;
```

**`CSEL_BLK_W` 是这张卡最该扫的维度**，它直接量化"投机粒度 vs 面积"的曲线。
本仓库已把它提成参数（`CSEL_BLK_W`，2026-09-28 之前叫 `CSEL_BLOCK`；标 `sweep: false` 因为只对 CSEL 有意义），
曲线已经测出来了 —— 见下面的「本地实测」。
**这是一条本地流完全能测准的曲线**（纯组合、只看面积和级数），
是本类里少见的"结论可信"的实验。

## 出处

- Parhi, K.K., *VLSI Digital Signal Processing Systems*, Wiley, 1999 ——
  look-ahead 变换（含 IIR 与线性递归）的形式化。
- Ercegovac, M.D. & Lang, T., *Digital Arithmetic*, Morgan Kaufmann, 2004 ——
  carry-select / conditional-sum 加法器与块宽优化。
- Alidina, M. et al., "Precomputation-based sequential logic optimization for
  low power," *IEEE Transactions on VLSI Systems*, vol. 2, no. 4, 1994 ——
  低功耗那个意思的"预计算"。**未逐行核实，引用前自行确认。**
- 前缀加法器作为 look-ahead 的实例见
  [`../arith/prefix-adders.md`](../arith/prefix-adders.md)。

## 本地实测

**有实测记录。** 本仓库 `designs/adder32`（该设计根 2026-10-02 删除、2026-10-14 恢复为演示设计，RTL 改写前后形式等价；历史记录的源码仍按记录的 `git_commit` 取，见 `docs/data-credibility.md` 的 D-29），`PIPE_STAGES = 0`，同一份流程下
三种进位结构：

- `adder32-RIPPLE-0-6c860bf1`（RIPPLE，不投机）
- `adder32-CLA-0-d64230f4`（CLA，look-ahead）
- `adder32-CSEL-0-170fc866`（CSEL，预计算）

三条结论：

1. **预计算的兑换比接近 1:1**：CSEL 相对 RIPPLE 是
   **2.59× 面积换 2.16× 延时**。没有免费午餐，但也没有明显亏损 ——
   在 timing-limited 的场合这笔交易成立。
2. **look-ahead 明显更划算**：CLA 相对 RIPPLE 是
   **1.33× 面积换 1.41× 延时**。因为它利用了进位递归的代数结构做了化简，
   而不是无脑复制两份。**"有结构就用 look-ahead，没结构才用预计算"
   这条经验在本仓库的数字上是成立的。**
3. **CSEL 的单元数增长远超面积增长** —— 说明投机出来的多是小单元
   （mux 和窄加法器），和"投机的成本主要在复制窄逻辑 + mux"的预期一致。

⚠️ 两条限制：功耗一列没有，因为反标失效（`docs/data-credibility.md` D-1）——
而**功耗恰恰是预计算最吃亏的地方**，所以上面的"1:1 兑换比"
只是面积-延时的账，不是完整的账。
连线代价为零也会小幅高估 CSEL（它的 mux 网络连线更多）。

**投机粒度曲线（2026-09-07 补测）**：`WIDTH=32, PIPE_STAGES=0`，扫 `CSEL_BLOCK`
（记录按 `params` 检索实验记录 `results/<设计根>/experiments.jsonl`）。**延时呈 U 形，最优块宽是 8**：

- **BLOCK=2**（16 块）：块间 mux 链太长，延时最差之一，面积却最大 ——
  两头不讨好，投机得太细。
- **BLOCK=4 / 8**：延时最好的两档，级数相同；**8 的面积和延时都优于 4**。
- **BLOCK=16**（2 块）：块内 ripple 太长，延时退回到接近 BLOCK=2 的水平，
  面积最省（复制的加法器最少）。

**√32 ≈ 5.66，实测最优落在 4~8 之间 —— 卡片开头"块宽相等时延时 O(√n) 最优"
的理论预期被证实。** 两端劣化的机理也和推导一致：块太多则块间 mux 链主导，
块太少则块内进位链主导。

**一条连带结论**：本仓库历史上所有 CSEL 数据都测在 `BLOCK=4` 这个**次优点**上，
所以"CSEL vs CLA"的对比其实**低估了 CSEL**。默认值保持 4 是有意的
（改默认会让历史记录与新记录口径不一致），要用 8 得显式给值。
见 `docs/data-credibility.md` 的 C-2。
