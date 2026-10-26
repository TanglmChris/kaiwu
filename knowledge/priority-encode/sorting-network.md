# 排序网络（Sorting Networks：Bitonic / Odd-Even / 最优小网络）

- **类别**：优先级与编码
- **一句话**：用固定接线的"比较—交换"格点排序，**没有数据相关的控制流**，
  所以可以任意流水；代价是比较器数量按 O(n log²n) 涨，而且连线是置换式的长线。
- **典型用途**：中值/Top-k 滤波、硬件调度器选最早的 k 个、
  网络包排序、直方图/分位数、
  排序驱动的稀疏计算、任何"n 很小但每拍都要排"的场合。

## 结构

### 基本格点：比较—交换（compare-exchange, CE）

```verilog
assign lo = (a <= b) ? a : b;
assign hi = (a <= b) ? b : a;
```

一个比较器 + 两个 w 位 mux（或一个比较器 + 一次条件交换）。
**这是网络的唯一构件**，比较器本身见
[`../arith/comparator.md`](../arith/comparator.md)。

### 为什么"网络"这个词是关键

排序网络的接线是**固定的**，比较谁和谁与数据无关，
只有交不交换取决于数据。后果：

- 无控制逻辑、无分支、无变长延迟；
- **每一级之间随便插寄存器就是流水线**（见
  [`../arch-technique/pipelining.md`](../arch-technique/pipelining.md)）；
- 吞吐 = 1 组/拍，延迟 = 级数拍。

这正是硬件排序和软件排序的分界：软件用快排（数据相关、平均 O(n log n)），
硬件用网络（数据无关、面积 O(n log²n)）。

### Bitonic（Batcher，1968）

递归：先把前后两半分别排成升序和降序（构成 bitonic 序列），
再做 bitonic merge。对 n = 2^m：

- 比较器数：**n·log₂n·(log₂n + 1) / 4**。n=16 → 80，n=32 → 240。
- 级数（深度）：**log₂n·(log₂n + 1) / 2**。n=16 → 10，n=32 → 15。

结构极其规整，每一级都是"跨距 2^k 的两两比较"，很好 generate 出来。

### Odd-Even merge sort（Batcher，同一篇）

同样的深度，**比较器更少**（n=16 时约少两成）。
接线不如 bitonic 规整，写起来烦一点。
**面积敏感就用 odd-even，代码可读性优先就用 bitonic。**

### 小 n 的最优网络（查表，不是构造）

n 小的时候，已知的最优网络比 Batcher 好不少：

| n | 最优比较器数 | 最优深度 | Bitonic 比较器数 |
|---|---|---|---|
| 4 | 5 | 3 | 6 |
| 5 | 9 | 5 | — |
| 6 | 12 | 5 | — |
| 7 | 16 | 6 | — |
| 8 | 19 | 6 | 24 |

**n ≤ 8 时直接抄最优网络的接线表，别用 Batcher 构造。**
这些网络是穷举/计算机搜索出来的，没有简洁公式，
Knuth 卷 3 §5.3.4 有表。（n ≥ 9 的最优性是后来的计算机搜索结果，
**未逐行核实，用前自行确认。**）

### 部分排序：绝大多数时候你不需要全排序

| 需求 | 结构 | 代价 |
|---|---|---|
| 最大值 | max 树 | n−1 个 CE，深度 log n |
| 最大 + 次大 | max 树 + 沿路径回溯 | ≈ n + log n |
| 中值（n=3） | 3 个 CE | 深度 2 |
| 中值（n=9，图像 3×3）| 已知最优 19 个 CE | 深度 7 |
| Top-k | 部分网络 / 选择网络 | 远小于全排序 |

**"我要排序"十有八九其实是"我要最大的那个"或"我要中位数"。
先确认需求，能省一个数量级。**

## 关键路径

一级 CE 的延时 = `比较器 O(log w)` + `一级 mux`（w 是键宽）。整网：

```
延时 ≈ 深度 × (O(log w) + 1 级 mux)
     = O(log²n) × O(log w)        [bitonic]
```

**两个对数相乘** —— 这是排序网络最容易被低估的地方。
n=32、w=32 时深度 15 级，每级又是一个 5 级的比较器加 mux，
纯组合做完是 90+ 级逻辑。**基本不可能不流水。**

## PPA 权衡

- 面积按 **O(n log²n) 个比较器 × O(w) 位宽**涨，是本知识库里
  最贵的一类组合电路。n 从 16 到 32，比较器数 80 → 240（3 倍）。
- **流水是必须的，也是免费的**（无反馈、无控制）：
  在每级之间插寄存器，吞吐保持 1 组/拍，代价是 `深度 × n × w` 个触发器 ——
  **触发器的面积经常超过比较器本身**。这是排序网络真正的成本中心，
  参数化时一定要把"每几级插一拍"做成参数。
- **只排索引不排数据**：如果载荷很宽（比如 64 位 key + 512 位 payload），
  就只让 key 和一个 log n 位的索引过网络，最后用索引去选 payload。
  面积从 O(w_payload · n log²n) 降到 O((w_key + log n) · n log²n) + 一次置换。
  **这一招通常比换网络拓扑省得多。**

> ⚠️ 连线警告（全库通则，见 [`../README.md`](../README.md)）：
> bitonic 的每一级都是跨距 2^k 的置换接线，
> **最大跨距那几级要把数据搬过半个阵列**。本仓库没有 LEF / 没有 P&R /
> 没有寄生参数，**这些长线在本地流里成本为零**。
> 所以本地测出来的排序网络会比它在真实版图上好看，
> 而且 bitonic 和 odd-even 的**连线差异根本测不出来**。
> 本地可信的只有比较器数（面积）和级数。

