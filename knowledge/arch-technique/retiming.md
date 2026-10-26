# retiming（寄存器重定时：工具能做什么、不能做什么）

- **类别**：架构范式与技巧
- **一句话**：在不改变寄存器总数的前提下，把它们沿着组合图**挪位置**以平衡各级延时 ——
  综合工具能自动做，但**本仓库当前的流程一刀都没做**（已核实），
  而且它有一条谁也突破不了的下界：iteration bound。
- **典型用途**：把手工流水切歪的级重新平衡、
  把寄存器推过一段长逻辑、DC 的 `optimize_registers`、
  FPGA 的自动重定时。

## 结构

### 基本操作

对某个组合节点，**把它所有输入线上的寄存器同时移到所有输出线上**（前推），
或者反过来（后推）。功能等价的条件是"同时"和"全部"——
少挪一根线就错。

Leiserson & Saxe 把它形式化成一个整数规划：给每个节点一个整数 `r(v)`，
边 `u→v` 上的寄存器数变成 `w(u,v) + r(v) − r(u)`，要求处处非负。
**最小周期 retiming** 就是在这个约束下最小化关键路径，可以用
二分周期 + 最短路（Bellman-Ford）在多项式时间解出来。

### iteration bound：谁也过不去的下界

对含反馈环的电路：

```
T∞ = max over 所有环 L 的  ( 环上组合总延时 / 环上寄存器总数 )
```

**retiming 只能挪寄存器，不能改变任何一个环上的寄存器数**（挪出去多少就挪进来多少），
所以 `T∞` 是 retiming 的硬下界。

- 组合路径 100 ps 的环上只有 1 个寄存器 → 这条环永远跑不过 10 GHz，
  流水化和 retiming 都无效。
- 想突破只有两条路：**改算法**（把环拆开，比如 look-ahead 展开，见
  [`precompute-lookahead.md`](precompute-lookahead.md)），
  或者**往环里塞寄存器**——那会改变功能，除非用
  **C-slow**（见 [`parallel-unroll-cslow.md`](parallel-unroll-cslow.md)）。

这条是流水化最容易撞上的墙：**前馈部分切得再细，一个环就把 fmax 钉死了。**

## 关键路径

- retiming 后的理想周期 = `max(T∞, 单级不可分逻辑的延时) + t_ovh`。
- 它**不减少**总延迟（latency）—— 寄存器总数不变，从输入到输出还是那么多拍。
  **retiming 是纯粹的"把 fmax 拉上去"，不改吞吐语义、不改延迟。**

## PPA 权衡

- **面积基本不变**（寄存器数不变），但**位宽会变**：把一个 8 位寄存器
  前推过一个把 8 位扩成 16 位的逻辑，就变成 16 个触发器。
  **工具做 retiming 时面积可能悄悄涨**，这是真实发生的事。
- 功耗：翻转位置变了，可能涨可能跌，不可预测。
- **收益完全取决于原始 RTL 切得有多歪**。切得已经很平衡的设计，
  retiming 给不了什么。

## ⚠️ 本仓库现状（2026-09-07 核实）

**本仓库的流程完全没有做 retiming**，两个独立的原因：

1. **yosys 0.68 的 `synth` 没有 `-retime` 选项**
   （`yosys -h synth` 的选项表里没有它；默认脚本里也没有任何重定时 pass）。
2. **`flow/synth/synth.py` 调的是 `abc -liberty <lib>`，没有 `-dff`。**
   不加 `-dff` 时 ABC 拿不到触发器，只能看到组合锥 ——
   **它连做 retiming 的输入都没有。**

要打开的话是 `abc -liberty <lib> -dff -D <ps>`：yosys 会把 ABC 默认脚本里的
`dretime` 换成 `dretime; retime -o <D>`。**但这是改 `flow/**`，按
`CLAUDE.md` 必须走 keel Full 模式**，而且会让历史记录不可比 ——
不要顺手改。

这条现状有一个重要的连带结论：

> **本仓库目前测到的"流水级数 vs fmax"，是纯 RTL 的结果，
> 不含任何工具重定时的成分。** 这让
> [`pipelining.md`](pipelining.md) 的实测数据非常干净
> （切点策略的效果不会被工具抹平）。
> **但接了 DC 之后立刻失效** —— DC 默认会做寄存器优化，
> 同一份 RTL 的 `CUT_POLICY` 对比可能直接归零。
> 这和 `fmax_method = analytic` 那条注意事项（`docs/data-credibility.md` 的 D-7）
> 是同一个性质的问题：**本地流的很多"干净"来自它不够聪明**。
> 而 2026-09-13 发现连这句也要打折 —— ABC 其实**能**被加压（`abc -D`），
> 只是这个流程从来没用过，见 内部#26。

