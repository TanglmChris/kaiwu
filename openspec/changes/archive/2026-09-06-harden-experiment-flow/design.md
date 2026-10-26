## Context

`restructure-repo-layout`（2026-09-06 归档）把流程泛化成了 `params.yaml` 驱动，
但泛化只覆盖了**参数**，没覆盖**信号命名假设**。`vcd_stats` 的时钟名假设、
仿真失败后的功耗计算、缺失 VCD 的错误路径，这三处都还是 `adder32` 形状的，
且都以「静默给一个合法值」的方式失败。

## Goals / Non-Goals

**Goals**
- 三处会写假数据的地方改成报错或 `null`
- 设计相关的信号命名假设移出流程代码
- 长跑体验：`runs/` 可回收、`make sta` 可单跑、扫参可续跑
- 报告的 Pareto 前沿去重

**Non-Goals**
- 不动 `results/experiments.jsonl` 的 schema（字段集合不变）
- 不收紧 `fast_check.sh` 的 iverilog SKIP（遗留 内部#2，故意为之）
- 不碰 `scripts/score.py`（遗留 内部#5，用户暂缓）
- 不接 `flow/dc/`（遗留 内部#6）

## Verified Facts

**F1** — `flow/sim/vcd_stats.py:22-27`：`references_to_ids.get(clock_signal)` 返回
`None` 时循环整段被跳过，`cycles` 保持初始值 `0` 并被返回。2026-09-06 实测同一份
VCD：`vcd_stats(vcd, 'adder32.clk')` → `{'total_toggles': 19243, 'cycles': 58}`；
`vcd_stats(vcd, 'foo.clock')` → `{'total_toggles': 19243, 'cycles': 0}`，无任何提示。

**F2** — `scripts/run_experiment.py:46` 用 `clock_signal=f"{design}.clk"` 硬编码。
这是流程代码里仅剩的设计专属假设（参数名已在上个变更中消除）。

**F3** — VCD 的信号引用是**全限定名**，形如 `adder32.clk`（顶层模块名 + `.` + 端口名）。
2026-09-06 实测：该 VCD 有 1191 个引用，含 `clk` 的只有 `adder32.clk` 一个。
所以约定回退 `<design>.clk` 对当前设计成立。

**F4** — `scripts/run_experiment.py:43-55`：仿真未通过时只把 `activity` 置为 `None`，
随后**照常**调用 `run_synth` 与 `run_sta`。`run_sta` 拿到的仍是那份失败仿真的 VCD，
功耗照算并写进记录。

**F5** — `flow/sta/run_sta.py:66` 的 `vcd` 参数无 None 检查，直接 `.format()` 进
tcl 模板第 51 行的 `read_vcd {vcd}`，`None` 会变成字面量 `read_vcd None`。

**F6** — 2026-09-06 实测：单次实验的 `runs/<id>/` 约 750 KB～1.3 MB，12 次共 9.0 MB。
项目目标是上百条实验，量级约 75 MB。

**F7** — 2026-09-06 实测：19 条记录（9 组合各测两次 + 1 条重复）时，
`REPORT.md` 的 Pareto 前沿列了 17 行，`RIPPLE p0` 这一个点出现了 3 次。

**F8** — `flow/Makefile` 的 `sta` 目标要求手填 `NETLIST=` 与 `VCD=`，
否则退出码 2；`scripts/sweep.py:17-22` 无条件遍历全部组合，没有跳过或续跑。

## Decisions

**D1** — 时钟信号名由设计在 `params.yaml` 新增的 `sim:` 段声明，
键名 `clock_signal`，取值是 VCD 里的**全限定名后缀**（端口名，如 `clk`），
流程拼成 `<design>.<clock_signal>`。未声明时按约定回退到 `clk`。
显式声明 `clock_signal: null` 表示纯组合设计，跳过周期计数、`cycles` 为 `null`。
Basis: F2、F3。放进 `params.yaml` 而不是新开文件，是因为设计根已有这个配置入口；
放在 `sim:` 段而不是 `params:` 段，是因为它不是扫描维度，混进去会被 `param_combos` 枚举。

