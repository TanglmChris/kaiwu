# sim-regression Specification

## Purpose
TBD - created by archiving change tb-regress. Update Purpose after archive.

## Requirements

### Requirement: 自检型 TB 的回归必须有仓库内的分层入口

一个设计的自检型 SV TB 回归 MUST 由仓库内的固定入口运行：`flow/verify/regress.py`（或 `make -f flow/Makefile regress`），
读设计根 `tb/regress.<顶层>.yaml` 这一份清单。清单 MUST 分 `inner`（内循环）与 `full`（全量）两层，
两层的组合都只写在这一处。

理由是散在会话 scratchpad 里的脚本既不可复现，也会各自漂移（内部#83）。

#### Scenario: 跑内循环

- **WHEN** 运行 `regress.py --design <顶层> --tier inner`
- **THEN** 只跑清单里标了 `inner` 的组合，逐个报结论，最后报通过数与总耗时

### Requirement: 回归清单必须去重并在一个任务池里调度

引擎 MUST 把各组展开的作业合成一份清单，按「补齐 TB 默认值后的完整参数」去重；全部作业 MUST 进同一个任务池，
按预计时长降序提交（没有实测时长的排在最前）。并行度默认 MUST 不超过 4。

理由是分段串行时每段都要等自己的尾巴，而段与段之间大量重叠（内部#83 的五段 600 个作业去重后 504 个）。

#### Scenario: 省略的参数等于 TB 默认值

- **WHEN** 一组不写 `LANES`，另一组写 `LANES=2`，而 TB 里 `LANES` 的默认值是 2，其余参数相同
- **THEN** 两者只算一个作业

#### Scenario: 上次更慢的作业先跑

- **WHEN** 上一次实测里作业 A 比作业 B 慢
- **THEN** 这一次 A 先于 B 提交

### Requirement: 缺结论的作业必须算失败

每个作业的通过判据 MUST 是：输出中最后一行匹配 `done` 正则的行同时匹配 `pass` 正则。编译失败、没有 `done` 行、
超时，MUST 都算失败；有任何失败时入口 MUST 以非 0 退出。

#### Scenario: 仿真没打出结论行

- **WHEN** 某作业的仿真输出里没有匹配 `done` 的行
- **THEN** 该作业判为失败，汇报里带上输出尾巴，入口以非 0 退出
