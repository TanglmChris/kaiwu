## ADDED Requirements

### Requirement: 无法测得的指标必须缺席，不得以合法值代替

当某个指标所依赖的输入不存在或不可信时，流程 MUST 报错或写入 `null`，
MUST NOT 写入一个语法合法、看上去正常的替代值（例如 `0`）。

判据是「读记录的人能否分辨这个值是测出来的还是凑出来的」。凑出来的值一旦落进
`results/experiments.jsonl` 就无法事后识别，会污染整个数据集。

#### Scenario: VCD 中找不到指定的时钟信号

- **WHEN** 统计仿真活动时，指定的时钟信号名在 VCD 中不存在
- **THEN** 报错并指出找不到的信号名
- **AND** 错误信息列出 VCD 中实际存在的顶层信号，便于对照
- **AND** MUST NOT 返回 `cycles` 为 `0` 的结果

#### Scenario: 时钟信号存在且被找到

- **WHEN** 指定的时钟信号名在 VCD 中存在
- **THEN** `cycles` 为该信号的上升沿计数
- **AND** 与本次变更之前对同一 VCD、同一信号名的统计结果相同

### Requirement: 仿真未通过时不得记录依赖该仿真的指标

动态功耗与静态功耗由 STA 从仿真产出的 VCD 反标算得。当仿真未通过时，
该 VCD 描述的是一次错误的行为，据此算出的功耗 MUST NOT 被记录为该设计的功耗。

流程 MUST 仍然写入记录（`sim.passed` 为 `false` 本身是有价值的信息），
但依赖仿真活动的字段 MUST 为 `null`。不依赖仿真的字段（面积、单元数、
关键路径延时与级数）SHALL 照常记录。

#### Scenario: 仿真未通过但产出了 VCD

- **WHEN** 仿真跑完但存在失败用例，且 VCD 已生成
- **THEN** 记录被写入，`sim.passed` 为 `false`
- **AND** `sta.dynamic_power_w` 与 `sta.static_power_w` 为 `null`
- **AND** `synth.area_um2`、`synth.cell_count`、`synth.critical_path_delay_ns` 照常有值

#### Scenario: 仿真通过

- **WHEN** 仿真全部用例通过且产出 VCD
- **THEN** 功耗字段照常由 VCD 反标算得并记录

### Requirement: 缺少必需输入时必须报出真正的原因

当流程的某一段缺少上游产出时，报出的错误 MUST 指明缺的是什么、由哪一段产生，
MUST NOT 把缺失值传给外部工具并让用户面对该工具的内部错误。

#### Scenario: 仿真未产出 VCD 就进入 STA

- **WHEN** 仿真未产出 VCD，而流程需要 VCD 做功耗反标
- **THEN** 报错说明仿真未产出 VCD
- **AND** MUST NOT 调用 OpenSTA
- **AND** 错误信息中不出现 `read_vcd None` 这类工具内部语法