**D2** — 仿真未通过时仍然写记录，但 `sta.dynamic_power_w` 与 `sta.static_power_w`
为 `null`，`sta` 的时序字段（`slack_ns` / `fmax_mhz` / `clock_period_ns` /
`fmax_method`）照常有值。
Basis: F4。时序分析只依赖网表和 liberty，与仿真是否通过无关；只有功耗依赖 VCD 活动率。
`sim.passed: false` 本身是有价值的记录，不该整条丢掉。
注意这不是 schema 变更——字段仍在，只是取值可能为 `null`。

**D3** — 功耗被置 `null` 时，STA 仍然跑（拿时序），只是不做 VCD 反标。
Basis: D2。实现上就是不给 OpenSTA 喂 `read_vcd`。

**D4** — `make sta` 增加 `RUN=<experiment_id>` 形式的定位方式，从
`runs/<experiment_id>/synth/` 与 `runs/<experiment_id>/sim/` 找网表与 VCD；
`NETLIST=`/`VCD=` 保留为显式覆盖。
Basis: F8、上个变更确立的 `runs/<experiment_id>/{sim,synth,sta}` 布局。

**D5** — `sweep` 的跳过是**显式开关**（`--skip-existing`），默认关闭，行为与现在一致。
匹配依据是 `design` + `params` 完全相等。
Basis: F8。默认跳过会让「我就是想重测一遍」变成意外行为；而重测正是这次拿到
provenance 正确记录的做法。

**D6** — 全量表新增 `run` 列，取 `experiment_id` 的末 8 位十六进制。
Basis: F7 与 design-report 规格「全量表必须能区分重复测量」。选 `experiment_id`
后缀而不是 `timestamp`，是因为它短、稳定、且本来就是这条记录的唯一标识；
选后缀而不是全串，是因为全串含设计名与参数，在表里是冗余的。

**D7** — `make clean` 删除整个 `runs/`，不做「保留最近 N 次」之类的策略。
Basis: `runs/` 全部 gitignored 且可由记录+代码重新生成；CLAUDE.md 要求脚本不做过度设计。

**D8** — Pareto 前沿按 `(area_um2, critical_path_delay_ns)` 二元组去重，
保留首次出现的那条。全量表不去重。
Basis: F7 与 design-report 规格。

## Hidden Knowledge / Assumptions

**A1** — 假设 VCD 的顶层模块名总是等于设计名（`hdl_toplevel=design`）。
这在当前 cocotb runner 的调用方式下成立（`flow/sim/run_sim.py` 的
`hdl_toplevel=design`），但如果将来 tb 包一层 wrapper 就不成立了。
Owner: 流程；届时 `sim.clock_signal` 改成写全限定名即可，声明位置不用动。

**A2** — 假设「仿真失败」与「VCD 不可信」是同一件事。对断言型失败成立；
如果将来有「仿真通过但覆盖率不足」这类情况，需要另一个维度的判据。
Owner: 用户，等 `verify.md` 有实质内容时再谈。

## Risks / Trade-offs

- **`sta` 子段出现 `null` 会影响读记录的工具**。`scripts/gen_report.py` 的
  `fmt()` 已经处理 `None`（渲染成 `—`），但 `pareto_front()` 依赖的面积与延时
  不受影响。风险在于将来的偏差分析工具要记得处理。
- **回退约定 `clk` 会掩盖声明缺失**。缓解：回退失败时报错并列出 VCD 中的实际信号，
  用户一眼能看出该声明什么。
- **`--skip-existing` 匹配的是参数而非代码版本**。同一组合在不同 commit 下的结果
  可能不同，跳过会漏掉重测。这是显式开关、默认关闭，且文档要写明这一点。

## Open Questions

（无。三档范围由用户于 2026-09-06 选定「可信度 + 易用性」，
其余缺口已在 proposal 的「不做」中明确排除。）
