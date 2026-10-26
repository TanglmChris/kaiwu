## Why

流程现在能从干净工作区一路跑到记录和报告，但有三处会**静默写出假数据**，
以及三处让长跑变难受的缺口。CLAUDE.md 明确指出这个项目最容易翻车的地方是
「流程跑通了但指标不可信」，而门禁不判断数字对不对——所以这三处必须从代码层面堵死，
不能靠每次盯着看。

现在是做这件事的时机：`adder32` 只有一个设计、只有 19 条记录，问题还只在
`vcd_stats` 的时钟名假设上潜伏着；一旦第二个设计（时钟不叫 `clk`、带握手）进来，
写出来的就是一批看着正常的错记录，事后无法分辨。

## What Changes

**可信度（会写假数据，必须堵）**

- `flow/sim/vcd_stats.py` 在 VCD 里找不到指定时钟信号时**报错**，不再返回
  `cycles: 0`。实测：`vcd_stats(vcd, 'foo.clock')` 现在返回
  `{'total_toggles': 19243, 'cycles': 0}`，无任何提示。
- 时钟信号名不再由 `scripts/run_experiment.py` 用 `f"{design}.clk"` 硬编码，
  改为由设计声明；未声明时按约定回退，但找不到就报错而不是给 0。
- 仿真未通过时**不再计算并记录动态/静态功耗**。现在 `passed: false` 会如实写进
  记录，但 STA 仍拿这份失败仿真的 VCD 反标算功耗，数字会照常落进
  `sta.dynamic_power_w`——活动率来自一次错误的仿真，这个功耗是垃圾。
- 仿真未产出 VCD 时，报「仿真失败」而不是把 `None` 拼进 tcl 变成
  `read_vcd None`、让用户看 OpenSTA 的内部错误。

**易用性**

- `flow/Makefile` 增加 `clean` 目标回收 `runs/`（实测单次实验约 750 KB，
  目标 100+ 次实验约 75 MB）。
- `make sta` 不再要求手填 `NETLIST=` / `VCD=`，能定位同一 `experiment_id`
  下上一步的产物。
- `scripts/sweep.py` 支持跳过记录中已存在的参数组合，使中断的扫参可以续跑。

**报告呈现**

- `REPORT.md` 的 Pareto 前沿去重：同一个 (面积, 延时) 点不再重复列出。
  实测 19 条记录（9 组合各测两次）时，前沿列了 17 行、同一个点出现 3 次。
- 全量表保留全部记录（D13 不变），但要能把重复组合区分开。

## 不做

- 不收紧 `scripts/fast_check.sh` 的 iverilog `SKIP`（遗留 内部#2，当初是为了不挡
  GUI 客户端 push 而**故意**选的 skip）
- 不动 `results/experiments.jsonl` 的 schema
- 不碰 `scripts/score.py` / `scoring.yaml`（遗留 内部#5，用户 2026-09-05 主动暂缓）
- 不接 `flow/dc/`（遗留 内部#6，商业工具未安装）
- 不把 carry-select 的 `BLOCK` 变成扫描维度（遗留 内部#3，属于设计不属于流程）

## Capabilities

### New Capabilities
- `experiment-trust`: 指标在什么条件下才允许被记录，以及流程必须在哪些情况下
  拒绝写记录而不是写一个看着正常的错值

### Modified Capabilities
- `flow-parameterization`: 设计相关的仿真配置（时钟信号名）从流程代码里移出，
  由设计声明
- `design-report`: Pareto 前沿去重；重复组合可区分

## Impact

- `flow/sim/vcd_stats.py` — 找不到时钟信号的返回值语义（当前第 21-28 行静默返回 0）
- `scripts/run_experiment.py:46` — 硬编码的 `clock_signal=f"{design}.clk"`
- `scripts/run_experiment.py:48-55` — 仿真失败仍继续调 `run_sta`
- `flow/sta/run_sta.py:66` — `vcd` 参数未做 None 检查，直接进 tcl 模板
- `flow/Makefile` — 新增 `clean`；`sta` 目标的参数解析
- `scripts/sweep.py:17-22` — 无条件跑全部组合
- `scripts/gen_report.py` — `pareto_front()` 去重
- `designs/adder32/params.yaml` 或设计根 — 承载时钟信号名的声明位置
- **风险**：`sta` 段拒绝为失败仿真算功耗后，记录里 `sta` 子段的字段可能为 `null`。
  这不是 schema 变更（字段仍在），但读记录的工具要能处理 `null`
