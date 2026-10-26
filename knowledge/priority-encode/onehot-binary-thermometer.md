# 独热 / 二进制 / thermometer 码互转（One-Hot ↔ Binary ↔ Thermometer）

- **类别**：优先级与编码
- **一句话**：三种码之间的六个转换里，只有 **thermometer → binary（= popcount）**
  是贵的，其余都是一棵树或者一个 XOR —— 真正的设计决策不是"怎么转"，
  而是"**能不能不转**"。
- **典型用途**：mux 的选择信号、FSM 状态编码、FIFO 指针与占用率、
  仲裁 grant、片选/使能解码、DAC 与 flash-ADC 接口、
  跨时钟的格雷码指针。

## 结构

三种码（以 N=8、值 = 3 为例）：

```
binary       : 011
one-hot      : 0000_1000        // 第 3 位为 1
thermometer  : 0000_0111        // 低 3 位为 1（"小于 3 的位置"）
```

### binary → one-hot（解码器）

```verilog
assign onehot = 1'b1 << bin;
```

或者显式的树形解码：把 `bin` 的 log N 位逐位展开成 AND 树。

- 面积 **O(N)** 个 AND 门，深度 **O(log N)**。
- 便宜。

### one-hot → binary（编码器）

```verilog
// bin[k] = 所有"下标第 k 位为 1"的 one-hot 位的 OR
assign bin[k] = |(onehot & MASK_k);
```

log N 棵 OR 归约树，每棵 N/2 个输入。深度 **O(log N)**，面积 **O(N log N)** 门
（但每个门都极小）。

> **这个编码器假定输入恰好只有一位为 1。** 多于一位时输出是那些下标的
> **按位或**（一个看起来合法却完全错误的值），而且**不会报错**。
> 输入可能非 one-hot 时，必须先过优先编码器 ——
> 见 [`find-first-one.md`](find-first-one.md)。这是本卡第一号坑。

### binary → thermometer

```
therm[i] = (i < bin)
```

朴素做法是 N 个比较器（贵）。正确做法是**先解码再前缀 OR**：

```
onehot = 1 << bin
therm  = 排他性前缀 OR(onehot)     // "有没有更低的位是 1"
```

深度 = 解码 O(log N) + 前缀 O(log N)。前缀网络还是
[`../arith/prefix-adders.md`](../arith/prefix-adders.md) 那一套。

### thermometer → binary

**就是 popcount**（数有几个 1，即 n 个 1 位数求和）。见 [`../arith/csa-accumulation.md`](../arith/csa-accumulation.md)。
**六个转换里唯一贵的一个**：需要一棵压缩树。

### thermometer → one-hot（边沿检测）

```verilog
assign onehot = therm ^ (therm >> 1);   // 或 therm & ~(therm >> 1)
```

**一级 XOR，O(1) 深度，N 个门。** 全库最便宜的转换之一。
反过来 one-hot → thermometer 就是上面那次前缀 OR。

### binary ↔ gray

```verilog
assign gray = bin ^ (bin >> 1);        // O(1)：一级 XOR
// gray -> bin 是前缀 XOR：bin[k] = ^gray[N-1:k]
```

binary→gray 是 O(1)，gray→binary 是 **O(log N)** 的前缀 XOR。
**方向不对称**，这一点在
[`../storage-flow/async-fifo.md`](../storage-flow/async-fifo.md)
里决定了指针该在哪一侧转换。

### 转换代价一览

| 转换 | 深度 | 面积 | 备注 |
|---|---|---|---|
| binary → one-hot | O(log N) | O(N) | 解码树 |
| one-hot → binary | O(log N) | O(N log N) 小门 | **要求输入真是 one-hot** |
| binary → thermometer | O(log N) | O(N) | 解码 + 前缀 OR |
| thermometer → binary | O(log N) | **压缩树** | = popcount，**唯一贵的** |
| thermometer → one-hot | **O(1)** | N 个 XOR | 边沿检测 |
| one-hot → thermometer | O(log N) | O(N) | 前缀 OR |
| binary → gray | **O(1)** | N 个 XOR | |
| gray → binary | O(log N) | O(N) | 前缀 XOR |

