# 资源共享（Resource Sharing）

- **类别**：架构范式与技巧
- **一句话**：互斥的运算合用一份硬件 —— `sel ? a+b : c+d` 变成
  `(sel?a:c) + (sel?b:d)`，**一个加法器换两个 mux**；
  值不值只看"算子比 mux 贵多少"，而且它会把 mux 塞进关键路径。
- **典型用途**：ALU（加/减/比较合用一个加法器）、
  互斥分支里的乘法器、
  同一个 `always` 块里几条路径上的同型运算、
  DSP 里按模式切换的算子。

## 结构

### 基本变换

```verilog
// 共享前：两个加法器
y = sel ? (a + b) : (c + d);

// 共享后：一个加法器 + 两个 mux
wire [W-1:0] op1 = sel ? a : c;
wire [W-1:0] op2 = sel ? b : d;
y = op1 + op2;
```

前提是**两条路径互斥**（同一拍只可能用其中一条）。
不互斥就不能共享 —— 那是 [`folding-time-multiplex.md`](folding-time-multiplex.md)
的场景（不同拍轮流用）。

**两者的区别值得说清楚**：

| | 共享 | 折叠 |
|---|---|---|
| 前提 | 同一拍里**只需要一个**结果 | 同一拍里需要多个，但可以**分拍**做 |
| 吞吐 | 不变 | ÷N |
| 需要控制器 | 不需要（`sel` 本来就有） | 需要（调度） |

### 盈亏平衡点

```
省下：(K−1) × A_算子
付出：(操作数个数) × A_(K:1 mux) + sel 的扇出
```

- **加法器（W 位）vs 两个 W 位 2:1 mux**：加法器更贵，**共享划算**。
  这也是几乎所有 ALU 都只有一个加法器的原因（加/减/比较全靠它）。
- **乘法器**：贵得多，**一定要共享**。
- **窄逻辑、mux、编码器**：算子比 mux 还便宜，**共享是亏的**。

### 本地工具已经在做（2026-09-07 核实）

yosys 的 `synth` 默认脚本里有：

```
share        (unless -noshare)
alumacc      (unless -noalumacc)
```

- **`share` 就是这张卡的自动版**：它找互斥条件下的同型运算并合并。
- **`alumacc`** 把 `+ − <` 等归并成 `$alu` / `$macc` 宏单元，
  是共享的另一种形态（同一个加法器同时产出和与比较结果）。

所以在本仓库里，**手写共享大概率是多余的** ——
工具已经做了，手写反而可能挡住它。这一点和
[`../priority-encode/find-first-one.md`](../priority-encode/find-first-one.md)
那批"手写 vs 交给工具"的判断是同一类问题。

**本地有一个一行的对照实验**：`synth` vs `synth -noshare`。
不过那是改 `flow/synth/synth.py`，按 `CLAUDE.md` 要走 keel Full 模式。

## 关键路径

共享**几乎总是让关键路径变长**：

```
共享前： a ──[加法器]── y
共享后： a ──[mux]──[加法器]── y        // 多一级
```

而且 `sel` 现在跑在**数据通路的前面**，而不是后面的选择端 ——
这和 [`late-arriving-signal.md`](late-arriving-signal.md) 的方向**正好相反**。

> **共享和预计算是同一根轴的两端**：
> [`precompute-lookahead.md`](precompute-lookahead.md) 用面积买延时（复制 + 后置 mux），
> 共享用延时买面积（合并 + 前置 mux）。
> **同一个设计里两者不该同时出现在同一条路径上** —— 那说明有人没想清楚。

如果 `sel` 到得晚，共享就特别糟糕：晚到的信号被放在了路径最前面。
**`sel` 晚到时不要共享。**

## PPA 权衡

- **面积**：省 (K−1) 份算子，付 K:1 的 mux。K 越大省得越多，
  但 mux 也越大，收益饱和。
- **延时**：+1~2 级 mux。
- **功耗**：⚠️ **共享通常让动态功耗变差。** 共享的算子每拍看到的操作数
  在两组数据源之间跳变，翻转率显著高于两个各自专用的算子
  （后者在不用的那拍输入是静止的）。**这是共享最容易被忽略的代价**，
  而且它可以用[操作数隔离](operand-isolation-clock-gating.md)部分补救。
  本仓库当前测不了（`docs/data-credibility.md` D-1）。

