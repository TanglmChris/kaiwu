# 并行前缀加法器家族（Parallel Prefix Adders）

- **类别**：算术单元
- **一句话**：把进位链变成一棵可结合的前缀树，用 O(log n) 级数换掉 ripple 的 O(n)，
  而树怎么长决定了级数 / 扇出 / 连线三者怎么分账。
- **典型用途**：任何位宽 ≥ 16 的加法器；也是乘法器最后那级 CPA、比较器、
  增量器（incrementer）的骨架。

## 结构

把加法拆成两步。先逐位算出**生成**和**传播**：

```
g[i] = a[i] & b[i]        // 这一位自己就产生进位
p[i] = a[i] ^ b[i]        // 这一位会把低位来的进位传过去
```

关键在于，"一段连续位的整体进位行为"可以由两段拼起来，且拼接算子**可结合**：

```
(g_hi, p_hi) ∘ (g_lo, p_lo) = (g_hi | (p_hi & g_lo),  p_hi & p_lo)
```

可结合意味着**算这些前缀的顺序可以任意重排** —— 于是求所有位的进位就变成了一个
标准的并行前缀问题，可以用任何一棵前缀树来算。ripple 加法器不过是"最退化的那棵树"：
一条链，n 级。

不同的前缀网络就是不同的树形。业内常用的几种：

| 网络 | 提出者 | 一句话 |
|---|---|---|
| Sklansky | Sklansky 1960 | 每级把跨度翻倍，级数最少，但某些节点扇出巨大 |
| Kogge-Stone | Kogge & Stone 1973 | 每级所有位并行推进，扇出恒为 2，代价是连线极多 |
| Brent-Kung | Brent & Kung 1982 | 先归约再展开，连线和面积最省，级数约两倍 |
| Han-Carlson | Han & Carlson 1987 | 奇偶分治：外层 Brent-Kung、中间 Kogge-Stone，折中 |
| Knowles | Knowles 1999 | 一整个可调族，逐级指定允许的扇出 |

## 关键路径

**全都是 O(log n)，但常数差别很大**，而且"级数少"不等于"延时小"。

Harris 的分类法把这个家族放进一个三维空间：级数 `log₂N + l`、扇出 `2^f + 1`、
连线轨道 `2^t`，并且**三个指数受同一个预算约束**：

```
l + f + t = log₂N − 1
```

也就是说，**级数、扇出、连线三者是零和的** —— 想少一级，就得多付扇出或多付连线。
这是整个家族最值得记住的一句话。以 N = 32（log₂N = 5）为例：

| 网络 | (l, f, t) | 逻辑级数 | 最大扇出 | 连线轨道 |
|---|---|---|---|---|
| Sklansky | (0, 4, 0) | 5 | 17 | 1 |
| Kogge-Stone | (0, 0, 4) | 5 | 2 | 16 |
| Brent-Kung | (4, 0, 0) | 9 | 2 | 1 |
| Han-Carlson | (1, 0, 3) | 6 | 2 | 8 |

对照本仓库已经测过的 32 位 ripple：34 级。前缀树把它压到 5～9 级，
差一个数量级 —— 这就是为什么位宽一上去就必须换结构。

## PPA 权衡

- **Sklansky**：级数理论最优，但扇出 17 是要还的。真实工艺里驱动 17 个负载必须插缓冲，
  **插完缓冲级数就涨回来了**，所以它的"最快"只在不考虑负载的模型里成立。
- **Kogge-Stone**：级数最优且扇出恒定，教科书上的"最快"。代价是连线轨道 N/2，
  面积和连线功耗都很凶。**注意这正是本地流看不见的那部分代价**（见下）。
- **Brent-Kung**：节点数最少（约 2N），面积和功耗最省，级数约两倍。位宽大而
  时序不紧的场合它常常是最优解，也很适合做低功耗。
- **Han-Carlson**：只比 Kogge-Stone 多一级，连线减半。工业界最常见的落点。
- 面积大致排序：Brent-Kung < Han-Carlson < Sklansky ≲ Kogge-Stone。
- 动态功耗大致跟节点数和连线电容走，所以排序与面积接近；但 Sklansky 的大扇出
  会额外抬高功耗。

## 什么时候选它 / 什么时候别用

- **位宽 ≤ 8**：别用。前缀树的常数开销吃掉了级数优势，ripple 或简单 CLA 反而更好。
  本仓库 32 位的实测里 CLA 只有 22 级、CSEL 15 级，前缀树的收益要到更大位宽才充分体现。
- **位宽 16～64、时序吃紧**：Han-Carlson 或 Kogge-Stone。
- **位宽大但时序宽松、要省面积/功耗**：Brent-Kung。
- **加法在关键路径上但只差一点点**：先别换网络，先看能不能流水切一刀 —— 本仓库
  实测流水一级就把 32 位 ripple 从 34 级降到 20 级，比换结构便宜得多。
