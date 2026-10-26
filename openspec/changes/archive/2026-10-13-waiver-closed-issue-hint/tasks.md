## Invalidates

- I1: "豁免已用不上，或挂的 issue 已关，就报「失败豁免过时」" — docs/toolchain.md「推送、授权」。Updated by: 1.1
- I2: "或挂的 issue 已关，fast_check 报「失败豁免过时」" — flow/check_waivers.yaml 头注释。Updated by: 1.1
- I3: "或挂的 issue 已关，都算过时" — scripts/fast_check.sh 注释。Updated by: 1.1
- I4: "关自己名下、证据齐全的 issue"（无例外）— docs/toolchain.md 常备授权第 2 条与 CLAUDE.md 授权句。Updated by: 1.1

## 1. 豁免过时判定

- [x] 1.1 issue 已关而豁免仍在放行：由 FAIL 改为提示；规则「删豁免的提交进 main 后才关」进 toolchain / 豁免文件 / CLAUDE.md
  - Covers:
    - guardrail-scope / 秒级护栏必须检查失败豁免没有过时
    - D1
    - D2
  - Touch:
    - flow/check/check_waivers.py
    - tests/test_fast_check.py
    - flow/check_waivers.yaml
    - scripts/fast_check.sh
    - docs/toolchain.md
    - CLAUDE.md
  - Verify:
    - Strategy: vertical-tdd
    - M1: `pytest tests/test_fast_check.py -n 4 -k "waiver_issue_state or waiver_stale"`（带 ~/tools PATH）—— 桩 gh 报 closed、豁免仍在放行时 rc=0 且有「豁免挂的 内部#246 已关」提示；豁免不再放行时仍 FAIL「失败豁免过时」。Fails with: `assert 'note  豁免挂的 内部#246 已关，修复还没进本分支' in`
    - M2 (regression): `./scripts/fast_check.sh` rc=0；`pytest tests/ -m 'not flow' -n auto` 全过
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:12e7d49cf1352e16c95d095a9157b95be4e4d6425b82885ff36b77710ae9014a
    - M1: `pytest tests/test_fast_check.py -n 8 -k waiver`（带 ~/tools PATH）→ 12 passed
    - M1.red: 改 check_waivers.py 之前，同一组用例 → 1 failed, 2 passed：`test_waiver_issue_state[closed-…]` 报 `assert 'note  豁免挂的 内部#246 已关，修复还没进本分支' in` 输出（旧代码打的是「FAIL  失败豁免过时：挂的 issue 已关闭 —— 内部#246」）；按空白归一化后即 `assert 'note 豁免挂的 内部#246 已关，修复还没进本分支' in`
    - M1.green: 改后 → 12 passed in 5.48s（含 `test_waiver_stale_when_violation_fixed` 仍判 FAIL）
    - M2: `./scripts/fast_check.sh` rc=0；`pytest tests/ -m 'not flow' -n auto` → 690 passed（main 4676bdb9 + 本改动）
    - Review:
      - Status: pass
      - Acceptance check: 豁免还在放行且 issue 已关 → 只提示、rc=0；不再放行 → 仍 FAIL；离线照旧提示，与 MODIFIED 后的三个场景一一对应。规则句全局 grep（「issue 已关」「证据齐全」）后改了 toolchain 两处、豁免文件头、fast_check 注释、CLAUDE.md 一处
      - Scope check: 改动全在 Touch 内；task-start 在实现之后补录（PM 10:41 才定走 OpenSpec），红灯是实现前就跑出、按原样记下的
      - Findings: none
    - Blocker: none
    - Reauthorizations: none

## Expectation Coverage

- E1: 修复交付即关、还没进 main 时，基于 main 的分支不被豁免过时卡住。Covered by: 1.1
- E2: 「关了却没修」仍有兜底：规则要求进 main 后再关，推 main 时 PM 核对提示。Covered by: 1.1
