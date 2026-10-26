## Context

**F1** — 2026-09-13 在新 clone 的机器上实测：`./scripts/fast_check.sh` 打印
`ok python compileall` 与 `SKIP iverilog not on PATH`，**退出码 0**，而
`designs/` 下三个设计的全部参数组合一个都没有 elaborate。该机 `~/tools` 整个目录
不存在（yosys / iverilog / OpenSTA 均未安装），`.venv` 也不存在。
Basis: 当日实际运行该脚本并 `echo $?`。

**F2** — 同一台机器上 `git config core.hooksPath` 为空。`.githooks/pre-push` 存在
但未被挂载，git 用的是默认 `.git/hooks/`，**该 hook 从未运行过**。
`keel --doctor` 能看出这一层（报 `core.hooksPath: unset - default (.git/hooks)`），
但那是需要主动去跑的体检，不是护栏。
Basis: 当日 `git config core.hooksPath` 与 `keel --doctor` 输出。

**F3** — `scripts/fast_check.sh` 的两类检查中，只有 RTL 那一类依赖外部工具。
Python 那一类（`compileall flow scripts`）在 `.venv` 缺失时回落到系统 `python3`
并正常执行。参数组合展开依赖 `yaml`，缺失时走的是已有的 `FAIL` 路径
（第 45–65 行），本身是诚实的。
Basis: 通读 `scripts/fast_check.sh` 全文（100 行），并在本机实测两类检查的表现。

**F4** — 本脚本 2026-09-09 刚因同一类问题修过一轮（`FOLLOWUP.md` 第 17 条，
现 `docs/data-credibility.md` 对照表记为已完成）：当时修的是「部分组合失败时仍打印
`ok ... (all param combos)`」，以及「组合展开为空时拿空参数跑一次 iverilog、
退出码 0」。回归测试在 `tests/test_fast_check.py`，夹具是独立的最小仓库。
Basis: 读 `tests/test_fast_check.py` 与该文件第 43–44、94–96 行的注释。

**F5** — `.envrc` 的第一行是 `source ~/tools/env.sh`，该文件在本机不存在。
direnv 以严格模式执行 `.envrc`，因此这一行失败会让**其后的所有行都到不了** ——
包括 `.venv` 激活，以及本变更要加的 `core.hooksPath` 自愈。
Basis: 2026-09-13 `bash -c 'set -euo pipefail; source ~/tools/env.sh; echo 到达'`
在本机输出 `No such file or directory` 且未打印「到达」。

**F6** — **direnv 本身在本机未安装**（`command -v direnv` 无输出）。
因此 D4 的自愈路径在这台机器上不会被触发，`core.hooksPath` 仍需手工设置一次。
Basis: 2026-09-13 实测。

## Goals / Non-Goals

**Goals:**

- 让 `fast_check.sh` 的退出码诚实：0 意味着它声明的检查都跑了且通过。
- 让它每次都说出自己实际覆盖了什么 —— 通过路径也要说。
- 让 `core.hooksPath` 在正常工作流里自动补齐，不依赖谁记得。
- 保留「工具没装好时也能 push」这条正当需求，但把它变成具名的、可见的降级。

**Non-Goals:**

- 不把仿真 / 综合 / STA 加进 fast_check —— 它是秒级检查，一次扫参是分钟级，
  那属于 `keel gate change-close`（脚本开头的注释已声明这条边界）。
- 不改 `.githooks/pre-push`：它只是 `exec ./scripts/fast_check.sh`，本变更的语义
  全部落在被调用方。
- 不解决 issue 内部#9（`fast_check.sh` 不覆盖 `sweep: false` 参数的非默认取值）。
  那是覆盖面本身的缺口，本变更只让**现有**覆盖面变得可见。两者叠加会让人以为
  摘要行已经完整，因此 内部#9 必须单独收口。
- 不装任何工具链。本机缺 `~/tools` 是环境问题，不是代码问题。

## Decisions

**D1** — 退出码语义定为：**0 表示「声明的检查全部执行且通过」**，而不是
「没有检查失败」。
Basis: 后者是当前语义，它让「零个检查」与「全部通过」不可区分。前者与
`experiment-trust` 第一条同构 —— 那条要求测不到就写 `null` 而不是写 `0`，
理由同样是下游必须能把「没有值」和「值是 0」区分开。

**D2** — 工具缺失**默认失败**，降级开关是 `FAST_CHECK_ALLOW_MISSING_TOOLS=1`。
Basis: 原实现选 `SKIP` 是为了不挡住 GUI 客户端 push，这个顾虑成立；但它要的是
一个降级出口，不是默认静默。做成环境变量而非命令行参数，是因为调用方是
`.githooks/pre-push`（`exec` 一行，不传参），环境变量是它唯一能被外部影响的通道。
名字里带 `ALLOW_MISSING_TOOLS` 而不是 `SKIP` 或 `FORCE`，是为了让它在 shell 历史
和 CI 配置里被读到时就能说清自己允许了什么。

