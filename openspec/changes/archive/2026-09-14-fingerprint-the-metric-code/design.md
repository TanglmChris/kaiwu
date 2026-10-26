## Context

**F1** — 缺口可复现。把 内部#18 那次修复（`a7014ac`）的 tcl 改动撤回、只留 Python
解析侧的改动：`sta_recipe_sha256` 是 `d581f8c009b8`，与**修复前逐字相同**；
而模块 AST 哈希从 `9680b7a4638d` 变成 `e5bfe30e1841`。
Basis: 对 `a7014ac^` / `a7014ac` / 人造混合体各算一次
（`scratchpad/f25/decisive.py`）。

**F2** — **纯文档改动不分代。** `9db0feb`（提交信息就是「纠正说法，不动流程」）
与今天的 `f881f4e`（只改 `docs/` 与 `designs/*/design.md`）在七个候选模块上
AST 哈希**一个都没变**。
Basis: 逐 commit 对七个模块算 AST 哈希。

**F3** — 有行为的改动都被抓到：`a65029f`（tcl 模板加两行边界条件）与 `b252f22`
（逐端口 `foreach` + `ideal_drive_ports`）分别让 `run_sta.py` 与 `flow/paths.py`
的 AST 哈希变化。
Basis: 同 F2。

**F4** — `ast.dump` 默认 `include_attributes=False`，不带 `lineno`/`col_offset`，
所以加空行、改缩进之外的排版都不影响结果；注释根本不进 AST。docstring 会进
（`Expr(Constant(str))`），需要显式剥掉。
Basis: Python 文档 + F2 的实测。

**F5** — `scripts/run_experiment.py` **import 了** `flow.flow_fingerprint`。
所以这项哈希只能**按路径读源码**，不能 import 目标模块。
Basis: `scripts/run_experiment.py:18`。

**F6** — `flow_fingerprint.py` 的 docstring 记着当初的取舍：「哈希的是模块级常量
而不是源文件：改 `synth.py` 的注释或参数解析不影响测量结果，不该分代」，
以及「太粗比太细危险得多」。
Basis: 通读该文件。

**F7** — 加一项事实会改变全部指纹，`flow_fingerprint.py` 自己写着「那是对的 ——
那时确实换了『我们知道哪些事实决定结果』这件事本身」。
Basis: 同 F6。

## Goals / Non-Goals

**Goals:**

- 让「只改解析逻辑」必然分代。
- 让这件事**不依赖人记得**。
- 不让文档修订产生流程代噪声。

**Non-Goals:**

- **不采用手工 bump 的 `metrics_version`**（内部#25 原文的提议）。它靠人记得，
  而它要防的正是人忘了。
- 不改记录 schema 的字段集合语义（`flow` 段本来就是「指纹 + 各项事实」）。
- 不在本变更里重跑。
- 不覆盖**读取侧**（`scripts/score.py`、`gen_report.py`）—— 它们不写记录，
  改它们不改变任何已写下的数。

## Decisions

**D1** — 哈希 **AST** 而不是源文本。
Basis: F2/F4 —— 文档修订频繁（今天一天里 `run_sta.py` 的 docstring 就改了两次），
源文本哈希会让流程代被噪声淹没；而人一旦开始无视代的边界，这项事实就白加了。

**D2** — 显式剥掉 docstring。
Basis: F4 —— 注释不进 AST，docstring 进。不剥的话 F2 那两次纯文档提交就会分代。

**D3** — 以**模块**为单位，不做函数白名单。
Basis: 白名单的失效方式是"有人加了新的派生路径却忘了登记"，与这条要求要防的
是同一件事；而 F2 说明整模块的噪声成本接近零。

**D4** — 被覆盖的**模块清单本身**进入被哈希的文本。
Basis: 否则从清单里删掉一项是一次静默的覆盖面收缩。

**D5** — 按路径读源码，**不 import** 目标模块。
Basis: F5 —— `scripts/run_experiment.py` 反向 import 了本模块，import 会成环。

**D6** — 清单取这七个模块：`flow/paths.py`、`flow/sim/run_sim.py`、
`flow/sim/vcd_stats.py`、`flow/synth/synth.py`、`flow/synth/search.py`、
`flow/sta/run_sta.py`、`scripts/run_experiment.py`。
判据是「把工具输出变成记录字段，或决定要工具做什么」。
Basis: 逐字段追来源 —— `cycles`/`total_toggles` 来自 `vcd_stats`；`passed` 来自
`run_sim`；`cell_count`/`area_um2` 来自 `synth`；`delay_target_ps` 与"哪一份网表
胜出"来自 `search`；`slack`/`cp`/`级数`/`fmax`/功耗来自 `run_sta`；记录字典本身
在 `run_experiment`；`clock_signal` 与 `ideal_drive_ports` 在 `paths`。
**不含** `flow/synth/merge_liberty.py` —— 它产出的 liberty 其**内容**已经单独进了
指纹，改它的效果在下游可见。

**D7** — 新事实叫 `metrics_code_sha256`，与既有的两个 `*_recipe_sha256` 并存。
Basis: 两者语义不同（"交给工具的配方" vs "解析工具输出的代码"），
且 `abc.constr` 是独立文件，不在任何模块的 AST 里。F6 的「太粗比太细危险得多」
支持保留冗余。

## Hidden Knowledge / Assumptions

**A1** — `ast.dump` 的输出形态随 Python 版本可能变化，所以换 Python 大版本会让
全部指纹改变。
Basis: CPython 各版本陆续给 AST 节点加过字段。
Owner: **这不是缺陷。** 解释器就是跑测量代码的那个工具，换掉它与换掉 yosys
是同一类事。写进 `docs/data-credibility.md` 的分代一节。

**A2** — 假设 D6 那七个模块确实覆盖了全部派生路径。
Basis: 逐字段追过一遍（D6 的 Basis），但这是一次人工核对。
Owner: 盲区的后果是"某条路径改了而不分代"，与今天的现状相同 —— 不会比现在更差；
真正的兜底是 `tests/test_run_sta.py` 那组对committed 报告的定值断言，口径变了会红。

## Coupled Iteration Contract

不适用。

## Risks / Trade-offs

| 风险 | 后果 | 缓解 |
|---|---|---|
| 又换一次指纹 | `cda605a7` 那 87 条落进历史 | F7：加事实必然如此，重跑约 10 分钟 |
| 改 argparse 的 `help=` 字符串会分代 | 一次无意义的代 | 罕见；且方向是"太细"，F6 说那是安全的一侧 |
| 换 Python 版本会分代 | 一次无意义的代 | A1：解释器就是工具，这其实是对的 |

## Open Questions

None.