- **乘法器末级 CPA**：几乎总是用前缀树，且因为输入到达时间不齐（压缩树中间位晚到），
  值得做**不规则**的前缀网络，让晚到的位走短路径。

## 实现要点与坑

- **必须防止综合把结构优化掉。** 前缀加法器的全部价值在**结构**，功能上它和
  `a + b` 完全等价。本仓库已经实测过：`synth -flatten` 配合 ABC 默认的 `&dch`
  会把 ripple / CLA / carry-select 收敛成同一个网表（见 `docs/pitfalls.md` 的 P-3）。
  写前缀加法器时，**前缀算子要独立成模块、在 `params.yaml` 的 `keep_hierarchy:` 里声明保层级，且不要 flatten**，
  否则测出来的家族差异是假的。
- **本地流看不见连线，会系统性偏袒 Kogge-Stone。** 本仓库没有 LEF、没有布局布线、
  没有寄生参数，连线轨道数为 16 和为 1 在 STA 里代价一样。所以本地跑出来
  Kogge-Stone 很可能"既快又不太贵"，而这**不是真的**。这一条要写进任何用本地流做的
  前缀网络对比结论里，等 DC / P&R 到位再校准。
- **命名混乱要小心。** "Ladner-Fischer" 在不同文献里指的东西不一样，有时就是 Sklansky。
  看论文时以**图**为准，不要以名字为准。
- **`p[i]` 用 XOR 还是 OR。** 计算进位时 `p = a|b` 也是对的（因为 `a&b` 的情况已由 g 覆盖），
  但求和那一步需要 `a^b`。用 OR 版可以让某些工艺下的进位路径更快，代价是要多算一份 XOR。
- **稀疏前缀（sparse prefix）**是实用优化：只算每 2/4 位一个进位，块内用小 carry-select
  补齐。级数再降一点，面积明显下降，工业实现常见。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module PREFIX_ADDER #(
    parameter DAT_W    = 32,
    parameter SCHEME   = 3,              // 0 SKLANSKY | 1 KOGGE_STONE | 2 BRENT_KUNG | 3 HAN_CARLSON
    parameter SPARSITY = 1               // 1=每位都算进位；2/4=稀疏前缀 + 块内 select
)(input [DAT_W-1:0] i_a, i_b, input i_cin, output [DAT_W-1:0] o_sum, output o_cout);
    localparam SCHEME_SKLANSKY    = 0;
    localparam SCHEME_KOGGE_STONE = 1;
    localparam SCHEME_BRENT_KUNG  = 2;
    localparam SCHEME_HAN_CARLSON = 3;
