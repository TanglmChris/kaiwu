## Why

内部#254（用户 2026-10-09 复盘 内部#241–内部#249）：fast_check 红着的分支照样推上去、进了 PR（内部#245 / 内部#246）。查下来，`.githooks/pre-push` 从 09-04 起就跑 fast_check，红就拒推（内部#254 issuecomment-6121147891）。所以缺口不在「没有钩子」，而在三处：
- 红灯没有合法的「先挂着」通道，想先推就只能 `--no-verify` 或 `FAST_CHECK_ALLOW_MISSING_TOOLS=1`，而且绕过不留痕；
- 推 main 前没有硬清单，内部#241 的全量 pytest 红是靠 PM 临时人工跑才拦住的；
- 钩子靠 `core.hooksPath` 挂载，新 worktree 没配上时不会报出来。

用户 2026-10-12 定（PM 会话，内部#254 issuecomment 2026-10-12T09:18:01Z）：A + B + C 全做，豁免粒度按「检查段 + 文件 glob」。

## What Changes

- **A. 有记录的例外**：新增 `flow/check_waivers.yaml`。每条登记检查段、文件 glob、issue 号和到期条件。fast_check 的检查段失败时，如果每一条违规都落在该段已登记的 glob 内，就降为「豁免」，不让退出码变红，摘要单列生效的豁免。只要有一条违规不在豁免内，照旧 FAIL。豁免过期也 FAIL：本次没有放行任何违规（已修好或写错了段名），或者 issue 已关。
- **B. 推 main 的硬清单**：`docs/toolchain.md`「推送、授权与共享资源」写明，PM 推 main 前在合并结果上跑 `fast_check` 与全量 pytest（带 EDA PATH），把退出码与摘要贴进推送记录；任一红就不推。
- **C. 绕过留痕**：`toolchain` 写明不许用 `--no-verify` 或 `FAST_CHECK_ALLOW_MISSING_TOOLS=1` 推送；确实要用，在 issue 里写原因。`scripts/new_worktree.sh` 建完后核一遍 `core.hooksPath`，没指向 `.githooks` 就报错。
- 不碰测量代码与记录，不换代。

## Capabilities

### Modified Capabilities

- `guardrail-scope`

## Impact

- fast_check 的成功退出多了一种合法情形：失败全部被登记的豁免覆盖。契约随之修改（guardrail-scope 的第一条要求）。
- 开豁免要改仓内文件，再走推送和 PM 推 main，例外因此留在 git 历史里。
