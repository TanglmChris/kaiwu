# 工具链：调用外部模型 CLI

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

## 调用外部模型 CLI（自己跑 / codex / dsh，由会话自选）

通用部分归 keel（5.92.0 起，keel#219）：委派边界、产出验收、数据外发检查、调用模板与通用的坑都由
`keel agents` 给出，本节只留本项目相关的部分。

- `keel agents`：列出本机的外部 agent，以及本项目是否允许；`keel agents codex` / `keel agents dsh`：
  命令模板、沙箱、数据发往哪里、带日期的坑。
- `keel agents brief <名字> --mode helper|implementation --dir <目录> --out <文件> --change <c> --task <t>`：
  从选中的 task 编译任务说明，并打印要跑的命令。keel 不启动进程，命令由会话自己跑。
- 本项目在 `keel/config.yaml` 的 `external_agents:` 里允许 codex 和 dsh。

**三种做法并列，由会话自己选**（用户 2026-10-05，内部#191）：一件活自己跑、交给 codex、还是交给 dsh，用哪个模型、
什么推理档位，都由干活的会话按活自己决定。本节只写能力、约束和验收要求，不规定哪类活必须交给谁。

| 做法 | 是什么 | 数据发往 | 沙箱 |
|---|---|---|---|
| 自己跑 | 本会话直接做 | — | 本会话的权限设置 |
| codex | OpenAI Codex CLI（`codex exec`，或 Claude Code 的 codex 插件 `codex:rescue` 等，包的是同一个 CLI） | OpenAI | 有（`-s`：评审 read-only，实现 workspace-write） |
| dsh | DeepSeek Harness（`dsh --profile headless`，命令模板见 `keel agents dsh`） | DeepSeek | **没有**，读写它启动目录下的一切 |

实测（2026-10-05，dsh 0.2.0-rc.2，`~/.local/bin/dsh` 已在 PATH 上）：`dsh --profile headless - < prompt` 在空目录里跑通，退出码 0；
不再报 MISSING_CREDENTIAL（密钥已在 app 里配好）。

**约束**（三种做法都一样，除非另注）：
- **数据外发**：codex 发往 OpenAI，dsh 发往 DeepSeek。交出去的范围两者相同：用户的凭据、密钥与不在本仓的
  资料不交；要用户拍板的取舍、跨会话 / 跨分支的协调、提交与推送、开关 issue 不交。
- **独立 worktree**：外部 agent 一律用自己的 worktree，不与任何会话共用分支或工作区。命名 `codex_<任务>` /
  `dsh_<任务>`，用 `scripts/new_worktree.sh --base <提交> <名字>` 建。dsh 没有沙箱，**即使只做评审也要**。
- **验收**：交回的结果由本会话复跑验收命令后才算证据；提交也由本会话做。
- **CPU 预算**：外部 agent 起的综合、仿真、回归进程照样占本机 CPU，计入「全机重活合计 ≤ 6」与各会话分到的
  路数（`docs/toolchain/worktree.md`「并行开发」一节）。任务说明里写明它最多开几路。

**统一流程**（G18，用户 2026-10-06 定；本阶段的问题：codex 额度用完要到 10-10 才恢复；dsh headless 越界写过 `/tmp`；9 个 `codex_*` worktree 留着未提交的改动）：

| 步 | 做什么 |
|---|---|
| 1. 选 | 自己跑 / codex / dsh，按活与额度选；codex 额度用完时用 dsh 或自己跑，不等 |
| 2. 说明 | `keel agents brief …` 编译任务说明；写明验收命令、最多开几路、PATH、只许写它 worktree |
| 3. worktree | `scripts/new_worktree.sh --base <提交> codex_<任务>` / `dsh_<任务>`；dsh 即使只读也要 |
| 4. 验收 | 调用方复跑验收命令，结果才算证据；提交由调用方做 |
| 5. 记录 | 在相关 issue 里写：用了哪个 agent、哪个 worktree、验收命令与结论；评审写明哪些条目来自它 |
| 6. 收尾 | 它的 worktree 里不留未提交的改动（要么由调用方提交，要么丢弃）；结果记下后删 `runs/`；worktree 与分支按「常备授权」第 3 条处理 |

**每一轮评审都加外部评审**（规格、LLD、RTL，G18）：评审会话另起 codex 或 dsh，在只含被评提交的独立 worktree 里，按同一份评审模板和角度独立出清单；评审会话合并两份清单、逐条核实后再发，核不实的不发，每条标来源。模板见 `flow/templates/review/review_rN.md` 的「外部评审」一节。从 r9 与 R007 的 RTL 评审起执行。

**参考例子**（各会话 2026-10 的实际用法，不是规定）：
- 规格明确、能独立验收的实现块，比如能用 TB 输出签名证明逐拍等价的 RTL 重构（设计会话交过 MIX_ADDR_EXP 的
  lookahead、判断级前移）；
- 量大而机械的活：批量写用例、跑大矩阵；
- 第二视角的只读评审：验证计划、规格、改动（验证会话用它评审验证计划草稿）。

**本项目的约定**：
- 任务说明与它的输出放它 worktree 的 `runs/`（已被 gitignore）；验收脚本由调用方先备好，放在同一个 `runs/` 下。
- 它的 shell 不继承 `env.sh`：任务说明里写明每个 shell 先
  `export PATH="$HOME/tools/oss-cad-suite/bin:$HOME/tools/OpenSTA-src/build:$PATH"`。
- 书写约定指向 `docs/` 与模板，不靠会话记忆转述；验收命令写全：fast_check、regress、签名比对、级数上限等。
- 结果只记命令、提交、种子与汇总，不打包波形 / trace / 日志（内部#104 的教训）。
- 验收完、结果记下后就删它 worktree 的 `runs/`（下一节「磁盘使用」第 4 条）；worktree 和分支留不留另说。
- macOS 没有 `timeout`：放后台跑，自己盯着，给它限定时长和产物。
