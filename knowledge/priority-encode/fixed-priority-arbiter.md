# 固定优先级仲裁（Fixed-Priority Arbiter）

- **类别**：优先级与编码
- **一句话**：`grant[i] = req[i] & 没有比我优先级更高的请求` ——
  它**就是** [`find-first-one.md`](find-first-one.md)，
  换了个名字和一套时序上的坑。
- **典型用途**：中断控制器、总线主设备仲裁、
  异常/陷阱优先级、资源池分配、
  [`round-robin-arbiter.md`](round-robin-arbiter.md) 的构件。

## 结构

```
grant[i] = req[i] & ~( req[i-1] | ... | req[0] )     // 位 0 优先级最高
```

后半截是 `req` 的排他性前缀 OR，所以三种实现和 find-first-one 一一对应：

| 实现 | 延时 | 说明 |
|---|---|---|
| 行波（"进位链"）| O(n) | `no_hi[i+1] = no_hi[i] & ~req[i]`，一条与链 |
| 前缀树 | O(log n) | Sklansky / KS / Brent-Kung 原样搬用 |
| 算术 `req & -req` | 一条进位链 | 只能做 LSB 优先 |
| 两级分组 | O(log n)，常数小 | n ≥ 32 的默认做法 |

细节见 [`find-first-one.md`](find-first-one.md)，这里不重复。

### 输出形态

- **one-hot `grant`**：直接当下游 mux 的选择信号用，**推荐**。
- **二进制 `grant_id`**：要多一棵编码树。**只在需要把编号存起来
  或送出去时才生成** —— 编码完再解码是白付两个 O(log n)。
- **`grant_valid = |req`**：一定要有。全零请求时 `grant` 全零、
  `grant_id` 是垃圾。

### 和"资源分配"的组合

常见形态是"n 个请求者抢 1 个资源"（这张卡），
但还有"n 个请求者抢 m 个资源"（allocator）。后者不是简单地跑 m 次仲裁 ——
跑 m 次的朴素做法是把前一次的 grant 从 req 里剔掉再跑，
**m 次串行 = m·O(log n)**。真正的做法（wavefront / separable allocator）
超出这张卡，见 Dally & Towles。

## 关键路径

- 前缀实现 **O(log n)**，节点是单个 OR/AND，比加法器的 (g,p) 轻。
- **但仲裁器的真实关键路径往往不在仲裁器里**：典型形态是

  ```
  req（来自各请求者的组合逻辑） → 仲裁 O(log n) → grant → 数据 mux → 下游
  ```

  这一整条常常是设计里最长的组合路径。见"实现要点与坑"。

## PPA 权衡

- 面积 O(n)，极便宜（32 路仲裁比一个 32 位加法器还小）。
- 前缀 vs 行波：n ≤ 8 基本没差；n ≥ 32 差距明显。
- **和 round-robin 比，固定优先级省掉了：** 状态寄存器、掩码逻辑、
  第二棵优先级树。大约是 round-robin 面积的 **一半以下**。
  这个差价就是"公平性"的价钱，值不值要看场景（见下）。

## 什么时候选它 / 什么时候别用

- **优先级本来就有语义差别** → 固定优先级是**正确**的，不是将就。
  中断优先级、异常优先级、"刷新优先于普通读写"，这些就该是固定的。
- **请求者天然不会持续满载** → 固定优先级够用，低优先级也能被服务到。
- **多个对等的请求者争带宽** → **别用**，低优先级会被饿死。
  用 [`round-robin-arbiter.md`](round-robin-arbiter.md)。
- **需要"最多等 k 拍"的保证** → 固定优先级给不了任何上界，
  连"最终会被服务"都保证不了。
- **只有 2 个请求者** → 别叫仲裁器了，一个 mux + 一个触发器做乒乓就行。

## 实现要点与坑

- **饿死不是理论风险。** 一个持续拉高 `req[0]` 的请求者会让
  `req[31]` 永远拿不到 grant。这是固定优先级唯一的、也是全部的问题，
  设计评审时必须回答"最低优先级那个会不会饿死"。
