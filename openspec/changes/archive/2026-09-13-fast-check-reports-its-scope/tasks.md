## 1. 让 fast_check 的退出码与摘要诚实

- [x] 1.1 `fast_check.sh` 加覆盖摘要、工具缺失默认失败、具名降级开关
  - Covers:
    - guardrail-scope / 护栏的成功退出必须意味着它声明的检查全部执行并通过
    - guardrail-scope / 护栏的成功退出必须意味着它声明的检查全部执行并通过 / 某一类检查因缺少工具而无法执行
    - guardrail-scope / 护栏的成功退出必须意味着它声明的检查全部执行并通过 / 调用方显式接受降级
    - guardrail-scope / 护栏必须报告它实际覆盖的范围
    - guardrail-scope / 护栏必须报告它实际覆盖的范围 / 一部分检查未能执行
    - D1（0 表示「声明的检查全部执行且通过」）
    - D2（默认失败，降级开关 `FAST_CHECK_ALLOW_MISSING_TOOLS=1`）
    - D3（通过与失败两条路径都打印摘要）
    - D5（摘要禁止用「全部 / all」描述非全部执行的集合）
    - F1（本机实测：退出 0 而 RTL 一个都没跑）
    - A2（挡住没装工具链的机器是可接受的，前提是失败消息给出两条具名旁路）
  - Touch:
    - scripts/fast_check.sh
    - tests/test_fast_check.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: `iverilog` 不在 PATH 且未设降级开关时，`fast_check.sh` 退出码非 0，且输出同时包含缺失的工具名、修复方式与两条具名旁路 Fails with: `AssertionError: iverilog 缺失却以 0 退出：护栏静默放行`
    - M2: `FAST_CHECK_ALLOW_MISSING_TOOLS=1` 且 `iverilog` 不在 PATH 时，退出码为 0，且摘要把 RTL elaborate 明确列为未执行 Fails with: `AssertionError: 降级运行没有在摘要里列出未执行的检查`
    - M3: 两类检查都能执行且通过时（以桩 `iverilog` 提供工具），退出码 0，摘要逐项列出实际执行的检查，且不含任何未执行项 Fails with: `AssertionError: 摘要缺失：护栏没有说出它这一轮检查了什么`
    - M4 (regression): 部分参数组合 elaborate 失败时仍然退出非 0，且不打印声称覆盖全部组合的那句话（`FOLLOWUP.md` 第 17 条的既有行为不被本次改动破坏）
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:4674b5feafe92913920ea0413ef878fe6033526d44ee3b96a4e75fa55f733d3d
    - M1: PASS。`.venv/bin/python3 -m pytest tests/test_fast_check.py::test_missing_tool_is_a_failure_not_a_skip` → PASSED。本仓根目录实跑 `./scripts/fast_check.sh` 佐证：退出码 **1**，输出含 `FAIL  iverilog 不在 PATH：RTL elaborate 一个组合都没能检查`，并逐行给出三条出路——`source ~/tools/env.sh`、`FAST_CHECK_ALLOW_MISSING_TOOLS=1`、`git push --no-verify`。
    - M1.red: `AssertionError: iverilog 缺失却以 0 退出：护栏静默放行`（`assert 0 != 0`，stdout 为 `ok python compileall` 加 `SKIP iverilog not on PATH`）——与契约预测的失败签名**逐字相同**。
    - M1.green: 实现后同一条命令 PASSED。
    - M2: PASS。`::test_named_downgrade_exits_zero_but_names_what_was_skipped` → PASSED。实跑佐证：`FAST_CHECK_ALLOW_MISSING_TOOLS=1 ./scripts/fast_check.sh` 退出码 **0**，输出含 `DEGRADED  iverilog 不在 PATH —— 本次运行没有检查任何 RTL`，且覆盖摘要仍列出 `未执行  RTL elaborate（iverilog 不在 PATH）`。
    - M2.red: `AssertionError: 降级运行没有在摘要里列出未执行的检查`——与契约预测逐字相同。首次运行时红落在更早的 `DEGRADED` 断言上（`降级运行没有被标明`），与预测不符；将断言顺序调整为「先断言 M2 声明的主行为（摘要列出未执行项）」后，红与声明对齐。
    - M2.green: 实现后同一条命令 PASSED。
    - M3: PASS。`::test_summary_is_printed_on_the_passing_path` → PASSED。全绿路径下退出码 0，输出含 `覆盖摘要`，逐项列出 `已执行  python compileall (flow/, scripts/)` 与 `已执行  RTL elaborate foo（2 个参数组合）`，且不含任何 `未执行` 项。
    - M3.red: `AssertionError: 摘要缺失：护栏没有说出它这一轮检查了什么`——与契约预测逐字相同。
    - M3.green: 实现后同一条命令 PASSED。
    - M4: PASS。`::test_partial_failure_still_fails_with_stub` → PASSED，且**改动前后均绿**（regression 检查，无诚实的红）。部分组合失败时退出码非 0 且 stdout 不含 `all param combos`，证明 `FOLLOWUP.md` 第 17 条修好的行为未被本次改动破坏。全文件 `pytest tests/test_fast_check.py -q` → `4 passed, 4 skipped`（4 skipped 是原有的 `@needs_iverilog` 用例，本机未装 iverilog）。
    - Review:
      - Status: pass
      - Acceptance check: M1 证明「某一类检查因缺少工具而无法执行」时退出码非 0 且给出修复与降级方式；M2 证明具名降级可退 0 但必须列出未执行项；M3 证明「护栏必须报告它实际覆盖的范围」在通过路径上也成立；M4 证明既有行为未回退。三条红的签名与 task-start 记录的预测逐字相符，红是为正确原因红的。
      - Scope check: 仅修改 Touch 列出的 `scripts/fast_check.sh` 与 `tests/test_fast_check.py`。`.githooks/pre-push` 未动。新建了 `.venv/`（已在 `.gitignore` 中，不进版本控制）以获得 pytest 与 pyyaml。
      - Findings: 两条。(1) **第一次跑出的红是假的**：测试夹具把 PATH 剥得只剩 stub 目录，导致失败原因是 `env: bash: No such file or directory`（退出 127）与 `ModuleNotFoundError: No module named 'yaml'`——夹具坏了，不是被测行为坏了。已修夹具（PATH 保留 bash/python3 的解析路径并接入本仓 `.venv/bin`），并新增 `_assert_harness_sane()` 在每个用例里断言「这一轮 iverilog 的可见性确实是该用例想要的那种」，使同类夹具失效下次立即暴露而不是伪装成红。Resolved here: M1 —— 该检查的 `.red` 记录的正是修好夹具之后、与预测逐字相符的红。(2) 实现过程中撞到两个 bash 3.2 的坑：全角括号紧跟变量名会被吃进变量名（`design` 后接全角左括号触发 unbound variable），以及 `set -u` 下展开空数组报 `skipped[@]: unbound variable`。两处都已修并在脚本里留注释说明原因。Resolved here: M3 —— 该检查走的正是全绿路径，两个坑都在它的执行路径上。
    - Blocker: none
    - Reauthorizations: none

