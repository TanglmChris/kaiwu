# 反压范式对比（valid-ready / credit / stall 链）

- **类别**：架构范式与技巧
- **一句话**：三种让上游"停一下"的办法 —— valid-ready 最通用但会拉出
  一条组合长路径，credit 把反压延时和链路长度解耦，
  stall 链最简单但扇出和路径都最糟。
- **典型用途**：任何多级流水的连接处 —— 模块间接口、
  NoC 链路、总线桥、DMA 通路、
  变延迟运算单元（除法器、CORDIC）接进定长流水线。

## 结构

### 一、valid-ready（AXI 式握手）

```
生产者 --valid/data--> 消费者
生产者 <----ready----- 消费者
数据在 valid && ready 的那一拍转移
```

**两条铁律**：
1. **`valid` 不能依赖 `ready`**（组合上）。违反会死锁：
   双方都等对方先动。
2. `ready` **可以**依赖 `valid`（"有货我才收"），
   但这样就产生了一条从下游到上游的组合路径。

**核心问题**：`ready` 从最下游一路组合地传到最上游，
N 级流水就是 N 级 `ready` 逻辑串起来的一条长路径。
**这条路径经常是整个设计的关键路径，而且它随流水加深而变长** ——
所以"加流水提频率"会被反压路径反噬。

**解法是 skid buffer**（寄存输出的握手级）：把 `ready` 路径切断，
代价是 2 个数据缓冲的面积和 1 拍延迟。
全部细节见
[`../storage-flow/skid-buffer.md`](../storage-flow/skid-buffer.md)。

### 二、credit-based（信用流控）

```
发送方持有 N 个 credit，每发一拍减 1，减到 0 就停
接收方每腾出一个槽，回一个 credit（可以延迟若干拍到达）
```

**关键性质：反压信号可以是流水的，不需要组合地传回来。**
所以：

- 发送方和接收方之间**可以插任意多级寄存器**，
  不影响正确性，只影响需要的 credit 数。
- 需要的 credit 数 ≈ **往返延迟（RTT）× 每拍最大发送量**，
  再加上接收方的处理缓冲。credit 给少了就吞吐不足（发一拍停几拍），
  给多了就浪费缓冲面积。
- **接收方必须有 credit 数那么多的缓冲**，否则 credit 是空头支票。

全部细节见
[`../storage-flow/credit-flow-control.md`](../storage-flow/credit-flow-control.md)。

### 三、stall 链 / 全局 enable

```verilog
always @(posedge clk) if (!stall) stage_n <= stage_n_minus_1;
```

一根 `stall` 信号喂给所有流水寄存器的使能端。

- 最简单，代码量最少。
- **`stall` 的扇出等于流水线里所有触发器数** —— 高扇出、长连线，
  需要复制（见 [`logic-replication.md`](logic-replication.md)）。
- **`stall` 本身通常是组合地从下游产生的**，
  于是既是长路径又是高扇出，两头都糟。
- 停就是整条流水线一起停，**没有"局部停"的能力**，
  上游的气泡填不进来，吞吐损失比必要的大。

### 四、不做反压（valid-only）

下游承诺永远能收（比如后面是一个足够大的 FIFO，或者一个恒定吞吐的消费者）。
**最便宜，零反压逻辑。** 前提是这个承诺必须在架构层面成立且被验证 ——
"我觉得应该来得及"不算。

### 四者对照

| | 组合反压路径 | 缓冲需求 | 扇出 | 能容忍链路延迟 | 面积 |
|---|---|---|---|---|---|
| valid-ready（裸） | **长，随级数增长** | 0 | 低 | 否 | 最小 |
| valid-ready + skid | 一级 | 每级 2 拍 | 低 | 否 | 中 |
| credit | **无** | RTT × 带宽 | 低 | **是** | 中~大 |
| stall 链 | 长 | 0 | **很高** | 否 | 小 |
| valid-only | 无 | 靠下游保证 | 无 | — | **最小** |

## 关键路径

- **裸 valid-ready 的 `ready` 路径是这张卡的核心问题。**
  它是"深流水 + 全流水吞吐"这个组合的固有代价，
  只能靠切（skid）或换范式（credit）解决。
- credit 的关键路径只有本地的 credit 计数器比较（`credit != 0`），
  **和链路长度无关**。这是 credit 唯一但决定性的优势。
- stall 链的路径 = 下游条件 + 一路传上来 + 巨大扇出的驱动延时。

## PPA 权衡

- **面积**：valid-only < 裸 valid-ready ≈ stall 链 < skid < credit。
  credit 最贵是因为它要缓冲 RTT 那么多数据。
- **延迟**：skid 每级 +1 拍；credit 不额外增加数据延迟
  （credit 返回的延迟只影响吞吐，不影响单笔延迟）。
- **吞吐**：裸 valid-ready 和 credit 都能做到 100%（credit 足够时）；
  stall 链因为不能局部停，在断续负载下吞吐更差。
- ⚠️ **功耗对比本仓库测不了**（`docs/data-credibility.md` D-1）。
  直觉上 credit 的计数器和返回通路是额外翻转，但量级未知。

## 什么时候选它 / 什么时候别用

- **模块内部、短流水、频率不紧** → 裸 valid-ready，最省事。
- **深流水、要满吞吐、频率紧** → valid-ready + skid buffer。
  **这是最常见的正确答案。**
