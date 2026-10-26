## Why

2026-09-13 在一台新 clone 的机器上实测：

```
$ ./scripts/fast_check.sh
ok    python compileall (flow/, scripts/)
SKIP  iverilog not on PATH (source ~/tools/env.sh)
$ echo $?
0
```

**退出码 0，而 RTL 那一半一次都没跑。** 更靠前的一层：`git config core.hooksPath`
未设置，`.githooks/pre-push` 根本没被挂载 —— 连那行 `SKIP` 都不会出现，push 静默通过。

这是本仓库的头号失效模式（**报告的范围大于实际检查的范围**）长在护栏自己身上，
而且是第二次：`FOLLOWUP.md` 第 17 条记的两个洞（失败时仍打印 `ok`、空组合展开仍
返回 0）2026-09-09 刚修过一轮。

它与仓库自己的 `experiment-trust` 第一条同构 ——「无法测得的指标必须缺席，
**不得以合法值代替**」。退出码 0 的含义是「声明的检查都跑了且通过」，
拿它表示「一个都没跑」，就是拿一个合法值顶替「没测到」。

原本选 `SKIP` 而不是 `FAIL` 是有理由的：免得 GUI 客户端 push 不动。那个顾虑成立，
但它要的是**一个具名的降级**，不是静默放行。

## What Changes

- **`scripts/fast_check.sh` 每次都打印覆盖摘要**，说明这一轮实际检查了什么、
  什么没能检查。通过与否都打印 —— 只在失败时才说明范围的话，成功路径仍然不可审计。
- **工具缺失默认为失败**。`iverilog` 不在 PATH 时退出码非 0，消息同时给出修复方式
  （`source ~/tools/env.sh`）与显式降级方式。
- **降级必须具名**：`FAST_CHECK_ALLOW_MISSING_TOOLS=1` 时，缺工具降为一条醒目的
  `DEGRADED` 行且退出 0，摘要里写明哪一类检查没跑。git 自己的 `--no-verify` 仍然
  是另一条正常的旁路。
- **`.envrc` 自愈 `core.hooksPath`**：检测到未指向 `.githooks` 就设上。direnv 已经是
  本仓的 bootstrap（`.envrc` 里已有 `source ~/tools/env.sh` 与 `.venv` 激活），
  cd 进目录即生效，无需记住任何步骤。
- **BREAKING（对本地工作流而言）**：此前在没有 `iverilog` 的环境里 `fast_check.sh`
  退出 0，此后退出非 0。这正是本变更的目的，但它会让「工具没装好」从无声变成挡路。

## Capabilities

### New Capabilities

- `guardrail-scope`: 护栏必须报告自己实际覆盖的范围，且成功退出必须意味着
  「声明要检查的东西全部检查了并通过」。无法执行的检查 MUST NOT 被当作通过；
  降级 MUST 是显式具名的，MUST NOT 是默认行为。

### Modified Capabilities

无。

## Impact

| 文件 | 动作 |
|---|---|
| `scripts/fast_check.sh` | 覆盖摘要 + 退出码语义 + 具名降级 |
| `.envrc` | 自愈 `core.hooksPath` |
| `tests/test_fast_check.py` | 新增用例覆盖新语义 |
| `.githooks/pre-push` | **不动**（它只是 `exec ./scripts/fast_check.sh`） |

**不受影响**：`results/experiments.jsonl`、`flow/` 的任何行为、任何已记录的 PPA 数字。

**风险**：

1. **挡住正常工作** —— 没装工具链的机器（例如只做文档的那台）从此 push 会被拦。
   缓解：`FAST_CHECK_ALLOW_MISSING_TOOLS=1` 与 `git push --no-verify` 两条具名旁路，
   且失败消息里直接给出。
2. **`.envrc` 隐式改本地 git config** —— cd 进目录会写 `core.hooksPath`。
   缓解：只写 `--local`（不碰全局），只在值不对时写，且在 `.envrc` 里写明理由；
   2026-09-13 已向用户确认此做法。
3. **降级开关被长期打开** —— 那就退回今天的状态，只是变得可见。
   缓解：摘要行在降级时仍然逐项写明哪类检查没跑，不会只剩一个 `ok`。
