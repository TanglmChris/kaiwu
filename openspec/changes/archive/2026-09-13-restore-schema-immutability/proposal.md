## Why

`CLAUDE.md` 的红线 2 说：「`results/experiments.jsonl` **只增字段**，不改名、不删、
不回填、不重写历史行。改 schema 是仓库里风险最高的改动。」

这条红线在 `openspec/specs/` 里**没有一条完整对应的 Requirement**：

- `experiment-record` 的「已有记录必须保持可读」覆盖了**不回填、不改写**，
  以及「新增字段 MUST NOT 使既有记录不可用」。
- 「**不改名、不删除**」没有任何 spec 说。
- `flow-parameterization` 里有一条看起来在管这件事的
  「实验记录的 schema 在本次变更中不得改变」，但它**是惰性的**：

  > 「**本次变更** MUST NOT 新增、改名或删除 `results/experiments.jsonl` 中的任何字段」

  这句是 `restructure-repo-layout` 归档时带过来的，归档后「本次变更」已无指代对象 ——
  它现在不禁止任何事。两个 Scenario 同样朽了：一个以「本次变更的全部任务完成」
  为触发条件，另一个断言「原有的 **10 行**内容逐字节不变」，而该文件现在有 392 行。

所以仓库当前的实际状态是：**最高风险的那条约束只活在 `CLAUDE.md` 的散文里，
`openspec` 一侧是一条不禁止任何事的死条文。** 这与 issue
内部#16 记的路由缺口叠加 ——
那条 issue 说改 schema 会被按体积判到 Lite，「目前靠 `CLAUDE.md` 的红线 2 顶着」，
而红线 2 在规格层并没有落地。

## What Changes

- **从 `flow-parameterization` 移除**「实验记录的 schema 在本次变更中不得改变」
  整条 Requirement（含两个朽掉的 Scenario）。该 capability 管的是「参数属于设计
  不属于流程」，schema 保护从来不是它的主题，当初落在这里是归档的副产物。
- **在 `experiment-record` 补上真正缺失的那一半**：字段 MUST NOT 被改名或删除。
  写成无时态的表述，并配可检验的 Scenario。
- **不重复已有内容**：「不回填、不改写」已由 `experiment-record` 的「已有记录必须
  保持可读」覆盖，新 Requirement 只说字段集合的单调性，不复述它。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `experiment-record`: 新增一条 Requirement，禁止改名或删除 `results/experiments.jsonl`
  的已有字段，使字段集合只能单调增长。
- `flow-parameterization`: 移除一条因归档而失去指代对象的惰性 Requirement。

## Impact

**受影响的文件**：2 个 spec，无代码改动。

| 文件 | 动作 |
|---|---|
| `openspec/specs/experiment-record/spec.md` | +1 Requirement（6 → 7） |
| `openspec/specs/flow-parameterization/spec.md` | −1 Requirement（6 → 5） |

**不受影响**：`results/experiments.jsonl` 一行不动；任何流程代码；任何已记录的
PPA 数字。本变更**不修改 schema**，它恢复的是禁止修改 schema 的那条约束。

**风险**：低。主要风险是措辞写得过紧，把「新增字段」这个明确允许的操作也挡住 ——
缓解是 Scenario 里显式给出一个「新增字段应当通过」的正例。

**为什么走 Full**：这条 Requirement 保护的是仓库最高价值的资产，且本变更是
`REMOVED` + `ADDED` 的跨 capability delta 操作。红线 2 本身不直接触发
（本变更不改 schema），但它保护的正是红线 2 的规格化身。

**落点为什么是 `experiment-record` 而不是 `experiment-trust`**：见 design.md 的 D1。
`FOLLOWUP.md` 第 10 条曾建议挪到 `experiment-trust`，那条建议写于
2026-09-04，而 `experiment-record` 2026-09-09 才存在。
