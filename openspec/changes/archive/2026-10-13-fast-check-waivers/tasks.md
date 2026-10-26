## Invalidates

- I1: "或绕过本次 push：git push --no-verify" — scripts/fast_check.sh 缺工具时的修复提示把 `--no-verify` 列为一条出路，与 C「不许绕过推送」矛盾。Updated by: 1.1
- I2: "仓里没有 CI（无 `.github/workflows/`），也没有 git 钩子" — 内部#254 正文的现状描述，实际上钩子从 09-04 起就在。Discard reason: issue 正文是提出时的记录，已在 内部#254 issuecomment-6121147891 更正，不改原文

## 1. 失败豁免与推送纪律

- [x] 1.1 fast_check 读 `flow/check_waivers.yaml`：11 个检查段的失败分支经豁免判定，过时与 issue 已关判 FAIL
  - Covers:
    - guardrail-scope / 护栏的成功退出必须意味着它声明的检查全部执行并通过 / 失败项全部被豁免
    - guardrail-scope / 秒级护栏的失败只能经登记的豁免放行 / 违规全部在豁免的文件里
    - guardrail-scope / 秒级护栏的失败只能经登记的豁免放行 / 同一段里有不在豁免内的违规
    - guardrail-scope / 秒级护栏的失败只能经登记的豁免放行 / 豁免缺字段
    - guardrail-scope / 秒级护栏必须检查失败豁免没有过时 / 违规已修好，豁免还在
    - guardrail-scope / 秒级护栏必须检查失败豁免没有过时 / 离线
    - D1, D2, D3, D4, D5
  - Touch:
    - scripts/fast_check.sh
    - flow/check/check_waivers.py
    - flow/check_waivers.yaml
    - tests/test_fast_check.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: `.venv/bin/python3 -m pytest tests/test_fast_check.py -q -k waiver -p no:cacheprovider` —— 夹具仓库里放一个违反「RTL 无综合指令」的文件：无豁免时退出非 0；登记该文件后退出 0，输出带 `WAIVED` 与「生效的豁免」；另加一个不在豁免内的违规文件时退出非 0，并区分两种行；缺 `issue` 时失败并点名；文件修好、豁免还在时失败并说「过时」；跳过联网查询时有「未核 issue 状态」一行。Fails with: `WAIVED`
    - M2 (regression): `./scripts/fast_check.sh` 在本仓退出 0；`.venv/bin/python3 -m pytest tests/ -q -n auto -m 'not flow' -p no:cacheprovider` 全过
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:56775148480a58c22c9ffbbc5774874449681ad73bae84d014255a625eb16866
    - M1: 无豁免时只有 directive 段 FAIL；登记 foo.v 后退出 0，打 WAIVED、行前 `[豁免 内部#246]`、摘要列「生效的豁免」；多一个 foo2.v 违规时 FAIL，并区分 `[豁免 内部#246]` 与 `[未豁免]`；缺 issue 报「失败豁免文件有误」；修好后豁免还在报「失败豁免过时」；桩 gh 返回 closed 时 FAIL、查不到 gh 时只提示「未核 issue 状态」
    - M1.red: 实现前 4 failed（夹具自检那一臂过），`assert 'WAIVED  可综合 RTL 里有综合指令属性' in …` —— artifact openspec/changes/fast-check-waivers/evidence/1.1-red.txt sha256:a1c67533db1d36134309411119ac89ca1c242b8e602a442479cb6f56bf3b468c
    - M1.green: 9 passed（含 issue 状态两臂）—— artifact openspec/changes/fast-check-waivers/evidence/1.1-green.txt sha256:a88354a5ac6282efa70bd960ebb0d0a31c08c01f22eeb80b800d0696dffd25f7
    - M2: 本仓 fast_check rc=0（多一项「失败豁免没有过时」）；not-flow pytest 641 passed —— artifact openspec/changes/fast-check-waivers/evidence/1.1-m2.txt sha256:485a03a50a7d983780dc70ed22639b03844068dca28b4351535b320c1bc03574
    - Review:
      - Status: pass
      - Acceptance check: 六个场景各有用例；判定脚本自己出错时以 3 退出，fast_check 照旧报原始 FAIL 与日志，不会因判定坏掉而放行
      - Scope check: 动了 scripts/fast_check.sh（11 段失败分支、末尾核对与摘要、I1 提示语）、新增 flow/check/check_waivers.py、flow/check_waivers.yaml（空）、tests/test_fast_check.py（夹具补拷判定脚本 + 新用例）
      - Findings: none
    - Blocker: none
    - Reauthorizations: 2026-10-13 rtl-flow：keel 升到 5.125 后锚点指纹漂移，task 正文自提交后未改（git log 核过），检查断言未动，按 --keep-evidence M1,M2 重录；红灯一臂因实现已在无法重现，沿用原证据。在 main aee9fa7d 上复跑：`pytest tests/test_fast_check.py -k waiver` 12 passed；`./scripts/fast_check.sh` rc=0；`pytest tests/ -m 'not flow' -n auto` 690 passed

