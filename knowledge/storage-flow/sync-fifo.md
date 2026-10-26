# 同步 FIFO（Synchronous FIFO）

- **类别**：存储与流控
- **一句话**：同一时钟域下的弹性缓冲，难点不在存储而在**满/空判断**——
  指针法要多一位来区分"绕了一圈"和"回到原点"。
- **典型用途**：速率匹配、突发吸收、解耦生产者与消费者、
  给 valid-ready 链路加深度。

## 结构

存储体是一块双口 RAM 或寄存器堆，读写各一个指针。核心问题是：
**读写指针相等时，是空还是满？**

### 指针法（多一位）

指针宽度取 `$clog2(DEPTH) + 1`，低 `$clog2(DEPTH)` 位寻址，最高位是"圈数"：

```
empty = (wptr == rptr)                                    // 完全相等
full  = (wptr[MSB] != rptr[MSB]) && (wptr[MSB-1:0] == rptr[MSB-1:0])
```

即：低位相同、最高位不同 ⇒ 写指针比读指针多绕了一圈 ⇒ 满。
**要求 `DEPTH` 是 2 的幂**，否则指针回绕不再等价于最高位翻转。

### 计数器法

单独维护一个占用计数 `count`：

```
count <= count + wr_en - rd_en;
empty = (count == 0);
full  = (count == DEPTH);
```

深度可以是任意值，判断直白。代价是 `count` 的加减法在关键路径上，
而且它是**读写两侧共同更新的单点**。

### 两者怎么选

| | 指针法 | 计数器法 |
|---|---|---|
| 深度 | 必须 2 的幂 | 任意 |
| 满/空判断 | 比较（O(log n) 或更浅） | 需要 count 的加减 |
| 关键路径 | 更短 | count 的进位链 |
| 跨时钟域 | **可以**（格雷码化，见异步 FIFO） | **不行**（count 无法安全跨域） |

**同步 FIFO 里两者都能用；异步 FIFO 只能用指针法**——这是指针法真正的
价值所在，也是它值得默认掌握的理由。

## 关键路径

- 指针法：指针增量 O(log DEPTH) + 比较 O(log DEPTH)，两者可并行准备。
- 计数器法：`count` 的加减 O(log DEPTH)，且满/空比较串在其后。
- **真正的关键路径往往不是这些**，而是 `full`/`empty` 到上下游 `ready`/`valid`
  的组合路径 —— 如果 FIFO 的 `ready` 直接由 `full` 组合驱动，
  又接进一条长链，问题和 [`skid-buffer.md`](skid-buffer.md) 里的一样。

## PPA 权衡

- **存储本体主导面积**：`DEPTH × WIDTH`。深度翻倍面积翻倍，
  控制逻辑那点面积可以忽略。
- **寄存器堆 vs SRAM 的分界线**：小而窄（几十个 bit 总量）用触发器，
  大了必须上 SRAM 宏。分界点是工艺相关的，本地流没有 SRAM 宏
  （`~/pdk/asap7/asap7_sram_0p0` 拉了但流程没接），所以**本地测出来的
  深 FIFO 面积会严重偏大**，这是测量边界不是结论。
- **深度不是越大越好**：深度只在突发长度的量级上有意义，超过之后
  纯属浪费面积和功耗。定深度要看流量模型，不要拍脑袋。
- **功耗**：空闲时 FIFO 应该几乎不耗动态功耗 —— 前提是没写入时
  存储体的写使能真的关掉了（见「实现要点」）。

## 什么时候选它 / 什么时候别用

- **两侧速率不匹配、有突发** → FIFO。
- **只是要切断组合路径、吞吐不能降** → skid buffer，别用 FIFO
  （FIFO 更贵且延迟更大）。
- **跨时钟域** → 异步 FIFO，见 [`async-fifo.md`](async-fifo.md)。
  **同步 FIFO 加两级同步器不等于异步 FIFO**，这是个危险的错误。
- **深度只要 1~2** → 直接用 skid buffer 或简单的 register slice。
- **需要乱序取用、按 tag 取** → 那不是 FIFO，是 buffer + 分配器，
  见 [`pingpong-circular-buffer.md`](pingpong-circular-buffer.md)。

## 实现要点与坑

- **`DEPTH` 非 2 的幂时指针法直接失效**，必须换计数器法或改深度。
  这是参数化时最容易漏的边界，**必测点**。
- **满时写、空时读的行为必须定义**：忽略？还是覆盖？还是拉 error？
  不定义就会在集成时变成两个模块各按各的理解来。
- **first-word-fall-through (FWFT) vs 标准模式**：
  FWFT 让数据在 `rd_en` 之前就出现在输出上（读延迟 0），
  和 valid-ready 语义天然契合；标准模式读延迟 1 拍。
  **两者的 `empty` 语义不同**，混用是经典 bug。参数化时要显式区分。
- **写使能门控**：存储体的写使能应该是 `wr_en && !full`，
  而不是把 `wr_en` 直接接进去再靠外部保证。同理读侧。
- **`almost_full` / `almost_empty` 的阈值**要留出反压传播的拍数，
  不是随便取个数。
- **不需要 `keep_hierarchy`**：FIFO 的结构由寄存器和存储体边界保住，
  综合不会把指针法优化成计数器法。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module SYNC_FIFO #(
    parameter DAT_W   = 32,
    parameter DEPTH   = 16,
    parameter COUNT_EN = 0,       // 0 PTR（指针法，DEPTH 须为 2 的幂） | 1 COUNT（计数器法）；二选一写成 _EN（D16）
    parameter FWFT_EN = 1         // 1 = first-word-fall-through
)(
    input clk, rst_n,
    input                  i_wr_vld, output o_wr_rdy, input [DAT_W-1:0] i_wr_dat,
    output                 o_rd_vld, input  i_rd_rdy, output [DAT_W-1:0] o_rd_dat
);
```

用 valid-ready 而不是 `wr_en`/`full` 做接口：前者可以直接串进链路，
后者每次集成都要写一遍转换逻辑。`COUNT_EN` 作为对照组，
测「指针法 vs 计数器法」在关键路径和面积上的实际差距。

## 出处

同步 FIFO 没有单一经典论文（它太基础）。指针法多一位的技巧和
FWFT 的语义区分，在 Cliff Cummings 的异步 FIFO 论文里有完整推导
（同步 FIFO 是其退化情形），见 [`async-fifo.md`](async-fifo.md) 的出处。

## 本地实测

暂无。建议与 [`skid-buffer.md`](skid-buffer.md) 一起做，共用同一套
valid-ready 激励。可扫的维度：`DEPTH`（面积随深度的斜率）、
`COUNT_EN`（指针 vs 计数器的关键路径差）、`FWFT`。

注意本仓库没有接 SRAM 宏，**深 FIFO 的面积数字只反映触发器实现**，
不能外推到真实设计。
