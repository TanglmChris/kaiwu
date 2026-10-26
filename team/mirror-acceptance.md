# 镜像验收：干净实例

镜像结构建好或改动较大之后，要从仓外拉一个没有记忆的会话，验证它只凭 `team/` 和镜像也能把一件已知答案的活做对。
契约见 `openspec/specs/team-organization/spec.md`「镜像改动要经干净实例验收」；谁来做见 `team/README.md` 的组织角色表。
下面是 2026-10-20 第一次验收（kaiwu-org-model 3.1，内部#305）实际走通的做法。

## 1. 仓外克隆

Claude Code 的项目记忆按主仓路径共用，仓内任何 worktree 起的会话都会读到同一份。换一个仓外路径，记忆目录就不同。

```bash
D=/private/tmp/kaiwu-accept-<日期>
git clone -q <主仓路径> $D                       # 本地克隆，秒级
cd $D
git remote set-url origin <GitHub 地址>
git fetch -q origin main
git checkout -q -B main <镜像提交>              # 通常是 origin/main
ln -s <主仓路径>/.venv .venv                    # 与 scripts/new_worktree.sh 同做法，.venv 已 gitignore
git status --porcelain --untracked-files=all    # 必须为空
```

- 用本地克隆，不从 GitHub 克隆：仓库 `.git` 约 2.5 GB，从 GitHub 克隆 7 分钟只下了 21 MB。
- 克隆前先 `ls -d ~/.claude/projects/*accept*`，确认没有同名的旧记忆目录。

## 2. 先做记忆检查的对照

会话转录不存系统提示，grep 转录证明不了「没加载记忆」，要靠会话自报。为了让这个自报有会失败的一臂，先在主仓的某个 worktree 里起一个探针，问同一句话：

```bash
claude -p --permission-mode plan "不要调用任何工具。只如实回答：本会话上下文里加载了哪些 CLAUDE.md（列绝对路径）和哪些记忆（auto-memory 的 MEMORY.md 路径，以及其中前三条条目标题原文；没有就写「没有」）。"
```

探针必须报出共享的 `MEMORY.md` 和条目标题。报不出来，说明这句问话查不出记忆，先改问法。

## 3. 起验收实例

- 必须是全新会话：不 resume，不 fork，也不用 Agent 工具派子代理。子代理跑在发起方的路径下，提示也由发起方写，都不干净。
- 提示只写三样，不给做法上的提示：
  1. 开工前先报告加载了哪些 CLAUDE.md 和记忆；
  2. 任务：「按 `team/` 镜像做」，再写要做的活；
  3. 边界：不推送、不开或评论 issue、不发 keel chat 消息、不改被测设计的文件。

```bash
cd $D && claude -p --session-id <uuid> -n kaiwu-accept --permission-mode auto \
  --output-format stream-json --verbose "<提示>" > instance.jsonl
```

放后台跑。2026-10-20 那次（adder32：规格评审一轮 + 一个参数点 TRIAL=1）用了 41 轮、约 10 分钟。

## 4. 活与对照

被测是 adder32（开源设计），活要有已知答案，不改设计：

- **规格评审一轮**：
  - 清单里引的版本、SHA、R 号、行号与原文，用脚本到所评提交里逐条核对；
  - 再加一条必然为假的核对项（如一个不存在的 R 号）当失败臂；
  - 清单是转述而不是原文照搬的，在证据里写明差在哪、意思变没变。
- **一个参数点 `make exp TRIAL=1`**：
  - 对照取 main 上同参数、同指纹的正式记录。
  - 流程换代后常常没有这样的记录。那就在干净的 main 同一提交上，用同参数自己跑一次 TRIAL=1 当对照（用户 2026-10-20 定），不动 `results/`。
  - 两份记录逐个叶子字段比，只允许 `experiment_id` 与 `timestamp` 不同。
  - 失败臂：扰动一个 PPA 字段（如 `synth.area_um2` 乘 1.001）再比，必须报不同。

## 5. 证据与收尾

- 证据有三项，放进对应 change 的 `evidence/`：
  - 记忆：实例开头的自报原文、第 2 步探针的输出，再加两条事实：实例的记忆目录为空，实例输出流里共享记忆路径出现 0 次；
  - 实例的产物：清单原文、试跑记录；
  - 对照：比较脚本、它的输出、失败臂的输出。
- 提交和推送：
  - 提交前看 `git rev-parse --abbrev-ref HEAD`，结果不能是 `HEAD`；
  - 推完用 `git merge-base --is-ancestor <提交> origin/<分支>` 核提交确实在远端；
  - 2026-10-20 撞过一次：同一个 worktree 里另一个会话把 HEAD 切成了分离状态，推上去的是旧分支头。分支对分支比得到 `0 0`，查不出这个问题。
- 收尾：
  - 删掉仓外克隆和自己跑出的 `runs/`；
  - 确认实例进程已经退出。
