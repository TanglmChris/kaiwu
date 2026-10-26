## Context

**F1** — `openspec/specs/flow-parameterization/spec.md` 的
「实验记录的 schema 在本次变更中不得改变」当前是惰性的：主语「本次变更」在
`restructure-repo-layout` 归档后无指代对象；Scenario 之一断言
「`results/experiments.jsonl` 中原有的 **10 行**内容逐字节不变」，而该文件
2026-09-14 实测为 **392 行**。
Basis: 2026-09-14 读该 spec 第 48 行起整条，并 `wc -l results/experiments.jsonl`。

**F2** — `experiment-record` 的「已有记录必须保持可读」已经覆盖了
「新增字段 MUST NOT 使既有记录不可用」与「已有记录 MUST NOT 被回填或改写」，
但**没有任何 spec 禁止改名或删除字段**。`CLAUDE.md` 红线 2 的四项
（只增、不改名、不删、不回填/不重写）中，规格层只落地了后两项。
Basis: 2026-09-14 通读 `openspec/specs/` 全部 7 份 spec 的 Requirement 标题与正文。

**F3** — `experiment-record` 这个 capability 创建于 **2026-09-09**
（`df39086`，归档 `add-fmax-and-scoring`），而 `flow-parameterization` 创建于
**2026-09-06**（`384ca7b`，归档 `restructure-repo-layout`）。
Basis: `git log --diff-filter=A` 对两份 spec 文件。

## Goals / Non-Goals

**Goals:**

- 让 `CLAUDE.md` 红线 2 的四项在 `openspec/specs/` 里全部有对应 Requirement。
- 移除一条不禁止任何事、却看起来在保护 schema 的死条文 —— 它比没有更糟，
  因为读到它的人会以为这件事已经被管住了。
- 新 Requirement 无时态，对仓库全生命周期成立。

**Non-Goals:**

- 不修改 `results/experiments.jsonl` 的任何一行，也不改变它现有的字段集合。
- 不改任何流程代码，不加任何自动检查。本变更产出的是规格，不是守卫 ——
  把这条约束变成可执行的门禁是另一件事（与 issue 内部#16 相关）。
- 不动 `experiment-trust`。

## Decisions

**D1** — 落点是 `experiment-record`，不是 `experiment-trust`。
Basis: 三条。（a）两份 Purpose 的分工是明确的 —— `experiment-record` 是
「`results/experiments.jsonl` 的 schema 契约」，`experiment-trust` 是
「一个数字在什么条件下才配被记下来」；字段的增删改名是 schema 概念，与某个数字
是否可信无关。（b）F2：`experiment-record` 已持有这条约束的另一半，放在一起才是
完整的一条，分开会让读者只看到半条。（c）F3：`FOLLOWUP.md` 第 10 条曾建议
「挪到 `experiment-trust`」，但该条内容截至 2026-09-04，当时 `experiment-record`
尚不存在 —— 那个建议是在一个没有正确选项的世界里做出的。
2026-09-14 已向用户确认此落点。

**D2** — 新 Requirement **只说字段集合的单调性**，不复述「不回填、不改写」。
Basis: `knowledge-placement` 的「每类知识必须有单一权威出处」要求其余地方以引用
形式指向权威出处，MUST NOT 复述其结论。复述出来的副本会在原件更新时静默过期。
新 Requirement 在需要提及回填时，明说它「已被『已有记录必须保持可读』禁止」。

**D3** — 删除而非改写那条惰性 Requirement。
Basis: 把「本次变更」改成「任何变更」能让它复活，但那样会与 `experiment-record`
的两条产生三方重叠，且把 schema 约束留在一个主题无关的 capability 里。
`REMOVED` 的正文在归档中完整保留原文与移除理由，历史可查。

**D4** — 停止写入某字段的正确做法是让它取 `null`，而不是删掉字段名。
Basis: 这与 `experiment-trust` 的「无法测得的指标必须缺席，不得以合法值代替」
方向一致 —— 那条要求写 `null` 而不是写 `0`；本条要求写 `null` 而不是让字段消失。
两者共同的理由是：下游必须能把「没有值」和「没有这个概念」区分开。

**D5** — 嵌套字段与顶层字段同等适用。
Basis: 实际字段多数是嵌套的（`sta.fmax_mhz`、`flow.fingerprint`、
`synth.critical_path_delay_ns`）。只约束顶层等于不约束。

## Hidden Knowledge / Assumptions

**A1** — 假设「新增字段」在可预见的将来仍是安全操作，即读取工具都能容忍未知字段。
Basis: `experiment-record` 的「已有记录必须保持可读」已从另一侧要求了这一点，
且 2026-09-09 的 `add-flow-fingerprint` 实际新增 `flow` 段后老记录仍可读
（`gen_report.py` / `score.py` 把无指纹记录归入「未知代」）。
Owner: `openspec/specs/experiment-record/spec.md` 的「已有记录必须保持可读」。

## Coupled Iteration Contract

不适用。本变更没有任务声明 `Coupling: required`。

## Risks / Trade-offs

| 风险 | 后果 | 缓解 |
|---|---|---|
| 措辞过紧，连「新增字段」也被挡 | 与 `add-flow-fingerprint` 那类正当变更冲突 | Scenario 一显式给出新增字段的正例并要求它通过 |
| 规格有了但没有守卫，仍靠人遵守 | 与现状相比没有实质提升 | 明确列为 Non-Goal；把它变成可执行门禁与 issue 内部#16 一并考虑，不在本变更假装解决 |
| 删掉的条文将来被人找不到 | 以为这条约束从未存在过 | `REMOVED` 块在归档中保留原文全文与移除理由；`flow-parameterization` 的 Purpose 已说明该 capability 的主题不含 schema |

## Open Questions

**Q1** — 这条约束要不要变成可执行的检查（例如在 `fast_check.sh` 或 pre-push 里比对
`results/experiments.jsonl` 的字段集合与上一版）？本变更**不做**，只出规格。
Basis: 当前 `fast_check.sh` 在本机连 RTL 那半都跑不了（见 issue 内部#3），
在护栏本身不可靠时先加检查会得到一个不被信任的检查。
Resolve by: issue 内部#16 收口，或 issue 内部#3 关闭后重新评估。
Owner: 内部#16
