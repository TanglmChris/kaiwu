## 1. 让解析逻辑进指纹

- [x] 1.1 `metrics_code_sha256()`：模块 AST 哈希，剥 docstring
  - Covers:
    - experiment-record / 记录必须自解释其产出流程 / 只改解析逻辑，不改交给工具的脚本
    - experiment-record / 记录必须自解释其产出流程 / 只改注释或 docstring
    - experiment-record / 记录必须自解释其产出流程 / 从覆盖清单里删掉一个模块
    - experiment-record / 记录必须自解释其产出流程 / 同一套流程下的两次测量
    - F1（缺口可复现：撤回 tcl 改动后 `sta_recipe_sha256` 与修复前逐字相同）
    - F2（纯文档改动在七个模块上 AST 哈希一个都没变）
    - F3（有行为的改动都被抓到）
    - F4（`ast.dump` 不带行号，注释不进 AST，docstring 要显式剥）
    - F5（`scripts/run_experiment.py` 反向 import 本模块，只能按路径读源码）
    - F6、F7
    - D1、D2、D3（整模块不做白名单）、D4（清单进哈希）、D5（不 import）、D6、D7
    - A1（换 Python 大版本会分代 —— 解释器就是工具）
    - A2（七个模块是否覆盖全部派生路径，人工核对）
  - Touch:
    - flow/flow_fingerprint.py
    - tests/test_flow_fingerprint.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: `.venv/bin/python -m pytest tests/test_flow_fingerprint.py -q` —— 四件事：改一个模块里的**可执行语句**则 `metrics_code_sha256` 与合成指纹都变；只改**注释与 docstring** 则两者都不变；从模块清单里删掉一项则改变；纯函数性质（同一环境连算两次逐字相同）保持。Fails with: `七项事实必须齐全`
    - M2 (regression): `.venv/bin/python -m pytest tests/ -q` —— 既有测试无回归，且 `results/experiments.jsonl` 一行不增（红线 2/3）
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:37bf16a72d441abe5e56352e421c1035783d59ad71f44c61fda8414c1e2686a3
    - M1: `.venv/bin/python -m pytest tests/test_flow_fingerprint.py -q` — `6 passed in 0.98s`。四条：把 `run_sta.py` 的一行解析语句改掉（`splitlines()` → `reversed(splitlines())`）之后 `metrics_code_sha256` 与合成指纹都变，**而 `sta_recipe_sha256` 与 `synth_recipe_sha256` 一个字没变** —— 那正是 内部#18 那个缺口的形状；只换 docstring、加一行注释、加空行则指纹**逐字不变**；把 `METRIC_MODULES` 缩掉一项则指纹改变；`flow_fingerprint()` 的七项事实齐全且纯函数性质保持。
    - M1.red: 同一命令，实现前：`AssertionError: 七项事实必须齐全`（`tests/test_flow_fingerprint.py:77`），以及三条 `AttributeError: module 'flow.flow_fingerprint' has no attribute 'METRIC_MODULES'`。
    - M1.green: 实现后 `6 passed`。`METRIC_MODULES` 7 个，`metrics_code_sha256() = sha256:1d8f65ae…`。
    - M2: `.venv/bin/python -m pytest tests/ -q` — `64 passed, 2 warnings in 267.91s`。上一个变更完成时是 61 passed，增量 3 条正是本任务新增的。`results/experiments.jsonl` 前后都是 728 行。
    - Review:
      - Status: pass
      - Acceptance check: 「只改解析逻辑，不改交给工具的脚本」这条 Scenario 的两个 THEN 都被断言：指纹变了，**且两个 `*_recipe_sha256` 都没变** —— 第二条断言是关键，没有它这个用例无法区分"新机制起作用了"与"顺带把模板也改了"，而 内部#18 当年正是被后者救了一次。「只改注释或 docstring」用的是 `== base` 的整字典比较，不是逐项挑，所以七项事实里任何一项被文档改动带偏都会红。「从覆盖清单里删掉一个模块」直接缩 `METRIC_MODULES` 验证。D3（整模块不做白名单）与 D4（清单进哈希）分别落在实现与第三条用例上。A1（换 Python 大版本会分代）写在 `metrics_code_sha256()` 的 docstring 里，本变更不验它 —— 它不是缺陷而是该机制的正确后果。
      - Scope check: 产品写入两个文件，与 Touch 一致 —— `flow/flow_fingerprint.py`(+72/−3)、`tests/test_flow_fingerprint.py`(+69/−3)。被覆盖的那七个模块**一个都没动**（它们是被哈希的对象，不是本任务的产物）。`git status --porcelain` 除这两个与本变更自己的目录外无条目；`results/experiments.jsonl` 未动（红线 2/3）。
      - Findings: 测试需要一个能"改掉某个被覆盖模块"的接缝，而直接改仓库里的 `flow/sta/run_sta.py` 会污染工作区、也会让 M2 跑在一份被改坏的流程上。做法是把该模块复制到 `tmp_path`，再 monkeypatch `_metric_module_paths()`。为此在产品代码里留了这一个函数（docstring 写明它是给测试的接缝）—— 是为可测性付的一点代价，但比让测试去动真实文件安全得多。Resolved here: M1
    - Blocker: none
    - Reauthorizations: 2026-09-14 改 M1 的 `Fails with`。原写的是 `cannot import name 'metrics_code_sha256'`，但测试用的是属性访问（`ff.METRIC_MODULES`）而不是直接 import，实际红信号是 `AttributeError`。改成 `七项事实必须齐全` —— 那条断言直接表达的就是"指纹里少了这项事实"，比一个导入错误更贴近要验的东西。契约已重记。

