# 命令手册与工作约定

从根 `CLAUDE.md` 搬来（2026-10-20，原文照搬，只改了标题层级）：根 `CLAUDE.md` 每个会话都整份加载，
这里放每次用到才查的命令全集、两个跳过开关的完整口径、路由与零差异任务的细则。根 `CLAUDE.md` 只留
最常用的几条命令和一句话提醒。

## 命令

```
keel context          # 现在该做什么（从 OpenSpec+Git 重算，扛 /clear 和 compaction）
keel --doctor         # 体检
keel openspec <args>  # openspec CLI 的唯一入口（裸 openspec 不在 PATH）
./scripts/fast_check.sh   # ~10 s：全参数组合 elaborate + lint（豁免见 flow/lint/waivers.vlt）+ Python 编译
scripts/new_worktree.sh [--base <ref>] <名字>   # 并行开发：建 .claude/worktrees/<名字>（分支 worktree-<名字>，默认基于 main），软链 .venv；分支上的记录不提交
.venv/bin/python3 flow/verify/freeze.py --top <顶层> --design-ref <设计提交> --out <目录>   # 功能验证：按提交冻结两侧输入、记出处（设计/验证分属两个 worktree 时）
.venv/bin/python3 -m pytest tests/ -q -n 4 -m 'not flow'      # 内循环：不跑真 EDA 工具的用例；不用 -n auto（内部#359）
.venv/bin/python3 -m pytest tests/ -q -n 4                    # 全量；全机大活，推 main 前用 merge_check（排队拿 cpu-heavy）

make -f flow/Makefile exp    DESIGN=CBB_FIFO PARAMS="DAT_W=32 FIFO_DEP_N=4 PT_EN=1 RST_EN=1"   # 参数给全；SCHEME 类参数取编号（params.yaml 的 labels）
make -f flow/Makefile exp    DESIGN=<顶层> POINT=<点名>           # 按 params.yaml 的 sweep_points 点名取全部参数（内部#332）；sweep 用 POINTS="a b"，depth 也认 POINT
make -f flow/Makefile sweep  DESIGN=CBB_FIFO JOBS=8                     # JOBS 默认 1（有意的，内部#57）
make -f flow/Makefile sweep  DESIGN=CBB_FIFO SKIP_EXISTING=1              # 续跑中断的同一轮扫参
make -f flow/Makefile sweep  DESIGN=CBB_FIFO SKIP_EXISTING_GENERATION=1   # 换代重跑的断点续跑
make -f flow/Makefile report DESIGN=CBB_FIFO   # 独立命令，绝不是实验的副作用
make -f flow/Makefile sta    DESIGN=CBB_FIFO RUN=<experiment_id>  # 只重跑 STA
make -f flow/Makefile depth  DESIGN=ADDER32 MODULE=PREFIX_ADDER PARAMS="…"     # 不写记录地量某个模块的逻辑级数（内部#111）
make -f flow/Makefile clean                   # 删 runs/，不碰记录与 REPORT.md

.venv/bin/python3 scripts/score.py --design CBB_FIFO          # 事后打分，不跑任何工具
.venv/bin/python3 scripts/gen_report.py --design CBB_FIFO --all-generations
.venv/bin/python3 scripts/pair_generations.py --list                 # 各代：条数、指纹里变了哪几项
.venv/bin/python3 flow/equiv/netlist_equiv.py -j 8                   # 本代每份网表 ≡ 它的 RTL（读 runs/，clean 之前跑）
.venv/bin/python3 flow/sim/gate_sim.py -j 8                          # 本代每份网表跑一遍 TB（门级仿真，读 runs/，clean 之前跑）
.venv/bin/python3 scripts/pair_generations.py --design CBB_FIFO --base previous --head latest   # 两代逐字段配对，零差异才退出 0；指纹按设计算（内部#146），按设计配
```

容易误用的开关：
- **两个跳过开关的匹配口径不同，不要混用。** 它们的输出长得一模一样（都是
  「跳过 N 条」），差别只在 N 按什么算出来，所以同时给两个会当场报错而不是择一。
  - `SKIP_EXISTING` 匹配 `(design, params, synth.sources_sha256)`，**不含流程版本**
    —— 任何一代、用同一份 RTL 跑过就算已有。用于**续跑中断的同一轮扫参**。
    同一组合在不同流程代下结果可能不同，跳过就漏掉重测，所以它默认关闭。
  - `SKIP_EXISTING_GENERATION` 匹配 `(design, params, flow.fingerprint,
    synth.sources_sha256)` —— 只有**本代**、同一份 RTL 跑过才算已有。用于**换代
    重跑**（改了 `METRIC_MODULES` 里的文件之后的全量重跑）被打断时接着补。在这个
    场景里 `SKIP_EXISTING` 开了等于一条都不补，因为要补的那些组合在上一代全都跑过。
  - 两者都按当前 RTL 的读入集合摘要匹配（开跑前现算），所以**改了 RTL 之后续跑
    是安全的**：改过的顶层不会被跳过。指纹不含 RTL、改 RTL 不换代，以前两个开关都
    会把最该重跑的那批跳过（2026-09-16 实撞，`docs/data-credibility.md` 的 D-14；
    2026-09-28 修，`guardrail-scope`）。2026-09-20 之前的记录没有这个字段，不算已有。
  - 两者都**只看记录在不在，不看 `sim.passed`**。每轮扫参的头尾各有一行覆盖摘要，
    写明本轮按哪种口径跳、跳了多少、实际跑了多少。
- **扫参维度必须给全**，缺一个就报错（守卫是有意的，见 P-6）。唯一的例外是
  `params.yaml` 里标了 `sweep: false` 的参数。

## 路由、零差异任务、设计内部改动

政策本身在 `AGENTS.md`「项目路由政策」（Claude 与 Codex 共读，内部#372），这里只放细则。

- **认不出来的 Full 要自己认**：`full_mode_paths:` 按路径认不全测量口径，往
  `flow/flow_fingerprint.py` 的 `METRIC_MODULES` 加文件时同步加进那张表，换合并
  liberty（不在仓内）也算。
- **零差异类任务**的写法：不硬套 red/green（内部#59），`Base:` 写旧一代记录所在的 git ref，`Fields:` 写比的字段，
  判据是 `scripts/pair_generations.py --design <顶层> --base <旧代> --head <新代>` 逐设计退出 0；它的输出
  存进 change 目录（如 `openspec/changes/<change>/evidence/pair.txt`），Evidence 写
  `artifact <路径> sha256:<…>`，不转述。
- **设计内部改动**的判定：只动设计根下的 RTL / TB / 设计文档，flow 与记录口径一处不动；
  沾到 `flow/`、`scripts/`、`openspec/specs/` 或记录字段的就不算。
