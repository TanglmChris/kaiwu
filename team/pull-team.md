# PM 从镜像拉 team

一个 IP 的 PM 要人干活时，按下面五步从镜像拉起运行态会话。契约见
`openspec/specs/team-organization/spec.md`「PM 按书面流程从镜像拉 team」。

## 1. 开 issue 列要的能力

PM 在本仓开一个 issue，标题 `<ip>：拉 team`，正文列要哪些能力（每种能力一个会话）、
各自先做什么，并提醒 lead（开 issue 之后发一条消息，只写 issue 号）。

## 2. lead 回镜像版本

lead 在 issue 里回一行：`镜像版本：<提交号>`（`git rev-parse --short origin/main`，镜像在 main 上）。
这个提交号就是这批会话用的镜像。镜像以后改了，正在跑的会话不自动跟着变，换不换由 PM 定。

## 3. 建 worktree、起会话、绑角色

每个会话一个 worktree，一个 worktree 只开一个会话：

```bash
scripts/new_worktree.sh <ip>_<能力>                  # 分支 worktree-<ip>_<能力>
( cd .claude/worktrees/<ip>_<能力> && claude --bg -n kaiwu-<能力>-<ip> )
# 在新会话里：
keel chat role --set kaiwu-<能力>-<ip>
```

把新角色加进该 IP 的群：`keel chat group add <ip> kaiwu-<能力>-<ip>`（由已在群里的会话执行）。IP 群只放本 IP 的会话，
组织角色不进（`team/README.md`「keel chat 群」）。
需要的话再把 issue 标签路由加进 `keel/config.yaml` 的 `issue_roles:`。

## 4. 冷启动读什么

新会话开工前按顺序读：

1. `team/README.md`：组织分工与命名；
2. `team/roles/kaiwu-<能力>/README.md`：本能力的职责、交接、禁区、经验；
3. 设计根：`designs/<根>/` 或 `cbb/<根>/` 的规格、方案、验证文档，以及派工 issue。

IP 的事实只从设计根和 issue 读，不从别的 IP 的记忆里推。

## 5. 用完回收

活做完、结果进了 issue，PM 回收这个会话：

```bash
keel chat role --park kaiwu-<能力>-<ip> --reason "<issue 号> 已完成"
claude rm <会话>        # 不删对话记录
```

worktree 按 `docs/toolchain.md`「并行开发」的「合并」一步处理。回收后在第 1 步的 issue 里回一句。

## 需要并行：本会话拉 subagent

每个 IP 的每种能力只开一个常驻会话 `kaiwu-<能力>-<ip>`，同能力不再另起 `-sub` 会话（用户 2026-10-25 定，内部#418；契约
`openspec/specs/team-organization/spec.md`「运行态会话按能力与 IP 命名」）。工作量大要并行时，由这个会话自己拉
subagent：Claude 的 Agent 工具，或按 `docs/toolchain.md`「调用外部模型 CLI」把 codex / dsh 当工具用（内部#191）。
对别的角色来说，每种能力仍只有一个出口；`team/README.md` 的分工表、只经 GitHub 交互、
「发布 → 验证 → 交付 → 集成 → 出口」几步都不变。

- **subagent 不占角色**：不绑 keel chat 角色、不进群、不单独挂 issue 标签、不单开派工 issue；派工、回报都写在本会话的 issue 里。
- **只有本会话提交**：subagent 的改动由本会话审过、验收后由本会话提交，算本会话的交付。只有一个会话提交本方分支，
  就不会出「过期 index 覆盖对方提交」那种事故。要改共享文件（顶层端口、加参数）、要改规格的，照旧由本会话处理或转给规格方。
- **不建常驻 worktree**：subagent 默认在本会话的 worktree 里工作；要隔离检出（例如在另一个提交上跑检查）的，用临时 worktree，用完即删。
- **CPU 预算计入本会话**：本机所有会话同时运行的 `JOBS`、等价证明 `-j`、pytest `-n` 加起来不超过 6，大活排队拿 `cpu-heavy`
  （见 `docs/toolchain.md`「跑」的「CPU 预算」，内部#359）；本会话拉的 subagent 用的核算在本会话的份额里，几个 subagent 同时跑重活也不能超。
- **外部模型 CLI**（codex / dsh）的判断与约束同 `docs/toolchain.md`「调用外部模型 CLI」一节；回来的改动由本会话复跑验收再提交。
