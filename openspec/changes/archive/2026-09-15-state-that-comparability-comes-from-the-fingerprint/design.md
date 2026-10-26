## Context

`flow/synth/search.py` 在 `DELAY_TARGET_RATIOS` 上各综合一次、取最好者，所以
`sta.fmax_mhz` 是一个**搜索结果**，不是一次固定测量。可信度文档从来没写过这件事。

F1 — 那组比例**已经**进了流程指纹。Basis：`flow/flow_fingerprint.py` 的
`synth_recipe_sha256()`：`_sha256_text(YOSYS_TEMPLATE + abc.constr 内容 + json.dumps(list(DELAY_TARGET_RATIOS)))`
（2026-09-15 读）。其 docstring 也已写明理由（本仓 内部#25）。

F2 — `docs/` 与 `openspec/` 都不在 `METRIC_MODULES`（七项：`flow/paths.py`、
`flow/sim/run_sim.py`、`flow/sim/vcd_stats.py`、`flow/synth/synth.py`、
`flow/synth/search.py`、`flow/sta/run_sta.py`、`scripts/run_experiment.py`），
也不进任何配方哈希。Basis：同上文件。所以本变更不换代。

F3 — `openspec/specs/experiment-trust/spec.md` 现有 15 条 requirement，其中
**没有一条**管「指标的可比性来源」或 `fmax` 的定义。Basis：
`grep '^### Requirement' openspec/specs/experiment-trust/spec.md`（2026-09-15）。

## Goals / Non-Goals

**Goals:**

- 把「可比性来自指纹、不来自参数冻结」写进读记录的口径里。
- 给它一条**机械判据**：改搜索范围必须换代（机制已满足，本变更把它变成被守住的
  要求而不是碰巧成立的事实）。
- 说清 `fmax_mhz` 与走固定 recipe 的外部数字不是同一个量 —— `calibration/` 会撞上。

**Non-Goals:**

- **不改任何代码。** 机制侧已经对了；这里缺的是文字与守住它的判据。
- 不改搜索策略本身。「搜到最好」与「冻结参数」两条路哪条更对不在本变更范围内 ——
  本变更只要求把选了哪条、后果是什么写清楚。
- 不动 `REPORT.md` 的生成。让每份报告都重复这段定义会把它变成噪音；
  归置在 `docs/data-credibility.md`（读记录的口径的唯一去处）。

## Decisions

**D1 — 要求写进 `experiment-trust` 而不是 `experiment-record`。**
Basis：`experiment-record` 管的是字段集合与 schema 演进（「只能单调增长」那类），
本条管的是**一个已有字段的含义能不能被正确读出来**，与
`experiment-trust` 既有的「无法测得的指标必须缺席」「依赖连线代价的结论必须标注
本地流的测量边界」同属一类 —— 后者尤其像：那条也是「数字本身没错，但读它要带个边界」。

**D2 — 要求措辞按「以搜索得到的最优值报告的指标」泛化，不点名 `fmax_mhz`。**
Basis：`search.py` 同一次搜索还决定了 `delay_target_ps` 与哪份网表胜出（进而
`cell_count` / `area_um2` / `critical_path_stages` 全都是胜出那份的）。只写
`fmax_mhz` 会让下一个同形状的字段漏在外面，而漏掉的方式是静默的。

**D3 — 进指纹的是比例集合，不是推导出的每设计皮秒值。**
Basis：`synth_recipe_sha256()` 的 docstring 已经写死这条取舍（皮秒值由各设计自己的
d0 决定，写进指纹会让每个设计自成一代）。spec 把它复述一遍，使它不能在将来被
「顺手改得更精确」掉。

**D4 — 文档落点是「先看这一条：怎么给记录分代」一节下的新小节，不新开 `D-13`。**
Basis：`D-x` 是「哪批记录因何不可用」的逐批台账；本条不针对任何一批记录，
它是分代机制本身的一条读法。放进 `D-x` 会让那张台账混进一条没有批次的条目。

## Hidden Knowledge / Assumptions

A1 — 本变更不产生新的一代，既有 1269 行记录一字节不动。
Resolve by：M3（指纹实测 + `cmp`）。

## Risks / Trade-offs

- **这条要求的判据有一半是「文档里有没有写」**，机械性弱于本仓其他要求。缓解：
  另一半（改比例必须换代）是可执行的 —— 改一个数、重算指纹、比对，能当场证伪。
  文档那一半用 `grep` 定位关键措辞，弱但不为零。
- **要求泛化到「搜索得到的最优值」之后，理论上把 `delay_target_ps` 等也纳入了。**
  这是有意的（D2），但当下没有额外动作要做：它们与 `fmax_mhz` 共用同一组比例、
  同一个指纹项。

## Open Questions

None.
