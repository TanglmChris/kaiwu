# 找首个 1 / 找首个 0（Find-First-Set / Priority Encoder）

- **类别**：优先级与编码
- **一句话**：从一堆位里挑出优先级最高的那一个 —— 它本质上是个**前缀问题**，
  所以 `../arith/prefix-adders.md` 那整套网络原样可用；`x & -x` 是同一件事的
  算术写法，便宜但只能找最低位。
- **典型用途**：仲裁器、空闲资源分配（free list）、中断优先级、
  FIFO 空槽查找、CLZ/CTZ 的第一步、稀疏向量遍历。

## 结构

问题定义：输入 `x[n-1:0]`，输出 one-hot 的 `first`（只有优先级最高的那个 1 保留）
和它的二进制下标 `idx`，外加 `valid = |x`。下面按"位 0 优先级最高"（LSB-first）写，
MSB-first 把位序倒过来即可。

### 写法 A：算术技巧 `x & -x`

```verilog
wire [N-1:0] first = x & (~x + 1);   // 即 x & -x
```

原理：`x-1` 把末尾连续的 0 全变成 1、把最低的那个 1 变成 0，
所以 `x & ~(x-1) = x & -x` 只剩最低的 1。同族的还有
`x & (x-1)`（清掉最低的 1）、`x | (x-1)`（把末尾 0 全填 1）。

代价是一条**全宽的进位链**（那个 `+1`）。

### 写法 B：前缀扫描（推荐）

```
none_below[i] = ~( x[i-1] | x[i-2] | ... | x[0] )   // i=0 时恒为 1
first[i]      = x[i] & none_below[i]
```

`none_below` 就是 `x` 的**排他性前缀 OR** 取反。这一步和加法器的进位前缀
是同一个代数结构（算子是 OR，可结合），所以
[`../arith/prefix-adders.md`](../arith/prefix-adders.md) 里
Sklansky / Kogge-Stone / Brent-Kung / Han-Carlson 的整张网络表
可以直接搬过来用，连 (l, f, t) 的权衡都一样：
Sklansky 级数最少但有 fanout n/2 的节点，Kogge-Stone 连线最多，
Brent-Kung 面积最省级数最多。

**节点比加法器还简单**：这里每个前缀节点只有一个 OR 门，
没有 (g, p) 那一对信号，也没有和的那一路。所以同样的网络拓扑，
比较器/优先编码器的实现成本比加法器低一大截。

### 写法 C：两级（分组）

把 n 位切成 g 组、每组 m 位：

```
grp_any[j] = |x[组 j]                  // g 位
grp_sel    = first_one(grp_any)        // g 位的同一个问题
first      = 组内 first_one 的结果 & grp_sel 展开
```

延时 O(log g) + O(log m)，还是 O(log n)，但**常数和 fanout 都更好**，
而且 `grp_any` 可以被别处复用（比如同时要 `valid`）。位宽 ≥ 64 时这是默认做法。

### one-hot → 二进制下标

```
idx[k] = | { first[i] : i 的第 k 位为 1 }
```

log n 棵 OR 归约树，每棵 n/2 个输入。这一段和
[`onehot-binary-thermometer.md`](onehot-binary-thermometer.md) 里的编码器
是同一个电路。

### 找首个 0

`first_zero(x) = first_one(~x)`。没有别的花样，一个反相器的事。

## 关键路径

- 写法 A：`+1` 的进位链。用行波进位是 **O(n)**，用前缀进位是 **O(log n)**，
  但节点是 (g,p) 对，比写法 B 的纯 OR 节点重。
- 写法 B：前缀 OR 网络 **O(log n)** + 一级 AND。
- 写法 C：**O(log n)**，常数更小。
- 加上 one-hot → 下标的编码：再 **O(log n)**。
  **如果下游只要 one-hot（例如直接当 mux 的选择信号），就别编码成二进制** ——
  编码再解码是白付两个 O(log n)。见
  [`onehot-binary-thermometer.md`](onehot-binary-thermometer.md)。

## PPA 权衡

- **写法 B 面积和延时都优于写法 A**，除非那条进位链能和别处已有的加法器复用
  （比如你本来就要算 `x-1`）。复用比省更重要，这条和
  [`../arith/comparator.md`](../arith/comparator.md) 里"既要差值又要比较"是同一条道理。
- 前缀网络的选择完全等价于加法器：级数少 ↔ 连线多 / fanout 大。
  **注意本仓库测不出连线代价**（见 `../README.md` 的全库警告），
  所以本地流会系统性偏爱 Kogge-Stone 这一端。
- 位宽小（≤16）时三种写法差别不大，综合工具怎么做都行；
  差距要到 32/64 位才显出来。