- **跨长距离/跨芯片/跨时钟域、或者中间要插很多级寄存器** →
  **credit**。这是它唯一无可替代的场景。
- **短流水、吞吐要求低、面积极紧** → stall 链可以接受。
- **下游是大 FIFO 或恒定消费者** → valid-only，别过度设计。
- **变延迟单元**（除法器、CORDIC）接进定长流水 →
  必须有反压，而且要想清楚"算不完的时候上游怎么办"，
  见 [`folding-time-multiplex.md`](folding-time-multiplex.md)。

## 实现要点与坑

- **`valid` 依赖 `ready` = 死锁。** 最常见的写法错误是
  `assign valid = ready && has_data;`。这不是性能问题，是挂死。
  **要写断言**：`valid` 一旦拉高，在 `ready` 到来之前不能撤，
  且数据不能变（AXI 的 VALID 稳定性要求）。
- **反压下的数据必须不丢不重。** 这是所有握手接口的第一必测项，
  而且**只有在随机 backpressure 激励下才测得出来** ——
  `ready` 恒为 1 的激励会让 skid buffer 的整个旁路分支从不被走到。
  **必须有随机拉低 `ready` 的测试。**
- **credit 的初值和复位。** 复位后 credit 应当等于接收方的缓冲深度。
  复位不同步（发送方复位了、接收方没有）会让 credit 账目永久错位，
  表现为"跑一段时间后吞吐莫名下降"或"溢出"。
  见 [`../storage-flow/reset-strategy.md`](../storage-flow/reset-strategy.md)。
- **credit 数不足时不是坏，是慢。** 这类问题不会在功能仿真里报错，
  只会让吞吐低于预期。**必须量吞吐，不能只看"通过"** ——
  这正是记录里 `cycles` 字段该起的作用。
- **stall 链的 `stall` 一定要复制。** 见
  [`logic-replication.md`](logic-replication.md)，
  而且要注意 `opt_merge` 会把副本合并回去。
- **仲裁与反压的交互**：被授权者当拍收不下时指针要不要推进，
  见 [`../priority-encode/round-robin-arbiter.md`](../priority-encode/round-robin-arbiter.md)
  的 `USE_READY`。**这是仲裁 + 反压组合起来才出现的 bug 类别。**
- **保层级（`params.yaml` 的 `keep_hierarchy:`）**：比较三种范式时，它们**功能不等价**
  （延迟和时序行为都不同），工具不会把它们收敛，
  所以**不需要**为此设边界。但接口两侧如果被 flatten 到一起，
  `ready` 路径会和数据逻辑一起被重组，**skid buffer 的切断效果可能被削弱** ——
  这一点没验证过，值得实测确认。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module LINK #(
    parameter DAT_W       = 32,
    parameter SCHEME      = 1,          // 0 VR（裸握手） | 1 VR_SKID | 2 CREDIT | 3 STALL | 4 VALID_ONLY
    parameter PIPE_STAGES = 4,          // 中间流水级数
    parameter CREDIT_N    = 8           // SCHEME = SCHEME_CREDIT 时的信用数
)(
    input clk, rst_n,
    input              i_vld, output o_rdy, input  [DAT_W-1:0] i_dat,
    output             o_vld, input  i_rdy, output [DAT_W-1:0] o_dat
);
    localparam SCHEME_VR         = 0;
    localparam SCHEME_VR_SKID    = 1;
    localparam SCHEME_CREDIT     = 2;
    localparam SCHEME_STALL      = 3;
    localparam SCHEME_VALID_ONLY = 4;
```

**`PIPE_STAGES` 是这个实验的关键维度**：它能直接展示核心论点 ——
`VR` 的关键路径随 `PIPE_STAGES` 增长，`VR_SKID` 和 `CREDIT` 不随之增长。
**这是一条形状清晰、容易证伪的预期曲线**，很适合做本类的第一个握手实验。

## 出处

- Dally, W.J. & Towles, B., *Principles and Practices of Interconnection
  Networks*, Morgan Kaufmann, 2004 —— credit-based 流控、
  缓冲与 RTT 的定量关系（本库
  [`../storage-flow/credit-flow-control.md`](../storage-flow/credit-flow-control.md)
  也引它）。
- ARM, *AMBA AXI Protocol Specification* —— VALID/READY 的依赖规则
  （VALID 不得等待 READY）。
- skid buffer 的实现出处见
  [`../storage-flow/skid-buffer.md`](../storage-flow/skid-buffer.md)。

## 本地实测

暂无。**这张卡被 内部#7 那条流程前提直接挡住** ——
它的每一个结论都要握手激励和吞吐测量，而现有 `flow/sim` 和记录里的
`cycles` 语义是按组合/短流水加法器设计的。

**这是第四次指向同一个前提**（`arith/` 的除法器与 CORDIC、
`storage-flow/` 的 skid 与 credit、`arch-technique/` 的折叠、
再加这张卡）。四类知识里有三类的核心实验都停在这里。

流程支持之后，本卡的实验是**整个知识库里优先级最高的一个**，
因为它同时验证两件事：
(a) 三种反压范式的关键路径随 `STAGES` 的走势（架构结论）；
(b) **仿真流程本身能不能正确测吞吐** —— 一个 credit 不足的链路
应当表现为 `cycles` 变多而不是仿真失败，
这是对记录里 `cycles` 语义的一次真实检验。
