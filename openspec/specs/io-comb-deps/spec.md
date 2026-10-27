# io-comb-deps Specification

## Purpose
被测顶层的输出端口只能组合依赖 LRS「接口组合依赖」表允许的输入端口（内部#266，用户 2026-10-11 定）。`flow/check/io_comb_deps.py` 按逐位网表实测每组配置的组合依赖，与表逐项比对，发布前必跑：跨接口的组合环与端口直通在接到实际应用之前就要查出来。

## Requirements

### Requirement: 端口组合依赖必须按逐位网表实测

`flow/check/io_comb_deps.py` MUST 对被测顶层的一组参数，算出每个输出端口组合依赖的输入端口集合（内部#266，用户 2026-10-11 定 Q1–Q5）。
- **网表**：读入集合与 `make synth` 相同；yosys 展平后用 `techmap` 拆成逐位门；
- **单元**：时序单元与存储切断依赖，其余单元的每个输出位依赖它的每个输入位；
- **不计的输入**：时钟端口（`sta.clocks`）、复位（`sim.reset_signal`）、`sta.static_ports` 匹配到的端口。

#### Scenario: 输入直通到输出

- **WHEN** 小设计里输出 `o_y` 由输入 `i_a` 经组合逻辑驱动
- **THEN** 工具 SHALL 报 `o_y ← i_a`

#### Scenario: 跨接口的握手依赖

- **WHEN** 小设计里 `o_rdy` 组合依赖 `i_vld`
- **THEN** 工具 SHALL 报 `o_rdy ← i_vld`

#### Scenario: 总线里只有一位直通

- **WHEN** 两位输出总线里一位由输入直通、另一位经寄存器
- **THEN** 工具 SHALL 报直通那一位所在的端口
- **AND** 输入只经寄存器到达的输出 SHALL NOT 被报

#### Scenario: 静态端口不计

- **WHEN** 一个输入端口匹配 `sta.static_ports` 的某个模式，并组合驱动某个输出
- **THEN** 这一对 SHALL NOT 出现在结果里

### Requirement: LRS 必须用固定写法声明接口组合依赖

在 `params.yaml` 里声明了 `iodeps_configs` 的顶层，它的接口文档 MUST 有且只有一张「接口组合依赖」表。接口文档是设计根里的 `lrs.<顶层>.md`；没有 LRS 的通用构件（`cbb/` 下按 `flow/templates/cbb-root/` 只写精简规格的）是 `spec.<顶层>.md`，两者都有时以 LRS 为准（内部#415）。下文的「LRS」都指这份接口文档；「允许的接口组合环」表也从同一份文档读。
- **认表**：表头前两格依次是「输出」「允许组合依赖的输入」。
- **「输出」格**：反引号写的端口名或通配。
- **「允许组合依赖的输入」格**：
  - 用「；」分段，每段可带条件前缀 `` `参数` 取 v1 / v2 时：``；
  - 去掉条件前缀与全角括号里的说明之后，只能是反引号写的端口 / 通配，或者「无」。
- **同名绑定**：同一行里输出与输入都含 `*` 时，两边的 `*` 匹配同一串。
- **表外的输出**不允许组合依赖任何输入端口。

#### Scenario: 写法错误

- **WHEN** 「允许组合依赖的输入」格的某一段里，除了反引号端口、「无」、条件前缀与括号说明，还有别的文字
- **THEN** 检查 SHALL FAIL，并指出 LRS 的行号

#### Scenario: 通用构件只有精简规格

- **WHEN** `cbb/<目录>/` 下的顶层声明了 `iodeps_configs`，设计根里只有 `spec.<顶层>.md`、没有 `lrs.<顶层>.md`
- **THEN** 检查 SHALL 从 `spec.<顶层>.md` 读「接口组合依赖」表

#### Scenario: 同名绑定

- **WHEN** 表里一行是 `` `m_wdat_*` `` ← `` `s_wdat_*` ``
- **THEN** `m_wdat_data ← s_wdat_data` SHALL 被允许
- **AND** `m_wdat_data ← s_wdat_strb` SHALL 判违规

#### Scenario: 条件段

- **WHEN** 一段的条件是 `` `M_RDAT_MODE` 取 2 / 3 时 ``，而这组配置取 1
- **THEN** 这一段允许的依赖 SHALL NOT 计入

### Requirement: 未声明的组合依赖必须判 FAIL

每组配置的实测结果 MUST 与 LRS 表逐项比对。
- 实测有、表里没允许的一项判违规，并给出一条从输出到输入的单元路径（带 src）；
- 表里允许、实测没有的只提示；
- 表里写的端口在顶层不存在，判写法错误。

