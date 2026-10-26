# ppa-scoring Specification

## Purpose

规定分数是事后导出量，不是测量结果。

打分与实验执行**解耦**：`scripts/score.py` 从已有记录算分，不跑任何 EDA 工具，
因此改权重、换基线、切换功耗口径都不需要重跑实验。反过来，分数也不得写进
实验记录（`results/<设计根>/experiments.jsonl`）—— 权重会随优化目标变，把它冻进资产等于让资产带上一个
会过期的字段。

三个口径必须是显式的。**归一化基线固定**，由配置指定，基线不存在时报错而不是
默默换一个。**功耗口径可配置** —— 同一批记录在 `iso_frequency` 与 `at_fmax` 两种
口径下参与打分的功耗不同，这个选择必须写出来而不是内置。**分数由加权比值和给出**，
公式只有一份（`sweep.py` 调用 `score.py`，不得有第二份实现）。

打分规则的改动走 `scoring.yaml`，不改代码。

最后一条与 `design-report` 对称：**打分必须限定在单一流程代内**。跨代的记录放进
同一个归一化里，比出来的是流程差异而不是设计差异。

## Requirements

### Requirement: 打分与实验执行解耦

打分工具 MUST 从 `results/*/experiments.jsonl` 读取已有记录计算分数，MUST NOT 触发
仿真、综合或 STA。

#### Scenario: 对已有记录打分

- **WHEN** 在没有 yosys / OpenSTA 可用的环境中运行打分工具
- **THEN** 工具正常输出分数表
- **AND** 不产生任何新的实验记录

### Requirement: 归一化基线固定

归一化 MUST 相对于一个固定的基线实现，MUST NOT 使用被打分批次内部的
最大/最小值。基线 MUST 写在该顶层所在设计根 `params.yaml` 的 `tops:<顶层>:score_baseline:`
（内部#314，用户 2026-10-14 定：闭源内容只放设计根，基线随设计根走）；仓库根 `scoring.yaml`
MUST NOT 再有 `baselines:`。给已删顶层的历史记录打分时，MAY 用 `--baseline-config <旧配置>`
显式取一份旧配置里的基线。

#### Scenario: 向已打分的集合中加入新记录

- **WHEN** 一条新记录被追加，然后重新打分
- **THEN** 原有各条记录的分数不变

#### Scenario: 基线记录缺失

- **WHEN** 设计根 `params.yaml` 的 `score_baseline` 指定的基线实现在 `results/<设计根>/experiments.jsonl` 中不存在
- **THEN** 工具以明确的错误说明缺少哪个基线，并且不输出分数

#### Scenario: 仓库根配置里还留着基线

- **WHEN** 默认的 `scoring.yaml` 含有 `baselines:`
- **THEN** 工具报错，点名基线应写进各设计根 `params.yaml` 的 `score_baseline`，并且不输出分数

#### Scenario: 给已删顶层的历史记录打分

- **WHEN** 以 `--baseline-config <旧 scoring.yaml>` 给一个已不在 `tops:` 里的顶层打分
- **THEN** 基线取自那份旧配置的 `baselines:`，权重等仍取当前 `scoring.yaml`

### Requirement: 功耗口径可配置

打分工具 SHALL 支持两种功耗口径：`iso_frequency`（各设计在同一参考周期下比较）和
`at_fmax`（各设计在各自 fmax 下比较）。因动态功耗与频率成正比，两种口径 MUST 由同一批
测量数据换算得到，MUST NOT 要求重跑 STA。

#### Scenario: 同频口径

- **WHEN** `power_basis` 为 `iso_frequency`、`reference_period_ns` 为 5.0
- **THEN** 每条记录参与打分的动态功耗为
  `dynamic_power_w × (clock_period_ns / 5.0)`

#### Scenario: 各自 fmax 口径

- **WHEN** `power_basis` 为 `at_fmax`
- **THEN** 每条记录参与打分的动态功耗为
  `dynamic_power_w × (clock_period_ns × fmax_mhz / 1000)`

