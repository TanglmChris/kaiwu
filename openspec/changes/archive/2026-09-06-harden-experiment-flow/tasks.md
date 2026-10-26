## 1. 可信度：堵住三处假数据

- [x] 1.1 `vcd_stats` 找不到时钟信号时报错，时钟名由设计声明
  - Covers:
    - experiment-trust / 无法测得的指标必须缺席，不得以合法值代替
    - flow-parameterization / 设计相关的仿真配置必须由设计声明
    - D1, F1, F2, F3
  - Touch:
    - flow/sim/vcd_stats.py
    - flow/paths.py
    - scripts/run_experiment.py
    - designs/adder32/params.yaml
    - flow/templates/design-root/params.yaml
  - Verify:
    - Strategy: vertical-tdd
    - M1: 传一个 VCD 中不存在的时钟信号名时报错，错误信息含该名字与 VCD 中实际存在的顶层信号
    - M2 (regression): 传 VCD 中存在的信号名时，`cycles` 与本次变更前对同一 VCD 的统计结果相同
    - M3: 设计声明 `sim.clock_signal: null` 时命令成功，`cycles` 为 `null` 且不报错
    - M4 (regression): 设计未声明 `sim` 段时回退到 `<design>.clk`，`adder32` 跑通且 `cycles` 非零
    - M5 (regression): `flow/**` 与 `scripts/**` 中不出现任何具体设计的信号名字面量
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:c20b8062a770bb2336920e388eae9f0b782762ee320f8b275b034f04edb5b7b0
    - M1: pass — `vcd_stats(vcd, 'foo.clock')` 抛 `ClockSignalNotFound`，消息含该名字、VCD 路径、该怎么声明，以及 VCD 中实际存在的 12 个顶层信号（`adder32.clk` 在列）
    - M1.red: fail（预期）— 改动前同一调用无报错，返回 `{'total_toggles': 19243, 'cycles': 0}`，一个看着完全正常的假值
    - M1.green: pass — 见 M1
    - M2: pass — `vcd_stats(vcd, 'adder32.clk')` 返回 `{'total_toggles': 19243, 'cycles': 58}`，与改动前对同一 VCD、同一信号名的结果逐字段相同
    - M3: pass — `sim.clock_signal: null` 时 `clock_signal('adder32')` 返回 `None`，`vcd_stats(vcd, None)` 返回 `cycles: None`，不报错
    - M3.red: fail（预期）— 改动前 `params.yaml` 无 `sim` 段、`flow/paths.py` 无 `clock_signal`，`grep` 无任何命中，声明「没有时钟」这件事无处可表达
    - M3.green: pass — 见 M3；临时把 `adder32` 的 `clock_signal` 改成 `null` 验完即还原
    - M4: pass — 未声明 `sim` 段时回退到 `adder32.clk`；显式声明后端到端 `make exp DESIGN=adder32 PARAMS="CARRY_STRUCT=CLA PIPE_STAGES=1"` 跑通，`cycles=114`，与变更前同组合的两条历史记录（均为 114）一致
    - M5: pass — `grep -rnE "\.clk\b|\"clk\"|'clk'"` 扫 `flow/**` 与 `scripts/**`，唯一命中是 `flow/paths.py:19` 的 `DEFAULT_CLOCK_PORT = "clk"`。那是有文档的通用回退常量，不是设计专属名（不含设计名、对任何设计一视同仁），且回退失败会报错而非给替代值
    - Review:
      - Status: complete
      - Acceptance check: 五条 M 检查全部 pass，M1/M3 走了真红绿。「静默给 0」这条路径已被彻底移除：`vcd_stats` 现在只有三种出口——有时钟且找到（计数）、显式无时钟（`None`）、找不到（报错）
      - Scope check: 产品写入 5 个文件，全部在 Touch 内。`results/experiments.jsonl` 在 M4 中被追加 1 行，任务结束前已还原到 19 行基线并经 `cmp` 确认
      - Findings: `sim` 段与 `params` 段是并列的两个顶层键，`load_params_spec` 只读 `params`，所以 `sim.clock_signal` 不会被 `param_combos` 当成扫描维度枚举。Resolved here: M4 —— 端到端跑通且组合数仍是 9，未因新增 `sim` 段而变化
    - Blocker: none
    - Reauthorizations: none

