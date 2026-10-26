## Context

2026-09-07 给 `adder32` 加上 `WIDTH` 维度之后，三种进位结构的位宽-延时渐进阶
第一次被实测。RIPPLE 与 CSEL 的结果干净漂亮，`CLA` 却露了馅。

- **F1** — （2026-09-07 实测，67 条记录）`PIPE_STAGES=0, CSEL_BLOCK=4`、
  `WIDTH=8/16/32/64` 下的 log-log 斜率：RIPPLE 延时 1.012 / 面积 1.000（O(n)），
  CSEL 延时 0.573 / 面积 1.002（O(√n)），CLA 面积 1.239 且**延时非单调**
  （0.2163 / 0.4112 / 0.6977 / 0.5252 ns，64 位比 32 位快，级数 22 → 16）。
- **F2** — （2026-09-07 读 RTL 核实）`designs/adder32/rtl/flat_lookahead.v`
  把每一位的进位展开成完全平铺的与或式（第 i 位 i 个 term，且
  `pacc[j+1] = pacc[j] & p[i-1-j]` 是长度 i 的串行与链），naive 规模 O(N²)，
  深度靠 ABC 事后重构。**所以 `CLA` 的级数是综合启发式的产物，不是 RTL 的结构性质。**
  已记入 `FOLLOWUP.md` 第 11 条。
- **F3** — （`knowledge/arith/prefix-adders.md`，Harris 分类法）前缀网络家族受
  同一预算约束 `l + f + t = log₂N − 1`：级数 `log₂N + l`、最大扇出 `2^f + 1`、
  连线轨道 `2^t`。N=32 时三个角分别是
  Sklansky (0,4,0) 5 级/扇出 17/轨道 1、
  Kogge-Stone (0,0,4) 5 级/扇出 2/轨道 16、
  Brent-Kung (4,0,0) 9 级/扇出 2/轨道 1。
- **F4** — （2026-09-07 实测）本仓库 32 位的**总逻辑级数**：RIPPLE 34、CLA 22、CSEL 15。
  前缀级数之外还要加上 g/p 预计算与末级 sum XOR，所以 F3 的前缀级数不能直接与之比较。

结果是**本仓库至今没有任何 O(log n) 结构的实测数据**，而
`knowledge/arith/prefix-adders.md` 是全知识库被引用最多的一张卡
（`comparator.md`、`../priority-encode/find-first-one.md`、
`../priority-encode/fixed-priority-arbiter.md`、
`../priority-encode/onehot-binary-thermometer.md` 都把自己的前缀结构指向它），
它的「本地实测」却是空的。`WIDTH` 维度已经就位，现在补网络正是时候。

## Goals / Non-Goals

**Goals:**

- 给 `adder32` 增加三个真前缀网络，实测出 O(log n) 那一档。
- 验证 Harris 的 `l + f + t` 零和约束在本地流上看不看得见（尤其"级数少 ≠ 延时小"）。
- 给 `knowledge/arith/prefix-adders.md` 挂上第一批 `experiment_id`。

**Non-Goals:**

- 不改也不删 `CLA`（见 D1）。
- 不做 Han-Carlson、不做稀疏前缀 `SPARSITY`（见 D2）。
- 不改 `results/experiments.jsonl` 的 schema，不改写历史记录。
- 不碰功耗（反标仍失效，`FOLLOWUP.md` D-1）。

## Decisions

- **D1** — 新增 `SKLANSKY` / `KOGGE_STONE` / `BRENT_KUNG` 三个 `CARRY_STRUCT` 取值，
  **`CLA` 原样保留**。
  Basis：28 条以上的历史记录用 `CARRY_STRUCT=CLA`，删改会让它们失去指代，
  而按 `CLAUDE.md` 历史记录不回填改写。而且那个平铺与或式不是"错误实现"，
  它是一个有价值的**对照组** —— "把功能平铺出来交给工具优化"正是
  `knowledge/` 多张卡反复要求的 `TOOL` 档。本变更只在文档里把它的语义讲清楚。

- **D2** — 只实现三个角（Sklansky / Kogge-Stone / Brent-Kung），不做 Han-Carlson (1,0,3)。
  Basis：三个角已经张开 F3 那条预算约束的整个空间（极端扇出 / 极端连线 / 极端级数），
  足以验证 O(log n) 与三者零和；Han-Carlson 是内插点，加它增加实现风险
  （它是 Kogge-Stone 只作用于奇数位再补一级）而不增加结论。列为后续。

- **D3** — 三个网络模块各自带 `(* keep_hierarchy *)`，综合照旧不 `-flatten`。
  Basis：`CLAUDE.md`「综合坑」—— 它们功能上全都等价于 `a+b`，
  不设边界会被 ABC 的 `&dch` 收敛成同一个网表。这条同时是本变更新增的
  `experiment-trust` 需求「功能等价的微架构取值必须产出可区分的网表」的实现手段。

- **D4** — 三者共用同一份 g/p 预计算与末级 sum XOR，**只有前缀网络本身不同**。
  Basis：保证测出来的差异只来自网络拓扑，而不是来自前后级的写法差异。
  实现上是一个 `prefix_adder` 外壳模块 + 三个可替换的网络模块。

- **D5** — 直接复用现有 testbench，不改。
  Basis：`designs/adder32/tb/test_adder32.py` 已在上一个变更里按 `WIDTH` 参数化，
  且它测的是 `a + b + cin` 的功能等价性 —— 新结构要满足的正是同一个判据。
  新增取值只需进 `params.yaml`，tb 一行不用动。

