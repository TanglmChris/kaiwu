# ADDER32 综合与 PPA 预期

## 1. 综合口径

要保层级的模块列在 `params.yaml` 的 `tops:ADDER32:synth:keep_hierarchy`，包括算子 `PREFIX_NODE`。不保层级时 ABC 的 `&dch` 会跨模块重构，几种结构收敛成同一网表，对比整条失效。没有存储模型与参考口径端口。

## 2. 面积预期

| 部分 | 预期 | 依据 |
|---|---|---|
| RIPPLE / CSEL | 随位宽线性增长，CSEL 约为 RIPPLE 的两倍多 | 每块两份加法器加 mux |
| 前缀网络 | Brent-Kung 最省，Kogge-Stone 最大 | 节点数 O(N) 与 O(N log N) |

## 3. 关键路径预期

RIPPLE 延时 O(n)，CSEL O(√n)，三种前缀网络 O(log n)；CLA 由工具决定，没有良定义的渐进阶。本地流没有连线寄生，会系统性高估 Kogge-Stone。
