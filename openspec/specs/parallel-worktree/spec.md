# parallel-worktree Specification

## Purpose
规定多模块并行开发（一个模块一个 git worktree、一个会话，main 只用来合并）时的工作区契约。

它存在的理由是：并行开发最容易出的错不是「跑不起来」，而是「跑起来了但出处断了」。
worktree 带进来的一个未跟踪条目会让脏树守卫拦下全部实验；分支上提交的记录在 rebase
或 squash 合入之后，`git_commit` 指向一个 main 历史里没有的提交。两件都不报错。

三条要求各管一段：worktree 不得弄脏任何工作区；正式记录只在白名单分支（main、各 PM 集成分支、report 分支）上
提交；秒级护栏机械检查后者，并把 provenance 与合并丢行两条风险各做成一项检查（2026-10-25 起，内部#422）。流程与约定见 `docs/toolchain.md` 的「并行开发：一个模块一个 worktree」。

## Requirements

### Requirement: 建立或使用 worktree 不得让任何工作区变脏

为并行开发建立的 git worktree，以及它为了能跑流程而引入的东西（例如共享的 Python 环境），MUST NOT 让主工作区或该 worktree 自己的 `git status --porcelain` 出现条目。

理由：`scripts/run_experiment.py` 的脏树守卫把 `git status --porcelain` 的任何条目（本次追加的那个 `results/<设计根>/experiments.jsonl` 除外）都当成未提交的代码，直接拒绝写记录（红线 3、P-7）。worktree 带进来的一个未跟踪条目，在守卫看来和一份没提交的 RTL 没有区别。结果是：放在主工作区里的 worktree 会拦下 **main 上所有设计**的实验；worktree 自己的软链会拦下**它自己**的实验。2026-09-27 这两件都实测复现过（内部#69）。

#### Scenario: 在 Claude Code 的默认位置建立 worktree

- **WHEN** 在主工作区下的 `.claude/worktrees/<名字>` 建立一个 worktree
- **THEN** 主工作区的 `git status --porcelain` MUST 为空（假设建立之前也为空）

#### Scenario: worktree 通过软链共享主仓的 Python 环境

- **WHEN** worktree 里的 `.venv` 是指向主仓 `.venv` 的软链
- **THEN** 该 worktree 的 `git status --porcelain` MUST 为空（假设它的已跟踪文件没有改动）

#### Scenario: 用仓库提供的脚本建立 worktree

- **WHEN** 用 `scripts/new_worktree.sh <名字>` 建立 worktree
- **THEN** 脚本 MUST 在退出前检查主工作区与新 worktree 的 `git status --porcelain`，任一非空时以非零退出并列出条目

### Requirement: 正式实验记录只在白名单分支上提交

记录文件（`results/*/experiments.jsonl`）的新增记录，以及由记录生成的 `REPORT.*.md`，MUST 只在**记录分支白名单**里的分支上提交。白名单在仓库配置文件 `flow/record_branches.yaml` 里声明，成员是：main、各 PM 集成分支（例如 `cbb_open`；名单以白名单文件为准）、各 report 会话的分支（用户 2026-10-25 定，内部#422）。每个 PM 集成分支就是这个 team 的 main：正式扫参与 REPORT 在集成分支上产生，合 main 只做汇聚，不在 main 上重跑。

其他分支 MAY 为了验证而运行实验，但这些记录和报告的改动 MUST NOT 随这些分支自己的提交提交。从白名单分支同步进来的记录（例如组员把集成分支合进自己的分支）不算这些分支自己的提交。

原来只许 main 的两条理由，换成下面两条答法：
- **provenance**：合并只用 merge 或快进，由「已提交记录的 `git_commit` 必须是 HEAD 的祖先」机械检查（`experiment-record`），rebase 或 squash 当场失败。
- **合并**：记录按设计根分文件（`experiment-record`），一个设计根只归一个 team，跨 team 合并不再碰同一个文件；同一文件被两边追加时，下一条要求的历史行检查保证合并没有丢行或改行。

这条要求不改变记录 schema，也不改变 `run_experiment.py`。

#### Scenario: 分支上跑实验做开发验证

- **WHEN** 在不在白名单里的分支的 worktree 里运行 `make -f flow/Makefile exp`
- **THEN** 记录写进该 worktree 的 `results/<设计根>/experiments.jsonl`，作为未提交改动留在工作区
- **AND** 脏树守卫不因这一改动拒绝后续实验

#### Scenario: 集成分支上产生正式记录

- **WHEN** report 会话在白名单里的分支上跑正式扫参并提交记录与 `make report` 刷新的报告，PM 再把它 merge 进集成分支
- **THEN** 两个分支上的 `fast_check.sh` SHALL 都通过