## 什么时候选它 / 什么时候别用

- **手工切点不好调（逻辑很不规则）** → 交给工具 retiming。
- **要精确控制每一级切在哪（比如做 PPA 对比实验）** → **关掉 retiming**，
  否则你测的是工具的决策不是你的设计。**本仓库属于这一类。**
- **瓶颈在反馈环上** → retiming 无效，先算 `T∞`；
  要突破去 [`parallel-unroll-cslow.md`](parallel-unroll-cslow.md)。
- **设计里有形式验证/等价性检查的要求** → 慎用，见下面的坑。

## 实现要点与坑

- **retiming 会破坏组合等价性检查。** 挪过寄存器之后，网表和 RTL 已经不是
  逐触发器对应了，普通的组合等价性检查（comb EC）会直接失败，
  必须用**时序等价性检查**（sequential EC）。这是引入 retiming 的隐藏成本，
  而且往往是在流片前才被发现的。
- **初始状态可能丢失。** 寄存器挪位置之后，原来的复位值不一定能等价地
  传递过去（要解一个"反推初始值"的问题，有时无解）。工具的做法通常是
  **拒绝挪带复位的寄存器**——所以**给所有流水寄存器都加复位，
  等于把 retiming 关掉了一半**。这条和
  [`../storage-flow/reset-strategy.md`](../storage-flow/reset-strategy.md)、
  以及 [`pipelining.md`](pipelining.md) 里"数据寄存器不要复位"直接呼应：
  那条建议不只是省面积，**也是为了给工具留出重定时的空间**。
- **不能跨过存储器、黑盒、时钟域边界、带 `dont_touch` 的东西挪。**
  所以一个被保层级（`params.yaml` 的 `keep_hierarchy:`）切碎的设计，retiming 的活动范围也被切碎了。
  **这是本仓库"结构保真"和"工具优化"之间的一个真实矛盾**：
  为了测出微架构差异必须设边界，设了边界就限制了重定时。
  目前本仓库不做 retiming，所以矛盾还没兑现；接 DC 时要重新想。
- **别用 retiming 去补救糟糕的划分。** 模块边界上的寄存器（I/O 寄存
  时序约定）通常是不能挪的，retiming 帮不了跨模块的长路径。
- **测量陷阱**：如果不确定工具有没有做 retiming，看**触发器总数**和
  **各级延时的方差**。数量不变、方差显著下降 = 做了。

## 参数化接口建议

retiming 不是 RTL 里的东西，**没有模块接口** —— 它是综合选项。
本仓库要做这个实验的话，参数在流程侧：

```
abc -liberty <lib>                    # 现状：无 retiming
abc -liberty <lib> -dff -D <period_ps> # 打开重定时
```

配套要记录的：触发器数、各级延时分布（不只是 max）。
**只记 `critical_path_delay_ns` 是看不出 retiming 有没有生效的。**
这意味着开这个实验要先扩实验记录（`results/<设计根>/experiments.jsonl`）的 schema ——
按 `CLAUDE.md`，那是仓库里风险最高的改动，必须走 Full 模式。

## 出处

- Leiserson, C.E. & Saxe, J.B., "Retiming synchronous circuitry,"
  *Algorithmica*, vol. 6, no. 1, pp. 5–35, 1991 —— 形式化与多项式算法。
- Parhi, K.K., *VLSI Digital Signal Processing Systems*, Wiley, 1999 ——
  retiming、iteration bound、C-slow 的统一处理，比原论文好读。
- yosys / ABC 的具体行为由 `yosys -h synth`、`yosys -h abc` 的输出核实
  （2026-09-07，yosys 0.68+182）。

## 本地实测

暂无，**而且暂时不该做**。理由：打开 retiming 要改 `flow/synth/synth.py`
（keel Full 模式），还要扩记录 schema 才看得出效果（更高风险），
而收益是"验证一个本仓库当前有意不用的功能"。

**正确的顺序是**：先按 [`pipelining.md`](pipelining.md) 把
`CUT_POLICY` 的实验做掉（纯 RTL、零流程改动），
拿到"手工切点值多少钱"的基线；等接了 DC，
再用同一份 RTL 去看"工具的 retiming 能不能把 `CUT_POLICY` 的差异抹平"。
**那个对比才是这张卡真正的价值**，而且它天然属于
`calibration/`（本地 vs 参考工具流的偏差分析）那条线。
