## 1. 写下来并守住

- [x] 1.1 `experiment-trust` 加一条要求；`docs/data-credibility.md` 写清三点
  - Covers:
    - experiment-trust / 以搜索得到的最优值报告的指标必须声明它的取值来源
    - experiment-trust / 以搜索得到的最优值报告的指标必须声明它的取值来源 / 搜索范围被改动
    - experiment-trust / 以搜索得到的最优值报告的指标必须声明它的取值来源 / 读记录的人要判断一个 fmax 是什么意思
    - experiment-trust / 以搜索得到的最优值报告的指标必须声明它的取值来源 / 要与走固定 recipe 的外部流程比较
    - D1（写进 experiment-trust 而不是 experiment-record）
    - D2（措辞泛化到「以搜索得到的最优值报告的指标」，不点名 fmax_mhz）
    - D3（进指纹的是比例集合，不是推导出的每设计皮秒值）
    - D4（文档落点是「怎么给记录分代」下的新小节，不新开 D-13）
    - F1（`DELAY_TARGET_RATIOS` 已经进 `synth_recipe_sha256`）
  - Touch:
    - docs/data-credibility.md
  - Verify:
    - Strategy: evidence-first
    - Reason: 本变更不改任何代码 —— 机制侧已经满足新要求（F1），要写的是契约条文与读记录的口径，没有可以先失败的行为。M1 用真实的指纹重算把「改搜索范围会换代」当场证一遍，而不是引用 docstring。
    - M1: 把 `DELAY_TARGET_RATIOS` 临时改掉一个值后重算 `synth_recipe_sha256()` 与 `flow_fingerprint()`，两者都与改动前不同；改回来之后逐字复原 —— 证「搜索范围一动就换代」成立且可逆
    - M2: `docs/data-credibility.md` 里能 `grep` 到三点：可比性来自指纹而非参数冻结、改搜索策略自动分代、`fmax_mhz` 是搜索得到的最好值而非物理上限
    - M3 (regression): `flow_fingerprint` 仍是 `sha256:0c80b2af…`，`results/experiments.jsonl` 与 HEAD 逐字节相同，`pytest tests/ -q` 163 passed
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:caa44f631d6e7b4e2784204d8b549a0e0f3badedfb77e44da0b668221ec89a32
    - M1: 原比例 `(1.5, 1.0, 0.5, 0.3)`。改前 `synth_recipe_sha256` = `sha256:b9e04615…`，`fingerprint` = `sha256:0c80b2af…`；把末项改成 `0.99` 后分别变成 `sha256:53ac7a48…` 与 `sha256:4b758c56…`（两者都变了）；改回原值后两个哈希**逐字复原**。改搜索范围就是换代，实测成立且可逆。
    - M2: `docs/data-credibility.md:77` 起新增「可比性来自指纹，不来自参数冻结」一节，三点各自可 grep：`:90` 「不是参数一样，而是**指纹相同**」、`:94` 「`fmax_mhz` 是「在这组比例里能拿到的最好值」，不是电路的物理上限」、`:98` 「改搜索策略就是换代，而且是机械保证的」。第 3 点（与固定 recipe 的外部数字不是同一个量，calibration/ 会撞上）在 `:103`。末尾指回 `experiment-trust` 的新条款。
    - M3: `flow_fingerprint` 仍是 `sha256:0c80b2af014dec58…`（与 M1 的「改前」同一个值）；`cmp <(git show HEAD:results/experiments.jsonl) results/experiments.jsonl` 无输出，1269 行逐字节相同；`source ~/tools/env.sh; pytest tests/ -q` → `163 passed, 6 warnings in 462.84s`。
    - Review:
      - Status: pass
      - Acceptance check: 新条款的三个 Scenario 各有落点 —— 「搜索范围被改动」由 M1 实测，另两个由 M2 的文档措辞满足。F1（比例已进指纹）不是被引用的 docstring，而是 M1 当场重算出来的。
      - Scope check: 只动了 `docs/data-credibility.md`（Touch）与本变更自己的 tasks.md。一行代码都没改 —— 机制侧本来就满足新要求，本变更加的是条文与判据。
      - Findings: 首次跑 `pytest` 时忘了 `source ~/tools/env.sh`，得到 `1 failed, 114 passed, 48 skipped`（`test_high_fanout_net_is_buffered` 因 yosys 不在 PATH 而失败）。那不是回归，是环境没准备好；补 env 后 163 passed。 Discard reason: 环境操作失误，已在同一任务内用正确环境重跑并记下结果，不遗留动作。
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "**它不覆盖**：`flow/synth/merge_liberty.py`（产出的 liberty 其内容已单独进指纹）、`scripts/score.py` 与 `gen_report.py`（只读记录，不写）。" —— `docs/data-credibility.md` 的「第七项」小节。这句仍然成立，但它是目前文档里唯一谈「指纹覆盖了什么」的地方，新小节要接在这条口径之后而不是与它冲突。 Updated by: 1.1
- I2: "`fmax` 是"在这组目标里能拿到的最好值"，换掉这组比例就换掉了这个量的定义" —— `flow/flow_fingerprint.py` 的 `synth_recipe_sha256()` docstring。这句话是对的，但它只活在代码注释里，读记录的人看不到。本变更把它提升为契约条文与文档口径；docstring 本身不必改。 Discard reason: 代码注释与文档各自成立、内容一致，不构成过时措辞；本变更只是给它加一个读者能找到的家。
- I3: "本仓取向相反 —— `search.py` 给每个设计都搜到最好。两种都成立，但值得写进可信度文档说清" —— 已发布的项目台账（artifact）里 nano-kpu 对照那一段，把这件事记为「残余」。本变更落地后它不再是残余。 Durable owner: https://claude.ai/code/artifact/e8708cff-d1e7-4828-8391-ff0d347407d7

## Expectation Coverage

- E1: 搜索范围（`DELAY_TARGET_RATIOS`）必须进指纹，改它必须换代。 Covered by: 1.1
- E2: `fmax_mhz` 的定义（搜索得到的最优值，非物理上限）必须写在读记录的人会看到的地方。 Covered by: 1.1
- E3: 本仓数字之间的可比性来自指纹相同，不是来自参数冻结 —— 这一点必须写明。 Covered by: 1.1
- E4: 与走固定 recipe 的外部流程比较时，同名字段不是同一个量，这件事必须落到读记录的口径里而不只是某次对照的结论。 Covered by: 1.1
- E5: 本变更不产生新的一代，既有 1269 行记录一字节不动。 Covered by: 1.1