## 什么时候选它 / 什么时候别用

- **n 小（≤16）、每拍都要排、延迟要确定** → 排序网络。
- **只要最大/最小/中值/Top-k** → **别做全排序**，用部分网络（见上表）。
- **n 大（≥64）** → 排序网络不划算，改成多周期的
  merge sort / bitonic 分批（面积换时间，见
  [`../arch-technique/folding-time-multiplex.md`](../arch-technique/folding-time-multiplex.md)）。
- **数据本来就在 FIFO 里逐个到达** → 插入排序阵列（脉动式）更合适：
  面积 O(n)，每拍进一个，n 拍出结果。这是完全不同的结构，不在这张卡里。
- **只是想找优先级最高的请求** → 那是
  [`fixed-priority-arbiter.md`](fixed-priority-arbiter.md)，别用排序网络。

## 实现要点与坑

- **稳定性由比较符决定。** CE 里写 `a <= b` 还是 `a < b`，
  决定键相等时保不保持原有顺序。带 payload 的排序里这不是学术问题 ——
  不稳定的网络会让相同 key 的记录顺序在不同输入下抖动，
  下游如果依赖顺序就是间歇性 bug。**接口上要写死。**
- **有符号 / 无符号**：同 [`../arith/comparator.md`](../arith/comparator.md)，
  Verilog 里比较的符号性取决于操作数声明。排序网络里这个错误会
  在负数出现时才暴露。
- **generate 递归写 bitonic 时，n 必须是 2 的幂。** 不是的话要
  padding 到 2 的幂（用最大值/最小值填充），
  **padding 值选错会把真实数据挤出去** —— 升序排序要用 `{w{1'b1}}` 填。
- **必须保层级（`params.yaml` 的 `keep_hierarchy:`）。** 排序网络是纯函数（输入的一个置换），
  `-flatten` + ABC 的 `&dch` 有很强的动机把整张网络重新推导，
  bitonic / odd-even / 最优小网络会被收敛成同一个结果 ——
  这正是 `docs/pitfalls.md` 的 P-3描述的场景，而且比加法器更极端
  （网络更大、结构信息更多）。**CE 格点和每一级都要设边界。**
- **验证要用 0-1 原理。** 排序网络的正确性有一个经典定理：
  **一个比较—交换网络能正确排序所有 0/1 序列，当且仅当它能排序所有输入。**
  所以 n=16 的网络只要穷举 2^16 = 65536 个 0/1 向量就**证明**了正确性，
  不需要随机测多位宽数据。这条应当直接写进设计的 `verify.md` ——
  它把"随机测一测"变成了"穷举证明"，是本知识库里少有的能做到这一点的电路。
- **流水切分点要参数化。** 全组合和逐级流水之间差着几十倍的触发器，
  这个维度不扫就等于没测。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module SORT_NET #(
    parameter KEY_N      = 8,        // 必须是 2 的幂（除非 SCHEME = SCHEME_OPTIMAL）
    parameter KEY_W      = 16,       // key 位宽
    parameter SCHEME     = 0,        // 0 BITONIC | 1 ODDEVEN | 2 OPTIMAL（查表，KEY_N<=8）
    parameter PIPE_EVERY = 0,        // 0=纯组合；k=每 k 级插一拍
    parameter GEN_IDX_EN = 0,        // 是否同时输出原始下标的置换
    parameter DESCEND_EN = 0
)(
    input                        clk,
    input                        rst_n,
    input  [KEY_N*KEY_W-1:0]     i_dat,
    output [KEY_N*KEY_W-1:0]     o_dat,
    output [KEY_N*$clog2(KEY_N)-1:0] o_idx   // GEN_IDX_EN=1 时给出排序后的原始下标
);
    localparam SCHEME_BITONIC = 0;
    localparam SCHEME_ODDEVEN = 1;
    localparam SCHEME_OPTIMAL = 2;
```

`PIPE_EVERY` 是这张卡最重要的参数：**它一个人就能让面积变化一个数量级**，
而且它测的是本仓库真正关心的东西（面积/频率的取舍）。
`GEN_IDX_EN` 用来量化"只排索引"那一招的收益。

## 出处

- Batcher, K.E., "Sorting networks and their applications,"
  *AFIPS Spring Joint Computer Conference*, pp. 307–314, 1968 ——
  bitonic 与 odd-even merge sort 的原始论文。
- Knuth, D.E., *The Art of Computer Programming, Vol. 3: Sorting and
  Searching*, 2nd ed., Addison-Wesley, 1998, §5.3.4 "Networks for Sorting" ——
  0-1 原理的证明、小 n 最优网络表、深度/大小下界。
- 比较器构件见 [`../arith/comparator.md`](../arith/comparator.md)。

## 本地实测

暂无。这张卡有**两个互补的实验**：

1. **`SCHEME` 对照（BITONIC / ODDEVEN / OPTIMAL，N=8）** ——
   纯组合，测比较器数与级数。**注意这也是一次 `keep_hierarchy` 的验证**：
   三者的比较器数已知不同（24 / ~19 / 19），
   **如果测出来面积一样，就是结构被抹平了，先查流程再看数**。
2. **`PIPE_EVERY` 扫参** —— 面积 vs fmax 的经典权衡，
   而且排序网络是做这个实验最干净的载体（无反馈、无握手、
   切在哪一级都合法）。**这一条不依赖 valid-ready 支持**，
   现有 `flow/` 就能跑。

延时和功耗的绝对值不可信（连线为零，见上面的警告），
但**同一位宽下不同 SCHEME / PIPE_EVERY 的相对趋势是可信的**。
