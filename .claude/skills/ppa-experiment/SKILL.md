---
name: ppa-experiment
description: 对 designs/ 或 cbb/ 下的设计跑仿真、综合、STA、参数扫描，或刷新 REPORT.md。用户说要跑实验、扫参数、看某个设计的 PPA 数据、出报告时用这个。
allowed-tools: Bash(make:*), Bash(git:*), Read, Grep, Glob
---

# 跑 PPA 实验

全部操作走 `flow/Makefile` 的目标，**不要自己拼 yosys / iverilog / sta 命令行**，
也不要直接调 `flow/**` 下的 Python——那样会绕开参数校验和产物归属。

## 目标

```
make -f flow/Makefile exp    DESIGN=<名字> PARAMS="NAME=VALUE ..."   # 单次完整实验
make -f flow/Makefile sweep  DESIGN=<名字>                           # 扫全部参数组合
make -f flow/Makefile sweep  DESIGN=<名字> SKIP_EXISTING=1           # 续跑中断的同一轮扫参
make -f flow/Makefile sweep  DESIGN=<名字> SKIP_EXISTING_GENERATION=1   # 换代重跑的断点续跑
make -f flow/Makefile report DESIGN=<名字>                           # 只刷新 REPORT.md
make -f flow/Makefile sim    DESIGN=<名字> PARAMS="..."              # 只跑仿真
make -f flow/Makefile synth  DESIGN=<名字> PARAMS="..."              # 只跑综合
make -f flow/Makefile sta    DESIGN=<名字> RUN=<experiment_id>       # 只重跑 STA
make -f flow/Makefile clean                                          # 删 runs/
make -f flow/Makefile check                                          # 秒级检查
```

可选变量：`LIBERTY`（默认 ASAP7 RVT/TT 合并库）、`SIM`（icarus/verilator）、`PERIOD_NS`、
`JOBS`（扫参并行度，默认 1；并行不改变测量值）。

- 两个跳过开关的口径不同、不能混用（同时给会报错）：`SKIP_EXISTING` 续跑中断的同一轮，`SKIP_EXISTING_GENERATION` 续跑换代重跑；两者都按当前 RTL 摘要匹配，改了 RTL 之后续跑是安全的 —— 见 `CLAUDE.md`「容易误用的开关」。
- `make sta RUN=<id>` 从 `runs/<id>/{synth,sim}/` 找网表和 VCD，产物写回 `runs/<id>/sta/`。
- `make clean` 只删 `runs/`，不碰实验记录（`results/<设计根>/experiments.jsonl`）与各设计的 `REPORT.md`。
- **扫参 / 换代重跑之后证一遍网表**：`.venv/bin/python3 flow/budget.py run --heavy netlist-equiv -- .venv/bin/python3 flow/equiv/netlist_equiv.py -j 4`
  （本代每条记录的网表 ≡ 它的 RTL，ABC `dprove`）。它读 `runs/<id>/synth/`，所以要在
  `make clean` 之前跑。报 `UNDECIDED` 的是限时内没结论，不是通过，也不是反例。
- 同样在 `make clean` 之前：`.venv/bin/python3 flow/budget.py run --heavy gate-sim -- .venv/bin/python3 flow/sim/gate_sim.py -j 4` —— 网表 + ASAP7 单元
  Verilog 模型跑该顶层现有的 TB（门级仿真，零延时，只验功能、不产出记录字段）。

## 开跑之前

1. **确认设计名**。设计根按 `designs/` → `cbb/` 的顺序解析，同名在两处都有会报错。
   不确定有哪些设计就 `ls designs cbb`。
2. **参数名从 `params.yaml` 读**，不要猜。key 就是 RTL 参数名，取值必须是声明过的
   字面量——拼错会被 `flow/paths.py` 拒掉（这是故意的：RTL 的参数分派没有 else 分支，
   传错值会综合出一个悬空电路，指标看着正常但是假的）。
3. **新设计要在 `params.yaml` 里声明 `sim.clock_signal`**（只写端口名，如 `clk`）。
   不声明会回退到 `clk`；回退后在 VCD 里找不到会**报错**，不会静默把 `cycles` 记成 0。
   纯组合设计写 `clock_signal: null`，`cycles` 记为 `null`。
4. **工作区必须是干净的**（正式记录）。`run_experiment.py` 会把 `git rev-parse HEAD` 写进记录，
   脏工作区跑出来的记录 provenance 是错的（红线 3）。先 `git status`，按归属分三种：
   - 脏的是**本任务自己的改动**：有 commit 授权（`keel/config.yaml` 的 `commit`）就先提交再跑；
   - 脏的是**别人的改动**（别的会话、用户手上的）：不替人提交，停下来问；
   - 只想**试跑**看个数：`TRIAL=1`，记录写到 `runs/trial/`、不进 `results/`、不要求工作区干净，不能当正式数据用（内部#222）。

## 等长任务

扫参、等价证明这类分钟级的任务用后台方式启动（`run_in_background`），**等它的完成通知**，
不要写 `until grep …; sleep` 去轮询输出文件 —— 那样模型整段时间在空等，而完成通知本来就会来。
要看中途进度，读一次输出文件即可。

## 跑完之后

- 原始产物（网表 / VCD / STA 报告 / log）在 `runs/<experiment_id>/`，已 gitignore。
- 指标追加到本设计根的记录文件 `results/<设计根>/experiments.jsonl`（内部#422，由 `flow/records.py` 定位）。**记录的 schema 不要动**，
  要改得走 keel Full 模式。
- `REPORT.md` 不会自动更新，需要显式 `make report`。这是有意的：报告生成不能是
  实验的副作用，否则扫参会弄脏工作区，把下一条记录的 provenance 带坏。

## 看数的时候

门禁只查证据齐不齐，**不判断数字对不对**。这个项目最容易翻车的是
「流程跑通了但指标不可信」，盯这几处：

- **动态功耗只能同周期比**（正比于频率）。`REPORT.md` 的 `period_ns` 列不一致时
  报告会打警告，别忽略它。
- **`fmax_mhz` 是 setup-only、单角 TT、无 OCV 的理想值**，用来横向比架构，
  不是这个电路真能跑到的频率。
- **比微架构时综合不 `-flatten`，关键 building block 最好保住层级**，否则 ABC 可能把
  不同结构优化成同一个电路，差异是假的。保层级由该顶层 `params.yaml` 的
  `tops:<顶层>:synth:keep_hierarchy:` 声明，不写在 RTL 里 —— 见 `docs/pitfalls.md` 的 P-3 / P-15（2026-10-05 起保层级不强制，内部#216）。
- **`sta` 的功耗字段可能是 `null`**：仿真没过时流程不拿那份 VCD 算功耗。看到 `null`
  不是流程坏了，是它在拒绝给你一个假数字——先去看 `sim.passed`。
- **新数与历史对不上就停下来查**，不要直接记录。