- [x] 1.2 推 main 硬清单、绕过留痕写进 toolchain；new_worktree.sh 核 core.hooksPath
  - Covers:
    - guardrail-scope / 护栏的挂载状态必须是自愈的或可见的 / 新克隆的工作副本
    - D6
  - Touch:
    - scripts/new_worktree.sh
    - tests/test_new_worktree.py
    - docs/toolchain.md
  - Verify:
    - Strategy: vertical-tdd
    - M1: `.venv/bin/python3 -m pytest tests/test_new_worktree.py -q -k hooks -p no:cacheprovider` —— 夹具主仓没配 `core.hooksPath` 时 new_worktree.sh 退出非 0 并给出 `git config core.hooksPath .githooks`；配上后退出 0。Fails with: `hooksPath`
    - M2 (regression): `.venv/bin/python3 -m pytest tests/test_new_worktree.py -q -p no:cacheprovider` 全过
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:f3f6954c87f286b2dde2cc558f139cf5126ee01bb4b5d96dc71bc70b7543055a
    - M1: 夹具主仓没配 / 配到别处时 new_worktree.sh 退出非 0，stderr 给出 `git config core.hooksPath .githooks`；配成 `.githooks` 或主仓 `.githooks` 的绝对路径时退出 0
    - M1.red: 实现前 2 failed：`core.hooksPath=None：退出码 0`、`core.hooksPath=/elsewhere/hooks：退出码 0` —— artifact openspec/changes/fast-check-waivers/evidence/1.2-red.txt sha256:87297cdd27fe56c569813c0b919934424a6734fe984789b4d0d0f9b296d009bd
    - M1.green: 4 passed —— artifact openspec/changes/fast-check-waivers/evidence/1.2-green.txt sha256:f5ab1178fcbddaac22a97feb2b96d61f09ac21677f4e7de84eef1b31696cf0bf
    - M2: tests/test_new_worktree.py 17 passed（夹具照真仓配上 core.hooksPath 后旧用例不变）—— artifact openspec/changes/fast-check-waivers/evidence/1.2-m2.txt sha256:ac50441f04c9fae3a5a4ae10afcb079ad3f6021b6a01ac0fc6bf3188fe733861
    - Review:
      - Status: pass
      - Acceptance check: 「新克隆的工作副本」场景：钩子没挂上时建 worktree 当场报错并给修复命令；toolchain「推送、授权与共享资源」加了推 main 硬清单（B）与禁止绕过、豁免登记（C）
      - Scope check: 只动 scripts/new_worktree.sh、tests/test_new_worktree.py、docs/toolchain.md 与本 change 目录
      - Findings: none
    - Blocker: none
    - Reauthorizations: 2026-10-13 rtl-flow：keel 升到 5.125 后锚点指纹漂移，task 正文自提交后未改（git log 核过），检查断言未动，按 --keep-evidence M1,M2 重录；红灯一臂因实现已在无法重现，沿用原证据。在 main aee9fa7d 上复跑：`pytest tests/test_new_worktree.py -k hooks` 4 passed；全文件 17 passed

## Expectation Coverage

- E1: fast_check 的失败只能经 `flow/check_waivers.yaml` 登记的豁免放行，过时或挂的 issue 已关判 FAIL。Covered by: 1.1
- E2: 推 main 前跑 fast_check 由 pre-push 钩子强制，新 worktree 核 `core.hooksPath`，绕过要留痕。Covered by: 1.2