- [x] 1.2 仿真未通过时不记录功耗，缺 VCD 时报真正的原因
  - Covers:
    - experiment-trust / 仿真未通过时不得记录依赖该仿真的指标
    - experiment-trust / 缺少必需输入时必须报出真正的原因
    - D2, D3, F4, F5
  - Touch:
    - flow/sta/run_sta.py
    - scripts/run_experiment.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: 仿真未通过但有 VCD 时，记录被写入且 `sim.passed` 为 `false`，`sta.dynamic_power_w` 与 `sta.static_power_w` 均为 `null`
    - M2 (regression): 同一次运行中 `synth.area_um2` / `synth.cell_count` / `synth.critical_path_delay_ns` 与 `sta.slack_ns` / `sta.fmax_mhz` 照常有值
    - M3: 仿真未产出 VCD 时报错说明仿真未产出 VCD，错误信息中不含 `read_vcd None`，且 OpenSTA 未被调用
    - M4 (regression): 仿真通过时功耗字段照常有值，与变更前对同一组合的记录数值相同
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:3e77de7d520604be068dc056d69abdcbfd999a356cc8199a821e8809f6825627
    - M1: pass — 临时把 tb 的期望值改错制造真实失败后跑 `make exp`，记录写入且 `sim.passed` 为 `false`，`sta.dynamic_power_w` 与 `sta.static_power_w` 均为 `null`
    - M1.red: fail（预期）— 改动前同样场景下 STA 仍拿这份失败仿真的 VCD 反标，功耗字段会写进一个看着正常的数值
    - M1.green: pass — 见 M1
    - M2: pass — 同一次运行中 `synth.cell_count=174` / `area_um2=16.73784` / `critical_path_delay_ns=0.697688`、`sta.slack_ns=4.302312` / `fmax_mhz=1433.31` / `clock_period_ns=5.0` / `fmax_method=analytic` 全部照常有值
    - M3: pass — 打桩让 `run_sim` 返回 `passed=True, vcd_path=None`，`run_experiment` 抛 `RuntimeError`「仿真通过但未产出 VCD…」；消息不含 `read_vcd None`；`run_sta` 与 `run_synth` 均未被调用（校验在综合之前）
    - M3.red: fail（预期）— 用 `git show HEAD:flow/sta/run_sta.py` 取改动前的模板，以 `vcd=None` 渲染后得到字面量 `read_vcd None`，且该版本源码中不存在任何 `vcd is None` 守卫
    - M3.green: pass — 见 M3
    - M4: pass — 仿真通过的同一组合（CLA p0）跑完，`dynamic_power_w=3.45e-06`、`static_power_w=1.02e-08`，与记录中两条历史 CLA p0 的数值逐位相同
    - Review:
      - Status: complete
      - Acceptance check: 四条 M 检查全部 pass，M1/M3 走了真红绿。三条路径现在互斥且都可解释：仿真通过且有 VCD → 功耗由 VCD 反标；仿真未通过 → 跳过 `read_vcd`/`report_power`，功耗为 `null`，时序照测；仿真通过但无 VCD → 在综合之前就报错
      - Scope check: 产品写入 `flow/sta/run_sta.py` 与 `scripts/run_experiment.py`，均在 Touch 内。`designs/adder32/tb/test_adder32.py` 被临时改坏以制造真实失败，验完已还原（`git diff` 无输出）；`results/experiments.jsonl` 追加的 2 行已撤回并经 `cmp` 确认
      - Findings: 没有让 OpenSTA 在缺活动率时用默认活动率估功耗，而是直接不出功耗。Resolved here: M1 —— CLAUDE.md 明确写明「必须用 VCD/SAIF 反标算，不接受无活动率的静态估算」，给一个静态估算值等于把假数据写进最重要的资产
    - Blocker: none
    - Reauthorizations: none

## 2. 报告呈现

