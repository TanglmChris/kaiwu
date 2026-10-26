# 工具链：推送、授权、共享资源与换班（原「设计与验证分属两个 worktree」一节）

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

### 设计与验证分属两个 worktree（内部#79）

这一节原来的角色分工、找用户拍板、交接两步走、issue 规则、项目经理与 PPA 报告的分工已迁到 `team/README.md`「协作规则」；
各能力的做法迁进了镜像：规格评审 → `team/roles/kaiwu-review/README.md`；发布 → 验证 → 交付 → 集成 → 出口、冻结输入、版本编号与出口 tag →
`team/roles/kaiwu-verify/README.md`；设计侧的自测范围（含「改动的等价证据分三级」「SVA 文件的分工」）与集成期的过渡端口表 → `team/roles/kaiwu-design/README.md`；主会话分发 → `team/pull-team.md`
（kaiwu-org-model，内部#305）。下面只留全仓共用的流程约定。

**推送、授权与共享资源（内部#213、内部#218，用户 2026-10-05 / 10-06 定）**

- **推 main 统一由 kaiwu-chief 做**（用户 2026-10-20 定，内部#305；此前由项目经理做，内部#213 issuecomment-5996252758、-5996310644）：每天 9:00 一个窗口，里程碑与「有人被卡住」时例外。
  - 其他会话不推 main：在自己的特性分支上跑完回归，推到自己的分支，或在 main checkout 本地合并、提交；
  - 然后把分支名或提交号、fast_check 与全量 pytest 的结果贴进相关 issue，再给项目经理发一行。
  - 换代重跑与正式记录也在 main checkout 本地提交，不推。
- **推 main 前的硬清单**（内部#254，用户 2026-10-12 定）：推 main 之前，在**合并后的结果**上、在联网的 shell 里
  （`source ~/tools/env.sh` 之后）跑这两条，把命令、退出码和摘要最后几行贴进当次推送记录（推送 issue 或项目计划 issue 的推送评论）：
  - `./scripts/fast_check.sh`：退出 0。有 `WAIVED` 的，摘要末尾会列出「生效的豁免」，照贴；
  - `.venv/bin/python3 -m pytest tests/ -q -n 4`：全过（`scripts/merge_check.py` 一条命令跑完这两项，全量模式排队拿 `cpu-heavy`，只改文档的轻量模式不拿锁、只等负载（内部#440）；只改文档的批次与复用见下面「两种省法」）。不带 EDA PATH 时会静默跳过一百多条，不算数。

  任一不过就不推。不能「先推、再修」：要么修掉，要么按下一条登记豁免。
  一键做法（内部#344）：`.venv/bin/python3 scripts/merge_check.py --base origin/main --head <合并结果的提交>`。它在临时检出里跑上面两条，
  另比合入前后的用例 ID（`pytest --collect-only`），打三行结论，并列出删 / 增 / 改名 / 搬家的 ID（同一个「文件::函数」里删去不多于新增的，记为参数化 ID 改名、不算删去，内部#385；剩下的删去在新增里有只差文件路径的，记为搬家、也不算删去，内部#336）；三项都合格才退出 0。EDA 工具补过 `~/tools/env.sh`
  仍不在 PATH 时退出 2，不会静默跳过。复核别人的提交只要 fast_check 时，用 `./scripts/fast_check.sh --rev <提交>`。
  两种省法（用户 2026-10-20 定）也算数，贴的时候照贴它打印的首行：
  - **只改文档走轻量**：base..head 的改动全是 `*.md` / `*.drawio` / 图片、且都在 `designs/` `cbb/` `docs/` `knowledge/` `team/` 下时，
    pytest 只串行跑 `scripts/merge_check.py` 里的 `DOC_TESTS` 清单、fast_check 带 `--docs-only` 不跑 RTL lint（覆盖摘要里列为未执行），首行写「模式：轻量」；根目录 `CLAUDE.md` / `AGENTS.md` 和
    `openspec/` `.claude/` `.agents/` `flow/` `scripts/` `tests/` `keel/` 下的 md 不算文档。`--full` 强制全量。
    **新增读仓内文档的测试要加进 `DOC_TESTS`**，否则轻量检查不跑它。
  - **同一份内容只测一次**：同一组 base 树、head 树、检查脚本、EDA 工具与 Python 环境已经通过过一次（不论在哪个 worktree 跑的），
    再跑直接打印「复用」和当时的结论，不排队、不建检出；只复用通过的结果，`--no-cache` 强制重跑。
  临时检出里会先拷入本 worktree 的 `runs/.source_sets/`（读入集合缓存，按内容核键），省掉带 `-n` 的 pytest 开跑前约 9 分钟的单核预热（内部#384）。
