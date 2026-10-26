## 1. 让块边界与 liberty 的词法结构一致

- [x] 1.1 `_extract_blocks` 改为词法感知的扫描，并加回归测试
  - Covers:
    - experiment-trust / 合并出来的 liberty 必须自洽 / 花括号出现在字符串字面量或注释里
    - experiment-trust / 合并出来的 liberty 必须自洽 / 注释里出现形如块头的文本
    - experiment-trust / 合并出来的 liberty 必须自洽 / 合并后校验模板顺序
    - F1（实测：字符串里的 `{` 让 `cell (BUF)` 的块吞掉 `cell (INV)` 与 library 收尾花括号）
    - F2（注释里的花括号、注释里伪装成块头的文本，同样没有防护）
    - F4（后果静默：坏块拼进产物，解析器只警告一句就丢掉）
    - F5（既有校验函数不复用 `_extract_blocks`，所以它们仍是独立的第二双眼睛）
    - D1（一个扫描器同时管三件事，不做半成品）
    - D2（字符串只认双引号，转义只认反斜杠）
    - D3（注释只认 `/* */`，不认 `//`）
    - D4（用合成的最小 liberty，不依赖 ASAP7）
    - A1（不为未闭合的字符串/注释加防护）
  - Touch:
    - flow/synth/merge_liberty.py
    - tests/test_merge_liberty.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: `pytest tests/test_merge_liberty.py -q` —— 字符串里的 `{` 不影响块边界（`cell (BUF)` 的块不再吞掉后面的 cell）；`/* { */` 注释里的花括号同样不影响；注释里的 `cell (FOO)` 不被当作块头。Fails with: `cell (INV)`
    - M2 (regression): `pytest tests/ -q` —— 既有三个用例（模板顺序、去重规则、单一 library 块）保持绿，全套无回归
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:9a962712664fd7b1668c640f1c747158e8ee8ce95c1077f32b5e214fda91f94e
    - M1: `.venv/bin/python -m pytest tests/test_merge_liberty.py -q` — `6 passed`。三个新用例对同一份合成 liberty（`LEXICAL_LIB`，同时含三种触发形态）：`cell (BUF)` 的块不再含 `cell (INV)`、以 `}` 收尾、且 `function : "A { not a brace";` 逐字保留；`cell (INV)` 的块以 `cell (INV)` 开头并含 `area : 2.0;`；注释里那行 `cell (GHOST) {` 不出现在块名集合里。另对 `_blank_noncode` 做了四例边界自检：转义引号 `\"` 内的 `{` 被挖空、`/* { */` 被挖空且其后的真块头保留、未闭合注释一路挖到末尾（A1 记载的行为）、不含字符串与注释的文本逐字不变。
    - M1.red: 实现前同一命令 `3 failed, 3 passed`。`test_brace_in_string_literal_does_not_extend_the_block` 报 `AssertionError: assert 'cell (INV)' not in ...`，pytest 把吞进去的内容整段打了出来（`cell (INV) {` / `area : 2.0;` / `}`）—— 即声明的红签名 `cell (INV)`。另两个用例（注释里的花括号、注释里的伪块头）同红。第一版夹具把 `cell (GHOST)` 写在注释的行中间，第三个用例因此假绿（块头正则要求 `\n\s*`），已把它改到行首，三个用例才同时变红。
    - M1.green: `_extract_blocks` 改为在 `_blank_noncode` 的挖空副本上定位块头与配对花括号、切片仍取自原文后，同一命令 `6 passed`。
    - M2: `.venv/bin/python -m pytest tests/ -q` — `40 passed, 2 skipped in 230.78s`。改动前是 37 passed / 2 skipped，增量正好是本任务新增的 3 个用例；既有三个 merge_liberty 用例（模板顺序、去重规则、单一 library 块）保持绿。
    - Review:
      - Status: pass
      - Acceptance check: 「花括号出现在字符串字面量或注释里」由前两个用例证明，且断言不只是「块没吞掉别人」，还断言了**块内容逐字保留**（`function : "A { not a brace";` 原样在块里）—— 边界对了但内容被改写同样是错的。「注释里出现形如块头的文本」由第三个用例证明。「合并后校验模板顺序」由既有的 `test_templates_are_defined_before_first_use` 保持绿证明，且按 F5 它用的是独立正则、不复用 `_extract_blocks`，所以它是对本次改动的第二双眼睛而不是同一双。D1（一个扫描器管三件事）落在 `_blank_noncode` 同时处理字符串、注释与偏移保持上；D2/D3（只认双引号、只认 `/* */`）由边界自检的四例覆盖；D4（合成输入）是夹具本身。
      - Scope check: 产品写入两个文件，与 Touch 一致 —— `flow/synth/merge_liberty.py`（+55/−6）与 `tests/test_merge_liberty.py`（+56/−0）。未碰 `flow/sim` / `flow/sta`、未重新生成任何合并库（Non-Goal：那会改 `liberty_sha256` 让全部新记录换代，是独立决策）、未产生实验记录。
      - Findings: issue 内部#19 只写了「字符串字面量里的花括号」，实际查下去是同一个词法问题的三面：字符串里的 `{`、`/* */` 注释里的 `{`、以及注释里行首伪装成块头的 `cell (FOO)`——后两者源码里同样没有防护。只修第一条会留下「引号防住了、注释没防住」的半成品，而在这里半成品等于没修：产物照样坏，坏法照样静默。三条一起修了，Scenario 也按三条写。Resolved here: M1。另：写夹具时第一版把伪块头放在注释行中间，用例假绿了一轮——块头正则要求行首，放中间根本不触发。这是「测试通过不等于被测行为正确」的一个现成样本，夹具已收紧到真正触发。Resolved here: tests/test_merge_liberty.py
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "「正则定位块头 + 手工数花括号」" — `flow/synth/merge_liberty.py:35` 的 docstring 与 GitHub issue 内部#19 正文。
  Updated by: 1.1，随后关闭 内部#19。
- I2: "**未修。**" — GitHub issue 内部#19 正文。
  Updated by: 1.1

## Expectation Coverage

- E1: 字符串与注释里的花括号不参与块深度计算（F1、F2、D1）。 Covered by: 1.1
- E2: 注释或字符串里的块头不被当作块的开始（F2、D1）。 Covered by: 1.1
- E3: 这两点由回归测试覆盖，而不是靠「ASAP7 里没有这种写法」（F3、D4）。 Covered by: 1.1
- E4: 换 PDK 时这条仍然成立 —— 本机无 `~/pdk`，无法在真实库上复核（F3）。 Discard reason: 复核需要一份含触发条件的真实 liberty，而 ASAP7 按 内部#19 就不含。合成输入已覆盖全部三种触发形态；真实库上的行为由「不含触发条件则行为逐字相同」推出，这一点记在 design.md 的 Risks 表里。