#### Scenario: 分支合入之后

- **WHEN** 集成分支用 merge 或快进合进 main
- **THEN** main 上 SHALL 不再重跑这些设计的正式记录

### Requirement: 秒级护栏必须机械检查记录与报告的来源

`scripts/fast_check.sh` MUST 做两项检查，两项都 MUST 在覆盖摘要里出现：

1. **来源**：当前分支不在白名单里时，下面两条都 MUST 成立，否则失败并列出违规项。当前分支在白名单里时，这一项 SHALL 以通过计，并在摘要里注明「当前分支在白名单里」。
   - **记录行**：`HEAD` 上记录文件（含 `results/experiments.jsonl`）里的每一行，MUST 已经出现在 main 或某个白名单分支（本地的 `refs/heads/<名>` 与 `refs/remotes/origin/<名>`，存在哪个算哪个）那里的记录文件里。按内容判定而不是按提交判定：只搬动、不新增行的改动（`experiment-record` 的历史搬迁）不产生新记录，两条理由都不沾，放行；从集成分支合进来的记录行在白名单分支里，也放行。失败时列出新行所在的文件与行数。
   - **报告**：`HEAD` 上那些不属于 main 或任何白名单分支的提交，MUST NOT 改动 `designs/*/REPORT.*.md`、`cbb/*/REPORT.*.md`。失败时列出提交与文件。
2. **历史行**：对 `git merge-base HEAD main` 以及 `HEAD` 的每个父提交，那里的每个记录文件里的行 MUST 逐字节、按原相对顺序出现在 `HEAD` 上同一路径的文件里；记录文件 MUST NOT 被删除。唯一的例外是 `results/experiments.jsonl` 的搬迁：它可以消失，但它的每一行 MUST 逐字节出现在 `HEAD` 上某个设计根的记录文件里。这一项在所有分支上都跑，包括 main。

报告检查唯一的例外是**没有对应顶层的报告的删除**：一份 `<根>/REPORT.<顶层>.md` 被删除，且在 `HEAD` 上 `<根>/params.yaml` 不存在、或其 `tops:` 里没有 `<顶层>` 时，这一处改动 SHALL 不算违规；放行的文件 MUST 逐个列在输出里，MUST NOT 静默忽略。报告改名按「删旧 + 增新」判断，新路径照样算改动。

两项都只检查**已提交**的改动：非白名单分支上的开发运行会让记录文件在工作区里带着未提交的改动，这是允许的。

无法确定 merge-base（没有 `main` 这个 ref、不在 git 仓库里）、读不到白名单文件时 MUST 失败，不得当作通过或静默跳过。

理由：上一条如果只靠约定，「忘了」不会有任何东西失败，而后果（悬空的 `git_commit`、合并丢行）正是本仓最怕的「跑通了但数字不可信」。`fast_check` 是每个 worktree 的内循环，也挂在 pre-push 上，拦在这里代价最小。删除一份已没有顶层的报告不产生记录，不放行的话，删设计根的分支只能把报告留在仓里（内部#81）。

#### Scenario: 分支提交了新记录

- **WHEN** 当前分支不在白名单里，且它自己的某个提交改动了 `results/<设计根>/experiments.jsonl`
- **THEN** `fast_check.sh` MUST 以非零退出，并列出该提交与文件

#### Scenario: 非白名单分支合进了集成分支

- **WHEN** 当前分支不在白名单里，它把 `origin/cbb_open`（带着新记录与报告）合了进来，自己的提交没有碰记录与报告
- **THEN** 来源检查 SHALL 通过

#### Scenario: 分支提交了报告

- **WHEN** 当前分支不在白名单里，且它自己的某个提交改动了 `cbb/<根>/REPORT.<顶层>.md`
- **THEN** `fast_check.sh` MUST 以非零退出，并列出该文件

#### Scenario: 报告随设计根或顶层一起删除

- **WHEN** 当前分支不在白名单里，它自己的某个提交删除了 `<根>/REPORT.<顶层>.md`，且 `HEAD` 上该设计根已不存在、或其 `params.yaml` 的 `tops:` 里已没有 `<顶层>`
- **THEN** 来源检查 SHALL 通过，输出 MUST 列出放行的文件

#### Scenario: 顶层仍在却删了它的报告

- **WHEN** 当前分支不在白名单里，它自己的某个提交删除了 `<根>/REPORT.<顶层>.md`，而 `HEAD` 上 `<根>/params.yaml` 的 `tops:` 里仍有 `<顶层>`
- **THEN** `fast_check.sh` MUST 以非零退出，并列出该文件

#### Scenario: 分支上只有未提交的开发记录