**D3** — 覆盖摘要在**通过与失败两条路径上都打印**。
Basis: 成功路径才是没人细看的那条。F1 的实际表现是：日志中间有一行 `SKIP`，
结尾什么都没有，退出码 0 —— 读者看到没有 `FAIL` 就停止追问。摘要放在结尾、
紧邻退出码，是它最可能被读到的位置。

**D4** — `.envrc` 只在值不等于 `.githooks` 时写，且只写 `--local`。
Basis: 2026-09-13 用户在被告知「cd 会隐式改本地 git config」后选择此做法。
只写 `--local` 保证不触碰用户的全局配置；先读后写保证重复 cd 不产生副作用。
`.envrc` 已经是本仓的 bootstrap（`source ~/tools/env.sh` 与 `.venv` 激活都在里面），
增加一行不引入新的机制。

**D5** — 摘要里禁止用「全部 / all」描述非全部执行的集合。
Basis: F4 那次事故的具体形态就是 `ok elaborate <design> (all param combos)`
在部分组合失败时照常打印。这条写进 spec 是为了让同一个措辞陷阱不再出现在
新加的摘要行里。

**D6** — 不为「hook 未挂载」加运行时自检。
Basis: hook 未挂载时 `fast_check.sh` 根本不会被 push 调用，任何写在它里面的自检
都到不了现场。唯一能到现场的是 `.envrc`（D4）与 `keel --doctor`（已有）。

**D7** — 自愈那一行放在 `.envrc` 的**最前面**，在 `source ~/tools/env.sh` 之前。
Basis: F5 —— 那一行在缺工具链的机器上会失败并中断 `.envrc` 的其余部分，而缺工具链
的机器正是最需要这条自愈的场景（新 clone、hooksPath 未设、工具也没装）。
把自愈放在它后面，等于让它只在不需要它的机器上生效。这条顺序依赖必须写在
`.envrc` 的注释里，否则下次有人整理该文件时会把它挪走。

## Hidden Knowledge / Assumptions

**A1** — 假设 `.envrc` 的使用者启用了 direnv 并已 `direnv allow`。未启用 direnv 的
场景（GUI 客户端、CI）不会被 D4 覆盖。**本机即是此种场景**（F6：direnv 未安装），
所以本变更落地后，这台机器上的 `core.hooksPath` 仍需手工设置一次。
Basis: `.envrc` 存在且已含 `source ~/tools/env.sh`，说明本仓工作流以 direnv 为前提；
但这不能推出**每个**入口都经过 direnv。
Owner: `openspec/specs/guardrail-scope/spec.md` 的「护栏的挂载状态必须是自愈的或
可见的」—— 该 Requirement 要求「自愈**或**可见」，D4 覆盖自愈那一侧，
`keel --doctor` 覆盖可见那一侧；两者都不覆盖的入口是已知缺口，记在
内部#3。

**A2** — 假设本变更之后，没装工具链的机器上 push 被挡住是可接受的。
Basis: 这正是本变更的目的，且两条具名旁路（环境变量、`git push --no-verify`）
都在失败消息里直接给出。
Owner: 本变更的验收 —— 失败消息必须同时给出修复方式与两条旁路。

## Coupled Iteration Contract

不适用。本变更没有任务声明 `Coupling: required`。

## Risks / Trade-offs

| 风险 | 后果 | 缓解 |
|---|---|---|
| 挡住没装工具链的机器 | 只做文档的那台机器 push 被拦 | D2 的具名开关 + `--no-verify`，且写进失败消息 |
| 降级开关被长期打开 | 退回今天的状态 | 降级路径仍逐项列出未执行的检查，不会只剩一个 `ok`（D3） |
| `.envrc` 隐式改本地 git config | 用户意外发现配置变了 | 只写 `--local`、只在值不对时写、`.envrc` 里注明理由（D4） |
| 摘要行本身将来变得不准 | 又一层「报告大于实际」 | 摘要由实际执行路径累加得出，不是另写一份文案；回归测试断言摘要与实际执行一致 |

## Open Questions

**Q1** — `fast_check.sh` 当前不覆盖 `sweep: false` 参数的非默认取值
（`CSEL_BLOCK` 的 2/8/16），本变更让覆盖面**可见**但不**扩大**。
Basis: 该缺口与本变更的主题（诚实报告）正交，合并处理会让人误以为摘要行已经完整。
Resolve by: 内部#9 收口。
Owner: 内部#9
