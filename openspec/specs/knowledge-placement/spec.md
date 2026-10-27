# knowledge-placement Specification

## Purpose

规定仓库里每类知识的归属：哪一类必须记在哪，以及哪两种容器互相不能代替。

这个能力存在的理由是一次实际发生的失效。仓库曾用一个 `FOLLOWUP.md` 同时装
**会完结的事项**（待办、缺陷）与**永久读数口径**（哪批记录因何不可用），
两者寿命完全不同，混在一起的结果是：待办做完了没人回来划掉——账本自己过期，
而口径被淹没在编号序列里。更严重的是，该文件一度被 21 处已归档记录指为
`Durable owner:`，却对其中两件事（`knowledge/README.md` 声称"都记在 FOLLOWUP"的
两条流程硬边界）从未真正记录过——**声称的记录范围大于实际记录范围**，
正是本仓库的头号失效模式长在账本自身上。

因此本能力的两条约束是对称的一对：会完结的事项不得只记在仓库文档里
（文档没有状态机与所有权），永久口径不得记在 issue 里（issue 的终态是关闭，
关闭会让口径从视野中消失）。第三条要求归档不可回写，并规定失效引用如何
保持一跳可达。

## Requirements

### Requirement: 每类知识必须有单一权威出处

仓库里的每一类知识 MUST 只有一个权威出处。其余任何地方提到同一件事时
MUST 以引用的形式指向该出处，MUST NOT 复述其结论 —— 复述出来的副本会在
原件更新时静默过期，而读者无从判断手上这份是不是最新的。

归属如下：

| 知识类别 | 权威出处 |
|---|---|
| 踩坑的症状、判据命令、修复 | `docs/pitfalls.md` |
| 工具路径、PDK、环境，以及全仓共用的流程约定（并行开发、磁盘、外部模型 CLI 等） | `docs/toolchain/*.md`（按主题分文件；`docs/toolchain.md` 只作索引） |
| **记录的读数口径**：哪些记录因何不可用、不可横向比较、不可跨位宽比较 | `docs/data-credibility.md` |
| 会完结的事项：待办、已知缺陷、待决问题 | GitHub issue |
| 契约：仓库布局、记录 schema、打分、可信度 | `openspec/specs/*/spec.md` |
| 某个设计的接口/参数契约、方案、验证 | `designs/<name>/{spec,design,verify}.md` |
| 组织章程：各组织角色的职责、边界、上报路径 | `team/README.md` |
| 常备授权（按能力 / 组织角色分组） | `keel/config.yaml` 的 `authorize:` |
| 能力镜像：某个能力的职责、交接、禁区与能力经验（跨 IP 通用） | `team/roles/kaiwu-<能力>/README.md` |
| PM 从镜像拉 team 的流程 | `team/pull-team.md` |
| 通用架构知识（独立知识库，不属于任何镜像或 IP） | `knowledge/` |

`CLAUDE.md` MUST 只作为上表的索引存在，MUST NOT 成为其中任何一类的权威出处。

#### Scenario: 同一条注意事项出现在两个文件里

- **WHEN** 某条读数口径既写在 `docs/data-credibility.md`，又被另一个文件完整复述
- **THEN** 该复述 MUST 被改成指向 `docs/data-credibility.md` 的引用
- **AND** 引用处 MAY 保留一句话概括，但 MUST NOT 保留完整的判据、数据表或结论推导

#### Scenario: 新增一类知识

- **WHEN** 出现一类在上表中没有归属的知识
- **THEN** MUST 先决定它的权威出处并写进上表，再写内容
- **AND** MUST NOT 因为「暂时不知道放哪」而落在 `CLAUDE.md` 或任意一个就近的文件里

#### Scenario: 角色分工从 toolchain 迁进镜像

- **WHEN** 某条角色分工或协作规则原来写在 `docs/toolchain/*.md`，按本表应归能力镜像
- **THEN** 它 MUST 迁进对应镜像，原位置只留一行指向镜像的引用

#### Scenario: 按节名引用 toolchain

