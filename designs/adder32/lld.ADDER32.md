# ADDER32 逻辑详细设计方案（LLD）

## 0. 文档信息

| 项 | 内容 |
|---|---|
| 顶层 | `ADDER32` |
| 对应 LRS | `lrs.ADDER32.md` v1.0 |
| 版本 | v1.0 |

| 版本 | 日期 | 改动 |
|---|---|---|
| v1.0 | 2026-10-14 | 按现行 LLD 结构重写（原 design.ADDER32.md） |

## 1. 设计概述

位宽按 `PIPE_STAGES + 1` 切段，每段一个 `ADDER_CORE`，段间在进位链上打拍。`ADDER_CORE` 按 `SCHEME` 例化六种进位结构之一；三种前缀网络共用 `PREFIX_ADDER` 外壳，只有网络本身不同，测出的差异只来自拓扑。

需求追溯表：

| 需求 | 实现位置 | 说明 |
|---|---|---|
| R.001 | §2 | 段间寄存器只打进位与已算出的低位和，数据通路不打拍，因此要求输入保持 |
| R.002 | §3–§7 | 每种进位结构都实现完整加法 |
| R.003 | §2 | `PIPE_STAGES = 0` 时只有一段，不生成寄存器 |
| R.004 | §2 | 每个段间寄存器延迟一拍，共 `PIPE_STAGES` 拍 |
| R.005 | §2 | 段间寄存器异步复位清零 |
| R.006 | §3 | 各分支端口相同、功能相同，只换结构 |

## 2. 框图与模块划分

顶层 `ADDER32` 只做切段与段间打拍：第 k 段处理 `[k*SEG_W, HI)` 位，低于本段的位从上一段寄存器透传，进位来自上一段的 `cout_r`。末段吃 `DAT_W` 不整除段数的余数。

| 模块 | 例化名 | 功能 |
|---|---|---|
| `ADDER_CORE` | `U_ADDER32_SEG_ADDER_CORE` | 按 `SCHEME` 选一种进位结构 |
| `RIPPLE_ADDER` | `U_ADDER_CORE_RIPPLE_RIPPLE_ADDER` | 逐位串行进位 |
| `CLA_ADDER` | `U_ADDER_CORE_CLA_CLA_ADDER` | 平铺的超前进位 |
| `CARRY_SELECT_ADDER` | `U_ADDER_CORE_CSEL_CARRY_SELECT_ADDER` | 进位选择 |
| `PREFIX_ADDER` | `U_ADDER_CORE_PREFIX_PREFIX_ADDER` | 前缀加法器外壳与三种前缀网络 |

| 小模块 | 所在模块 | 功能 | 用到的 CBB |
|---|---|---|---|
| `FULL_ADDER` | `RIPPLE_ADDER` | 一位全加器 | 无 |

## 3. `ADDER_CORE`

每个 `SCHEME` 取值一个 generate 分支，分支显式列出合法取值，不写兜底 else：非法取值不生成任何分支，lint 报输出无驱动，`CBB_PARAM_CHK_ON` 下由 `$error` 点名。子模块：NA。

## 4. `RIPPLE_ADDER`

`DAT_W` 个 `FULL_ADDER` 串成进位链，延时随位宽线性增长。子模块：NA。

## 5. `CLA_ADDER`

g/p 预计算后交给 `FLAT_LOOKAHEAD`：每一位进位直接展开成 g/p 的积之和，深度交给综合工具决定。它是「交给工具」的对照组，不是前缀网络。

### 5.1 `FLAT_LOOKAHEAD`

`c[i] = OR_j (p[i-1..i-j] & g[i-1-j]) | (p[i-1..0] & cin)`，逐位独立展开。

## 6. `CARRY_SELECT_ADDER`

按 `BLK_W` 分块，每块两个 `RIPPLE_ADDER` 分别按进位入 0 与 1 预先计算，块间用 mux 按真实进位选择。末块在不整除时截短。子模块：NA。

## 7. `PREFIX_ADDER`

g/p 预计算、前缀网络、末级 `sum = p ^ c`。cin 不占网络的一列，进位由 `c[i+1] = G[i] | (P[i] & cin)` 补回。

### 7.1 `PREFIX_NETWORK_SKLANSKY`

分治：第 k 级块宽 2^(k+1)，块内上半区每一位与下半区最后一位合并。级数 log2N，扇出逐级翻倍。

### 7.2 `PREFIX_NETWORK_KOGGE_STONE`

第 k 级所有 i >= 2^k 的位与 i-2^k 合并。级数 log2N，扇出恒为 2，连线轨道 O(N)。

### 7.3 `PREFIX_NETWORK_BRENT_KUNG`

上扫生成块前缀，下扫填回中间位。级数 2*log2N-1，扇出 2，面积最省。

### 7.4 `PREFIX_NODE`

前缀算子 `(G, P) o (G', P') = (G | P&G', P&P')`。保层级必须落在这一层：只保网络时 ABC 会把树重构成长链，前缀拓扑整条失效。

## 8. DFX 实现

不适用：纯算术单元，没有调试与注错需求。

## 9. 设计断言

不适用：组合与等宽打拍结构，没有需要在 RTL 里断言的协议性质；功能由 TB 对照参考模型检查。