#### Scenario: 多出一项

- **WHEN** 实测有 `o_rdy ← i_vld`，表里 `o_rdy` 一行写「无」
- **THEN** 这组配置 SHALL FAIL，报出这一对与一条路径

#### Scenario: 声明了但没有

- **WHEN** 表里允许 `o_y ← i_a`，实测没有
- **THEN** 这组配置 SHALL NOT 因此 FAIL，结果里列出这一项

### Requirement: 检查的配置由设计显式列出

`tops:<顶层>:iodeps_configs:` MUST 是非空列表，每项 `{name, <参数>: 值}`：
- name 在本顶层内唯一；
- 参数名 MUST 是顶层 RTL 模块的参数，可以不在 `params:` 里声明；
- 没给的参数取 RTL 默认值。

这份清单 SHALL NOT 进 `design_recipe`，改它不换代。

#### Scenario: 参数名写错

- **WHEN** 某一项给了顶层 RTL 没有的参数
- **THEN** 工具 SHALL 在跑 yosys 之前失败，并指出是哪一项、哪个参数

#### Scenario: 没有声明清单

- **WHEN** 顶层没有 `iodeps_configs`
- **THEN** `make iodeps` SHALL 失败，说明要先声明配置清单

### Requirement: 发布前必须跑端口组合依赖检查

声明了 `iodeps_configs` 的顶层，每次发布之前 MUST 跑 `make -f flow/Makefile iodeps DESIGN=<顶层>`，结果贴进发布 issue。任一组 FAIL 就不能发布（Q4）；有覆盖缺口（见「配置清单必须覆盖条件段与开关的每个取值」，内部#338）也不能发布。它不进 fast_check。

#### Scenario: 一组 FAIL

- **WHEN** 10 组里有 1 组 FAIL
- **THEN** `make iodeps` SHALL 以非 0 退出，汇总里列出 FAIL 的组名

### Requirement: 外部耦合下不得有未允许的组合环

声明了 `iodeps_configs` 的顶层，`make iodeps` 对每组配置 MUST 在实测的端口组合依赖上补外部模型，再找组合环。顶层端口按名字前缀 `<侧>_<通道>_` 分组，对方按侧算。外部模型 MUST 包含两类边：
- AXI 基线：本方给某个对方的每个非 rdy 输出，组合送到本方从该对方来的每个 `*_rdy` 输入；
- 显式声明：本方给某个对方的每个 `*_rdy` 输出，组合送到本方从该对方来、在 `iodeps_loops.rdy_dependent` 里声明的输入。

存在不在 LRS「允许的接口组合环」表里的环时，这组 MUST 判 FAIL，并列出环上的端口与环内的内部依赖。按通道算的环 MUST 一并列出，但不判 FAIL。

理由：io-comb-deps 的白名单只回答「依赖了什么」，不回答「接上对端时会不会成环」。内部#264 那条环就是对端的标志位随我们的 rdy 变。用户 2026-10-12 定按对方整体判（内部#281）。外部模型取 AXI 基线加显式声明，因为全连模型会把每一条合法的组合直通都判成环。

#### Scenario: 对端 flg 随本方 rdy 变（内部#264）

- **WHEN** `m_rdat_rdy` 组合依赖 `m_rdat_flg`，且 `rdy_dependent` 声明了 `m_rdat_flg`
- **THEN** SHALL 报出 `m_rdat_flg`、`m_rdat_rdy` 的环并判 FAIL
- **AND** 没有这条声明时 SHALL 不报

#### Scenario: 跨通道成环

- **WHEN** `m_cmd_vld` 组合依赖 `m_wdat_rdy`，两者都归对方 `m`
- **THEN** 按对方整体 SHALL 报出这两个端口的环并判 FAIL
- **AND** 按通道（`m_cmd` 与 `m_wdat` 分开）SHALL 不报这个环

#### Scenario: 组合直通不成环

- **WHEN** `m_cmd_vld` / `m_cmd_dat` 组合依赖 `s_cmd_vld` / `s_cmd_dat`，`s_cmd_rdy` 组合依赖 `m_cmd_rdy`，没有声明
- **THEN** SHALL 不报环

#### Scenario: LRS 允许的环

- **WHEN** 报出的环端口集合与 LRS「允许的接口组合环」表的某一行恰好对得上
- **THEN** 这个环 SHALL 标为允许，不判 FAIL

### Requirement: 前缀分不进组的端口必须显式声明

不计的端口（时钟、复位、`sta.static_ports`）之外，名字不符合 `<侧>_<通道>_` 前缀的顶层端口，MUST 在 `params.yaml` 的 `tops:<顶层>:iodeps_loops:` 里声明：`peers` 归到某个对方，或 `no_peer` 表示外部不组合送回。有未声明的端口时，这组 MUST 判 FAIL，并一次列出全部未声明的端口。