- **`grant` 必须是 one-hot，要写断言。**
  ```verilog
  assert property (@(posedge clk) $onehot0(grant));
  ```
  非 one-hot 的 grant 会让下游的 AND-OR mux 输出多个数据的按位或 ——
  一个安静的、只在特定请求组合下出现的数据损坏。
- **grant 不能直接反馈进 req，会形成组合环。**
  典型误写：请求者用 `grant` 来决定 `req`（"没拿到就不请求了"）。
  `req` 必须是寄存器输出，或至少不依赖本拍的 `grant`。
- **"仲裁 + 数据 mux"是一条完整的组合路径。** 仲裁器本身只有 log n 级，
  但它后面通常紧跟一个 n:1 的数据 mux（宽度可能 512 位）。
  真正贵的是那个 mux。两条改法：
  (a) **把 grant 打一拍**再选数据（加一拍延迟）；
  (b) **数据 mux 用 one-hot 的 AND-OR 形式**并和仲裁并行展开
      （见 [`onehot-binary-thermometer.md`](onehot-binary-thermometer.md)）。
- **grant 与 ready 的关系要想清楚。** 如果被授权者当拍不能接收
  （下游 `ready` 为低），这一拍的 grant 就浪费了。两种口径：
  (a) `req` 里就已经包含"我能接收"；
  (b) 仲裁结果只在 `grant & ready` 时才算数。
  **(b) 会把 `ready` 拉进仲裁的关键路径**，
  和 [`../storage-flow/skid-buffer.md`](../storage-flow/skid-buffer.md)
  里的组合 ready 路径是同一类问题。
- **保层级（`params.yaml` 的 `keep_hierarchy:`）**：只有在比较不同前缀网络时才需要。
  单纯用一个仲裁器不需要 —— 它的功能语义就是要工具去优化的。
  但**只要参数里出现了 `SCHEME`，就一定要加**，否则测出来的差异是假的
  （`docs/pitfalls.md` 的 P-3）。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module FIXED_PRIO_ARB #(
    parameter REQ_N     = 8,
    parameter SCHEME    = 0,         // 0 PREFIX | 1 RIPPLE | 2 ARITH | 3 TOOL（casez）
    parameter GEN_ID_EN = 0          // 是否额外输出二进制编号
)(
    input  [REQ_N-1:0]         i_req,
    output [REQ_N-1:0]         o_grant,      // one-hot
    output [$clog2(REQ_N)-1:0] o_grant_id,
    output                     o_any_grant   // 不叫 o_vld：这不是握手
);
    localparam SCHEME_PREFIX = 0;
    localparam SCHEME_RIPPLE = 1;
    localparam SCHEME_ARITH  = 2;
    localparam SCHEME_TOOL   = 3;
```

无时钟、无复位 —— 固定优先级仲裁是**纯组合**的。
一旦接口里出现 `clk`，就说明它已经不是这张卡了
（多半是想做 round-robin）。

## 出处

- Dally, W.J. & Towles, B., *Principles and Practices of Interconnection
  Networks*, Morgan Kaufmann, 2004 —— Arbitration 一章：
  固定优先级、round-robin、matrix 仲裁器与 allocator 的系统梳理。
  本类里 [`round-robin-arbiter.md`](round-robin-arbiter.md) 也引它。
- Weste, N. & Harris, D., *CMOS VLSI Design*, 4th ed., Addison-Wesley, 2010 ——
  优先编码器与仲裁的电路实现。
- 前缀网络的理论基础见
  [`../arith/prefix-adders.md`](../arith/prefix-adders.md)。

## 本地实测

暂无。**纯组合、无握手，现有 `flow/` 直接能跑。**
和 [`find-first-one.md`](find-first-one.md) 共用同一套前缀网络，
应该做成同一个设计的两个输出模式，一次扫参同时覆盖。

真正有 PPA 意义的对比不在这张卡内部，而是
**固定优先级 vs round-robin 的面积/延时差价** ——
那是本类里最值得测的一组数，见
[`round-robin-arbiter.md`](round-robin-arbiter.md) 的「本地实测」。
