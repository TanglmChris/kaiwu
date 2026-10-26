## Why

`adder32` 是仓库里唯一的设计，28 条记录只覆盖 9 个参数组合。两个已识别的空维度一直挂着：

1. **`CSEL_BLOCK` 写死 4**（`adder_core.v:22` 的 `.BLOCK(4)`，`FOLLOWUP.md` 内部#3）。
   `carry_select_adder` 本身已经有 `BLOCK` 参数，只差透传。它是投机粒度的旋钮，
   理论上有个 √n 附近的最优点，而且**本地流测得准**（纯组合，只看面积和级数，
   不依赖已失效的功耗列）。
2. **`WIDTH` 固定 32**，从未测过位宽维度。

第 2 条的紧迫性刚刚上升。2026-09-07 复核 `PIPE_STAGES` 实测时发现
`knowledge/arch-technique/pipelining.md` 的初稿结论是错的：它按线性理想
（切 N 段应快 N 倍）算出"级平衡效率 74~79%"，而三种结构的实测加速比
（RIPPLE 1.95×/2.70×、CLA 1.57×/2.23×、CSEL 1.49×/1.81×）**正好是延时渐进阶的倒序** ——
差距不是效率损失，是因为 O(log n) 结构的延时本来就次线性于位宽。

**这意味着整个知识库 34 张卡的「关键路径」小节所依赖的位宽-延时渐进阶，
在本仓库一次都没有被实测验证过。** `WIDTH` 扫参正是去验证它。

## What Changes

- **`params.yaml` 新增可选字段 `sweep: false`**，用于声明"这是合法参数，但不参与
  `sweep.py` 的全量叉乘"。动机是 `CSEL_BLOCK` 只对 `CARRY_STRUCT=CSEL` 有意义：
  若按普通维度声明，3×3×4 的叉乘里有 24 条是 RIPPLE/CLA 下的冗余重复 ——
  参数标签不同、测的却是同一个电路，会污染 `results/experiments.jsonl`。
- **`sweep.py` 尊重该标记**：标记为 `sweep: false` 的参数不进叉乘，取其 `values`
  的第一项作为默认值；这类参数的曲线用 `make exp` 显式跑。
- **`adder32` 提升两个参数**：`WIDTH`（普通扫参维度）与 `CSEL_BLOCK`（`sweep: false`），
  后者由顶层经 `adder_core` 透传给 `carry_select_adder`。
- **testbench 去掉 32 位硬编码**，按 `WIDTH` 生成掩码与定向向量。
- **不改 `results/experiments.jsonl` 的 schema**：不新增、改名或删除任何字段，
  不改写任何已有记录。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `flow-parameterization`: 参数声明契约增加"参数可以被声明为不参与全量扫参"这一维度，
  并明确此类参数在未显式给值时的默认取值来源。

## Impact

**代码**：`flow/paths.py`（params.yaml 解析与校验）、`scripts/sweep.py`（叉乘构造）、
`designs/adder32/params.yaml`、`designs/adder32/rtl/{adder32,adder_core}.v`、
`designs/adder32/tb/test_adder32.py`、`designs/adder32/{spec,design,verify}.md`。

**风险**：

- **最高风险是历史记录不可比。** 改 RTL 顶层与 tb 之后，9 个老参数组合的
  `area_um2` / `cell_count` / `critical_path_delay_ns` / `critical_path_stages`
  必须逐位复现原值 —— 若不复现，说明参数化过程改变了电路，此前所有跨结构结论作废。
  这是本变更的首要验收项。
- `sweep.py` 的改动影响所有设计，不只 `adder32`。
- 设计名 `adder32` 在 `WIDTH` 可变后名不副实。**本次不改名**（改名会牵动
  `experiments.jsonl` 里 `design` 字段的历史值），在 `spec.md` 里写明
  `WIDTH` 默认 32、名字是历史沿革。

**范围外的既有问题（不在本次修，记 `FOLLOWUP.md`）**：
`openspec/specs/flow-parameterization/spec.md` 里那条
"实验记录的 schema **在本次变更中**不得改变"是从 `restructure-repo-layout` 归档
带过来的措辞，归档后"本次变更"已无指代对象。本变更同样不改 schema，故不受影响，
但该措辞应当择机改成无时态的表述。