- **WHEN** 当前分支不在白名单里，记录文件有未提交的改动，但分支自己的提交没有改动它
- **THEN** 来源检查 SHALL 通过

#### Scenario: 在 main 上运行

- **WHEN** 当前分支是 main 或白名单里的其他分支
- **THEN** 来源检查 SHALL 通过，覆盖摘要 MUST 注明当前分支在白名单里

#### Scenario: 非白名单分支上的历史搬迁

- **WHEN** 当前分支不在白名单里，它的提交把 `results/experiments.jsonl` 搬进各设计根文件并删除原文件，没有新增任何一行
- **THEN** 来源检查 SHALL 通过，历史行检查 SHALL 通过

#### Scenario: 合并丢了一行历史记录

- **WHEN** 一次合并解冲突时删掉或改动了 `results/<设计根>/experiments.jsonl` 里父提交已有的一行
- **THEN** 历史行检查 MUST 以非零退出，并列出文件与丢失的行数

#### Scenario: 找不到 main

- **WHEN** 仓库里没有名为 `main` 的分支，或当前目录不在 git 仓库里
- **THEN** 这两项检查 MUST 失败，输出 MUST 说明无法确定 merge-base 的原因

### Requirement: 脏树守卫只拦与测量有关的路径

写实验记录前的脏树守卫 MUST 拒绝工作区里任何未提交的条目，**以下路径除外**：以 `.claude/`、`.agents/`、
`docs/`、`knowledge/`、`openspec/` 开头的，以及正好是 `AGENTS.md`、`CLAUDE.md` 的。被豁免的条目 MUST
在输出里列出，MUST NOT 静默忽略。

豁免是黑名单：没列进来的路径一律当作可能影响测量，漏列只会多拦，不会少拦。

理由是项目本来就是多个会话并行（keel 维护、设计、流程），一个会话没提交的文档或协议刷新不该卡住
别处的实验（内部#67），而 RTL、TB、flow、参数这些只要脏着就必须拦（红线 3）。

#### Scenario: 另一个会话的 keel 升级没提交

- **WHEN** 工作区里只有 `AGENTS.md` 与 `.claude/skills/` 下的改动
- **THEN** 守卫 SHALL 放行，并列出被忽略的条目

#### Scenario: RTL 没提交

- **WHEN** 工作区里有 `designs/<根>/rtl/` 下的改动
- **THEN** 守卫 SHALL 拒绝写记录

### Requirement: 建 worktree 可以指定基线，分支或工作区不符时报错并保持原状

`scripts/new_worktree.sh` MUST 接受 `--base <ref>`，新分支从该 ref 建；不给时 SHALL 从本地 `main` 建。以下情况 MUST 以非零退出并说明原因，且 MUST NOT 新建、移动或重置任何分支，MUST NOT 改动任何工作区或暂存区：

- 分支 `worktree-<名字>` 已在另一个工作区检出：输出 MUST 给出那个工作区的路径，包括 `.claude/worktrees/` 之外的工作区。
- `.claude/worktrees/<名字>` 已存在，但检出的不是 `worktree-<名字>`。
- 给了 `--base`，而分支 `worktree-<名字>` 已经存在：已有分支不得被重置到新基线，也不得悄悄忽略 `--base`。
- `--base` 解析不到一个提交。

理由：设计与验证分属两条分支以后（内部#79、内部#80），两边的工作区都可能留着对方不知道的未提交成果；脚本自动「修正」分支或工作区，等于替其中一方丢掉成果。

#### Scenario: 从指定基线建验证分支

- **WHEN** 运行 `new_worktree.sh --base <设计分支的提交> v`，分支 `worktree-v` 还不存在
- **THEN** 新 worktree 的 `HEAD` SHALL 等于该提交，分支 SHALL 是 `worktree-v`

#### Scenario: 分支已被别的工作区检出

- **WHEN** 分支 `worktree-v` 已在某个工作区检出，且那个工作区不在 `.claude/worktrees/v`
- **THEN** 脚本 MUST 以非零退出，输出 MUST 含那个工作区的路径，所有分支与工作区 SHALL 保持原状

#### Scenario: 同名 worktree 检出的是别的分支

- **WHEN** `.claude/worktrees/v` 已存在，检出的是 `worktree-other`
- **THEN** 脚本 MUST 以非零退出并说明检出的是哪条分支，不补 `.venv`、不切换分支

#### Scenario: 已有分支又给了基线

- **WHEN** 分支 `worktree-v` 已存在，又给了 `--base`
- **THEN** 脚本 MUST 以非零退出，分支 SHALL 仍指向原来的提交

#### Scenario: 基线解析不到

- **WHEN** `--base` 给的名字不是任何提交
- **THEN** 脚本 MUST 以非零退出，SHALL 不新建任何分支或工作区
