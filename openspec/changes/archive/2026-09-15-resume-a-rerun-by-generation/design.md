## Context

本仓库的换代重跑（改了 `flow_fingerprint.METRIC_MODULES` 里的任一文件 → 全部
既有记录变成上一代 → 全量重跑）是常规动作：`docs/data-credibility.md` 的分代表
已经 12 代。重跑一个设计的全量组合动辄几十分钟到几小时，**中途被打断是常态**
（2026-09-15 那次是被 OS 按内存杀掉两次）。

现有的 `--skip-existing` 在这个场景下帮不上忙，而且**它不该被改成能帮上忙**：
它的匹配依据只有参数组合、不含代码版本，这是写在 `CLAUDE.md` 与
`sweep()` docstring 里的有意选择。

F1 — `scripts/sweep.py`、`flow/Makefile`、`tests/test_sweep.py` **都不在**
`flow_fingerprint.METRIC_MODULES` 里。Basis：`flow/flow_fingerprint.py` 的
`METRIC_MODULES` 常量（七项，2026-09-15 读）。所以本变更**不分代**，当前代
`0c80b2af` 的 92 条不受影响 —— 但这要在实现里实测确认（M6）。

F2 — 读取侧已有现成的分代工具：`flow_fingerprint.generation_key(record)` /
`latest_generation(records)`。分代规则只写一份，`score.py` 与 `gen_report.py`
共用。Basis：`flow/flow_fingerprint.py` 末段「读取侧」注释。

F3 — `run_experiment()` 返回的记录里带 `record["flow"]["fingerprint"]`，
由 `flow_fingerprint(liberty, sim=sim)` 现算。Basis：
`scripts/run_experiment.py:137`。

## Goals / Non-Goals

**Goals:**

- 换代重跑被打断之后，重新起一条命令就能只补本代还缺的组合。
- 「这一轮实际覆盖了哪些组合」在输出里看得见，成功路径上也看得见。
- 被打断时，从日志能直接读出跑到第几个组合。
- `scripts/sweep.py` 第一次有测试。

**Non-Goals:**

- 不改 `--skip-existing` 的语义。两个开关并存。
- 不做断点文件 / 状态文件。唯一的真相是 `results/experiments.jsonl`，
  再引入一份状态就有两份可能不一致的真相，而不一致的那一份不会报错。
- 不做并行扫参。被 OOM 杀掉的那次正是因为内存，并行只会更糟。
- 不自动决定「用哪个开关」。见 D2。

## Decisions

**D1 — 新开关叫 `--skip-existing-generation`，匹配键是
`(design, params, flow.fingerprint)`。**
Basis：换代重跑要补的正是「本代缺的」，而「本代」的唯一机械定义就是指纹。
设计名与参数组合沿用 `--skip-existing` 的口径，只多加一维。

指纹从哪来：sweep **开跑前算一次**
`flow_fingerprint(liberty, sim)["fingerprint"]`，用它过滤。不从记录里猜
「最新一代」—— `latest_generation()` 给的是记录里最后一条所属的代，而重跑到
一半时那恰好就是本代，看起来对；但在**换代之后第一次跑**的时刻，记录里最后
一条还属于上一代，`latest_generation()` 会把整代都判成「已有」，一条都不跑，
且以 0 退出。那是这个开关能犯的最严重的错误，且完全静默。

**D2 — 两个开关同时给出时当场报错，不做优先级。**
Basis：`guardrail-scope` 的新条款。两者的输出长得一模一样（都是「跳过 N 条」），
差别只在 N 按什么算。让一个静默胜出，产出的是一个不会报错的误解。
报错文本要写清两者口径，而不只是说「互斥」。

**D3 — 每跑一条打 `[i/N] design {params}`，i 是**组合序号**（含被跳过的），
N 是组合总数。**
Basis：被杀之后要能从日志直接读出位置。用「本轮第几条」而不是组合序号，
在开了跳过开关时会与总数对不上，读日志的人要自己做减法。被跳过的那些同样打
`[i/N] … 已有本代记录，跳过`，序号连续。

**D4 — 覆盖摘要打两行：开跑前一行、结束时一行，都走 stdout。**

```
# sweep adder32: 共 72 个组合，本代（flow=0c80b2af）已有 69 条，本轮要跑 3 条
#   跳过口径: (design, params, flow.fingerprint)
...
# sweep adder32 结束: 本轮跑了 3 条，本代现有 72/72
```

Basis：`guardrail-scope` 的「摘要必须在通过与失败两条路径上都输出」。
结尾那行的 `72/72` 是**重新数一遍记录**得到的，不是 `69+3` 算出来的 ——
算出来的那个数在「某条实验虽然跑了但没写进记录」时仍然是 72，而重数一遍会
露出来。不开跳过开关时摘要照打，口径那行写「无（全部重跑）」。

**D5 — 结尾摘要写在 `finally` 里。**
Basis：同上条款的「中途失败路径也要输出」。某个组合抛异常时，已经跑完的那些
是真实产出，摘要必须反映它们。异常继续往外抛，退出码仍然非 0。

**D6 — 每条实验跑完后校验它的指纹与开跑前算的那个一致，不一致就中止。**
Basis：这是 D1 的闭环。sweep 按指纹 X 过滤，若 `run_experiment` 写出的是指纹 Y
（liberty 被换掉、工具被换掉、有人在跑的过程中改了 `METRIC_MODULES` 里的文件），
那么本轮补的这些条根本不属于它以为的那一代，而新一代会**永远差着**被跳过的
那几十条 —— 且没有任何迹象。检查一行，代价为零。
只在开了 `--skip-existing-generation` 时检查：不开时没有「本代」这个前提。

**D7 — 「已有」只看记录在不在，不看 `sim.passed`。**
Basis：与 `--skip-existing` 保持同一口径。一条 `passed: false` 的记录也是这一代
对这个组合的测量结果，重跑它不会变成 true（RTL 没改），跳过是对的。
这条写进摘要的口径说明里，以免读者以为跳过的都是成功的。

## Hidden Knowledge / Assumptions

A1 — 本变更不改变任何既有记录，也不分代。
Resolve by：M6（跑一次全量测试 + 实测 `flow_fingerprint` 在改前改后逐字相同
+ `cmp` 确认 `results/experiments.jsonl` 前 1269 行未动）。

A2 — `flow_fingerprint()` 在 sweep 开跑前调一次是可接受的开销：它起三个
`-V` 子进程并读一遍合并 liberty（约 40 MB）。相对一次动辄几十分钟的扫参可以忽略。
Resolve by：实现时实测一次耗时，超过 2 秒就记进 design。

## Risks / Trade-offs

- **两个开关的名字很像**（`SKIP_EXISTING` / `SKIP_EXISTING_GENERATION`），
  容易打错。缓解：D2 的互斥报错管的是「两个都给」；「给错了一个」靠 D4 的
  摘要里那行口径说明兜住 —— 摘要会明说这一轮按什么匹配、跳了多少条，
  跳的条数与预期差一个数量级时一眼能看出来。
- **`make sweep` 的变量传递**：`SKIP_EXISTING_GENERATION=1` 与
  `SKIP_EXISTING=1` 都传下去时，Makefile 不拦，Python 侧报错。这是有意的 ——
  拦截逻辑只写一份，Makefile 里不长逻辑（`flow/Makefile` 开头的注释就是这条）。
- **本轮跑的组合与记录里多出来的条数可能对不上**：`run_experiment` 每次都追加
  一条，所以正常情况下相等。D4 的结尾摘要重数一遍记录，正是为了让不相等这件事
  可见。

## Open Questions

None.
