## Why

**换代重跑没有断点续跑**（本仓 内部#37）。

`--skip-existing` 的匹配依据**只有参数组合、不含代码版本** —— 这是有意的，
且必须保持（同一组合在不同 commit 下结果可能不同，跳过就漏掉重测）。但换代重跑
的全部意义就是同一组合要在新代下重测一遍，所以那个开关在这个场景下**开了等于
一条都不补**。

2026-09-15 重跑 92 条时（`support-multi-clock-sta-constraints`，内部#23）实际撞到：
`make sweep` 被 OS 按内存杀掉两次（不是失败，事后 `free -g` 仍有 26 GiB 可用），
每次都得人工按 `(design, params)` 对上一代取差集、再逐条 `make exp` 补。
取差集的代码每次现写，而**写错了不报错** —— 少补几条的后果是新一代不完整，
而「92 条」与「89 条」在记录里长得一模一样。

换代重跑是这个仓库的**常规动作**：`docs/data-credibility.md` 的分代表里已经
12 代，其中至少四次是「改了 `METRIC_MODULES` 里的文件 → 全量重跑」。

顺带两件在同一次事故里暴露的：

- `scripts/sweep.py` **一个测试都没有**，而它是唯一能一次写 72 条记录的入口。
- `make sweep` 除了日志没有任何进度输出，被杀之后连「跑到哪了」都要去翻
  `results/experiments.jsonl` 数。

## What Changes

- **新增 `--skip-existing-generation`**（Makefile 侧 `SKIP_EXISTING_GENERATION=1`）：
  匹配依据是 `(design, params, flow.fingerprint)` 三元组，只跳过**本代已有**的
  组合。指纹由本次运行的 `liberty` 与 `sim` 现算，与记录里的比。
- **与 `--skip-existing` 互斥**：同时给两个当场报错。两者语义不同
  （「这个组合跑过没有」vs「这个组合在**本代**跑过没有」），让其中一个静默压过
  另一个，就是把「我以为跳的是这一代」变成一个不会报错的误解。
- **覆盖必须可读**：开始时打印「本代已有 M / 共 N 个组合，本次要跑 K 个」，
  结束时打印「本代现有 M' / N」。`guardrail-scope` 的同一条要求 ——
  「跑完了」与「跳过了一大半」在输出上必须可区分。
- **逐组合进度**：每条前面打 `[i/N]`，被杀之后能直接从日志读出跑到哪了。
- **`scripts/sweep.py` 第一次有测试**：`tests/test_sweep.py`。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `guardrail-scope`: 新增「扫参必须说出它这一轮实际覆盖了哪些组合」——
  与既有的「护栏必须报告它实际覆盖的范围」同源，但对象是扫参而不是护栏。

## Impact

- `scripts/sweep.py`、`flow/Makefile`、`tests/test_sweep.py`（新增）、
  `CLAUDE.md`（两个开关的说明要写清区别）
- **不换代**：三个文件**都不在** `flow_fingerprint.METRIC_MODULES` 里
  （那七个是 `flow/paths.py`、`flow/sim/run_sim.py`、`flow/sim/vcd_stats.py`、
  `flow/synth/synth.py`、`flow/synth/search.py`、`flow/sta/run_sta.py`、
  `scripts/run_experiment.py`）。当前代 `0c80b2af` 的 92 条不受影响。
  **必须实测确认**。
- **不改 `--skip-existing` 的语义一个字符**：它在「续跑同一代的中断扫参」
  这个场景下仍然是对的，而且 `CLAUDE.md` 明文写着它的匹配依据。
  两个开关并存，不合并。
