## REMOVED Requirements

### Requirement: 实验记录的 schema 在本次变更中不得改变

本次变更 MUST NOT 新增、改名或删除 `results/experiments.jsonl` 中的任何字段，
也 MUST NOT 改写任何已有记录。

#### Scenario: 变更完成后检查历史文件

- **WHEN** 本次变更的全部任务完成
- **THEN** `results/experiments.jsonl` 中原有的 10 行内容逐字节不变

#### Scenario: 变更后写入的新记录

- **WHEN** 变更完成后运行一次实验
- **THEN** 新记录的字段集合与变更前的记录字段集合相同

**移除理由**：这条 Requirement 是 `restructure-repo-layout` 归档时带过来的，
主语「本次变更」在归档后已无指代对象，因此它当前**不禁止任何事**。两个 Scenario
同样失效：一个以「本次变更的全部任务完成」为触发条件，另一个断言「原有的 10 行
内容逐字节不变」，而 `results/experiments.jsonl` 现在有 392 行。

它保护的内容不因移除而消失，而是被拆到它们各自的归属：字段集合的单调性（不改名、
不删除）成为 `experiment-record` 的新 Requirement「实验记录的字段集合只能单调增长」；
「不回填、不改写」本就已由 `experiment-record` 的「已有记录必须保持可读」覆盖。

`flow-parameterization` 管的是「参数属于设计不属于流程」，schema 保护从来不是
它的主题。
