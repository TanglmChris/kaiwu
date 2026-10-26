# Skid Buffer（Skid Buffer / Pipeline Register Slice）

- **类别**：存储与流控
- **一句话**：在 valid-ready 链路上插一级寄存器又**不丢吞吐**的最小件 ——
  代价是必须能存下 2 个数据，因为 ready 的反压比 valid 慢一拍到。
- **典型用途**：切断 valid-ready 链路上的组合路径（AXI register slice）、
  跨模块边界打拍、把长反压链切成多段。

## 结构

问题的根源：valid-ready 握手里，**`ready` 是从下游往上游倒着传的组合信号**。
一条 N 级的链路，`ready` 会串成一条 N 级深的组合路径 —— 这几乎总是关键路径。

想切断它就得给 `ready` 打拍。但一旦 `ready` 晚一拍到达上游，上游在这一拍里
**已经把数据送出来了**，这个数据必须有地方放。所以叫 skid（打滑）buffer：
刹车指令晚到一拍，得留出一个车位。

最小实现是两个存储位 + 一个状态位：

```
        ┌──────────┐
 up ───►│ data_reg │───┬──► down
        └──────────┘   │
        ┌──────────┐   │
        │ skid_reg │───┘   (只在下游 stall 的那一拍写入)
        └──────────┘
```

- **正常态**：下游 ready，数据直通 `data_reg`，`up_ready = 1`。
- **下游 stall 的第一拍**：`data_reg` 里的数还没走，上游又送来一个 ——
  存进 `skid_reg`，同时拉低 `up_ready`。
- **下游恢复**：先吐 `skid_reg`，再回到正常态。

关键点：**`up_ready` 必须是寄存器输出**，否则白做。如果 `up_ready` 还是
`down_ready` 的组合函数，组合路径根本没被切断。

## 关键路径

- 切断前：`ready` 链 **O(N)**，N 是级数。
- 切断后：每级 **O(1)**，与链长无关。这就是 skid buffer 的全部意义。
- 数据路径本来就是寄存器到寄存器，不受影响。

## PPA 权衡

- **面积**：每级 2×WIDTH 个触发器 + 少量控制。比"只打一拍"贵一倍存储。
- **延时**：吞吐保持 100%（每拍一个数据），只增加 1 拍延迟。
- **对比廉价做法**：
  - 只打 `valid`/`data`、`ready` 直通 —— 面积省一半，但 `ready` 路径没切断，
    等于没解决问题。
  - `ready` 打拍但不加 skid —— 会丢数据，**功能错误**，不是权衡。
  - 半吞吐 register slice（每两拍一个数据）—— 面积同 skid 一半，
    吞吐砍半。链路不满载时可接受。

## 什么时候选它 / 什么时候别用

- **`ready` 是关键路径** → skid buffer，这是它存在的唯一理由。
- **链路很长（跨模块、跨 die 区域）** → 每隔几级插一个。
- **吞吐要求不满**（比如平均占用 < 50%）→ 半吞吐 slice 更省。
- **上游本来就不会背靠背发** → 不需要，直接打拍即可。
- **只是想加缓冲深度** → 用 FIFO，别用 skid buffer 串一堆；
  见 [`sync-fifo.md`](sync-fifo.md)。

## 实现要点与坑

- **valid-ready 的两条协议铁律必须守住**（AXI 的说法）：
  1. `valid` 一旦拉高，在握手完成前**不得撤销**，数据也不得改变。
  2. `ready` 可以随意拉高拉低，**不得依赖 `valid`**（否则两边互等，死锁）。
     "等 valid 来了再决定 ready" 是最常见的死锁写法。
- **`up_ready` 组合依赖 `down_ready` 是最常见的实现错误**，写出来仿真能过、
  吞吐也对，但没有切断路径 —— 综合完看时序才发现白干。**必测点：
  确认 `up_ready` 的驱动是触发器输出。**
- 复位后 `valid` 必须为 0，否则下游会收到一个幽灵数据。
- **不需要 `keep_hierarchy`**：这是时序结构不是组合结构，寄存器边界
  天然保住了，综合不会把它优化掉。
- 满/空的判断只有两级，别用计数器，用两个状态位更快更小。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module SKID_BUFFER #(
    parameter DAT_W  = 32,
    parameter SCHEME = 0        // 0 FULL（全吞吐，2 拍存储） | 1 HALF（半吞吐，1 拍） | 2 BYPASS（不打拍，做对照组）
)(
    input                  clk, rst_n,
    input                  i_up_vld,   output              o_up_rdy,
    input      [DAT_W-1:0] i_up_dat,
    output                 o_down_vld, input               i_down_rdy,
    output     [DAT_W-1:0] o_down_dat
);
    localparam SCHEME_FULL   = 0;
    localparam SCHEME_HALF   = 1;
    localparam SCHEME_BYPASS = 2;
```

`BYPASS` 档保留作对照组：它就是"不插 slice"，用来量插入前后关键路径的差。
这是这张卡最直接的实验价值。

## 出处

- ARM, *AMBA AXI and ACE Protocol Specification* —— valid-ready 握手的两条
  依赖规则（`valid` 不得等 `ready`、握手前不得撤销）出自这里，是所有
  skid buffer 实现的正确性前提。
- ZipCPU, "Building a Skid Buffer for AXI processing"（zipcpu.com）——
  公开的逐步推导与 Verilog 实现，**未逐行核实，引用具体代码前自行确认**。

Skid buffer 没有单一经典论文，它是 valid-ready 协议的直接推论：
`ready` 打拍 ⇒ 反压晚一拍 ⇒ 需要一个额外存储位。

## 本地实测

暂无。建议做法：把 `MODE = BYPASS / FULL` 作为对照，测同一条链路插入前后的
关键路径与面积。这是**纯时序结构**，不受 `arith/` 那条"工具会不会优化掉结构"
的困扰，实验干净。

需要注意本仓库当前的测量边界：**`cycles` 的语义是「跑完激励用了多少拍」**，
对带握手的设计不够用（见 内部#7）。skid buffer 是本知识库里第一个
真正需要 valid-ready 激励的结构，做它的实验前要先把仿真驱动泛化。