- **D6** — 验收的核心判据是**延时的 log-log 斜率严格小于 CSEL 的 0.573**。
  Basis：这是"O(log n) 优于 O(√n)"的直接可观察形式，不依赖对绝对值的解释。
  预期斜率在 0.1~0.45 之间（纯 log n 会给 0.333，加上不随位宽变的固定开销会更低）。

## Hidden Knowledge / Assumptions

- **A1** — Sklansky 与 Kogge-Stone 的面积是 O(n log n)，log-log 斜率预期约 1.33；
  Brent-Kung 是 O(n)，预期约 1.0~1.15。
  Basis：由网络节点数推得（KS 每级 n 个节点 × log n 级），未实测。
  Resolve by：本变更的位宽扫参；若 KS 的面积斜率显著低于 1.2，说明 ABC 跨节点
  做了共享，需要回头查 `keep_hierarchy` 的作用范围。

- **A2** — 三个网络在 `(* keep_hierarchy *)` 下会产出可区分的网表。
  Basis：三者的节点数与连接拓扑本就不同；但它们功能等价，这条不是自动成立的。
  Resolve by：本变更新增的 `experiment-trust` 需求对应的检查
  （六个 `CARRY_STRUCT` 取值的 `(cell_count, critical_path_stages)` 两两不同）。

- **A3** — 本地流会系统性高估 Kogge-Stone。
  Basis：`knowledge/README.md` 的全库警告 —— 无 LEF / 无 P&R / 寄生参数为零，
  而 KS 的代价正是 O(N) 条连线轨道。**这不是待验证的假设，是已知的测量边界**，
  写在这里是为了让它进入结论而不是事后解释。
  Owner：本变更新增的 `experiment-trust` 需求「依赖连线代价的结论必须标注本地流的
  测量边界」，以及 `knowledge/arith/prefix-adders.md` 的「本地实测」一节。

## Risks / Trade-offs

- **Brent-Kung 的上扫/下扫实现最容易写错**，而且错法往往只在特定位宽暴露。
  缓解：tb 的定向用例覆盖了全一相加与进位溢出，且 `WIDTH` 有四档；
  四档全绿才算通过。
- **组合数从 36 涨到 72**，全量扫参耗时翻倍。可接受，`SKIP_EXISTING` 不适用
  （历史记录的参数键集不同，见 `FOLLOWUP.md` 第 9b 条）。
- **"级数少 ≠ 延时小"可能在本地流上看不出来**：Sklansky 的扇出代价体现在
  负载电容上，而管脚电容在 liberty 里是有的（连线电容才为零），所以**部分可见**。
  这本身是个值得记录的观察，不是风险。

## Open Questions

- **Q2** — （任务 1.1 实现后实测发现）`WIDTH=32, PIPE_STAGES=0` 下 Sklansky 是
  25 级 / 0.7179 ns，**比 Brent-Kung 的 19 级 / 0.5436 ns 还差**，
  与理论级数序（Sklansky 5 级 < Brent-Kung 9 级）**相反**。
  Basis：2026-09-08 的 synth+sta 实测；三个网络共用同一外壳，功能仿真 36 组全通过，
  所以不是实现错误。工作假设是扇出 —— Sklansky 最后一级有一个节点要驱动 16 个消费者，
  而本地库 `asap7sc7p5t_RVT_TT` 的驱动档位很有限，综合必须插缓冲树，
  这些缓冲会计进关键路径级数。
  Resolve by：任务 2.1 的位宽扫参 —— 若假设成立，Sklansky 相对 Brent-Kung 的劣势
  应**随位宽扩大**（其最大扇出 2^(log₂N−1) 随 N 线性增长）；
  **已授权的回退是如实记录这一反转并归因到「本地库驱动档位有限」，
  不宣称 Sklansky 的结构本身劣于 Brent-Kung**。不阻塞任何任务。

  **【2026-09-08 已解决，工作假设是错的】** 四步诊断（见任务 2.1 的 Blocker）表明：
  (a) 用 Python 复刻三个网络 generate 的索引逻辑算 DAG 深度，前缀覆盖全部正确、
  深度正好是理论值，**RTL 没问题**；(b) W=64 的 STA 关键路径是 21 个 `A2O1A1O1I`
  + 20 个 `OAI21`、**一个 buffer 都没有**，所以不是扇出缓冲而是逻辑链；
  (c) `abc -liberty <lib> -D 300` 与不加 `-D` 的网表**逐字节相同**，加延时目标无效；
  (d) 把 `(* keep_hierarchy *)` 从网络模块下移到前缀算子节点后，W=64 的关键路径
  单元数 SKLANSKY 45→9、KOGGE_STONE 16→9、BRENT_KUNG 31→13，与理论级数序一致。
  **真正的原因是 `keep_hierarchy` 标错了粒度** —— 标在网络上只保住网络边界，
  网络内部对 ABC 仍是一整块可自由重构的组合锥。由任务 1.3 修正。

- **Q1** — 本地流能否分辨 Sklansky 与 Kogge-Stone？两者级数相同 (l=0)，
  差别全在扇出与连线；本地只有管脚电容、没有连线电容，可能测出来几乎一样。
  Basis：`knowledge/README.md` 的全库警告与 `logic-replication.md` 里
  "管脚电容那部分模型里有、连线电容没有"的判断，未实测。
  Resolve by：跑完看两者的 `critical_path_delay_ns` 差异；
  **已授权的回退是：若两者差异小于 2%，就在结论里如实写"本地流分辨不出，
  需等 P&R"，而不是宣称两者等价**。这不阻塞任何任务 ——
  无论哪种结果，D6 的核心判据（斜率低于 CSEL）都独立成立。