第一段是方向 `i` / `o`、后面还有一段的端口（通用构件的 `i_src_vld`、`o_dst_rdy`），第一段 MUST 当方向读，对方与通道取第二段（`src`、`dst`），MUST NOT 把 `i` / `o` 当成对方。按对方整体一条外部边都没连上时，结果里 MUST 提示「外部模型没有连上任何边」，不判 FAIL，MUST NOT 静默给出 0 个环（内部#449）。

#### Scenario: 通用构件的方向前缀

- **WHEN** 顶层端口是 `i_src_vld`、`o_src_rdy`、`i_dst_rdy`、`o_dst_vld`，没有声明 `peers`
- **THEN** 它们分到对方 `src` 与 `dst`；`o_dst_vld` 组合依赖 `i_dst_rdy` 时 SHALL 报出环

#### Scenario: 外部模型连不上边

- **WHEN** 分组之后，按对方整体没有任何一条外部边
- **THEN** 结果里 SHALL 有「外部模型没有连上任何边」的提示，这组不因此判 FAIL

#### Scenario: 中断输出没声明

- **WHEN** 顶层有输出 `alarm`，`iodeps_loops` 里没有它
- **THEN** 这组 SHALL 判 FAIL，报错里点名 `alarm`

### Requirement: 对外的同口 valid 与载荷不得允许组合依赖同口 ready

LRS「接口组合依赖」表展开到具体端口后，任何一对放行 `(输出 o, 输入 i)` 若 `i` 以 `_rdy` 结尾、`o` 以 `i` 去掉 `rdy` 后的前缀开头且 `o` 不是 `i` 本身，检查 MUST 记为错误、该组 MUST 判 FAIL（用户 2026-10-13 定，内部#286；原则见 `docs/spec-writing.md` §3「valid 不依赖 ready」）。ready 依赖别的 ready 不受本条限制。

#### Scenario: 表里放行了同口 valid ← ready

- **WHEN** 表里有一行 `` `s_cmd_vld` `` ← `` `s_cmd_rdy` ``
- **THEN** `make iodeps` 的该组 SHALL 判 FAIL，并指出 LRS 的行号与这一对端口

#### Scenario: 通配展开后命中同口载荷

- **WHEN** 表里有一行 `` `m_wdat_*` `` ← `` `m_wdat_rdy` ``
- **THEN** 展开出的 `m_wdat_dat` ← `m_wdat_rdy` 等 SHALL 各记一条错误

#### Scenario: ready 依赖 ready 不受影响

- **WHEN** 表里有一行 `` `m_rdat_rdy` `` ← `` `s_rdat_rdy` ``
- **THEN** 本条 SHALL NOT 报错

### Requirement: 配置清单必须覆盖条件段与开关的每个取值

`make iodeps` MUST 在跑 yosys 之前检查 `iodeps_configs` 的覆盖。参数的取值按有效值算：配置写了取配置值，没写取 RTL 默认值。

- LRS 接口组合依赖表里，每个条件段写到的每个（参数, 取值），MUST 至少有一组配置取到。
- `params.yaml` 里名字以 `_EN` 结尾、声明了 `values` 的参数，每个取值 MUST 至少有一组配置取到。
- 其余声明了 `values` 的参数，没取到的取值 SHALL 只作提示。

有前两类缺口时，`make iodeps` MUST 在汇总里写明缺口个数并以非 0 退出，即使每组配置自己都 PASS。只跑部分配置（`--config`）时，覆盖 MUST 仍按整份清单算。

理由：条件段与开关的某个取值没有一组配置取到时，那段条文或那种配置从没被测过，却不报（内部#338：rtl-r4 的组合环只在 `*_PT_EN=1` 下出现；内部#285 B3 的「取 0」段原先没覆盖）。

#### Scenario: 条件段的一个取值没人取到

- **WHEN** LRS 表写了 `M_RDAT_MODE` 取 1 时的依赖，而没有一组配置把它取成 1
- **THEN** `make iodeps` 点名这一行与这个取值，并以非 0 退出

#### Scenario: 开关只覆盖了一边

- **WHEN** `CHK_EN` 声明 `values: [1, 0]`，所有配置的有效值都是 1
- **THEN** `make iodeps` 点名 `CHK_EN` 取 0 没覆盖，并以非 0 退出

#### Scenario: 非开关参数的缺口

- **WHEN** `DEPTH` 声明 `values: [16, 2]`，没有一组取 2
- **THEN** 只列为提示，不影响退出码
