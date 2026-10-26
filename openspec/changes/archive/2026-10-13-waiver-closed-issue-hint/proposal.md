## Why

内部#291：verify 交付 内部#289 后马上关了 issue，可删豁免的提交还没进 main。于是基于 main 的每个分支跑 fast_check 都报「失败豁免过时：挂的 issue 已关闭」，pre-push 过不去，设计 R009 的批 1 / 2 被卡住。原因是护栏把「豁免还在放行违规、但 issue 已关」判成失败，而「修复已交付、还没进 main」这段时间正好就是这个状态。用户 2026-10-13 选方案 3：检查与规则两样都改。

## What Changes

- 豁免还在放行违规、但挂的 issue 已关：由 FAIL 改为一行提示。豁免不再放行任何违规时，仍判「过时」FAIL（不变）。
- 规则：挂着失败豁免的 issue，删豁免的提交进 main 之后才关。这是 内部#218「修好即关」常备授权的例外，写进 toolchain、豁免文件头注释与 CLAUDE.md 的授权句。PM 推 main 时看到这行提示，确认修复在这一批里。

## Capabilities

### Modified Capabilities

- `guardrail-scope`：「秒级护栏必须检查失败豁免没有过时」里 issue 已关一支。

## Impact

- `flow/check/check_waivers.py`（`final` 的一支）、`tests/test_fast_check.py`（issue 状态用例）、`flow/check_waivers.yaml` 头注释、`scripts/fast_check.sh` 注释、`docs/toolchain.md`、`CLAUDE.md`。
- 不改测量口径，不换代。