## 什么时候选它 / 什么时候别用

- **算子贵（乘法器、除法器、大位宽加法器）且条件互斥** → 共享。
- **算子便宜（窄加法、逻辑门、mux）** → **别共享**，会更大更慢。
- **`sel` 是晚到信号** → **别共享**，方向反了。
- **在关键路径上** → 别共享，共享是省面积的手段。
- **不互斥、但吞吐富余** → 那是 [`folding-time-multiplex.md`](folding-time-multiplex.md)。
- **在本仓库里** → **先别手写**，工具的 `share` 已经开着；
  想验证就跑 `-noshare` 的对照。

## 实现要点与坑

- **"互斥"必须是真的互斥。** 如果两条路径在某个边角情况下会同时需要结果，
  共享就是功能错误。这类 bug 只在特定输入组合下出现，
  **必须用定向用例覆盖每一条 `sel` 分支的边界**。
- **共享会创造伪路径（false path）。** 共享后的算子从 `a` 到 `y` 和从
  `c` 到 `y` 都有路径，但它们永远不会同时激活。STA 不知道这一点，
  会报一条实际上不存在的最长路径。**本仓库没有配 `set_false_path`
  的机制**，所以共享设计的 `critical_path_delay_ns` 可能偏悲观。
  这是一条**具体的、可预期的测量偏差**，值得记进 `calibration/`。
- **别在跨模块边界上指望工具共享。** 保层级（`params.yaml` 的 `keep_hierarchy:`）一旦设上，
  `share` 就不能跨那个边界了 —— 这又是"结构保真 vs 工具优化"的张力
  （同样的矛盾见 [`retiming.md`](retiming.md)、
  [`late-arriving-signal.md`](late-arriving-signal.md)）。
  **在本仓库里这是有意的代价**：为了测准微架构差异，放弃一部分跨模块优化。
- **手写共享会挡住工具的更好方案。** 你按 `sel` 分组共享，
  工具可能有更好的分组。**除非有实测证据，否则让工具做。**
- **保层级（`params.yaml` 的 `keep_hierarchy:`）**：比较"共享 vs 不共享"时，
  两者功能等价，ABC 会把它们收敛。要测就必须设边界
  （`docs/pitfalls.md` 的 P-3）—— 但更省事的做法是用 `-noshare` 开关，
  那是流程级的，不需要动 RTL。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module ALU #(
    parameter DAT_W    = 32,
    parameter SHARE_EN = 1      // 1 = 手写共享一个加法器；0 = 每条路径各一个
)(
    input  [DAT_W-1:0] i_a, i_b, i_c, i_d,
    input              i_sel,
    input  [1:0]       i_op,
    output [DAT_W-1:0] o_dat
);
```

但**更值得做的实验在流程侧而不是 RTL 侧**：同一份 `SHARE_EN=0` 的 RTL，
分别用 `synth` 和 `synth -noshare` 综合，看工具自己能省多少。
**那测的是"工具的共享能力"，正是本仓库真正想知道的东西。**

## 出处

- De Micheli, G., *Synthesis and Optimization of Digital Circuits*,
  McGraw-Hill, 1994 —— 资源共享/绑定（binding）作为高层综合的标准问题。
- Weste, N. & Harris, D., *CMOS VLSI Design*, 4th ed., Addison-Wesley, 2010 ——
  ALU 中加法器复用的电路视角。
- yosys 的行为由 `yosys -h synth`、`yosys -h opt_merge` 输出核实
  （2026-09-07，yosys 0.68+182）。

## 本地实测

暂无。**这张卡的实验载体应当是流程开关而不是 RTL**：

1. **`-noshare` 对照**（需要改 `flow/synth/synth.py`，keel Full 模式）：
   拿一个现有的 cbb 构件或一个新的小 ALU，测 `share` 打开/关闭的面积差。
   这直接回答"工具的资源共享值多少钱"。
2. **手写共享 vs 交给工具**：`SHARE=0/1` 两档 + `keep_hierarchy`，
   看手写能不能打过 `share` pass。
   预期是**打不过**（和 `../arith/comparator.md` 的结论同类），
   但这个预期没验证过。

两个实验都是纯组合、不依赖握手支持，**流程一改就能跑**。
