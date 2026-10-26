# team-organization Specification

## Purpose
规定 kaiwu 作为 IP 开发团队的组织层怎么落在仓库里：组织章程与能力镜像放在哪、必须有哪些节，运行态会话怎么命名，PM 怎么从镜像拉 team，常备授权怎么按能力分组，以及镜像改动后怎么用干净实例验收。

这个能力存在的理由，是用户 2026-10-19 定的组织模型（内部#305）：能力（规格、设计、验证、评审、报告）不和某个 IP 绑定，做成仓里的文件；每个 IP 由自己的 PM 拉一组运行态会话。此前这些分工只写在 issue 评论、各会话的记忆和 `docs/toolchain.md` 里，而且写死了第一个 IP 的会话名，第二个 IP 来了照着做不出来。

## Requirements

### Requirement: 组织章程与能力镜像必须在固定位置并有必备节

组织章程 MUST 是 `team/README.md`，写明 kaiwu-chief、kaiwu-lead、kaiwu-pm-<ip>、kaiwu-flow、kaiwu-layout 各自的职责、边界与上报路径。每个能力镜像 MUST 是 `team/roles/kaiwu-<能力>/README.md`，能力清单为 spec、design、verify、review、report，每份 MUST 有六节：「职责」「输入与输出」「交接」「禁区」「技能与模板」「经验」。

「技能与模板」一节 MUST 只列路径（技能在 `.claude/skills/`，模板在 `flow/templates/`），MUST NOT 复制它们的内容 —— 复制出来的副本会在原件更新时静默过期（`knowledge-placement`「每类知识必须有单一权威出处」）。

理由：组织模型（内部#305 issuecomment-6260764796）要求能力做成「镜像」——仓里的文件，不是会话。第二个 IP 的 PM 要能只读这些文件就拉起一组会话；节名固定，才能机械地查出缺了哪一节。

#### Scenario: 镜像齐全

- **WHEN** 检查 `team/roles/` 下的五个镜像
- **THEN** 每个都有 `README.md`，且六节标题都在

#### Scenario: 镜像缺一节

- **WHEN** 某个镜像的 `README.md` 没有「禁区」一节
- **THEN** 检查 MUST 失败，并报出镜像名和缺的节名

#### Scenario: 镜像复制了模板内容

- **WHEN** 某个镜像的「技能与模板」一节贴了 `flow/templates/` 下某个模板的正文
- **THEN** 评审 MUST 判为违反单一出处，改成只写路径

### Requirement: 镜像与组织章程不得含 IP 专属内容

`team/` 下的文件 MUST NOT 含闭源设计的名字或内容，判据是 `flow/export/manifest.yaml` 的 block 规则。IP 的知识 MUST 只放在该 IP 的设计根和它 PM 的项目记忆里；能力经验里需要举例时，MUST 用开源设计（如 adder32）。

理由：镜像要能被任何 IP 的 PM 拉起。混进某个 IP 的东西，别的 IP 的实例就会照着那个 IP 的前提干活：把一个 IP 的个例当成通用规则，是本仓 10-12 实撞过的失效（内部#264 推广出的 LRS §5.3 后来删掉）。这条也和 `repo-layout`「闭源内容只在闭源设计根下」一致。

#### Scenario: 镜像里写了闭源设计名

- **WHEN** 某个镜像的「经验」一节写了一个 block 规则匹配的闭源名字
- **THEN** 检查 MUST 失败，并报出文件与行号

#### Scenario: 镜像用开源设计举例

- **WHEN** 镜像用 adder32 举例
- **THEN** 检查通过

### Requirement: 运行态会话按能力与 IP 命名

从镜像拉起的会话的 keel chat 角色名 MUST 是 `kaiwu-<能力>-<ip>`，每个 IP 的每种能力 MUST 只有这一个常驻会话，MUST NOT 再开同能力的子会话角色（如 `kaiwu-<能力>-sub-<ip>`）。镜像本身叫 `kaiwu-<能力>`，不带 IP 后缀。组织角色（kaiwu-chief、kaiwu-lead、kaiwu-flow、kaiwu-layout）不带 IP 后缀，同样各只有一个会话。

需要并行时，由这个会话自己拉 subagent（Claude 的 Agent 工具，或按 `docs/toolchain.md`「调用外部模型 CLI」把 codex / dsh 当工具用，内部#191）。subagent MUST NOT 绑定 keel chat 角色，MUST NOT 单独挂 issue 标签或建常驻 worktree（要隔离检出的用临时 worktree，用完即删）；它的改动 MUST 由拉它的会话审过之后由该会话提交，算作该会话的交付；它占的 CPU 计入该会话的份额（内部#359）。

理由：命名由用户 10-19 定（内部#305 issuecomment-6260815697），镜像和运行态正好用 `-<ip>` 后缀区分，没有后缀的角色就是跨 IP 的。取消子会话由用户 2026-10-25 定（内部#418）：并行交给本会话的 subagent，能少开常驻会话；只有本会话提交，也就没有几个会话共用一个分支、过期 index 覆盖对方提交的事。取代 内部#380 留下的「lead 临时拉的会话叫 `kaiwu-lead-sub`」。