- **红灯只能经登记的豁免放行，不许绕过钩子**（内部#254）：
  - `.githooks/pre-push` 跑 fast_check，红就拒推。
  - 确实要先推的，在 `flow/check_waivers.yaml` 登记一条：检查段、文件 glob、issue 号、到期条件、`count`（登记时这条豁免放行的违规条数）。glob 只写到出问题的那几个文件。本次条数与 `count` 不等就 FAIL：多了是同一文件里有新违规，少了就把 `count` 改小（内部#330）。
    fast_check 把只落在豁免内的违规降为 `WAIVED`；豁免已用不上，就报「失败豁免过时」。还在放行违规而挂的 issue 已关，
    只出一行提示（修复多半已交付、还没进本分支，内部#291）。**挂着失败豁免的 issue，删豁免的提交进 main 之后才关**——
    这是常备授权「关自己证据齐全的 issue」（内部#218）的例外（用户 2026-10-13 定）；推 main 时看到这行提示，确认修复在这一批里。
    能豁免的是按文件定位违规的 11 段（段名见 `flow/check/check_waivers.py` 的 `CHECKS`）；elaborate / lint 不在其内，lint 用 `waivers.vlt`。
  - 不许用 `git push --no-verify`，也不许带 `FAST_CHECK_ALLOW_MISSING_TOOLS=1` 推送。确实要用（比如这台机器上就是没有某个工具），
    在相关 issue 里写明原因和推了哪个提交。
  - `scripts/new_worktree.sh` 建完 worktree 先自愈 `core.hooksPath`（`scripts/heal_hooks_path.sh`），再核生效值，不是相对的 `.githooks` 就报错；绝对路径也不认，工作区改名后会悬空（内部#417）。
- **常备授权（内部#218）**，不用每次问用户。条件不满足就照旧逐次问：
  1. **推本会话自己的特性分支**（`worktree-*`、评审分支等，**不含 main**）：推前 fast_check 通过，不强推（不 `--force`），推后在相关 issue 留提交号；
  2. **关自己名下、证据齐全的 issue**：关闭时附结论与证据链接（提交或评论）。别人名下的、等用户拍板的不关；挂着失败豁免的，删豁免的提交进 main 之后才关（内部#291）；
  3. **删本会话自己产生的中间产物**（用户 2026-10-06 定「自己的中间文件删除不用问我」，内部#218 issuecomment-6007129657）：不限 scratchpad，也包括本会话在 main checkout 或自己 worktree 里跑出来的 `runs/<id>/`（中止或失败的运行目录、算完功耗的 VCD）、临时 detached worktree。条件：是本会话产生的、结果已记下（或已合入）、删前 `lsof +D <目录>` 确认没有进程在用。**不含**实验记录（`results/<设计根>/experiments.jsonl`）、交付的 `results.jsonl`、证据文件，**不含分支**（本地、远端都不含），不含别人的东西。
  4. **kaiwu-flow 删已并入 main 的分支**（用户 2026-10-19 定：分支清理归 kaiwu-flow，「已并入的直接删」）：远端或本地分支的头整个在 `origin/main` 里（删前 `git fetch --prune`，逐个 `git merge-base --is-ancestor origin/<分支> origin/main`），且不被任何 `git worktree list` 检出，就可以删，不用逐次问；删前先存「分支 → 提交号」清单，删完在 issue 里列出。**不含**未并入的分支（别的会话的先问属主）、补丁分支（按设计不进 main，见 `team/roles/kaiwu-verify/README.md`）、tag。