- [x] 2.1 Pareto 前沿去重，全量表可区分重复测量
  - Covers:
    - design-report / Pareto 前沿中同一个点只出现一次
    - design-report / 全量表必须能区分重复测量
    - D6, D8, F7
  - Touch:
    - scripts/gen_report.py
    - designs/adder32/REPORT.md
  - Verify:
    - Strategy: vertical-tdd
    - M1: 当前 19 条记录下 Pareto 前沿不含重复的 (area, cp_delay) 二元组
    - M2: 全量表仍为 19 行，且同一参数组合的多行之间存在可区分的列
    - M3 (regression): 连续生成两次逐字节相同，打乱记录行序后产出不变
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:fd39dd40740a2106b47bcdb32156c751976cb910097ab230436c0742ebfcf473
    - M1: pass — 19 条记录下 Pareto 前沿 8 行、唯一 (area, cp_delay) 点 8 个，无重复
    - M1.red: fail（预期）— 改动前前沿 17 行但只有 8 个不同的点：`(12.59712, 0.98653)` 出现 3 次，其余 7 个点各出现 2 次
    - M1.green: pass — 见 M1。去重发生在支配判断之后，所以「同组合但指标不同」的两个点仍各自参与判断，只有完全相同的点被折叠
    - M2: pass — 全量表仍为 19 行；三条 `RIPPLE p0` 的 `run` 列分别是 `bdb78ecb` / `08d5ee7b` / `d61f0f4a`，可逐行区分
    - M2.red: fail（预期）— 改动前三条 `RIPPLE p0` 中有两条逐字段完全相同（`| RIPPLE | 0 | 12.5971 | 0.986530 | 5.0 | 1013.7 | 2.810e-06 | 7.530e-09 |`），读者无法分辨是重复测量还是渲染错误
    - M2.green: pass — 见 M2。`run` 取 `experiment_id` 末 8 位而非全串，因为前缀的设计名与参数值在表里已有专列
    - M3: pass — 连续生成两次 `cmp` 逐字节相同；打乱 `experiments.jsonl` 行序后渲染结果相同
    - Review:
      - Status: complete
      - Acceptance check: 三条 M 检查全部 pass，M1/M2 走了真红绿。前沿表不带 `run` 列（去重后一个点只剩一行，加了也没有区分作用）
      - Scope check: 产品写入 `scripts/gen_report.py` 与 `designs/adder32/REPORT.md`，均在 Touch 内
      - Findings: 加 `run` 列**当场打破了确定性**——M3 第一次跑就挂了。原因是 `sort_key` 只按参数排序，同参数的记录保持 `experiments.jsonl` 的输入行序；此前重复行的所有可见列都相同，这个缺陷被掩盖着，加了 `run` 列才暴露出来。Resolved here: M3 —— 给 `sort_key` 追加 `experiment_id` 作为末位 tiebreaker，打乱行序后产出恢复一致。顺带修正了 bool 分支的 key 元组长度（原为 2 元组，与另两条分支的 3 元组不齐，混用会在比较时抛 TypeError）
    - Blocker: none
    - Reauthorizations: none

## 3. 长跑易用性

- [x] 3.1 `make clean` 回收 `runs/`，`make sta` 按 experiment_id 定位产物
  - Covers:
    - D4, D7, F6, F8
  - Touch:
    - flow/Makefile
    - flow/sta/run_sta.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: `make clean` 后 `runs/` 不存在或为空，且 `results/experiments.jsonl` 与 `REPORT.md` 未被改动
    - M2: `make sta RUN=<experiment_id>` 无需 `NETLIST=`/`VCD=` 即可跑通，结果与显式传路径时一致
    - M3: `RUN=` 指向一个不存在的 experiment_id 时报错并指出查找过的目录
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:027cefa31ce5fb27cf8dca68af5047917cb59007632ab581943eb8fe4950c662
    - M1: pass — `make clean` 删掉 14 MB 的 `runs/`（目录不再存在），`md5sum -c` 确认 `results/experiments.jsonl` 与 `designs/adder32/REPORT.md` 均未改动
    - M1.red: fail（预期）— 改动前 `make clean` 报「没有规则可制作目标 clean」
    - M1.green: pass — 见 M1。只删 `runs/`：里面全是 gitignored 的单次原始产物，可由记录+代码重新生成；durable 的两样不碰
    - M2: pass — `make sta DESIGN=adder32 RUN=adder32-CLA-0-24c99655` 无需 `NETLIST=`/`VCD=` 跑通；与显式传路径的那次相比，除 `log_path`/`checks_report` 外全部指标字段相等（slack 4.302312、cp 0.697688、22 级、fmax 1433.31、功耗 3.45e-06 / 1.02e-08）
    - M2.red: fail（预期）— 改动前 `make sta DESIGN=adder32 RUN=adder32-CLA-0-24c99655` 报「需要 NETLIST= 与 VCD=」并以退出码 2 结束，`RUN` 变量不被识别
    - M2.green: pass — 见 M2
    - M3: pass — `RUN=nope` 报「在 /…/runs/nope/synth/ 下找不到网表（*_netlist.v）」，指出了查找过的目录；`RUN` 与 `NETLIST` 都不给时报 `需要 RUN=<experiment_id>，或显式给 NETLIST= 与 VCD=`
    - M3.red: fail（预期）— 改动前不存在按 `RUN` 定位这条路径，任何 `RUN` 值都只会得到「需要 NETLIST= 与 VCD=」
    - M3.green: pass — 见 M3
    - Review:
      - Status: complete
      - Acceptance check: 三条 M 检查全部 pass，均走了真红绿。`NETLIST=`/`VCD=` 保留为显式覆盖，`RUN=` 只是省事的定位方式，两者不互斥
      - Scope check: 产品写入 `flow/Makefile` 与 `flow/sta/run_sta.py`。后者是任务中途扩进 Touch 的，见 Reauthorizations。`results/experiments.jsonl` 未被改动（本任务不跑实验）
      - Findings: 第一版只做了「找输入」，产物仍落进 `runs/adhoc-<uuid>/sta/`，等于给 `RUN=` 定位之后又把结果扔到别处，产物归属被打散。Resolved here: flow/sta/run_sta.py —— 给它的 CLI 加了 `--out-dir`，Makefile 在 `RUN` 非空时传 `runs/<RUN>/sta`，产物落回该次实验自己的目录
    - Blocker: none
    - Reauthorizations: 自记 Touch 扩展 1 项（`flow/sta/run_sta.py`），未经用户事前授权。理由：`run_sta.py` 的 CLI 原本没有 `--out-dir`，只改 Makefile 无法把产物落回 `runs/<RUN>/sta/`，「按 experiment_id 定位」只能做一半

