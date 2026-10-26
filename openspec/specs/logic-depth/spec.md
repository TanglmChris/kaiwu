# logic-depth Specification

## Purpose
不写实验记录地量任一模块的逻辑级数：综合口径与实验流程相同，级数按组合单元个数与预算比，可按验收场景给静态输入定值分别量；两次结果能按终点集合比，也能按同一终点比路径在各模块里的构成（内部#111、内部#189、内部#225、内部#340）。

## Requirements

### Requirement: 可以不写记录地量任一模块的逻辑级数

流程 MUST 提供一个入口（`flow/synth/depth.py`，`make -f flow/Makefile depth`），对一个被测顶层的源文件集合里的任一模块（默认就是被测顶层），在给定参数下综合并报出最坏路径的逻辑级数、到达时间与起止点。

- 综合 MUST 用实验流程同一份 yosys 配方与 liberty；级数 MUST 按 `run_sta` 的同一套规则从最坏路径块数出，到达时间与起止点 MUST 取自同一块。
- 它 MUST NOT 写 `results/*/experiments.jsonl`，产物 MUST 落在 `runs/` 下。
- 模块不在该顶层的源文件集合里，或报告里没有完整的路径块，MUST 报错，MUST NOT 返回 0 级。

理由：写 RTL 时决定切不切流水要先量级数；`make exp` 写记录、只量被测顶层，没声明已验证的设计出不了记录（内部#111）。

#### Scenario: 量一个子模块

- **WHEN** 对顶层 `IP_TOP` 量它例化的组合子模块 `IP_SUB`
- **THEN** SHALL 报出大于 0 的级数与到达时间，起止点是 `IP_SUB` 的端口，`results/*/experiments.jsonl` 不变

#### Scenario: 模块名写错

- **WHEN** `--module` 给了一个该顶层源文件集合里没有的模块
- **THEN** MUST 报错并点名这个模块

### Requirement: 预算按组合单元个数比，报告行数另计

`make depth` 的 `BUDGET` MUST 按组合单元个数比较：一条路径上组合单元的个数，含综合插入的缓冲与反相器，MUST NOT 计起点寄存器的 CLK→Q 与终点的 D 或输出端口（内部#207；用户 2026-10-13 定写进契约，内部#286；措辞同 `docs/spec-writing.md` §8）。`make depth` 报的「级数」是路径报告的行数（与记录的 `critical_path_stages` 同口径），比组合单元数多一个常数：寄存器起点多 3、输入端口起点多 2。列出超预算终点时 MUST 两种数都给；文档与汇报引用级数时 MUST 写明是哪一种。

#### Scenario: 超预算终点按组合单元数判

- **WHEN** 一条寄存器起点的路径报告行数是 32、组合单元数是 29，`BUDGET=30`
- **THEN** 该终点 SHALL NOT 列为超预算

#### Scenario: 超预算终点两种数都给

- **WHEN** 一条路径的组合单元数是 31，`BUDGET=30`
- **THEN** 它 SHALL 列为超预算，且同时给出组合单元数与报告行数

### Requirement: 两次 depth 结果能按同一终点比路径的模块构成

`flow/synth/depth_compare.py --composition` MUST 对两次 depth 结果共有、且路径的模块构成变了的终点（组合单元总数变了也算在内），按模块列出最深那条路径上的组合单元个数，A 与 B 并排，并给出合计。数据 MUST 取自 `over_budget.tsv(.gz)` 已记下的路径引脚，MUST NOT 重跑 STA。按模块数出的个数之和 MUST 等于该行记下的组合单元数。

旧产物没有路径引脚这一列时，MUST 报错并说明要重跑 depth，MUST NOT 输出一张空表。

理由：设计侧判断改动挪了哪一段逻辑，要看同一终点在各模块里各占几个单元（例如 RDAT 14 → 16），只比终点集合看不出来（内部#340）。

#### Scenario: 同一终点在两个模块之间挪了单元

- **WHEN** A、B 的同一终点组合单元数都是 30，但 B 里 RDAT 多 2 个、ECC 少 2 个
- **THEN** `--endpoint <该终点>` 列出 RDAT +2、ECC −2，两边合计都是 30

#### Scenario: 旧产物没有路径引脚

- **WHEN** 输入的 `over_budget.tsv` 每行只有 4 列
- **THEN** `--composition` 报错并提示重跑 depth