- **keel 的配置（keel ≥ 5.105.0，keel#257；用户 2026-10-11 定方案 A）**：`keel/config.yaml` 的 `authorize:` 里，第 1 条写成 `push:<分支 glob>`，列全在用的分支命名——Claude 写入守卫强制执行（`keel --doctor` 显示 `push scope: enforced`），推表外分支或看不出目标分支的 push 一律拒，glob 只挡写错的分支名。main 不在 glob 里，改写成 `push-protected:main@<推 main 的角色>`（keel 5.114 / keel#280，用户 2026-10-12 定，内部#283；当前角色见 `keel/config.yaml`「组：推 main」）：只有绑定该角色的会话能推 main，每条 push 命令都由 Claude Code 当场问用户、keel 不存批准；别的会话推 main 一律拒，`bypassPermissions` / `dontAsk` 模式下也拒。第 2 条写成 `issue-close:<owner>/<本仓>`，第 3 条写成 `cleanup:scratch`，这两条 keel 只记录、不强制。新开一种分支命名前，先把它的 glob 加进 `authorize:`，否则推不上去。
- **桌面版自换班（keel 5.129 / 5.130 起，用户 2026-10-14 定，内部#309）**：`authorize:` 里声明 `self-shift` 与
  `shift-restore`。前者只管 `keel shift ready --wake` 之后 keel 打印的那几步（步骤随 keel 版本变，以当时的输出为准），
  不含「要不要换班」的决定；后者只管醒后按 keel 的提示恢复 Remote Control 与标题。对应的 Claude Code 工具权限（`permissions.allow`）由用户自己加。
- **巡逻与 issue 路由（keel 5.114，用户 2026-10-12 定，内部#283）**：`keel/config.yaml` 的 `patrol:` 声明由 PM 每 60 分钟跑
  `keel patrol`（keel 不排定时，只在 PM 新会话与 `keel shift resume` 时提醒重建会话级定时）；`issue_roles:` 把标签
  `flow` / `design` / `verify` 路由到对应角色（不设 `design-sub`，内部#418）（当前映射见 `keel/config.yaml` 的 `issue_roles:`），
  `keel patrol --issues` 对带标签的 issue 更新各发一条私信；一个 issue 挂几个标签就发给几个角色。
- **推送批准按提交号算**（G17）：用户批准推某个提交之后，要推的提交号变了（比如又合进了别人新推的提交），按新提交号重新请用户批准。
- **仍要用户在该会话里逐次批准**：推 main（kaiwu-chief 每次推仍由 Claude Code 当场问用户）、删分支（本地或远端；上面第 4 条 kaiwu-flow 删已并入 main 的除外）、对外发布（其他仓库的 issue，如 keel）、改 `CLAUDE.md`、强推、删别人的东西。
  项目经理汇聚这些待批事项：在 Slack 上 `@owner` 列出会话和链接，桌面侧栏另设「待批准」分组。
- **keel 的问题由各会话直接开 keel issue**（内部#213），不再经流程转。开之前照上一条，先问用户。
- **issue 管流转，仓库管知识**（内部#213）：派工、交接、要拍板的事开 issue；会话内部的拆分（一个人自己的子步骤）不再开 issue。结论与规则写进仓库（toolchain、spec、跟踪文档），不只留在 issue 评论里。
- **跨会话同步（G19，内部#213 issuecomment-5996131875）**：
  - 收到消息先读事实源（issue、git）再动手；
  - 积压多条时从最新一条开始，旧消息里的事如果事实源显示已经办了就跳过；
  - 规则变更类消息要回一行「已读」；
  - 消息第一行带时间（如 `10-06 09:10｜…`）。
- **取远端提交的稳妥写法**（内部#345）：`git fetch` 之后用 `git rev-parse --verify "origin/main^{commit}"`；报 `Needed a single revision`
  时先别重试同一条命令，改用 `git ls-remote origin refs/heads/main` 取 SHA，并把原命令、`git for-each-ref refs/remotes/origin/main`
  与 `ls "$(git rev-parse --git-common-dir)/refs/remotes/origin"` 的输出贴到 内部#345（间歇性的，还没查到原因）。zsh 里拼 `"$ref:path"`
  要写成 `"${ref}:path"`，否则 `:r` `:e` 等会被当成修饰符吃掉，拼出来的引用名就不对。
- **main checkout 是共享资源**，有三个使用者：验证（集成）、流程（换代重跑与记录）、PPA 报告（正式扫参）。用之前先声明占用：
  - 在 git 公共目录写一行占用说明，`echo "<会话> <做什么> 预计到 <时刻>" > "$(git rev-parse --git-common-dir)/main-checkout.owner"`，同时给项目经理发一行；
  - 用之前先 `cat` 这个文件，有人占用就等；
  - 用完删掉这个文件，发一行「已空出」。
  - 不另开记录专用的 worktree：记录的 `git_commit` 取自 HEAD、正式记录只在白名单分支上（`flow/record_branches.yaml`，内部#422；红线 3），同一个分支只能检出在一个 worktree 里；多一个 detached 的 main 副本，反而让「哪份是 main」说不清。