```

配合 `designs/adder32/params.yaml`（已删，见上）的风格，网络直接并进 `SCHEME` 这个 enum 参数，
和已有的 RIPPLE / CLA / CSEL 并列，就能一次扫完七种结构（2026-09-28 之前这两个维度叫 `NETWORK` / `CARRY_STRUCT`）。

## 出处

- [A Taxonomy of Parallel Prefix Networks](https://pages.hmc.edu/harris/research/taxonomy.pdf)
  — D. Harris, Asilomar 2003, pp. 2213–2217。**这个家族最该读的一篇**，
  三维分类法和上面那张 (l, f, t) 表就出自这里，还用 logical effort 做了统一比较。
  作者主页有公开 PDF。
- [A Parallel Algorithm for the Efficient Solution of a General Class of Recurrence Equations](https://dl.acm.org/doi/10.1109/TC.1973.5009159)
  — P. M. Kogge, H. S. Stone, IEEE Trans. Computers, vol. C-22, no. 8, pp. 786–793, 1973.
  Kogge-Stone 的原始出处；注意它本来讲的是递推方程的并行求解，加法只是一个应用。
- [A Regular Layout for Parallel Adders](https://maths-people.anu.edu.au/~brent/pd/rpb060_IEEETC.pdf)
  — R. P. Brent, H. T. Kung, IEEE Trans. Computers, vol. C-31, no. 3, pp. 260–264, 1982.
  Brent 本人主页的公开 PDF。标题里的 "Regular Layout" 就是重点：这篇关心的是**版图**，
  证明了 O(log n) 时间可以配 O(n) 面积。
- T. Han, D. A. Carlson, "Fast area-efficient VLSI adders", Proc. IEEE 8th Symposium on
  Computer Arithmetic (ARITH-8), 1987, pp. 49–56. —— Han-Carlson 原始出处，
  没找到公开全文，IEEE Xplore 有。
- J. Sklansky, "Conditional-Sum Addition Logic", IRE Trans. Electronic Computers, 1960.
  —— 未逐项核实卷期页码，引用前请自行确认。

## 本地实测

**2026-09-08 首次实测。** 本仓库 `designs/adder32`（该设计根 2026-10-02 已删，源码按记录的 `git_commit` 取，见 `docs/data-credibility.md` 的 D-29）已实现 Harris 分类法的三个角
（`CARRY_STRUCT = SKLANSKY / KOGGE_STONE / BRENT_KUNG`，共用同一份 g/p 预计算与末级
sum XOR，只有网络拓扑不同），扫 `WIDTH = 8/16/32/64`。代表记录（`WIDTH=64, PIPE_STAGES=0`）：
`adder32-SKLANSKY-4-0-64-b840b26c` / `adder32-KOGGE_STONE-4-0-64-871a1e82` /
`adder32-BRENT_KUNG-4-0-64-d2f5c33a`。

### 1. 级数与理论完全对上

映射后关键路径的逻辑级数（`WIDTH = 8/16/32/64`）：

- **Sklansky 8 / 9 / 10 / 11**，**Kogge-Stone 8 / 9 / 10 / 11** —— 两者**逐位相同**，
  每翻一倍位宽只多一级，正是 `l = 0`（级数 `log₂N`）。
- **Brent-Kung 9 / 11 / 13 / 15** —— 每翻一倍多**两级**，正是 `l = log₂N − 1`。

对照同一份流程测出的 32 位 ripple 是 34 级、CSEL 是 15 级。
**前缀树把 66 级（64 位 ripple）压到 11 级**，这就是位宽一上去就必须换结构的理由。

延时的 log-log 斜率：Kogge-Stone **0.221**、Brent-Kung **0.368**、Sklansky **0.447**，
全部远低于 CSEL 的 0.573（O(√n)）与 RIPPLE 的 1.012（O(n)）——
**O(log n) 这一档在本仓库第一次被实测确认。**

面积斜率：Kogge-Stone **1.236** > Sklansky **1.155** > Brent-Kung **1.058**，
与 O(n log n)（KS/Sklansky）对 O(n)（BK）的预期一致。

### 2. `l + f + t` 的零和约束看得见一半

Sklansky 与 Kogge-Stone 的 `l` 相同（级数逐位相同），差别全在 `f`（扇出）与 `t`（连线）。
本地实测的延时相对差：

| WIDTH | 8 | 16 | 32 | 64 |
|---|---|---|---|---|
| Kogge-Stone 比 Sklansky 快 | 2.5% | 13.3% | **25.1%** | **39.2%** |

**同样的级数，差距却随位宽拉大到 39%** —— 这是扇出代价的直接体现：
Sklansky 最后一级有一个节点要驱动 N/2 个消费者（64 位时是 32 个），
负载电容随位宽线性增长。

> ⚠️ **但这张表只算了一半的账，而且是对 Kogge-Stone 有利的那一半。**
> 本地流没有 LEF、没有布局布线、寄生参数为零：
> **管脚电容在 liberty 里是有的**（所以 Sklansky 的 `f` 代价可见），
> **连线电容为零**（所以 Kogge-Stone 的 `t` 代价完全不可见）。
> Kogge-Stone 的卖点正是用 O(N) 条连线轨道换扇出，
> **本地流因此系统性高估它**。上表的 39% 是上界，真实版图上会缩小、
> 甚至可能反转。**接 P&R 之前不要据此选型。**
>
> Brent-Kung 是这三者里本地测量最可信的一个 —— 它的 `f` 和 `t` 都是常数，
> 没有本地看不见的成本。

### 3. 一条比数字更值钱的教训：`keep_hierarchy` 的粒度

第一版实现只在**网络模块**上标了 `(* keep_hierarchy *)`，测出来的级数是
Sklansky 47、Kogge-Stone 16、Brent-Kung 31（64 位）—— 一棵 6 层的树被 ABC
重构成了 47 级的逻辑链，而且顺序完全颠倒。诊断确认：

- RTL 没问题（复刻 generate 的索引逻辑算 DAG 深度，前缀覆盖正确、深度就是理论值）；
- 不是扇出缓冲（关键路径上 21 个 `A2O1A1O1I` + 20 个 `OAI21`，**一个 buffer 都没有**）；
- 给 ABC 加延时目标无效（`abc -liberty <lib> -D 300` 与不加 `-D` 的网表**逐字节相同**）。

把边界下沉到**每个前缀算子**（一个 `PREFIX_NODE` 模块）之后，
级数立刻回到 11 / 11 / 15。

> **`keep_hierarchy` 的粒度决定了你能保住什么。标在「网络」上只保住网络的边界，
> 内部对 ABC 仍是一整块可自由重构的组合锥；要保住**树的拓扑**，
> 必须标在**承载拓扑的最小算子**上。**
>
> 代价是面积上升（64 位：445→640 / 687→898 / 483→496 cells），这是结构保真的价钱。
> 这一条对本知识库里所有"靠结构取胜"的电路都成立 ——
> 压缩树、排序网络、前缀比较器、仲裁树，都要标到算子级。

### 4. 还没测的

- Han-Carlson (1, 0, 3) 这个内插点没实现，`SPARSITY`（稀疏前缀）也没做。
- 功耗一列不可用（`docs/data-credibility.md` D-1，VCD 反标失效）。
- 连线代价要等 DC / P&R，见上面的警告。