## 关键路径

上表即是。要记的只有两条：
**thermometer→binary 是压缩树（贵）**，
**thermometer→one-hot 和 binary→gray 是一级 XOR（几乎免费）**。

## PPA 权衡

### 一号论点：one-hot 选择信号 + AND-OR mux，常常比二进制选择快

N:1 的数据 mux 有两种接法：

```
(a) 二进制 sel  -> mux 树：      log N 级 2:1 mux，每级都在关键路径上
(b) one-hot sel -> AND-OR：      1 级 AND + 1 棵 OR 树（log N 级小门）
```

看上去同阶，但 **(b) 的解码可以提前做、可以和数据到达并行、
可以被多个 mux 共享**；而 (a) 的每一级 mux 都必须等 `sel` 的对应位。
**当 sel 来得早、数据来得晚时 (b) 明显更好**；反过来（晚到的 sel）
(a) 的最后一级可以做"晚到信号后置"优化 —— 见
[`../arch-technique/late-arriving-signal.md`](../arch-technique/late-arriving-signal.md)。

这也是为什么**仲裁器应当直接输出 one-hot grant**
（见 [`fixed-priority-arbiter.md`](fixed-priority-arbiter.md)）：
编码成二进制再解码回 one-hot 去驱动 mux，是白付两个 O(log N)。

### 二号论点：FSM 的 one-hot vs binary

- one-hot：N 个触发器（vs log N 个），但**次态逻辑和输出逻辑都变浅**
  （状态判断是看一根线，不是译码）。状态数少（≤16）时通常 **面积也不亏**，
  因为省下的组合逻辑抵掉了多出来的触发器。
- binary：触发器少，但每次用状态都要译码。
- **综合工具会自己改 FSM 编码**（yosys 的 `fsm` pass、DC 的
  `set_fsm_encoding`），所以手写的编码可能根本没生效。
  详见 [`../arch-technique/fsm-encoding.md`](../arch-technique/fsm-encoding.md)。

### 三号论点：thermometer 是"占用率"的自然表示

FIFO 占用、credit 计数这类量，如果用 thermometer 表示：
- "满/空"判断 = 看一根线（O(1)），不需要比较器；
- 增减 = 移位（O(1)），不需要加法器；
- 但要拿到数值就得 popcount（贵），而且要 N 个触发器而不是 log N 个。

**N 很小（≤16）且只需要阈值判断时，thermometer 计数器比二进制计数器
延时好得多。** N 大就不划算。和
[`../storage-flow/credit-flow-control.md`](../storage-flow/credit-flow-control.md)
的计数器实现直接相关。

## 什么时候选它 / 什么时候别用

- **默认选择：让编码在整条路径上保持一致，不要反复转。**
  这张卡最有价值的一条就是这句。
- **N 小（≤32）、要驱动 mux 或做阈值判断** → one-hot / thermometer。
- **N 大、要存起来或送出模块** → binary（位宽小，寄存器和连线都省）。
- **跨时钟域的多位计数** → gray，见
  [`../storage-flow/async-fifo.md`](../storage-flow/async-fifo.md)。
- **输入可能不是 one-hot** → **别用编码器**，用优先编码器
  （[`find-first-one.md`](find-first-one.md)）。
- **只要 thermometer 的数值** → 先问问真的需要数值吗；
  多半只需要"够不够"，那就是一根线。

## 实现要点与坑

- **非 one-hot 输入喂给编码器 = 静默的数据损坏。** 见上。
  防御手段是断言：
  ```verilog
  assert property (@(posedge clk) $onehot(sel));   // 或 $onehot0 允许全零
  ```
  **写了断言仿真才管用，综合出来的电路照样错** —— 断言防的是
  "开发阶段没发现"，不是"流片后不出错"。真有可能非 one-hot 就要用优先编码器。
