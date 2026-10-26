## Why

`flow_fingerprint.py` 只哈希**模块级常量**（`YOSYS_TEMPLATE`、`abc.constr`、
`STA_TCL_TEMPLATE`、延时目标比例）。它不哈希把工具输出解析成记录字段的那部分
**代码**。于是：**改解析逻辑会改变字段的口径，而指纹不变。**

这已经发生过一次（内部#18）：
`_count_path_stages` 把所有 path group 的 cell 行加在一起，`critical_path_stages`
虚高 2。那次是**碰巧**顺带改了 tcl（加了 `-sort_by_slack`）才切开了代。

把那次修复的 tcl 改动撤回、只留 Python 解析侧的改动，就复现出这个缺口：

| | `sta_recipe_sha256` | 模块 AST 哈希 |
|---|---|---|
| 修复前 | `d581f8c009b8` | `9680b7a4638d` |
| 真实的修复（顺带改了 tcl） | `0b049664f974` | `dc584ff6c8d1` |
| **假想：只改 Python 解析** | **`d581f8c009b8`（与修复前逐字相同）** | `e5bfe30e1841` |

今天一口气产生了四个流程代，这个缺口留着最容易出事。

## What Changes

- **指纹新增一项事实 `metrics_code_sha256`**：对「把工具输出变成记录字段」的那几个
  模块做 **AST 哈希**（剥掉 docstring）。
- **`ast.dump` 天然丢弃注释与空行**，`include_attributes=False` 连行号都不带，
  所以**纯文档改动不会分代**。实测：`9db0feb`（「纠正说法，不动流程」）与今天的
  `f881f4e`（纯文档）在七个模块上 AST 哈希一个都没变。
- **哈希整个模块，不做函数白名单。** 白名单有盲区（有人加了新的派生逻辑却忘了登记，
  而那正是本 issue 要防的那种"忘了"）。整模块没有盲区，而上面两条实测说明噪声成本
  接近零。
- 模块**列表本身**进入被哈希的文本，所以从列表里删掉一项也会改变指纹。

`内部#25` 原本提的修法是手工 bump 一个 `metrics_version`。**不采用**：它靠人记得，
而它要防的正是人忘了。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `experiment-record`: 「记录必须自解释其产出流程」补上「派生字段的代码口径」这一项。

## Impact

| 文件 | 动作 |
|---|---|
| `flow/flow_fingerprint.py` | 新增 `metrics_code_sha256()` 与模块清单 |
| `tests/test_flow_fingerprint.py` | 新增：解析逻辑变了指纹必须变；改注释/docstring 必须不变 |
| `docs/data-credibility.md` | 分代总览补一项事实 |

**不受影响**：记录 schema（`flow` 段本来就是"指纹 + 各项事实"，加一项事实不改
字段集合的语义）、`flow/synth`、`flow/sta`、`flow/sim`、`scripts/`。

**本变更之后需要重跑**：加一项事实会让**全部**新记录换代 ——
`flow_fingerprint.py` 自己写着这是对的。
