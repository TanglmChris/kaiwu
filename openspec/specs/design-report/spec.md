# design-report Specification

## Purpose

规定 `REPORT.md` 是记录的一个视图，不是第二份真相。

报告 MUST 完全由实验记录（`results/<设计根>/experiments.jsonl`）生成，不含任何不能从记录推导的数据，
且不得手工编辑。生成 MUST 是**确定性的** —— 同一份记录产生逐字节相同的输出，不带
时间戳、不带随机顺序、浮点数固定位数；这样 `git diff` 里出现的每一处变化都对应
记录的真实变化，而不是噪声。

**刷新报告不得是实验的副作用**：跑实验或扫参不写任何 `REPORT.md`，必须由一条独立
的显式命令触发。理由是副作用式的生成会让报告在你没打算更新它的时候更新，而你从
diff 里看不出那是有意的还是顺带的。

两条关于「不要造出不存在的东西」的要求。**Pareto 前沿按 (面积, 延时) 去重** ——
前沿回答的是「哪些配置值得考虑」，重复行不增加信息，只让读者以为存在多个点。
**报告必须限定在单一流程代内** —— 这一条来自一次真实事故：某个闭源设计的前沿
里曾同时出现同一配置的新旧两个点，老点（12.3168 ns）在面积轴上「支配」新点
（1.1558 ns），看起来像一个真实的取舍，其实只是老流程的残留。

同时**全量表必须能区分重复测量** —— 前沿去重，全量表不去重，两者用途不同。

## Requirements

### Requirement: REPORT.md 必须只从实验记录派生

`designs/<name>/REPORT.md` 与 `cbb/<name>/REPORT.md` MUST 完全由
`results/<设计根>/experiments.jsonl` 中该设计的记录生成，MUST NOT 包含任何不能从记录推导出的
数据。该文件是生成产物，MUST NOT 被手工编辑。

#### Scenario: 删除后重新生成

- **WHEN** 删除某设计的 `REPORT.md` 并重新运行生成命令
- **THEN** 得到的文件与删除前的内容逐字节相同

#### Scenario: 没有任何实验记录的设计

- **WHEN** 对一个在 `results/<设计根>/experiments.jsonl` 中尚无记录的设计运行生成命令
- **THEN** 命令成功，生成的 `REPORT.md` 明确表示尚无实验数据
- **AND** 不报错、不产生空文件

### Requirement: REPORT.md 的生成必须是确定性的

对同一份 `results/<设计根>/experiments.jsonl`，生成命令 MUST 产生逐字节相同的输出。
输出 MUST NOT 包含生成时间戳、随机顺序或运行环境相关的内容。记录 SHALL 按稳定的
键排序，浮点数 SHALL 使用固定的格式化位数。

#### Scenario: 连续生成两次

- **WHEN** 在不改动 `results/<设计根>/experiments.jsonl` 的前提下连续运行两次生成命令
- **THEN** 两次产生的 `REPORT.md` 逐字节相同
- **AND** `git diff` 对该文件没有输出

#### Scenario: 记录在文件中的先后顺序改变

- **WHEN** 两份 `results/<设计根>/experiments.jsonl` 含有相同的记录集合但行序不同
- **THEN** 由它们生成的 `REPORT.md` 逐字节相同

### Requirement: 生成 REPORT.md 不得是实验执行的副作用

运行实验或扫描参数 MUST NOT 写入或修改任何 `REPORT.md`。刷新 `REPORT.md` SHALL 只能
由一条独立的、显式的命令触发。

#### Scenario: 扫描期间工作区保持干净

- **WHEN** 对某设计扫描全部参数组合
- **THEN** 期间和结束后都没有 `REPORT.md` 被修改
- **AND** 工作区不因扫描而变脏，后续实验记录的 `git_commit` provenance 仍然有效

#### Scenario: 显式刷新

- **WHEN** 运行独立的报告生成命令
- **THEN** 该设计的 `REPORT.md` 被更新
- **AND** 不触发任何仿真、综合或 STA

