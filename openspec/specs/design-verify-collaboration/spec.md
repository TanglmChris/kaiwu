# design-verify-collaboration Specification

## Purpose
同一个设计的设计与验证分属两条分支、两个工作区时，验证怎样取得设计的版本、每轮验证怎样冻结输入并说清两侧的来源、什么样的结果才算通过，以及发布、同步、交付、集成四步的约定（内部#79、内部#80）。

## Requirements

### Requirement: 验证按提交取设计版本

`flow/verify/freeze.py` MUST 能按一个 git 提交（`--design-ref`）取设计侧的 `designs/` 与 `cbb/`，内容 MUST 来自 git 对象库，MUST NOT 读任何工作区。按工作区路径取设计（`--design-worktree`）SHALL 只作开发运行：该轮的 `manifest.json` MUST 标 `deliverable: false`，并在 `not_deliverable_because` 里写明原因。

`--design-ref` 解析不到提交时 MUST 失败，并提示先在设计侧推送、在本侧 fetch。

理由：按路径取到的可能是设计侧没提交的 RTL，测出的结果指不回任何一个版本；验证结果要能被设计方与集成方在同一个提交上复查（内部#80）。

#### Scenario: 设计侧工作区有未提交的改动

- **WHEN** 设计分支的工作区里 RTL 有未提交的改动，验证按该分支的提交冻结
- **THEN** 冻结树里的 RTL SHALL 与该提交的内容逐字节相同，不含未提交的改动

#### Scenario: 按工作区路径取设计

- **WHEN** 用 `--design-worktree <路径>` 冻结
- **THEN** `manifest.json` 的 `deliverable` MUST 为 false，`not_deliverable_because` MUST 提到设计侧取自工作区

### Requirement: 每轮验证冻结输入并记录两侧出处

`freeze()` MUST 把一轮验证要读的输入复制到本轮输出目录下的 `tree/`（按仓库布局），并把整棵树设为只读。冻结之后，设计侧或验证侧工作区的任何改动 MUST NOT 改变这一轮读到的内容。

`tree/` 的组成：
- `designs/` 与 `cbb/` 取自设计侧；
- 被测设计根下的 `tb/` 与 `verify.<顶层>.md` 取自验证侧（本工作区或 `--tb-ref` 给的提交）；
- `params.yaml` 取自设计侧，但各顶层的 `sim:` 段取自验证侧；
- 给了叠加时，叠加的路径取自叠加的来源（见「冻结时可以把设计树的某个路径换成另一个来源」）。

`manifest.json` MUST 记录：
- 设计侧、验证侧、流程侧各自的来源（提交，或工作区路径加 `HEAD` 与是否有未提交改动）；
- 被测顶层与设计根；
- `tree/` 内每个文件的 sha256 及它来自哪一侧（叠加进来的记为 `overlay`）；
- 每个叠加的路径与出处；
- `deliverable` 与 `not_deliverable_because`。

`deliverable` 为真，当且仅当设计与 TB 都来自提交、没有来自本地文件的叠加，且流程侧没有未提交的改动。

要冻结的设计根或它的 `deps` 依赖在设计提交里不存在时，`freeze()` MUST 失败，MUST NOT 产出一棵缺文件的树。

#### Scenario: 冻结之后设计侧又改了 RTL

- **WHEN** 冻结完成之后，设计侧工作区的某个 RTL 文件被改写
- **THEN** `tree/` 里对应文件的 sha256 SHALL 与 `manifest.json` 记录的相同，`tree/` 里的文件 SHALL 不可写

#### Scenario: 两侧都来自提交

- **WHEN** 用 `--design-ref` 与 `--tb-ref` 冻结，流程侧工作区干净
- **THEN** `manifest.json` 的 `deliverable` SHALL 为 true，并记录两个提交的完整哈希

#### Scenario: TB 有未提交的改动

- **WHEN** TB 取自本工作区，且 `tb/` 下有未提交的改动
- **THEN** `deliverable` MUST 为 false，`not_deliverable_because` MUST 提到 TB 有未提交的改动

#### Scenario: 依赖缺失

- **WHEN** 设计提交里的 `params.yaml` 声明了一个 `deps` 构件，而该提交里没有这个构件
- **THEN** `freeze()` MUST 失败并指出缺的构件

### Requirement: 空用例、跳过与缺失的结果不算通过

`flow/verify/judge.py` 判定一组 JUnit 结果时，以下任何一种 MUST 判为不通过，并逐条给出原因：结果文件不存在；没有任何 `testcase`；任何 `testcase` 带 `skipped`、`failure` 或 `error`。

理由：「零个用例全部通过」与「跳过了失败的那条」都会让一轮验证看起来是绿的（内部#80 验收）。

#### Scenario: 结果文件里没有用例

- **WHEN** JUnit 文件存在但没有任何 `testcase`
- **THEN** 判定 MUST 为不通过，原因 MUST 说明没有用例

#### Scenario: 有一条被跳过

