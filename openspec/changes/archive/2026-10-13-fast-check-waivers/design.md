## Context

fast_check 里能按文件定位违规的检查段都是同一种写法：Python 片段把违规逐行写进 `$LOGDIR/<段>.log`，行首是 `路径:行号:` 或 `路径:`，续行缩进；失败分支统一是 `note "FAIL  …"; cat log; fail=1`。共 11 段：`ports`、`doc`、`dup`、`clean`、`escape`、`case`、`naming`、`enum`、`style`、`directive`、`bind`。

## Decisions

- **D1** — 检查段的名字取日志文件名（如 `style`），不取中文标题。标题会改措辞，日志名是代码里的标识。fast_check 头注释与 toolchain 列出全部 11 个名字。elaborate / lint 不接本机制：lint 已有 `waivers.vlt`，elaborate 失败没有可豁免的形态。
- **D2** — 一条违规算被豁免，要求它的路径匹配该段某条豁免的 glob（`fnmatch`，相对仓库根）。日志里不缩进的非空行都按违规行看待；行首认不出路径的行无法归属，按未豁免算。这样失败就是失败，不会因为格式认不出而被放行。
- **D3** — 豁免文件：`flow/check_waivers.yaml`，顶层 `waivers:` 列表，每条四个字段都必填：`check`（D1 的名字）、`files`（glob 字符串或列表）、`issue`（本仓 issue 号）、`until`（到期条件，文字）。缺字段、段名不认识、文件读不了，都 FAIL。文件不存在等于零条豁免。
- **D4** — 过期：跑完全部检查段后，一条豁免如果本次没有放行任何违规，就判过期 → FAIL，点名这一条。它要么已经修好，要么写错了段名或 glob。查 issue 状态要联网：调 `gh api`，超时 5 秒；issue 已关 → FAIL；查不到（离线、没装 gh、超时）→ 只提示「未核 issue 状态」，不拦。pre-push 不能因为网络不通而红，这条由 B 的推 main 清单兜底（PM 推之前在联网环境下跑）。`FAST_CHECK_WAIVER_ISSUE_CHECK=0` 可以跳过联网查询（测试用），跳过时照样提示。
- **D5** — 输出：被豁免的段打 `WAIVED  <标题>（豁免 N 条违规，见 flow/check_waivers.yaml）`，并照样打印日志，在被豁免的行前加 `[豁免 #<issue>]`；进覆盖摘要的「已执行」，后缀「（有豁免）」。摘要末尾单列「生效的豁免」，逐条写段名、glob、issue、到期条件。
- **D6** — hooksPath：`scripts/new_worktree.sh` 结束前读 `git config core.hooksPath`，与主仓 `.githooks` 的绝对路径或相对写法 `.githooks` 比对，不一致就以非零退出并给出修复命令。

## Risks

- glob 写得太宽（如 `designs/**`）等于整段豁免。缓解：toolchain 写明 glob 只写到出问题的文件；评审时看豁免文件的改动。
