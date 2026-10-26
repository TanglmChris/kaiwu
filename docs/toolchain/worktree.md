# 工具链：并行开发：一个模块一个 worktree（建 / 跑 / 合并）

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

## 并行开发：一个模块一个 worktree

几个模块同时开发时，**一个模块一个 git worktree、一个会话，main 只用来合并**
（内部#69）。挤在同一个 checkout 里不行：脏树守卫是全局的，一个会话没提交的 RTL
会拦下所有设计的实验；git index 共用，`git add` 会带走别人的半成品；keel 只认
一个写者。契约在 `openspec/specs/parallel-worktree/spec.md`。

### 建

```bash
scripts/new_worktree.sh <名字>     # → .claude/worktrees/<名字>，分支 worktree-<名字>，基于本地 main
scripts/new_worktree.sh --base origin/worktree-<设计> <名字>   # 新分支从指定提交起（验证 worktree 用，见 `docs/toolchain/collaboration.md`）
scripts/new_worktree.sh --detach <提交> <名字>   # 一次性：分离 HEAD、不建分支（评审、外部 agent、按提交跑 fast_check，内部#229），用完 git worktree remove
.venv/bin/python3 scripts/review_prep.py --rev <所评提交> --top <顶层> --prev <上一轮>   # 评审开工：fast_check、无豁免 lint、豁免增减、文档版本，出「所评版本」表，不留检出（内部#196）
cd .claude/worktrees/<名字>
source ~/tools/env.sh              # 本机没装 direnv，每个新 shell 都要自己来
```

⚠️ **Claude Code 用 worktree 功能切进 worktree 之后，会话的隔离检查会拒绝
`source ~/tools/env.sh`**：它看不出被 source 的脚本里会不会跑 git，就整条拒掉
（2026-09-28 实测）。这时直接把两个工具目录加进 PATH，和 `env.sh` 做的是同一件事：

```bash
export PATH="$HOME/tools/oss-cad-suite/bin:$HOME/tools/OpenSTA-src/build:$PATH"
```

同一个检查也会拒绝过长的复合命令和嵌着长脚本的 heredoc：拆成几条简单命令，
或者把脚本先写成文件再执行。

脚本软链主仓的 `.venv`，最后检查主工作区和新 worktree 都干净，不干净就列出条目、
以非零退出。**Claude Code 的 worktree 功能**建在同一个位置、同一个命名，可以混用：

- 它建的 worktree 没有 `.venv`。对它再跑一次 `scripts/new_worktree.sh <名字>`，
  脚本是幂等的，只补软链。
- 它默认从 **`origin/main`** 起分支（`worktree.baseRef: fresh`），不是本地 main。
  本地 main 有没 push 的提交时，它建出来的 worktree 会落后：要么先 push，要么用脚本建。

两个会把工作区弄脏、从而让脏树守卫拦下**全部**实验的坑已经由 `.gitignore` 堵上
（`.claude/worktrees/`，以及不带斜杠的 `.venv` —— `.venv/` 不匹配软链）。
**基点早于这条规则的分支**，它自己 checkout 的 `.gitignore` 还是旧的，软链之后
仍会显示 `?? .venv`；rebase 到新 main 就消失。

### 跑

- 记录按设计根分文件 `results/<设计根>/experiments.jsonl`（内部#422，读写都经 `flow/records.py`）。
  只有 `flow/record_branches.yaml` 白名单里的分支（main、各 PM 集成分支、report 分支）自己的提交可以
  新增记录行、改 `REPORT.*.md`；集成分支就是本 team 的 main，正式扫参与报告在那里产生，合 main 只做汇聚。
- 其余分支上可以跑实验做开发验证，记录写进该 worktree 的记录文件，**留在工作区、不提交**；`REPORT.*.md` 同理。
- `fast_check` 有四项（`flow/check/fc_record_branches.py`）：**记录与报告的来源**（非白名单分支上不得有
  main 与白名单分支都没有的记录行；自己的提交不得改报告，唯一例外是删除一份**在 `HEAD` 上已没有对应顶层**
  的 `REPORT.<顶层>.md`，放行并逐个列出，内部#81）；**记录历史行原样保留**（merge-base 与每个父提交上的记录行
  逐字节、保序留在 HEAD，合并解冲突丢行改行就失败，红线 2）；**记录的 git_commit 可达 HEAD**（集成分支只许
  merge 或快进进 main，rebase / squash 会断 provenance）；**旧单文件已搬迁**（HEAD 上留着
  `results/experiments.jsonl` 就失败，跑 `python -m flow.records migrate`）。