- **`1 << bin` 的位宽陷阱。** `bin` 取值可能 ≥ N 时（比如 N 不是 2 的幂），
  移出去的 1 会丢，`onehot` 全零。要么保证 `bin < N`，要么显式饱和。
- **N 不是 2 的幂时，one-hot 有 N 个合法值但 binary 有 2^⌈log N⌉ 个编码**，
  多出来的是非法状态。FSM 里必须定义 `default` 分支
  （或者用 one-hot + 奇偶校验来检测），否则综合出的电路进了非法态就出不来。
- **X 传播**：`case` 没有 `default` 时，仿真里非法状态给出 X，
  而综合出的电路给出某个确定值。**仿真通过不代表电路对**，
  这是 FSM 的经典 RTL/门级不一致来源。
- **保层级（`params.yaml` 的 `keep_hierarchy:`）通常不需要**，因为这些转换本来就是希望工具去优化的
  纯布尔函数。但**只要你在做"one-hot mux vs binary mux"这类结构对比，
  就必须加** —— 两者功能完全等价，ABC 的 `&dch` 一定会把它们收敛成同一个网表
  （`docs/pitfalls.md` 的 P-3）。这是本卡唯一需要 `keep_hierarchy` 的场景，
  但它恰好也是本卡最值得测的实验。
- **别相信"手写解码器比工具好"。** binary→one-hot 是小规模布尔函数，
  综合工具做得很好。这张卡的所有转换都属于"先测 `TOOL` 档再决定"的那一类，
  和 [`find-first-one.md`](find-first-one.md)、
  `../arith/comparator.md` 同批。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
// 转换本身太小，不值得单独做设计；有实验价值的是"用哪种编码去选数据"
module MUX_NTO1 #(
    parameter IN_N             = 16,
    parameter DAT_W            = 32,
    parameter SCHEME           = 0,         // 0 BINARY（mux 树） | 1 ONEHOT（AND-OR） | 2 TOOL
    parameter DECODE_INSIDE_EN = 0          // 1: 内部把 binary 解码成 one-hot
)(
    input  [IN_N*DAT_W-1:0]    i_dat,
    input  [$clog2(IN_N)-1:0]  i_sel_bin,
    input  [IN_N-1:0]          i_sel_oh,
    output [DAT_W-1:0]         o_dat
);
    localparam SCHEME_BINARY = 0;
    localparam SCHEME_ONEHOT = 1;
    localparam SCHEME_TOOL   = 2;
```

**这张卡的实验载体应该是 mux，不是转换器本身** ——
单独测一个 `1 << bin` 只会得到几十个门的噪声，
而 "N:1 宽 mux 用哪种选择编码" 是个真实的、反复出现的设计决策。

## 出处

- Weste, N. & Harris, D., *CMOS VLSI Design*, 4th ed., Addison-Wesley, 2010 ——
  解码器、编码器、AND-OR mux 与 one-hot 选择的电路实现。
- Warren, H.S., *Hacker's Delight*, 2nd ed., Addison-Wesley, 2012 ——
  gray ↔ binary 与相关位技巧。
- 格雷码在跨时钟中的用法见
  [`../storage-flow/async-fifo.md`](../storage-flow/async-fifo.md) 的出处
  （Cummings 的 SNUG 论文）。
- 前缀网络见 [`../arith/prefix-adders.md`](../arith/prefix-adders.md)。

## 本地实测

暂无。**建议只做一个实验，就是上面那个 `mux_nto1`**：
`SEL_ENC = BINARY / ONEHOT / TOOL`，扫 `N = 4/8/16/32`、`W = 8/64`。

它同时回答三件事：
1. one-hot 选择到底快多少（一号论点，本类最实用的一条）；
2. 宽度 `W` 怎么改变结论（W 大时 mux 本身主导，编码方式的影响被稀释）；
3. **工具会不会把两种写法做成同一个东西** —— 如果 `TOOL` 档和另外两档
   三者面积延时全同，那就是 `keep_hierarchy` 没生效，先查流程。

纯组合、无握手，现有 `flow/` 直接能跑。