- **WHEN** 其余用例都通过，但有一条 `testcase` 带 `skipped`
- **THEN** 判定 MUST 为不通过，原因 MUST 列出这条用例

### Requirement: 发布、同步、交付与集成的约定写在仓库文档里

验证能力的镜像 `team/roles/kaiwu-verify/README.md` 的「发布 → 验证 → 交付 → 集成 → 出口」一节 MUST 写明以下四步，每一步都要说清谁做、在哪条分支、留下什么可复查的痕迹：

1. 设计发布：设计方把提交推到设计分支，并单开一个发布 issue（标题带顶层名与发布序号），写明提交号与要点；主线 issue 的索引关联它。
2. 验证同步：验证分支 merge 设计已发布的提交，或用 `--design-ref` 直接测，不必先 merge。
3. 验证交付：验证方把提交推到验证分支，并在发布 issue 里回一条交付小结，写明设计提交、TB 提交与 `deliverable`。
4. 集成：验证方把两条分支合进该 IP 的集成分支，先设计、后验证（用户 2026-10-05 定，内部#213），合完交 PM 推集成分支；没设集成分支的 IP 在 main checkout 本地合、交 kaiwu-chief 推 main（用户 2026-10-20 定）。

各方 MUST 只在自己的分支提交。`docs/toolchain.md` 原来的「设计与验证分属两个 worktree」一节 MUST 只留指向镜像的引用（kaiwu-org-model，内部#305）。

#### Scenario: 新会话接手验证

- **WHEN** 一个没有任何会话记忆的验证会话读 `team/roles/kaiwu-verify/README.md`、主线 issue 的索引与发布 issue
- **THEN** 它 SHALL 能确定要测的设计提交、冻结与运行的命令，以及交付时要写的内容

### Requirement: 冻结时可以把设计树的某个路径换成另一个来源

`freeze()` SHALL 接受若干叠加，每个叠加把冻结树里设计树下的一个路径换成另一个来源，按给出顺序生效：

- 来自提交（`--overlay <ref>:<路径>`）：内容 MUST 取自该提交的 git 对象。来自提交的叠加 MUST NOT 让 `deliverable` 变成 false。
- 来自本地文件或目录（`--overlay-local <源>:<路径>`）：该轮的 `deliverable` MUST 为 false，`not_deliverable_because` MUST 写明叠加的源与路径。

叠加的路径 MUST 在 `designs/` 或 `cbb/` 之下，MUST NOT 落在被测设计根的 `tb/` 或 `verify.*.md` 上（那是验证侧的输入）；违反时 `freeze()` MUST 失败，MUST NOT 留下输出目录。来自提交的叠加，在该提交里找不到这个路径时 MUST 失败。`manifest.json` MUST 记下每个叠加的路径与出处（提交的完整哈希或本地源路径），叠进来的文件 `side` MUST 记为 `overlay`。

理由：组合被测（设计提交加另一个提交的 `cbb/`）和 RTL 变异体做失败臂，以前都要手拼临时提交（内部#341）。

#### Scenario: 设计提交加另一个提交的 cbb

- **WHEN** `--design-ref A --overlay B:cbb/cbb_bar`
- **THEN** 冻结树里 `cbb/cbb_bar` 是 B 的内容，其余是 A 的，`deliverable` 不因叠加变成 false，manifest 记下 B 的完整哈希

#### Scenario: 本地变异体

- **WHEN** `--overlay-local /tmp/mut.v:designs/foo/rtl/foo.v`
- **THEN** 冻结树里 `foo.v` 是变异体，`deliverable` 为 false，原因写明 `/tmp/mut.v`

#### Scenario: 叠到 TB 上

- **WHEN** 叠加路径是被测设计根的 `tb/`
- **THEN** `freeze()` 失败，不留输出目录

### Requirement: 给应用的补丁一步交付并自证可还原

仓库 MUST 提供 `scripts/patch_deliver.py --base <提交> --head <提交> --out <目录>`：导出 `base..head` 的补丁，在 base 的临时检出上逐个应用，比应用结果与 head 的树哈希，跑完删掉临时检出。

- 两个树哈希不一致、补丁应用失败、或检出里留下 `.orig` / `.rej` 时，MUST 以非 0 退出。
- `<out>` 里 MUST 留下补丁文件与一份交付说明：base、head、两个树哈希、每个补丁的 sha256。
- `<out>` 已存在时 MUST 拒绝，不覆盖旧的交付。

理由：内部#282 的补丁是手工导出、手工 `git am`、手工比树哈希的，漏一步就不知道应用拿到的是不是我们测的那一版（内部#340）。

#### Scenario: 补丁能在干净基线上还原

- **WHEN** head 是 base 之后的两个 RTL 修复提交
- **THEN** 脚本退出 0，交付说明里两个树哈希相同，列出两个补丁

#### Scenario: 补丁还原不出 head

- **WHEN** base..head 里有一个合并提交，合并时另改了内容（`format-patch` 不导出合并本身，这部分改动不在任何补丁里）
- **THEN** 脚本以非 0 退出，并打印两个树哈希