- **CPU 预算**（内部#359，用户 2026-10-19：「mac 动不动就卡……总要留点空闲空间」）：本机 10 核 / 16 GB，要给用户
  留出余量。`sweep -j 8` 实测有效并行只有 4.2×（`docs/data-credibility.md` 的 D-20 一节），满开只会互相抢；
  10-19 实测几个会话同时跑全量 pytest / iodeps，1 分钟负载到 94、swap 用到 3.5 GB。
  - **单个任务默认并发 4**：fast_check 的 elaborate、merge_check 与 review_prep 里的 pytest / 线程池都从
    `flow/budget.py jobs` 取（`KAIWU_JOBS` 可调，钳在 1..核数），不再按核数满开；手跑 pytest 用 `-n 4`，不用 `-n auto`。
  - **全机重活合计 ≤ 6**：各会话同时运行的 `JOBS`、等价证明 `-j`、pytest `-n` 加起来。
  - **fast_check 同一份内容只检查一次**（内部#382）：工作区干净（含设计根下没有被忽略的散落文件）、没设 `FAST_CHECK_ALLOW_MISSING_TOOLS` 时，按 HEAD 树、相对本地 `main` 的 merge-base、参数、iverilog / verilator 与 Python 环境记下通过的结果（`$(git rev-parse --git-common-dir)/kaiwu-fast-check/`，所有 worktree 共用）；同一组输入再跑打印「复用」与当时的覆盖摘要，不跑其余检查。例外是「记录与报告」几项：它们看分支名与提交历史，缓存键盖不住，命中时照样实跑、失败就拦（内部#432）。只记通过的，`--no-cache`（或 `FAST_CHECK_NO_CACHE=1`）强制重跑。pre-push 快进到别人验过的提交时就走这条。
  - **fast_check 开跑前等负载**（内部#382）：1 分钟负载 > 核数（`KAIWU_MAX_LOAD`）时每 30 秒打印「等负载」，最多等 10 分钟（`KAIWU_FASTCHECK_WAIT_MIN`）后照跑；不拿 `cpu-heavy`。在大活里（`KAIWU_HEAVY_HELD=1`，如 merge_check）或 `FAST_CHECK_NO_LOAD_WAIT=1` 时不等。
  - **大活排队**（本仓所有 worktree 之间；租约在 git 公共目录，别的仓的重活不经这把锁，靠下面的巡检点名，内部#375）：`make regress / sweep / iodeps`、`scripts/merge_check.py`（全量模式；只改文档的轻量模式不拿锁，只等负载，内部#440）、`scripts/review_prep.py` 开跑前经
    `flow/budget.py` 等 1 分钟负载 ≤ 核数（`KAIWU_MAX_LOAD`）、内存压力正常（`kern.memorystatus_vm_pressure_level` 为 1；`KAIWU_MAX_MEM_PRESSURE`），再拿 keel
    共享租约 `cpu-heavy`（`--for 3h`，跑的期间每 30 分钟续一次，`KAIWU_RENEW_MIN` 可调；续租失败只告警、命令照常跑完），跑完释放。被占时每 30 秒重试、打印持有者，等满 60 分钟（`KAIWU_WAIT_MIN`）
    退出 3。别的大活手工包一层：`.venv/bin/python3 flow/budget.py run --heavy <名字> -- <命令…>`；
    谁占着看 `keel lock list`。外层已持有时（`KAIWU_HEAVY_HELD=1`）里层不再拿。
  - **全机 CPU 由 kaiwu-flow 兼管**（用户 2026-10-19 定，内部#359）：跨所有仓，不只 kaiwu。权限只到点名，请对方自己停或降并发，不 kill、不暂停、不降别人进程的优先级。`.venv/bin/python3 flow/cpu_watch.py` 打印此刻谁在占（沿父进程链归到工作区根下的仓或 worktree——工作区根是本仓 git 公共目录的上两级，不写死目录名，`KAIWU_WATCH_ROOT` 可覆盖；kaiwu 的 worktree 换成 keel chat 角色名；merge_check 的临时检出归到启动它的会话）。主机定时任务（`flow/cpu_watch_agent.sh install <群>`，launchd 每 5 分钟）在 1 分钟负载连续两次超过核数时，在安装时指定的 keel chat 群里点名合计一个核以上的前 5 家，同一家 30 分钟内不重复。
- **CPU 分配写进项目计划**（G8，内部#157）：每个会话占几路写在项目计划 issue 里，外部 agent 起的进程也算在调用方名下；
  冷启动时的读入集合探测（conftest 预热、`source_files`，大设计一次几十组 elaborate）很重，先单独预热一次，再开并行。
- `.venv` 是共享的：在任何一个 worktree 里 `uv pip install` 都会影响所有 worktree。
  依赖只在 main 上改（`requirements.txt` 随代码走）。

### 合并

1. 在 worktree 里跑 `./scripts/fast_check.sh`，绿了再合。**这一步是约定**：本地
   `git merge` 不触发 pre-push，所以提交了记录的分支直接在 main 上合并时没有东西拦。
2. 在主仓 `git merge worktree-<名字>`。lint 豁免放在各设计根自己的 `waivers.vlt`（与
   `params.yaml` 同级，内部#109），`flow/lint/waivers.vlt` 只留通用条目，所以合并时一般不冲突；
   fast_check 会把指向已删文件或信号的过时豁免报出来。
3. 在 main 上跑这个设计的正式记录（`make … sweep` / `exp`），先提交再跑（红线 3），
   然后 `make report` 刷新 REPORT。
4. 删 worktree 和分支：`git worktree remove .claude/worktrees/<名字>`、
   `git branch -d worktree-<名字>`。里面的 `.venv` 软链被忽略，remove 会一起清掉，
   **不会**顺着软链删主仓的 `.venv`（2026-09-27 玩具仓实测）。

**换代的工作不能和别的并行**：改测量口径会改所有设计的指纹。它合入 main 之后，
其他分支 rebase 到新 main 再继续，分支上之前跑的开发记录作废。