- **memory 的文件名**用 `<角色>-<主题>.md`，各会话只改自己的条目（G20，keel 不做写保护）。
- **keel chat 角色名**：按 `team/README.md`「命名」写成 `kaiwu-<能力>-<ip>`；各 IP 当前的角色表在该设计根的 `doc/process.<顶层>.md`。
  - 各会话在自己的 worktree 跑 `keel chat role --set <角色>`。
  - 绑定是推荐项，用于通知：内部群、`keel shift request`、回执都要靠它；换班本身不要求绑定（keel 5.99）。

**阶段整理**（G10，内部#213）：每个大版本发布后做一次，项目经理用 `flow/templates/phase-review.md` 开 issue，各会话交十项清单，整理完换班。

**换班（G16，内部#217；用户 10-05 要求「PM 在合适时间触发各会话换班」，10-06 定改用 keel 的换班）**：用 `keel shift`（keel ≥ 5.98，说明见 keel 的 `docs/shift-change.md`（中文版 `.zh-CN.md`）），本仓不另写就绪脚本。

| 步 | 谁 | 做什么 |
|---|---|---|
| 1. 触发 | 项目经理 | `keel shift request <角色>`（要绑了角色才会送达，角色名见 `team/README.md`「命名」）；没绑的会话发一条跨会话消息「换班：请收尾」 |
| 2. 自查 | 会话 | `keel shift check`：查未提交改动、不在远端的提交、还开着的写保护、在本 worktree 里跑的进程、临时 worktree、发给本角色还没处理的待办与未读，有任何一项就退出 1。逐项处理掉，或在便条里写明为什么留着（`keel shift ready --force-reason …`） |
| 3. 交接 | 会话 | 状态写进自己的 issue 和阶段清单的「带进下一阶段的事」（下一步、等谁、在哪个分支或文件）；长期事实补进 memory（只改自己的条目）；`keel shift ready "<在做什么、下一步、在等谁、东西在哪>"` 留便条（存在 git 公共目录的 `keel-chat/shift/` 下，不进仓库） |
| 4. 清 | 会话 | `clear_session("self")` 或 `/clear`。Remote Control 不挡自清，但清完后该会话的 Remote Control 会变成 off，要在手机上用得重新打开（spec 10-05 试点） |
| 5. 叫醒 | 项目经理 | `keel shift start <角色>`（便条留下后才允许），或发冷启动消息 |
| 6. 新的一班 | 会话 | `keel context`，再 `keel shift resume` 读便条（绑了角色的会自动回项目经理「已就位」）；接着读自己名下 open 的 issue 和阶段清单里的交接 |

- 项目经理最后换班：出阶段总结、用户批准归档后，写项目计划 issue 的快照，再自清。
- `keel shift status` 看各角色到了哪一步。
- keel 5.99.0 的 `keel shift check` 会把同一仓库里**其他会话** scratchpad 的临时 worktree 也列为本 worktree 的遗留；5.99.1（keel#258）起只算本 worktree 里启动的会话建的，别人的只列为 note。还在 5.99.0 时，遇到不是自己的临时 worktree，用 `--force-reason` 写明。

#### 规格评审（内部#114、内部#115）

已迁到 `team/roles/kaiwu-review/README.md`「规格评审」。

#### 发布 → 验证 → 交付 → 集成 → 出口（内部#80、内部#300）

已迁到 `team/roles/kaiwu-verify/README.md`「发布 → 验证 → 交付 → 集成 → 出口」；设计侧的自测范围在 `team/roles/kaiwu-design/README.md`「设计侧的自测范围」。

#### 需要并行：本会话拉 subagent（内部#418，用户 2026-10-25；取代 10-04 的主会话 / 子会话）

已迁到 `team/pull-team.md`「需要并行：本会话拉 subagent」。

### 集成期的过渡端口表（内部#119）

已迁到 `team/roles/kaiwu-design/README.md`「集成期的过渡端口表」。