- [x] 3.2 `sweep --skip-existing` 支持续跑
  - Covers:
    - D5, F8
  - Touch:
    - scripts/sweep.py
    - flow/Makefile
  - Verify:
    - Strategy: vertical-tdd
    - M1: 带 `--skip-existing` 时，记录中已存在的组合被跳过并打印跳过信息，不触发仿真/综合/STA
    - M2: 带 `--skip-existing` 且某组合尚无记录时，该组合照常跑完并写入记录
    - M3 (regression): 不带该开关时全部组合照常跑，行为与变更前一致
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:6ac03b0329eabb89d362d894d7307e7bf8b12d05f98e65982be5f5082980de9d
    - M1: pass — 9 个组合在记录中都已存在时，`make sweep DESIGN=adder32 SKIP_EXISTING=1` 对每个组合打印「已有记录，跳过」；`runs/` 目录未被创建，`experiments.jsonl` 经 `cmp` 确认未变，说明未触发仿真/综合/STA
    - M1.red: fail（预期）— 改动前 `sweep.py --skip-existing` 报 `unrecognized arguments: --skip-existing`
    - M1.green: pass — 见 M1
    - M2: pass — 端到端：从记录里摘掉 CSEL p2 的 2 条（19→17）后带开关跑，8 个组合跳过、只有 `{'CARRY_STRUCT': 'CSEL', 'PIPE_STAGES': 2}` 实际执行，记录变成 18 条且最后一条正是该组合、`passed` 为 `true`；`runs/` 只多出 1 个目录
    - M2.red: fail（预期）— 改动前不存在 `--skip-existing` 这条路径，「只跑缺的那个组合」这个行为无从发生：任何调用都会跑满 9 个组合
    - M2.green: pass — 见 M2
    - M3: pass — 不带开关跑，9 个组合全部执行，记录从 19 增到 28，新增 9 条的组合集合与 `params.yaml` 声明的全组合一致，与变更前的扫参行为相同
    - Review:
      - Status: complete
      - Acceptance check: 三条 M 检查全部 pass。开关默认关闭，`sweep()` 的 `skip_existing` 参数默认 `False`，不带 `SKIP_EXISTING=1` 时代码路径与变更前等价
      - Scope check: 产品写入 `scripts/sweep.py` 与 `flow/Makefile`，均在 Touch 内。验证过程中 `experiments.jsonl` 先被摘掉 2 条、后被追加 10 条，任务结束前已还原到 19 行基线并经 `cmp` 确认
      - Findings: 匹配依据只有 `design` + `params`，不含 `git_commit`。Discard reason: 把代码版本纳入匹配会让「换了 commit 就全部重跑」成为默认，与续跑中断扫参这个用途相悖；这一点已写进 `scripts/sweep.py` 的 `sweep()` docstring 与 design.md 的风险一节，由使用者自行判断
    - Blocker: none
    - Reauthorizations: none

