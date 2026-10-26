# Credit-based 流控（Credit-based Flow Control）

- **类别**：存储与流控
- **一句话**：发送方**自己记着**接收方还剩多少空位，所以不需要等反压信号
  绕回来 —— 用一个计数器换掉一条长反压路径，代价是必须预留满往返延迟的缓冲。
- **典型用途**：长距离链路（跨 die、跨芯片、NoC）、深流水互连、
  反压路径已经成为关键路径的场合。

## 结构

### 和 valid-ready 的区别

valid-ready 是**即时反压**：接收方满了就拉低 `ready`，发送方当拍就停。
前提是 `ready` 能在一个周期内传回来 —— 链路一长就不成立。

credit 是**预算制**：

```
发送方                                    接收方
credit = N (初始 = 接收方 buffer 深度)
  │
  ├─ 每发一个数据: credit--             收到数据存进 buffer
  ├─ credit == 0: 停发
  └─ 收到 credit_return: credit++  ◄──  每消费一个: 回一个 credit
```

**发送决策只看本地的 `credit` 计数器**，不看任何来自接收方的组合信号。
链路可以插任意多级流水，不影响正确性 —— 只影响需要多深的 buffer。

### 需要多深的 buffer

设往返延迟（发送→接收→credit 回来）为 `RTT` 拍。要维持满吞吐，
发送方必须能在 credit 回来之前一直发：

```
BUFFER_DEPTH >= RTT
```

不满足就会周期性停顿，吞吐 = `BUFFER_DEPTH / RTT`。
**这是 credit 流控唯一的设计公式**，也是它的主要成本。

## 关键路径

- 发送侧：`credit` 计数器的加减 + 零判断，O(log N)，**与链路长度无关**。
- 这正是它相对 valid-ready 的全部优势：把 O(链路级数) 的组合反压路径
  换成 O(log N) 的本地计数。
- 对比 [`skid-buffer.md`](skid-buffer.md)：skid buffer 也切断反压路径，
  但**每级都要付 2×WIDTH 的存储**；credit 只在接收端付一次 buffer，
  中间级可以是纯寄存器。**链路越长，credit 越划算。**

## PPA 权衡

- **面积**：接收端 `RTT × WIDTH` 的 buffer + 两个小计数器。
  中间流水级只要普通寄存器，不用 skid buffer。
- **对比 skid buffer 链**：N 级链路上，
  - skid 链：`N × 2 × WIDTH` 触发器
  - credit：`RTT × WIDTH`（RTT ≈ 2N）+ 中间 `N × WIDTH` 普通寄存器
  数量级相当，但 credit 把存储集中在一端（可以用 SRAM），
  skid 是分散的触发器。**长链路上 credit 更省，也更好布局。**
- **功耗**：credit 回传占一条窄通道，持续翻转。链路很宽时可忽略，
  很窄时（比如 1 bit 数据）反而是开销。
- **延迟**：不增加数据延迟。credit 只影响吞吐上限，不影响单笔延迟。

## 什么时候选它 / 什么时候别用

- **反压路径是关键路径，且链路长** → credit。
- **短链路（1~2 级）** → valid-ready + skid buffer 更简单，别过度设计。
- **多个虚通道 / 多优先级共享物理链路** → credit 几乎是唯一选择
  （每个虚通道一套 credit，物理链路共享）。这是 NoC 的标准做法。
- **接收方 buffer 深度不能保证 ≥ RTT** → 吞吐会打折，
  先算清楚再决定是否接受。
- **需要严格的即时反压语义**（比如接收方要能在任意拍精确叫停）→
  credit 做不到，它是预算制，发出去的就收不回来了。

## 实现要点与坑

- **credit 初值必须精确等于接收方 buffer 深度**。多了会溢出（丢数据），
  少了浪费吞吐。复位后两端的认知必须一致，这是**必测点**。
- **复位不同步是经典 bug**：接收方先复位、发送方后复位，
  credit 计数器和实际 buffer 占用就对不上了。要么共用复位，
  要么设计一个 credit 重同步流程。
- **credit 回传本身也可能被反压**。回传通道必须保证不丢 ——
  通常做成"每拍最多回一个 credit"的窄通道，或者回传累积计数而非脉冲。
  **回传丢一个 credit，吞吐就永久少一格，而且很难查。**
- **计数器位宽**要能表示 0..DEPTH，是 `$clog2(DEPTH+1)` 不是 `$clog2(DEPTH)`。
- **跨时钟域时 credit 计数不能直接跨**（多位信号），
  要么用格雷码，要么在域边界放异步 FIFO 再各自做 credit。
  见 [`cdc-synchronizers.md`](cdc-synchronizers.md)。
- **不需要 `keep_hierarchy`**：这是时序+协议结构，不会被布尔优化抹平。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module CREDIT_SENDER #(
    parameter DAT_W      = 32,
    parameter MAX_CREDIT = 16    // 必须等于接收端 buffer 深度
)(
    input  clk, rst_n,
    input  i_up_vld,  output o_up_rdy, input [DAT_W-1:0] i_up_dat,
    output o_link_vld,                 output [DAT_W-1:0] o_link_dat,
    input  i_credit_return             // 每拍最多一个
);
```

做对照实验时，关键的可扫维度是**链路级数**（插几级流水）：
valid-ready+skid 的关键路径应当随级数增长，credit 的应当持平。
这个对比能直接量化 credit 的价值。

## 出处

- William J. Dally & Brian Towles, *Principles and Practices of
  Interconnection Networks*, Morgan Kaufmann, 2004 —— 流控章节系统对比了
  credit-based、on/off、ack/nack 三类机制，以及 buffer 深度与 RTT 的关系。
  这是互连网络流控的标准教材。

credit 流控在各家总线协议（CHI、多种 NoC 实现）里都有，
但**具体协议细节各不相同，引用前需确认所用协议的规范**。

## 本地实测

暂无。这是本类里**最值得做 PPA 实验**的一张卡，因为它的核心主张
（"反压路径与链路长度解耦"）可以被直接测出来：

- 扫 `LINK_STAGES = 1..8`，对比 `SCHEME = READY_SKID` vs `CREDIT` 的
  关键路径延时。前者应当随级数上升，后者应当持平。
- 面积对比则应当反过来。

前提同样是仿真驱动要先支持 valid-ready 激励（见
[`skid-buffer.md`](skid-buffer.md) 末尾）。
