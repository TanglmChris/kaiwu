## ADDED Requirements

### Requirement: 参数可以被声明为不参与全量扫参

`params.yaml` 中的每个参数 MAY 携带一个布尔字段 `sweep`（缺省为 `true`）。
`sweep: false` 的参数 MUST 仍然是合法参数名（可以显式指定取值、取值范围照常校验），
但 MUST NOT 参与 `sweep.py` 构造的全量参数叉乘。

动机是"只对某些其他参数取值有意义"的参数：把它放进叉乘会产生大量
参数标签不同、实际电路相同的冗余记录，污染 `results/experiments.jsonl`。

#### Scenario: 扫参时跳过被标记的参数

- **WHEN** 某设计的 `params.yaml` 中有一个参数标记为 `sweep: false`
- **AND** 对该设计发起一次全量扫参
- **THEN** 生成的参数组合数等于其余参数（`sweep` 为真的那些）取值个数的乘积
- **AND** 每个组合中该参数取其 `values` 列表的第一项

#### Scenario: 被标记的参数仍可显式指定

- **WHEN** 以显式取值发起单次实验，该取值属于某个 `sweep: false` 参数的 `values` 列表
- **THEN** 实验正常执行
- **AND** 该取值原样落进记录的 `params` 段

#### Scenario: 被标记的参数取值仍受校验

- **WHEN** 以某个 `sweep: false` 参数的、不在其 `values` 列表内的取值发起实验
- **THEN** 流程报错并列出该参数的合法取值
- **AND** 不执行仿真、综合或 STA

### Requirement: 只有不参与扫参的参数可以省略取值

发起单次实验时，`sweep: false` 的参数 MAY 省略取值，此时流程 SHALL 取其
`values` 列表的第一项。参与扫参的参数（`sweep` 缺省或为真）MUST 仍然强制给出取值，
省略 MUST 报错。无论取值来自显式给出还是默认，写入记录的 `params` 段
MUST 包含该设计声明的全部参数键。

放宽只针对 `sweep: false` 参数，是因为它们通常只对其他参数的某些取值有意义，
强制每条命令都写出来没有信息量；而扫参维度的缺失往往是笔误，
保留"缺一个就报错"的守卫。

#### Scenario: 省略一个不参与扫参的参数

- **WHEN** 发起实验时给出了全部扫参维度的取值，但省略了某个 `sweep: false` 参数
- **THEN** 该参数按其 `values` 第一项取值
- **AND** 写入的记录 `params` 段包含该设计声明的全部参数键

#### Scenario: 省略一个扫参维度

- **WHEN** 发起实验时省略了某个参与扫参的参数
- **THEN** 流程报错并指出缺少哪些参数取值
- **AND** 不执行仿真、综合或 STA

## MODIFIED Requirements

### Requirement: 流程参数必须由 params.yaml 驱动

流程的参数接口 MUST 以设计无关的映射（参数名到取值）传递，MUST NOT 把具体设计的
参数名写进函数签名。可取的参数名与取值范围 SHALL 由该设计根下的 `params.yaml` 声明。
参数声明 MAY 附带控制扫参行为的元数据（见「参数可以被声明为不参与全量扫参」），
该元数据 MUST NOT 使流程代码依赖任何具体设计的参数名。

#### Scenario: 加入一个参数集完全不同的新设计

- **WHEN** 新增一个设计，其 `params.yaml` 声明的参数名与 `adder32` 完全不同
- **THEN** 该设计可以跑完整实验流程
- **AND** `flow/` 与 `scripts/` 下没有任何文件为此需要修改

#### Scenario: 传入 params.yaml 未声明的参数

- **WHEN** 以一个 `params.yaml` 中未声明的参数名发起实验
- **THEN** 流程报错并指出该参数名未被声明
- **AND** 不执行仿真、综合或 STA

#### Scenario: 传入声明范围之外的取值

- **WHEN** 以某个已声明参数的、不在其 `values` 列表内的取值发起实验
- **THEN** 流程报错并列出该参数的合法取值

#### Scenario: 参数声明携带扫参元数据

- **WHEN** 某参数声明中带有 `sweep` 字段
- **THEN** 流程按该字段决定它是否进入全量叉乘
- **AND** 流程代码中不出现该参数的名字字面量