- [x] 3.3 同步 `CLAUDE.md` 与 `ppa-experiment` skill
  - Covers:
    - D1, D2, D5, D7
  - Touch:
    - CLAUDE.md
    - .claude/skills/ppa-experiment/SKILL.md
  - Verify:
    - Strategy: evidence-first
    - M1: `CLAUDE.md` 的记录格式一节写明「仿真未通过时功耗字段为 `null`」
    - M2: skill 列出 `make clean`、`make sta RUN=`、`sweep --skip-existing` 三个新用法
    - M3: skill 与 `CLAUDE.md` 都写明 `sim.clock_signal` 的声明方式与回退约定
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:4ad07d13f3ef3fc31825b6eb88ca3eb1ebd894e5ccaed880ca4bf2a17a06d1cd
    - M1: pass — `CLAUDE.md` 记录格式一节的 `sta` 条目下新增「仿真未通过时两个功耗字段是 `null`」，并写明时序字段照常有值、这不是 schema 变更但读记录的工具要处理 `null`（I2 关闭）
    - M2: pass — skill 的目标清单补齐 `make clean`、`make sta RUN=<experiment_id>`、`sweep SKIP_EXISTING=1` 三项，并各配一行说明；`CLAUDE.md` 常用命令块同步（I3 关闭）。frontmatter 经 `yaml.safe_load` 仍可解析，`name` 为 `ppa-experiment`
    - M3: pass — 两处都写明 `sim.clock_signal` 只写端口名、流程拼成 `<design>.<port>`、不声明则回退 `clk`、回退失败报错而非给 0、纯组合写 `null`（I1 关闭）
    - Review:
      - Status: complete
      - Acceptance check: 三条 M 检查全部 pass。skill 的「看数的时候」一节加了一条新的判读口径——看到功耗 `null` 先去看 `sim.passed`，因为那是流程在拒绝给假数字而不是坏了
      - Scope check: 产品写入 `CLAUDE.md` 与 `.claude/skills/ppa-experiment/SKILL.md`，均在 Touch 内。另在本任务开始前把 3.3 的 Blocker 从「依赖 1.1、1.2、3.1、3.2 先完成」改成 `none`（四者均已完成），这是任务元数据不是产品写入
      - Findings: `CLAUDE.md` 增至 174 行。Discard reason: 新增内容都是不可由代码或 `ls` 推导的行为契约（功耗何时为 `null`、时钟名怎么声明、`SKIP_EXISTING` 不看代码版本），且都是「不知道就会误读数据」的那一类，不适合挪去懒加载
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "cycles" 的含义 — `designs/adder32/spec.md` 时序约定一节与 `CLAUDE.md` 记录格式一节。
  纯组合设计的 `cycles` 将变成 `null` 而不是某个计数。Updated by: 1.1, 3.3
- I2: "`sta`: `clock_period_ns`, `slack_ns`, `fmax_mhz`, `fmax_method`, `dynamic_power_w`
  （**必须用 VCD/SAIF 反标算，不接受无活动率的静态估算**）, `static_power_w`" —
  `CLAUDE.md` 记录格式一节。该说法将不再完整：仿真未通过时这两个功耗字段是 `null`。
  Updated by: 3.3
- I3: "make -f flow/Makefile ..." 用法清单 — `.claude/skills/ppa-experiment/SKILL.md`
  与 `CLAUDE.md` 常用命令块，缺 `clean` / `sta RUN=` / `--skip-existing`。Updated by: 3.3
- I4: "| RIPPLE | 0 | 12.5971 | 0.986530 |" 在「## 面积-延时 Pareto 前沿」一节中
  连续出现三次 — `designs/adder32/REPORT.md`。同一个点被重复列出，读者会误以为
  存在多个不同的配置。Updated by: 2.1

## Expectation Coverage

- E1: VCD 中找不到时钟信号时报错而不是返回 `cycles: 0` Covered by: 1.1
- E2: 时钟信号名由设计声明，流程代码中无设计专属信号名 Covered by: 1.1
- E3: 纯组合设计能跑通，`cycles` 为 `null` Covered by: 1.1
- E4: 仿真未通过时不记录功耗，但仍记录面积与时序 Covered by: 1.2
- E5: 缺 VCD 时报「仿真未产出 VCD」而不是 OpenSTA 的内部错误 Covered by: 1.2
- E6: Pareto 前沿去重，全量表可区分重复测量 Covered by: 2.1
- E7: `runs/` 可回收、`make sta` 可单跑、扫参可续跑 Covered by: 3.1, 3.2
- E8: 文档与 skill 跟上以上全部行为变化 Covered by: 3.3
- E9: 仿真通过但覆盖率不足这类「通过≠可信」的情况需要另一个判据
  Durable owner: CLAUDE.md
