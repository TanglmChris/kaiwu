## Why

本仓 内部#40。从 nano-kpu 的对照里露出来的一条：**让本仓的数字之间可比的是「指纹相同」，
不是「参数冻结」** —— 而可信度文档从来没说过这句话。

nano-kpu 走的是另一条路：README 明说「为保证不同设计之间的可比性，测量使用一套
固定、冻结的综合参数」，并且明确不做 design-specific 优化。本仓相反 ——
`flow/synth/search.py` 在一组 delay target 比例上各综合一次、取最好的那份网表。

两种都成立，但它们让**同一个词（`fmax`）指不同的量**：

- 冻结参数那一侧：`fmax` 是「这套固定 recipe 下测到的值」。
- 本仓：`fmax` 是「在 `DELAY_TARGET_RATIOS` 这组比例里能拿到的**最好**值」。

拿两者直接比，比的不是同一个量。这不是假想的风险 —— `calibration/`（本地开源流
vs VCS/DC 参考流的偏差分析，内部#6）是这个项目的终点目标，而参考流那一侧多半就是
固定 recipe。到那时这条会直接撞上，而现在没有任何地方写着它。

机制侧其实已经是对的：`DELAY_TARGET_RATIOS` 已经进 `synth_recipe_sha256`
（`flow/flow_fingerprint.py` 的 `synth_recipe_sha256()` 把 `YOSYS_TEMPLATE` +
`abc.constr` 内容 + 这组比例一起哈希），所以改搜索策略会自动分代。缺的是
**把这件事写下来**，以及写下它的后果。

## What Changes

- `openspec/specs/experiment-trust/spec.md` 新增一条要求：以搜索得到的最优值报告的
  指标，其取值来源（那组比例）MUST 进流程指纹，且该指标的定义 MUST 写在读它的人
  会看到的地方。
- `docs/data-credibility.md` 的「怎么给记录分代」一节新增一小节，写清三点：
  可比性来自指纹而非参数冻结；搜索策略一动就是换代（机制已保证）；
  `fmax` 是搜索得到的最好值、不是物理上限，与固定 recipe 的数字不是同一个量。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `experiment-trust`: 新增「以搜索得到的最优值报告的指标必须声明它的取值来源」。

## Impact

- `openspec/specs/…`（本变更自己的 delta）、`docs/data-credibility.md`
- **不换代**：`docs/` 与 `openspec/` 都不在 `flow_fingerprint.METRIC_MODULES` 里，
  也不进任何配方哈希。当前代 `0c80b2af` 的 92 条不受影响。
- **不改任何代码**。机制侧已经满足新要求，本变更要做的是把它写下来并加上机械判据，
  使它将来被改掉时不是静默的。