## 什么时候选它 / 什么时候别用

- **需要"最高优先级的那一个"** → 就是这张卡。
- **需要"有没有"** → 只要 `|x`，一棵 OR 树，别做优先编码。
- **需要"有几个"** → 那是 popcount（多操作数求和，见 [`../arith/csa-accumulation.md`](../arith/csa-accumulation.md)），完全不同的电路。
- **需要"最高位在哪"** → 是 [`clz-lzd.md`](clz-lzd.md)（MSB-first 的这个问题，
  但那边有更好的树结构）。
- **需要公平轮转** → 固定优先级会饿死高位请求者，
  用 [`round-robin-arbiter.md`](round-robin-arbiter.md)。

## 实现要点与坑

- **`casez` / `for` + `break` 写法会综合成什么，不要想当然。** RTL 里
  `for (i=0;i<N;i=i+1) if (x[i]) begin idx = i; disable f; end` 这种写法
  语义上是串行扫描，综合工具**通常**能识别成优先级 mux 链，
  但那是一条 O(n) 的链，不是前缀树。位宽大了必须显式写前缀结构。
- **这是"工具可能做得比你好"的一类。** 逻辑规模小、布尔优化有效，
  32 位以下直接写 `casez` 很可能打不过手写前缀树也追不上工具。
  所以参数化接口里保留 `TOOL` 档做对照组 —— 这和
  [`../arith/comparator.md`](../arith/comparator.md)、
  `../arith/constant-multiplication.md` 是同一批实验，应该打包做。
- **要比较不同前缀网络就必须保层级（`params.yaml` 的 `keep_hierarchy:`）。** 写法 A/B/C 在**功能上
  完全等价**，不设模块边界的话 ABC 的 `&dch` 会把三者收敛成同一个网表 ——
  这是本仓库踩过的坑（`docs/pitfalls.md` 的 P-3）。这张卡的所有结构对比实验
  都受这条约束。
- **`valid` 别忘了。** `x == 0` 时 `first` 全 0、`idx` 是垃圾。
  下游如果无条件用 `idx` 去索引，就是一个只在"全空"时才复现的 bug。
- **`x & -x` 在 Verilog 里的位宽陷阱**：`-x` 对 `wire [N-1:0]` 是按 N 位取补，
  没问题；但如果 `x` 被隐式扩展到 32 位（比如混进了整数运算），
  结果就错了。显式写 `(~x + 1'b1)` 更安全。
- **优先级方向要在接口上写死。** LSB 优先还是 MSB 优先，
  换个人接手一定会搞反，注释不够，参数化出来。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module FIND_FIRST #(
    parameter DAT_W        = 32,
    parameter MSB_FIRST_EN = 0,        // 0: 位0优先  1: 最高位优先
    parameter SCHEME       = 0,        // 0 PREFIX | 1 ARITH（x&-x） | 2 BLOCK（两级） | 3 TOOL（casez）
    parameter BLK_W        = 8,        // SCHEME = SCHEME_BLOCK 时的组宽
    parameter GEN_IDX_EN   = 1         // 0 时只出 one-hot，省掉编码器
)(
    input  [DAT_W-1:0]         i_dat,
    output [DAT_W-1:0]         o_first,   // one-hot
    output [$clog2(DAT_W)-1:0] o_idx,
    output                     o_zero     // i_dat == 0
);
    localparam SCHEME_PREFIX = 0;
    localparam SCHEME_ARITH  = 1;
    localparam SCHEME_BLOCK  = 2;
    localparam SCHEME_TOOL   = 3;
```

`GEN_IDX_EN` 单独拿出来是有意的：**"要不要二进制下标"往往决定一半的面积**，
把它做成参数才量得出来。

## 出处

- Warren, H.S., *Hacker's Delight*, 2nd ed., Addison-Wesley, 2012 —
  第 2 章有 `x & -x`、`x & (x-1)` 一族恒等式的完整推导。
- Weste, N. & Harris, D., *CMOS VLSI Design*, 4th ed., Addison-Wesley, 2010 —
  datapath 一章讲优先编码器与前缀结构的对应关系。
- 前缀网络本身的理论基础见
  [`../arith/prefix-adders.md`](../arith/prefix-adders.md) 的出处
  （Harris 的 (l, f, t) 分类法完全适用）。

## 本地实测

暂无。**这张卡属于"第一批便宜实验"**：纯组合、无握手、无多周期，
现有 `flow/` 直接能跑。建议和 `../arith/comparator.md`、
`../arith/constant-multiplication.md` 打包成同一组 ——
三者都在回答同一个问题：**手写结构 vs 交给工具，分界线在哪里。**
