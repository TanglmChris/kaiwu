## 1. 让这一段不再报告它没有产出的产物

- [x] 1.1 修 `_fst_to_vcd` 的参数顺序，并在返回前断言产物存在
  - Covers:
    - experiment-trust / 流程的某一段不得报告它没有产出的产物 / 外部工具以 0 退出但没有产出文件
    - experiment-trust / 流程的某一段不得报告它没有产出的产物 / 产物确实存在
    - F1（`fst2vcd` 的 usage 是 `[OPTION]... [FSTFILE]`，文件在前时 `-o` 不被识别，VCD 打到 stdout 被 `capture_output` 吞掉）
    - F2（故障延后到 `flow/sim/vcd_stats.py` 才爆成 `vcdvcd` 的 `FileNotFoundError`）
    - D1（用 `-f <fst> -o <vcd>` 的全选项形式，不依赖「位置参数在末尾」这一约定）
    - D2（错误信息必须带上 `fst2vcd` 的实际输出，否则读者被引向「仿真没产出波形」这个错误方向）
    - D4（回归测试用桩 `fst2vcd`，因为「以 0 退出但不产出文件」这个输入用真工具构造不出来）
    - A1（`-f` 形式在主力机器上同样有效——修复后端到端跑通一次即为本机证据）
  - Touch:
    - flow/sim/run_sim.py
    - tests/test_run_sim.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: `pytest tests/test_run_sim.py -q` —— 桩 `fst2vcd` 以 0 退出且不生成文件时，`_fst_to_vcd` 抛 `RuntimeError`，消息里同时含「哪一段」「缺的是哪个文件」「该工具的实际输出」三者。Fails with: `DID NOT RAISE`
    - M2: `python3 <scratchpad>/check_vcd_real.py` —— 用**真** `fst2vcd` 跑一次 `adder32` 仿真，`run_sim` 返回的 `vcd_path` 确实存在且非空（端到端，不写实验记录）。Fails with: `run_sim 报告了 vcd_path 但该文件不存在`
    - M3 (regression): `pytest tests/` —— 既有测试无回归
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:be09dc7ed450fd19061f0d1ff9717b0f3e92039341a573a06fecd33120b3ea0f
    - M1: `.venv/bin/python -m pytest tests/test_run_sim.py -q` — `3 passed in 0.52s`。三个用例：桩以 0 退出且不生成文件时抛 `RuntimeError`（消息同时含 `fst2vcd`、`…/dump.vcd` 全路径、桩打到 stdout 的 `$date Mon Sep 13 2026 $end STUB-VCD-ON-STDOUT`）；识别 `-o` 的桩写出文件时照常返回该路径；build 目录里一个 `.fst` 都没有时仍返回 `None`。
    - M1.red: 实现前同一命令：`1 failed, 2 passed` —— `test_tool_exit_zero_without_output_is_caught` 报 `Failed: DID NOT RAISE <class 'RuntimeError'>`（`tests/test_run_sim.py:78`）。另两个用例实现前已通过，是本任务要保住而非新增的行为。
    - M1.green: 改 `_fst_to_vcd`（`-f <fst> -o <vcd>` + 产出断言 + `_head()` 带上工具输出）后同一命令 `3 passed`。
    - M2: `.venv/bin/python <scratchpad>/m2/check_vcd_real.py` — 真 `fst2vcd`，`run_sim("adder32", {CARRY_STRUCT: RIPPLE, PIPE_STAGES: 0, WIDTH: 32})` 产物落 scratchpad。`passed = True`，`PASS vcd 存在且非空，53062 字节`。不追加任何实验记录。
    - M2.red: 实现前同一命令：`passed = True`、`vcd_path = …/m2_sim/adder32.vcd`，随后 `FAIL run_sim 报告了 vcd_path 但该文件不存在：…/m2_sim/adder32.vcd` —— `fst2vcd` 退出码 0，`check=True` 放行，函数返回了一个没核实过的路径。
    - M2.green: 见 M2；同一份 FST，改后得到 53062 字节的 VCD。
    - M3: `.venv/bin/python -m pytest tests/ -q` — `30 passed, 2 skipped in 229.86s`。改动前是 27 passed / 2 skipped，增量正好是本任务新增的 3 个用例；2 个 skip 仍是需要 `~/pdk` 合并 liberty 的那两个，与本变更无关。
    - Review:
      - Status: pass
      - Acceptance check: 「外部工具以 0 退出但没有产出文件」这条 Scenario 由 M1 的第一个用例逐项证明——抛 `RuntimeError`，且消息同时含哪一段（`fst2vcd`）、缺哪个文件（`.vcd` 全路径）、工具的实际输出（断言的是桩打到 stdout 的标记串，所以「带上工具输出」不是靠描述、是靠字符串命中）。「产物确实存在」由 M1 的第二个用例（桩）与 M2（真工具，53062 字节）两级证明。D1 落在 `-f <fst> -o <vcd>` 的全选项形式上；D2 落在 `_head()`；D4 落在桩夹具（真工具构造不出「0 退出但不产出」这个输入）；A1 由 M2 在本机端到端跑通证实。红绿两对都是真的：M1.red 是 `DID NOT RAISE`，M2.red 是仿真 `passed=True` 而 VCD 不存在——正是这个 bug 的原貌。
      - Scope check: 产品写入两个文件，与 Touch 一致——`flow/sim/run_sim.py`（+31/−2）与新增的 `tests/test_run_sim.py`。未碰 `scripts/run_experiment.py`、`flow/synth`、`flow/sta`、`flow/equiv`，也未追加任何实验记录（M2 的产物落 scratchpad，`results/experiments.jsonl` 无改动）。任务过程中 `designs/adder32/params.yaml` 被意外改动过一次，已还原，见 Findings。
      - Findings: M2 第一次运行时，scratchpad 里上次会话遗留的 `py.py` 遮蔽了 site-packages 的真 `py` 模块——cocotb 导入 pytest、pytest 导入 `py`，于是那个脚本被当作模块执行，把它的补丁往 `designs/adder32/params.yaml` 里又贴了两遍。这本身就是本仓库头号失效模式的一个实例：一次「只是跑个检查」的操作静默改了 Touch 之外的产品文件，而 `git status` 之前没人看。已 `git checkout -- designs/adder32/params.yaml` 还原（`git diff` 为 0 行），并把 scratchpad 里那个文件改名为 `DO_NOT_IMPORT_py_py.txt` 以免再被 import。Resolved here: designs/adder32/params.yaml。另：`scripts/run_experiment.py:52` 的提示文字「检查 tb 是否开了波形转储、fst2vcd 是否在 PATH 里」列的两个排查方向，对本次这个真实原因从来不会触发（守卫条件是 `vcd_path is None`，而当时它不是 None）。Discard reason: 见 `## Invalidates` 的 I1 —— 修复后这道守卫剩下的唯一可达原因就是「tb 没开波形转储」，提示对它是准确的；改它要动 Touch 之外的文件。
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "检查 tb 是否开了波形转储、fst2vcd 是否在 PATH 里" — `scripts/run_experiment.py:52`。
  这句提示属于 `if sim_passed and vcd_path is None` 那道守卫。本次修复之前，它对
  `fst2vcd` 静默失败这个真实原因**根本不会触发**（`vcd_path` 不是 `None`，而是一个
  指向不存在文件的路径），于是这两个排查方向从来没被验证过就写在了那里。
  Discard reason: 修复后 `_fst_to_vcd` 在产物缺失时当场抛出带工具输出的错误，这道守卫
  剩下的唯一可达原因就是「tb 没开波形转储」（`rglob("*.fst")` 一个都没找到），该提示
  对这个原因是准确的。改它需要动 Touch 之外的 `scripts/run_experiment.py`，属于扩大范围。

## Expectation Coverage

- E1: `fst2vcd` 必须真的产出 VCD，而不是把它打到 stdout（D1、A1）。 Covered by: 1.1
- E2: 产物缺失时必须在**产出它的那一段**失败，并带上足以定位参数误解的工具输出（D2）。 Covered by: 1.1
- E3: 不把断言铺到 `flow/synth` 与 `flow/sta`——它们产出后立刻读取，缺文件会在使用点当场失败（F3、Non-Goals）。 Discard reason: 本变更的 Non-Goal，理由记在 design.md 的 F3；铺开会让验收对象变得模糊。