## 2. 让 hook 的挂载自愈

- [x] 2.1 `.envrc` 在最前面补齐 `core.hooksPath`
  - Covers:
    - guardrail-scope / 护栏的挂载状态必须是自愈的或可见的
    - guardrail-scope / 护栏的挂载状态必须是自愈的或可见的 / 新克隆的工作副本
    - D4（只写 `--local`，只在值不对时写）
    - D7（放在 `source ~/tools/env.sh` 之前，因为那一行在缺工具链的机器上会中断其余部分）
    - F2（本机 `core.hooksPath` 为空，hook 从未运行）
    - F5（`.envrc` 第一行在本机失败，严格模式下会中断后续）
    - A1（direnv 未装的入口不被此路径覆盖，本机即是）
  - Touch:
    - .envrc
  - Verify:
    - Strategy: evidence-first
    - Reason: 产出是 `.envrc` 里的一段 shell。本机未安装 direnv（F6），无法端到端执行它的真实调用路径，因此不存在一个能诚实标记为「红」的失败；可验证的是这段 shell 本身在「未设置 / 已设置 / 设成别的值」三种前置状态下的行为，用等价的 shell 执行来取证。
    - M1: 在一个临时 git 仓库中，`core.hooksPath` 未设置时执行 `.envrc` 的自愈片段，之后 `git config --local core.hooksPath` 返回 `.githooks`，且 `git config --global` 未被写入
    - M2: `core.hooksPath` 已经是 `.githooks` 时执行该片段，`git config` 不产生新写入（幂等）
    - M3: 该片段位于 `.envrc` 中 `source ~/tools/env.sh` 之前，且相邻注释写明了这条顺序依赖的理由
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:a85982bd169dbfa8a04203f26cc643379eaffca0b5002b01c006c261a5206ed7
    - M1: PASS。在 `mktemp -d` 的临时 git 仓库中，前置 `core.hooksPath` 为空字符串；以 `bash -c 'set -euo pipefail; <自愈片段>'` 执行后 `git config --local core.hooksPath` 返回 `.githooks`。全局配置未被写入：`git config --global core.hooksPath` 在片段执行前后均以退出码 1 返回（该键不存在）。
    - M2: PASS。同一临时仓库中值已是 `.githooks` 时再次执行该片段，`.git/config` 的 mtime 前后相同（1789290634 → 1789290634），证明没有发生写入，重复进入目录无副作用。
    - M3: PASS。按**非注释行**精确定位：自愈语句在第 12 行，可执行的 `source ~/tools/env.sh` 在第 15 行，自愈确在其之前。（按原始 grep 会命中第 6 行，那是注释里对该语句的引用，不是语句本身。）相邻注释写明了顺序依赖的理由——「那一行在没装工具链的机器上会失败，而 direnv 以严格模式执行本文件，失败即中断其后的一切」，并直书「整理本文件时不要把它挪到后面」。
    - Review:
      - Status: pass
      - Acceptance check: M1 与 M2 共同证明「新克隆的工作副本」这条 Scenario——默认状态下配置被补齐，已补齐时不重复写入。M3 证明 D7 的顺序约束真的落在文件里，且理由随之留存，使下次整理该文件的人不会无声地破坏它。
      - Scope check: 仅修改 Touch 列出的 `.envrc`。另在本仓执行了一次 `git config --local core.hooksPath .githooks`——那是本机的 git 配置，不是产品文件写入，见 Findings。
      - Findings: 两条。(1) **本机 direnv 未安装（design 的 F6），所以自愈路径在这台机器上不会被触发**，已手工执行一次 `git config --local core.hooksPath .githooks` 把 hook 挂上。挂载后端到端验证：`.githooks/pre-push` 直接调用时退出码 1 并打印覆盖摘要，`FAST_CHECK_ALLOW_MISSING_TOOLS=1` 下退出码 0 且摘要仍列出未执行项——两条路径都与任务 1.1 的实现一致。Resolved here: M1 —— 自愈片段本身的正确性由它证明；本机的手工挂载是环境动作，不改变该片段的行为。(2) 未经 direnv 的入口（GUI 客户端、CI、本机）仍不被自愈覆盖，这是 A1 已声明的已知缺口，`keel --doctor` 是它那一侧的可见性来源。Durable owner: 内部#3
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "SKIP  iverilog not on PATH (source ~/tools/env.sh)" 这一行所代表的语义——跳过后仍以 0 退出 — `scripts/fast_check.sh` 第 33 行。Updated by: 1.1
- I2: "当时是故意选 skip 而不是 fail，免得 GUI 客户端 push 不动。如果要收紧，改 `fast_check.sh` 里那个分支。" — issue 内部#3（内部#3） 正文；本变更即是那次收紧，且保留了 GUI 场景所需的具名旁路。Updated by: 1.1
- I3: "`./scripts/fast_check.sh`   # 秒级检查：全参数组合 elaborate + Python 编译" — `CLAUDE.md` 的「常用命令」；该描述无条件声称覆盖「全参数组合」，而工具缺失时并不覆盖。Durable owner: 内部#9
- I4: "2. **pre-push 的 RTL 检查会静默失效**" 这一条的「静默」二字 — 已迁移至 issue 内部#3（内部#3）；本变更后它不再静默。Updated by: 1.1, 2.1

## Expectation Coverage

- E1: 护栏以 0 退出时，它声明的检查确实全部执行并通过（D1） Covered by: 1.1
- E2: 工具缺失不再被当作通过，且降级是具名的（D2） Covered by: 1.1
- E3: 覆盖范围在通过路径上也被说出（D3、D5） Covered by: 1.1
- E4: `core.hooksPath` 在正常工作流中自动补齐（D4、D7） Covered by: 2.1
- E5: 未经 direnv 的入口（GUI 客户端、CI、本机）不被自愈覆盖，属已知缺口（A1） Durable owner: 内部#3
- E6: `fast_check.sh` 的覆盖面本身仍有缺口——`sweep: false` 参数的非默认取值未被检查（Q1） Durable owner: 内部#9
- E7: `FOLLOWUP.md` 第 17 条修好的两个行为不被本次改动破坏 Covered by: 1.1