#### Scenario: 新 IP 拉设计会话

- **WHEN** IP `foo` 的 PM 从 kaiwu-design 拉一个会话
- **THEN** 它的角色名是 `kaiwu-design-foo`

#### Scenario: 角色名少了 IP 后缀

- **WHEN** 一个运行态设计会话绑定成 `kaiwu-design`
- **THEN** 这是错的：`kaiwu-design` 是镜像名，不是会话名

#### Scenario: 设计要并行做两个子模块

- **WHEN** `kaiwu-design-foo` 要同时改两个子模块
- **THEN** 它自己拉两个 subagent 分头做，审过它们的改动后由 `kaiwu-design-foo` 提交；不另起 `kaiwu-design-sub-foo` 会话，subagent 不绑角色、不单开派工 issue 标签

#### Scenario: 绑了子会话角色

- **WHEN** 一个会话绑定成 `kaiwu-verify-sub-foo`
- **THEN** 这是错的：同一 IP 的验证只有 `kaiwu-verify-foo` 一个常驻会话

### Requirement: PM 按书面流程从镜像拉 team

PM 拉 team MUST 按 `team/pull-team.md` 的五步走：开 issue 列要的能力 → lead 在 issue 回镜像所在的提交号 → 建 worktree、起会话、绑角色、进该 IP 的群 → 新会话冷启动时读 `team/README.md`、对应镜像和设计根 → 用完由 PM 回收（`claude rm`、`keel chat role --park`）。拉起时记下的镜像提交号就是该实例用的镜像版本；镜像以后改了，正在跑的实例不自动跟着变，要不要换由 PM 定。

理由：内部#352 的迁移实际就是这样一步步做的（内部#305 issuecomment-6261954498）。不写下来，下一次拉 team 又要靠记忆重拼。镜像版本按提交记，和「验证按提交取设计版本」同一个道理。

#### Scenario: 拉 team 留下版本记录

- **WHEN** PM 为 IP `foo` 拉了 design 与 verify 两个会话
- **THEN** 该 issue 里有 lead 回的镜像提交号，两个会话的角色分别是 `kaiwu-design-foo`、`kaiwu-verify-foo`

#### Scenario: 用完回收

- **WHEN** IP `foo` 的某个运行态会话的活做完
- **THEN** PM 回收它，`keel chat role` 里该角色是 parked，不再被巡检唤醒

### Requirement: 常备授权按能力分组声明

`keel/config.yaml` 的 `authorize:` 列表 MUST 按能力或组织角色分组：每组以一行注释 `# 组：<能力或组织角色>` 开头，组内条目都归这个能力或组织角色。keel 不能按角色强制的组（目前除 `push-protected` 以外的全部），组头 MUST 标「（仅声明）」。每一条 `authorize:` 条目 MUST 落在某一组下。

分组 MUST NOT 改变授权的含义：重排前后，`authorize:` 的条目集合 MUST 相同。

理由：用户 10-19 定授权按能力划分（内部#305 issuecomment-6262335699 第 3 条）。keel 5.152 只有 `push-protected` 认 `@<role>`。所以先声明、后强制，强制的部分等 TanglmChris/keel#378。

#### Scenario: 重排不改授权

- **WHEN** 比较重排前后 `keel/config.yaml` 的 `authorize:` 条目集合
- **THEN** 两个集合相同

#### Scenario: 有条目不在任何组下

- **WHEN** `authorize:` 里某一条前面没有 `# 组：` 组头
- **THEN** 检查 MUST 失败，并报出这一条

### Requirement: 授权只在 config 一处

授权的权威出处 MUST 只有 `keel/config.yaml` 一份。`team/README.md` MUST 指向它，MUST NOT 另抄一张授权表。

理由：抄出来的表会静默过期；而且 IP 专属条目（如推 main 守卫的角色名）含 IP 名，抄进 `team/` 就违反「镜像与组织章程不得含 IP 专属内容」。

#### Scenario: 章程里抄了授权条目

- **WHEN** `team/README.md` 逐条列出了 `authorize:` 的条目
- **THEN** 评审 MUST 判为违反单一出处，改成指向 `keel/config.yaml`

### Requirement: 镜像改动要经干净实例验收

镜像结构建好或改动较大之后，MUST 从镜像在仓外的临时 clone 里拉一个干净实例，验证它不靠任何 IP 的项目记忆也能完成一件已知答案的活。被测设计是 adder32。证据 MUST 包括三项：会话开头确认没有加载共享记忆、实例的产物、与对照结果的比较。

理由：共享记忆按主仓路径共用，仓内任何 worktree 起的会话都会读到已有 IP 的项目记忆。不换路径验，就证明不了镜像本身够用。

#### Scenario: 验收实例读到了共享记忆

- **WHEN** 验收实例启动时加载了主仓路径对应的共享记忆目录 `~/.claude/projects/<主仓路径编码>/memory/`
- **THEN** 这次验收作废，要换到仓外路径重做

#### Scenario: 验收通过

- **WHEN** 干净实例只凭 `team/` 与镜像做完那件活，产物与对照一致
- **THEN** 证据贴进镜像验收的 issue，镜像算可用