## 2. 把新增的那项事实写进读数口径

- [x] 2.1 `docs/data-credibility.md` 的分代一节补上
  - Covers:
    - F1（这个缺口曾经放过一次 内部#18）
    - A1（换 Python 大版本会分代，那是对的）
  - Touch:
    - docs/data-credibility.md
  - Verify:
    - Strategy: evidence-first
    - Reason: 纯文档。补的是读记录时要知道「指纹现在还包含什么」，没有任何可执行行为随之改变 —— 行为已由 1.1 的四条检查覆盖。
    - M1: `grep -n "metrics_code_sha256" docs/data-credibility.md` —— 分代一节写明这项事实覆盖什么、不覆盖什么，以及换 Python 版本会分代
    - M2 (regression): `.venv/bin/python -m pytest tests/ -q` —— 文档改动不影响测试
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:4a673df655c9e22867bf3ca35ec01066e474f638fd99cd61d88d8fd04841d2f8
    - M1: `grep -n "metrics_code_sha256" docs/data-credibility.md` — `27:### 第七项：metrics_code_sha256（2026-09-14 补）` 等 3 处命中。「怎么给记录分代」一节从"六项事实"改成"七项"，并新起一小节写明：这个缺口**放过一次真的**（D-6 那次靠顺带改 tcl 才切开代，带三行哈希对照表）；覆盖 `METRIC_MODULES` 七个模块的 AST，以模块而非函数白名单为单位及其理由；明确列出**不覆盖**什么（`merge_liberty.py`、读取侧两个脚本）；纯文档改动不分代及其实测依据；以及换 Python 大版本会分代这件事为什么不是缺陷。
    - M2: `.venv/bin/python -m pytest tests/ -q` — `64 passed, 2 warnings in 269.17s`，与 1.1 完成时逐条相同。
    - Review:
      - Status: pass
      - Acceptance check: F1 落在那张三行对照表上 —— 读者能自己看出"只改 Python 解析"那一行的 `sta_recipe_sha256` 与修复前**逐字相同**，不必信我的转述。A1 落在末尾那条 ⚠️，而且给了"为什么不是缺陷"的理由（解释器就是工具），否则下一个看到指纹莫名全变的人会把它当 bug 去修。这一节还写清了**不覆盖**什么 —— 只写覆盖什么的话，读者会默认它覆盖一切，那比不写更危险。
      - Scope check: 只改 `docs/data-credibility.md` 一个文件（新增一节，插在分代规则与现状表之间），与 Touch 一致。`flow/flow_fingerprint.py` 与 `tests/test_flow_fingerprint.py` 的改动来自已完成的 1.1，未再动。`results/experiments.jsonl` 未动。
      - Findings: none
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "哈希的是**模块级常量**而不是源文件：改 `synth.py` 的注释或参数解析不影响测量
  结果，不该分代；真正决定结果的是那三个模板/约束的内容。" —
  `flow/flow_fingerprint.py` 的模块 docstring。前半句仍然成立（注释确实不该分代，
  而 AST 哈希正是为此），但「真正决定结果的是那三个模板/约束的内容」已被 内部#18 证伪：
  同一份工具输出换一种解析方式就是另一种口径，而模板一个字没变。
  Updated by: 1.1

- I2: "进指纹的六项事实" — `flow/flow_fingerprint.py` 的模块 docstring 与其表格。
  本变更之后是七项。
  Updated by: 1.1

## Expectation Coverage

- E1: 只改解析逻辑必须分代（F1、D1）。 Covered by: 1.1
- E2: 覆盖面不得依赖"记得登记"（D3、D4）。 Covered by: 1.1
- E3: 文档修订不得产生流程代噪声（F2、D1、D2）。 Covered by: 1.1
- E4: 读记录的人要知道指纹现在包含什么、不包含什么（A1、A2）。 Covered by: 2.1
- E5: 本变更之后的全量重跑。
  Durable owner: 内部#25