### Requirement: Pareto 前沿中同一个点只出现一次

面积-延时 Pareto 前沿 MUST 按 (面积, 关键路径延时) 去重。同一参数组合被重复测量
多次时，前沿 MUST 只列出一行。

前沿的用途是回答「哪些配置值得考虑」，重复行不增加任何信息，只会让读者误以为
存在多个不同的点。

#### Scenario: 同一参数组合被测量多次

- **WHEN** 某参数组合在记录中出现 N 次且指标相同
- **THEN** 该点在 Pareto 前沿中只出现一行

#### Scenario: 同一参数组合的两次测量指标不同

- **WHEN** 某参数组合出现两次但面积或延时不同
- **THEN** 两个点分别参与支配关系判断
- **AND** 未被支配的都列出

### Requirement: 全量表必须能区分重复测量

全量记录表 SHALL 列出所选流程代的全部记录（不去重），且 MUST 提供足以区分同一
参数组合的不同次测量的信息。

#### Scenario: 同一组合出现多行

- **WHEN** 全量表中同一参数组合占据多行
- **THEN** 这些行之间存在至少一个可区分的列
- **AND** 读者能判断它们是重复测量而非不同配置

### Requirement: 报告必须限定在单一流程代内

`REPORT.md` 的全量表与 Pareto 前沿 SHALL 只呈现同一个流程代的记录，默认取该设计
记录中最新的那一代（`flow.fingerprint` 出现在时间最晚的记录里的那一个）。
被排除的记录 MUST 在报告里以条数和原因说明，MUST NOT 静默消失。

跨代的点放进同一条 Pareto 前沿会得出假结论：旧流程的点可能在面积轴上「支配」
新流程的同一配置，看起来像一个真实取舍。

#### Scenario: 记录跨越多个流程代

- **WHEN** 某设计的记录里存在两个及以上不同的流程代
- **THEN** 全量表与 Pareto 前沿只含最新一代的记录
- **AND** 报告中写明被排除的条数

#### Scenario: 显式要求看全部

- **WHEN** 以「不限定流程代」的方式生成报告
- **THEN** 全部记录都进入全量表
- **AND** 报告写明这些记录跨越多个流程代、并排比较无效

#### Scenario: 全部记录同代

- **WHEN** 某设计的记录全部出自同一流程代
- **THEN** 报告不因此排除任何记录

### Requirement: Pareto 前沿必须按规模维度分组

面积-延时 Pareto 前沿 MUST 按该设计全部 `role: scale` 参数的取值**分组**，
每一组取值各出一张前沿表，表的标题 MUST 写明这一组是哪些取值。
同一张前沿表内 MUST 只包含 `scale` 取值完全相同的记录。

把规模不同的点放进同一条前沿，得到的不是取舍而是同义反复：做的活少的那档
必然又小又快，于是前沿永远由最小的那档独占。这与「报告必须限定在单一流程代内」
是同一个形状的错误 —— 那条防的是拿不同流程的点互相支配，这条防的是拿不同
功能规模的点互相支配。两者都会产出一张看起来完全正常的表。

实例（2026-09-16，某个闭源设计）：规模参数进扫参之后前沿三档全是最小那档，
而 256 位的 line 比 1024 位的少做四倍的活。

#### Scenario: 设计同时有 scale 与 microarch 维度

- **WHEN** 生成前沿时该设计有至少一个 `scale` 参数和至少一个 `microarch` 参数
- **THEN** 每一组 `scale` 取值各出一张前沿表
- **AND** 每张表的标题 MUST 写明该组的 `scale` 取值
- **AND** 支配关系 MUST 只在同组内判断

#### Scenario: 设计只有 microarch 维度

- **WHEN** 该设计没有任何 `role: scale` 的扫参参数
- **THEN** 前沿 SHALL 是一张表，与分组前的行为一致

#### Scenario: 设计没有任何 microarch 维度

- **WHEN** 该设计的扫参参数全部是 `role: scale`
- **THEN** 报告 MUST NOT 印出前沿表
- **AND** MUST 写明本设计没有微架构维度、无取舍可言