#### Scenario: 切换口径不需要重新测量

- **WHEN** `power_basis` 从 `iso_frequency` 改为 `at_fmax` 并重新打分
- **THEN** 工具仅读取现有记录即完成，不调用任何 EDA 工具

### Requirement: 分数由加权比值和给出

每个计分维度 SHALL 先化为「越大越好」的比值：`direction: higher` 取
`value / baseline`，`direction: lower` 取 `baseline / value`；总分 SHALL 为各维度比值
按权重加权求和再除以权重之和。权重为 0 的维度 SHALL 仍然显示但不影响总分。

#### Scenario: 基线自身的分数

- **WHEN** 对基线实现本身打分
- **THEN** 其各维度比值均为 1.0
- **AND** 其总分为 1.0

#### Scenario: 权重为零的维度

- **WHEN** 某维度权重为 0 且该维度的值远劣于基线
- **THEN** 该维度出现在输出中
- **AND** 总分与去掉该维度时相同

### Requirement: 打分规则改动不需要改代码

评分权重、方向、功耗口径与参考周期 MUST 全部来自 `scoring.yaml`；各顶层的基线 MUST 来自
设计根 `params.yaml` 的 `score_baseline`。两者都不需要改代码。

#### Scenario: 调整权重

- **WHEN** 需要把性能与功耗的权重改成其它比例
- **THEN** 只修改 `scoring.yaml` 即可生效
- **AND** 不需要修改任何 `.py` 文件

#### Scenario: 换一个顶层的基线

- **WHEN** 需要换某个顶层的归一化基线
- **THEN** 只修改该设计根 `params.yaml` 的 `score_baseline` 即可生效
- **AND** 不需要修改任何 `.py` 文件

### Requirement: 打分必须限定在单一流程代内

打分工具 SHALL 默认只给最新一个流程代的记录打分，并 MUST 说明被排除的条数。
归一化基线所在的记录 MUST 与被打分的记录同代；不同代时工具 MUST 报错并且不输出
任何分数，MUST NOT 给出跨代的比值。

跨代比值把「流程改了多少」算进了「设计好了多少」里，是一个看不出错的错数。

#### Scenario: 记录跨越多个流程代

- **WHEN** 某设计的记录里存在两个及以上不同的流程代
- **THEN** 只有最新一代的记录出现在分数表里
- **AND** 输出说明被排除的条数

#### Scenario: 基线与被打分记录不同代

- **WHEN** 配置指定的基线只存在于较早的流程代中
- **THEN** 工具报错说明基线属于另一个流程代
- **AND** 不输出任何分数

#### Scenario: 显式要求给全部记录打分

- **WHEN** 以「不限定流程代」的方式打分
- **THEN** 全部记录都参与
- **AND** 输出标明这些分数跨越多个流程代

### Requirement: 每个被测顶层都必须有按顶层名声明的基线

`params.yaml` 的 `tops:` 声明的每一个顶层 MUST 在同一处有 `score_baseline`；它的键 MUST 是该顶层
当前在 `params:` 里声明的参数名，值 MUST 在声明的取值之内。这一条 MUST 有机械检查（内部#63：模块名改大写之后
基线键还是小写，`score.py --design ADDER32` 失败了 6 天而没有任何东西报错）。

#### Scenario: 一个顶层没有基线

- **WHEN** `tops:` 声明了某个顶层，而它没有 `score_baseline`
- **THEN** 检查 SHALL 失败，并点名这个顶层

#### Scenario: 基线键指向不存在的顶层

- **WHEN** 仓库根 `scoring.yaml` 还留着 `baselines:`（例如旧的小写顶层名），而基线已改由设计根声明
- **THEN** 检查 SHALL 失败，并点名这个键与该迁去的位置

#### Scenario: 基线用了旧参数键

- **WHEN** 某顶层的 `score_baseline` 有一个键不在它的 `params:` 声明里（例如改名前的旧键）
- **THEN** 检查 SHALL 失败，并点名这个顶层与这个键