- **WHEN** 某个文件写的是「`docs/toolchain.md`「某节」」，而这一节已在 `docs/toolchain/` 下的某个文件里
- **THEN** `docs/toolchain.md` 的索引 MUST 有这一节的标题，并写明它在哪个文件（内部#336：`METRIC_MODULES` 里的注释改一个字就换代，引用靠索引一跳到达）

### Requirement: 会完结的事项必须记在 issue，不得只记在仓库文档里

待办、已知缺陷、待决问题 —— 任何**有完成状态**的事项 —— MUST 记在 GitHub issue 里。
仓库内的 Markdown 文档 MUST NOT 作为这类事项的唯一记录处。

理由是仓库文档没有状态机、没有所有权、没有讨论线。事项做完之后需要有人回来手工
划掉，而这一步在实践中会被漏掉：被本变更取代的 `FOLLOWUP.md` 里，第 19 条在其
「遗留」部分实际完成之后仍描述着已经不成立的状态。

文档 MAY 在说明某个限制时引用 issue 编号，此时该引用 MUST 指向 issue，
MUST NOT 在文档内重述该事项的完整待办内容。

#### Scenario: 发现一个新的流程缺陷

- **WHEN** 发现一个需要修但暂时不修的流程缺陷
- **THEN** MUST 建 issue 记录现象、后果、暂缓理由与恢复条件
- **AND** 若该缺陷同时使某批已有记录不可用，那部分 MUST 另行写入 `docs/data-credibility.md`

#### Scenario: 事项完成

- **WHEN** 一个 issue 描述的事项完成
- **THEN** 关闭该 issue 即为该事项的终态，MUST NOT 需要另外去某个文档里划掉一行

### Requirement: 永久口径不得只记在 issue 里

不随时间完结的知识 —— 「哪一批记录为什么不能这样读」「某个默认值为什么有意保持次优」
「某个参数的数字为什么不能跨位宽比较」—— MUST 记在仓库文档里，
MUST NOT 以 issue 作为其唯一记录处。

理由与上一条对称：issue 的终态是关闭，而关闭会让这类知识从读者的视野里消失。
它们没有完成条件，不该进入一个以完成为终点的容器。

当一条事实**既有可执行的修法、又使某批记录永久带上读法限制**时，
这两半 MUST 分开记：修法进 issue，读法限制进 `docs/data-credibility.md`，
且 issue MUST 声明其关闭不影响该读法限制继续成立。

#### Scenario: 一条缺陷同时有修法和永久后果

- **WHEN** 某个流程缺陷已被修复，但修复之前产生的记录永久不可与修复之后的记录横向比较
- **THEN** 修法与修复动作记在 issue，issue 可以关闭
- **AND** 「这批记录不可横向比较」MUST 留在 `docs/data-credibility.md`，不随 issue 关闭而移除

#### Scenario: 试图用 issue 承载读数口径

- **WHEN** 一条读数口径被提议记成一个长期开着、永不关闭的 issue
- **THEN** MUST 改为写入 `docs/data-credibility.md`
- **AND** MAY 保留一个 issue 仅用于追踪与之相关的可执行动作

### Requirement: 已归档的变更不得回写

`openspec/changes/archive/` 下任何已归档变更的正文 MUST NOT 因仓库其他部分的
后续变动而被修改，包括其中已失效的文件路径引用。归档记录的是**当时的事实**，
回写会让归档的叙述与产生它的那次 commit 不符，从而毁掉它作为历史证据的价值。

当归档正文中的引用目标被移动或删除时，MUST 在归档目录（`openspec/changes/archive/`）下的 README
中提供从旧目标到新位置的对照，使该引用保持**一跳可达**。

#### Scenario: 归档引用的文件被删除

- **WHEN** 一个被多份归档变更引用的仓库文件被删除或拆解
- **THEN** 归档正文中的引用 MUST 逐字保持原样
- **AND** 归档目录下的 README MUST 说明该文件的去向，并指向承载其内容的新位置

#### Scenario: 读者顺着归档里的失效链接查找

- **WHEN** 读者在归档正文中读到一个指向已不存在文件的引用
- **THEN** 该文件的去向 MUST 能在归档目录下的 README 中找到
- **AND** MUST NOT 需要读者翻 git 历史才能定位其内容