分组之后每组只剩一个点，那样的「前沿」每张都是单行表。印出来比不印更误导：
它看起来像一个结论，实际上只是把每条记录各抄了一遍。

### Requirement: 报告必须按名字显示结构枚举

生成 `REPORT.md` 时，声明了 `labels` 的参数 MUST 显示成「编号 (名字)」（如 `1 (CLA)`），名字取自
**生成报告时**该设计的 `params.yaml`。记录里的取值 MUST NOT 被改写；排序与分组 MUST 仍按编号。

#### Scenario: 记录里的编号有名字

- **WHEN** 一条 `ADDER32` 记录的 `params.SCHEME` 是 `1`，`params.yaml` 的 `labels` 给 `1: CLA`
- **THEN** 报告的单元格 SHALL 是 `1 (CLA)`

#### Scenario: 分界之前的字符串取值

- **WHEN** 报告读到的记录 `params.SCHEME` 是字符串（分界之前）或是 `labels` 里没有的编号
- **THEN** 单元格 SHALL 原样显示记录里的取值
- **AND** MUST NOT 猜名字、MUST NOT 报错

### Requirement: 报告必须给出每个配置的面积拆分表

`REPORT.md` MUST 为本代每个带 `synth.area_breakdown` 的配置给出一张面积拆分表（内部#174），所有设计用同一种表头：层次 × {面积 µm²、门数、单元数、时序面积、组合面积、占比}，顶层一行汇总；声明了存储模型的设计另附一行存储模型合计，以及一行「扣除存储模型后」的逻辑面积与门数。门数 = 面积 ÷ 记录里 `gate_unit` 的面积。没有这个字段的旧记录 MUST 注明「记录无面积拆分」，MUST NOT 留空让人以为是 0。

#### Scenario: 存储模型单列

- **WHEN** 设计声明了 `memory_models`，某个配置的记录带面积拆分
- **THEN** 该配置的表里有存储模型合计一行，以及「扣除存储模型后」一行

### Requirement: 报告必须列出按场景的时序

本代有记录带非空 `sta.scenarios` 时，`REPORT.md` MUST 给出「按场景的时序」一节：每个配置一行，每个场景列出 TT 关键路径延时、级数、fmax 与 SS 延时、slack，并列出主字段的 TT 延时作对照，写明主 fmax 是各场景最坏。没有记录带场景的设计 MUST NOT 出现这一节。

#### Scenario: 按场景列出

- **WHEN** 设计声明了两个场景、记录带 `sta.scenarios`
- **THEN** 报告的「按场景的时序」一节每个配置一行、两个场景各一组列

### Requirement: 报告必须单列参考口径

本代有记录带非空 `reference` 时，`REPORT.md` MUST 给出「参考口径」一节：写明口径（配置端口按目标配置接成常数、跨层次优化、保层级），每个带 `reference` 的配置一行，列参考口径的面积、门数、时序面积、TT fmax、关键路径级数、超预算终点数，以及「参考 − 正式」的面积、时序面积、fmax 差值。参考值 MUST NOT 出现在正式口径的表里。表里 MUST 有「等价」一列：PROVED 写「已证」，SKIPPED（设计声明不做等价，内部#232）写「未经等价验证」，两者都照常列参考值与差值。`reference.equiv` 是 UNDECIDED 或 FAILED 的配置 MUST 只列场景与「未证等价（<结论>），不报数」，不列参考值与差值。没有记录带 `reference` 的设计 MUST NOT 出现这一节。

#### Scenario: 参考与正式的差值

- **WHEN** 一个配置的记录带 `reference`
- **THEN** 「参考口径」一节有它一行，差值等于参考值减正式值

#### Scenario: 未经等价验证照常报数

- **WHEN** 一个配置的 `reference.equiv` 是 `SKIPPED`
- **THEN** 它在参考口径表里照常有参考值与差值，「等价」一列写「未经等价验证」
