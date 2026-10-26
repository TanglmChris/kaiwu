## Why

2026-09-07 的位宽扫参暴露出 `adder32` 的 `CLA` 分支没有良定义的渐进阶
（`FOLLOWUP.md` 第 11 条）：`rtl/flat_lookahead.v` 是完全平铺的与或式而非真前缀网络，
naive 规模 O(N²)、深度靠 ABC 事后重构，实测延时随位宽**非单调**（64 位比 32 位快）、
面积 log-log 斜率 1.239（RIPPLE 与 CSEL 均为 1.00）。

后果是**本仓库至今没有任何 O(log n) 结构的实测数据**。RIPPLE 的 O(n)（斜率 1.012）
与 CSEL 的 O(√n)（0.573）都已确认，唯独最重要的那一档缺席 ——
而 `knowledge/arith/prefix-adders.md` 是全知识库引用最多的一张卡
（`comparator.md`、`find-first-one.md`、`fixed-priority-arbiter.md`、
`onehot-binary-thermometer.md` 都把自己的前缀结构指向它），
它的「本地实测」却是空的。

`WIDTH` 维度现在已经就位，补上真前缀网络就能一次性回答两件事：
O(log n) 断言成不成立，以及 Harris 的 `l + f + t = log₂N − 1` 零和约束
在本地流上看不看得见。

## What Changes

- **新增三个 `CARRY_STRUCT` 取值**：`SKLANSKY`、`KOGGE_STONE`、`BRENT_KUNG`，
  各自一个带 `(* keep_hierarchy *)` 的模块，共用同一份 g/p 预计算与末级 sum XOR，
  **只有前缀网络本身不同**。
- **`CLA` 保留不动**。它不是要被替换的错误实现，而是一个有价值的对照组：
  "把功能平铺出来交给工具去优化"正是多张知识卡反复要求的 `TOOL` 档。
  本变更只在文档里把它的**语义**说清楚，不改 RTL、不改取值名。
- **不做 Han-Carlson**（见 design.md 的 D2）。
- **不改 `results/experiments.jsonl` 的 schema**，不改写任何历史记录。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 —— 本变更只增加一个设计的参数取值与 RTL 实现，不改变任何流程契约。
`flow-parameterization` 的现有条款已经覆盖"参数取值由 `params.yaml` 声明"这件事。）

## Impact

**代码**：`designs/adder32/rtl/` 新增前缀网络模块、`rtl/adder_core.v` 增加分派分支、
`designs/adder32/params.yaml` 扩 `CARRY_STRUCT` 取值、
`designs/adder32/{spec,design}.md`、`knowledge/arith/prefix-adders.md` 的「本地实测」。

**风险**：

- **前缀网络功能上完全等价于 `a + b`**，不设模块边界会被 ABC 的 `&dch` 收敛成同一个网表
  （`CLAUDE.md` 综合坑）。三个网络必须各自 `(* keep_hierarchy *)`，
  且"三者级数/面积测出来若完全相同"是明确的翻车信号而非结论。
- **连线代价本地为零**（`knowledge/README.md` 全库警告）。Kogge-Stone 的卖点是
  级数少、代价是 O(N) 连线轨道，**本地流会系统性高估它**。这一条必须写进结论，
  而不是事后解释。
- 全量扫参组合数从 36 涨到 72（6 种结构 × 4 位宽 × 3 流水级）。

**范围外**：Han-Carlson、稀疏前缀（`SPARSITY`）、以及把 `CLA` 改名 ——
后者会让 28 条历史记录的 `CARRY_STRUCT` 值失去指代。
