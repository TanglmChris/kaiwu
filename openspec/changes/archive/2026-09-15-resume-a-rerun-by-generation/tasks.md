## 1. 按代跳过

- [x] 1.1 `existing_combos` 加指纹维度，新增 `--skip-existing-generation`，与 `--skip-existing` 互斥
  - Covers:
    - guardrail-scope / 判定「已有」的口径不同的跳过开关必须彼此排斥
    - guardrail-scope / 判定「已有」的口径不同的跳过开关必须彼此排斥 / 同时启用两个口径不同的跳过开关
    - guardrail-scope / 判定「已有」的口径不同的跳过开关必须彼此排斥 / 只启用其中一个
    - D1（匹配键是 `(design, params, flow.fingerprint)`；指纹开跑前现算，不用 `latest_generation()`）
    - D2（同时给出两个开关当场报错，不做优先级）
    - D7（「已有」只看记录在不在，不看 `sim.passed`）
  - Acceptance:
    - `sweep()` 与 `existing_combos()` 都接受一个 `log_path`，使测试能对着临时记录文件跑，
      而不是对着 `results/experiments.jsonl`。默认值不变。
    - `--skip-existing` 的行为逐字不变：同一份记录、同一个设计下，它跳过的组合集合
      与本变更前完全相同。
  - Touch:
    - scripts/sweep.py
    - tests/test_sweep.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: 同一组合在记录里有指纹 A 与指纹 B 两条，当前指纹为 B 时 `--skip-existing-generation` 跳过它、当前指纹为 C 时不跳过，而同一份记录下 `--skip-existing` 两种情况都跳过 Fails with: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M2: 同时给两个开关时 `sweep()` 抛 `SweepError`、`run_experiment` 一次都没被调用，报错文本里同时出现两者的匹配字段 Fails with: `AttributeError: module 'scripts.sweep' has no attribute 'SweepError'`
    - M3: 命令行入口同时给两个开关时以非 0 退出，输出里同时出现两者的匹配字段（不是一个 traceback） Fails with: `sweep.py: error: unrecognized arguments: --skip-existing-generation`
    - M4: 记录里一条 `sim.passed == false` 的本代记录同样被 `--skip-existing-generation` 跳过（D7） Fails with: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M5 (regression): 记录里只有上一代的全部组合、当前是新一代时 `--skip-existing-generation` 一条都不跳（`latest_generation()` 在这里会判错）
    - M6 (regression): 不给任何跳过开关时 `run_experiment` 被调用的次数等于组合总数
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:04f9418963bd813eb2a8a3685d70866bcc7f84777024cdf28707ef93167cdb27
    - M1: `pytest tests/test_sweep.py -k also_matches` → 1 passed。同一组合的 FP_A/FP_B 两条记录下：当前=FP_B 跳过、当前=FP_C 跑、`--skip-existing` 两种都跳过。
    - M1.red: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`（实现 `git checkout` 掉之后实测）
    - M1.green: 1 passed, 13 deselected in 0.05s
    - M2: `pytest tests/test_sweep.py -k two_switches` → 1 passed。`SweepError` 抛出、`runner.calls == []`、报错含 `(design, params)` 与 `(design, params, flow.fingerprint)` 两行。
    - M2.red: `AttributeError: module 'scripts.sweep' has no attribute 'SweepError'`
    - M2.green: 1 passed, 13 deselected in 0.03s
    - M3: `pytest tests/test_sweep.py -k cli_exits` → 1 passed。子进程真跑 `scripts/sweep.py --skip-existing --skip-existing-generation`，returncode=2，stderr 以 `FLOW-ERROR:` 开头并含两者匹配字段。
    - M3.red: `sweep.py: error: unrecognized arguments: --skip-existing-generation`
    - M3.green: 1 passed, 13 deselected in 0.11s
    - M4: `pytest tests/test_sweep.py -k failed_record` → 1 passed。`sim.passed == false` 的本代记录同样被跳过。
    - M4.red: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M4.green: 1 passed, 13 deselected in 0.04s
    - M5: `pytest tests/test_sweep.py -k brand_new` → 1 passed。记录里 72 条全属上一代、本次是新一代时，`run_experiment` 被调用 72 次（`latest_generation()` 在这里会判成 0 次）。
    - M6: `pytest tests/test_sweep.py -k without_any_switch` → 1 passed。不给开关时调用次数 == 组合总数 72。
    - Review:
      - Status: pass
      - Acceptance check: `sweep()` 与 `existing_combos()` 都接受 `log_path`，默认值仍是 `EXPERIMENTS_LOG`；`--skip-existing` 的匹配集合由 M1 第三段与 M6 一并守住 —— 同一份记录下它两种代都跳过，与本变更前逐字一致。
      - Scope check: 只动了 Touch 里的两个文件。`existing_combos` 的既有签名靠追加关键字参数保持兼容（`fingerprint=None` 即旧行为）。gate 提示 1.1/1.2/2.1 共用 Touch：三者是三件独立的事（匹配键 / 指纹一致性 / 输出可读性），各自的红互不相同，不是一个行为切两半。
      - Findings: none
    - Blocker: none
    - Reauthorizations: none

- [x] 1.2 每条实验跑完校验其指纹与开跑前算的一致，不一致就中止
  - Covers:
    - D6（sweep 按指纹 X 过滤而记录写的是 Y 时，新一代会永远差着被跳过的那些条，且无迹象）
    - F3（`run_experiment()` 返回的记录带 `record["flow"]["fingerprint"]`）
  - Touch:
    - scripts/sweep.py
    - tests/test_sweep.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: `run_experiment` 返回的记录带着与开跑前不同的指纹时 `sweep` 抛错中止、报错同时给出两个指纹，且后面的组合不再开跑 Fails with: `AttributeError: module 'scripts.sweep' has no attribute 'SweepError'`
    - M2 (regression): 指纹一致时照常跑完全部组合
    - M3 (regression): 未开 `--skip-existing-generation` 时不做这项校验，指纹不一致也照常跑完（没有「本代」这个前提）
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:e6f51575bdfc6ea184aa158244133eeada62d1fd6cd519a6be00bb555cf244f6
    - M1: `pytest tests/test_sweep.py -k different_fingerprint_aborts` → 1 passed。替身写出 FP_C、开跑前算的是 FP_B：抛 `SweepError`、`len(runner.calls) == 1`（后面 71 个组合没开跑）、报错文本里两个指纹都在。
    - M1.red: `AttributeError: module 'scripts.sweep' has no attribute 'SweepError'`（实现 `git checkout` 掉之后实测）
    - M1.green: 1 passed, 13 deselected in 0.04s
    - M1.strawman: 只把一致性校验那几行拿掉、其余实现保留 → `Failed: DID NOT RAISE SweepError`。这条判据不是空过：撑住它的是校验本身，不是 1.1 的匹配键。
    - M2: `pytest tests/test_sweep.py -k matching_fingerprint_runs` → 1 passed。指纹一致时 72 个组合全跑完。
    - M3: `pytest tests/test_sweep.py -k check_does_not_apply` → 1 passed。未开按代跳过时替身写 FP_C 也照常跑完 72 条 —— 没有「本代」这个前提就不做这项校验。
    - Review:
      - Status: pass
      - Acceptance check: D6 的闭环成立 —— 过滤依据的指纹与记录实际写入的指纹对不上时当场中止，且中止在第一条上而不是跑完再报。
      - Scope check: 只动了 Touch 里的两个文件，且只在 `skip_existing_generation` 那一支加了校验。gate 提示与 1.1/2.1 共用 Touch：稻草人证明了 1.2 有自己的红（拿掉这几行，1.1 的检查全绿而 1.2 的红出来），不是一个行为切两半。
      - Findings: none
    - Blocker: none
    - Reauthorizations: none

## 2. 覆盖摘要与逐组合进度

- [x] 2.1 开跑前与结束时各打一行覆盖摘要，每个组合打 `[i/N]`
  - Covers:
    - guardrail-scope / 扫参必须报告它这一轮实际覆盖了哪些组合
    - guardrail-scope / 扫参必须报告它这一轮实际覆盖了哪些组合 / 一轮完整扫参
    - guardrail-scope / 扫参必须报告它这一轮实际覆盖了哪些组合 / 启用跳过开关、只补了一部分
    - guardrail-scope / 扫参必须报告它这一轮实际覆盖了哪些组合 / 扫参中途被打断
    - D3（`[i/N]` 的 i 是组合序号，含被跳过的）
    - D4（摘要两行；结尾那行重数一遍记录，不是加出来的）
    - D5（结尾摘要写在 `finally` 里）
  - Touch:
    - scripts/sweep.py
    - tests/test_sweep.py
  - Verify:
    - Strategy: vertical-tdd
    - M1: 组合总数 N、本代已有 N-3 条时，开跑摘要同时给出总数/已有数/本轮要跑 3 条与匹配口径那行，结尾摘要给出本轮 3 条与本代 N/N Fails with: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M2: 让 `run_experiment` 少写一条记录时，结尾摘要显示 N-1/N 而不是 N/N（该数是重数记录得来的，不是加出来的） Fails with: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M3: 第三个组合抛异常时异常继续外抛，而结尾摘要已经打出且反映已跑完的 2 条 Fails with: `TypeError: sweep() got an unexpected keyword argument 'log_path'`
    - M4: 被跳过的组合也打 `[i/N]`，序号与未跳过的连续，最后一个是 `[N/N]` Fails with: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M5 (regression): 不开任何跳过开关时摘要照打、口径那行写「无（全部重跑）」，且摘要里不出现用「全部 / all」描述一个并非全部执行的集合
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:d23aab510fb478ecb38f48efae9ab0c0beb0398f4a34bc47656ced592385f7a8
    - M1: `pytest tests/test_sweep.py -k summary_reports_total` → 1 passed。72 组合 / 本代已有 69 / 本轮 3 条，实跑一次的真实输出：`# sweep adder32: 共 72 个组合，已有 69 条，本轮要跑 3 条` + `#   跳过口径: (design, params, flow.fingerprint)，本代 bbbbbbbb —— 只看记录在不在，不看 sim.passed` + `# sweep adder32 结束: 本轮跑了 3 条，本代现有 72/72 个组合`。
    - M1.red: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`（实现 `git checkout` 掉之后实测）
    - M1.green: 1 passed, 13 deselected in 0.04s
    - M2: `pytest tests/test_sweep.py -k closing_count_is_recounted` → 1 passed。替身第 2 条跑了但不落盘，结尾摘要给 `71/72`。
    - M2.red: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M2.green: 1 passed, 13 deselected in 0.04s
    - M2.strawman: 把结尾的重数换成 `have + ran` → `AssertionError: 结尾摘要把跑过但没落盘的那条算进去了：… 本代现有 72/72 个组合`。重数这件事是这条判据的全部内容。
    - M3: `pytest tests/test_sweep.py -k printed_even_when_a_combo_fails` → 1 passed。第 3 个组合抛 `RuntimeError`，异常继续外抛，结尾摘要已打出且写着本轮 2 条。
    - M3.red: `TypeError: sweep() got an unexpected keyword argument 'log_path'`
    - M3.green: 1 passed, 13 deselected in 0.03s
    - M3.strawman: 把 `try/finally` 换成顺序执行 → `AssertionError: 扫参中途失败，结尾摘要一个字都没打`。
    - M4: `pytest tests/test_sweep.py -k contiguous_progress_index` → 1 passed。`[1/72]`…`[72/72]` 一个不缺，被跳过的 69 个也各占一个序号。
    - M4.red: `TypeError: sweep() got an unexpected keyword argument 'skip_existing_generation'`
    - M4.green: 1 passed, 13 deselected in 0.04s
    - M4.strawman: 把序号改成「本轮第几条」→ `AssertionError: 缺了 69 个进度标记，例：['[4/72]', '[5/72]', '[6/72]']`。
    - M5: `pytest tests/test_sweep.py -k without_a_switch_the_summary` → 1 passed。不开开关时口径那行是 `无（全部重跑）`；开了按代跳过、跳了 69 条的那一轮，摘要行里不含「全部」/「all」。
    - Review:
      - Status: pass
      - Acceptance check: 「跑完了」与「跳过了一大半」在输出上可区分（D4），中断位置可从日志直读（D3），失败路径上摘要照打（D5）。三条都各有一个稻草人证明不是空过。
      - Scope check: 只动了 Touch 里的两个文件。gate 提示与 1.1/1.2 共用 Touch：本任务的三个稻草人分别只动摘要计数、`finally`、序号来源，1.1/1.2 的检查在这三种稻草人下全绿 —— 三者不是一个行为切三半。
      - Findings: none
    - Blocker: none
    - Reauthorizations: none

## 3. 入口与说明

- [x] 3.1 `make sweep` 透传新开关；`CLAUDE.md` 与 Makefile 帮助写清两者的区别
  - Covers:
    - D2（报错文本要写清两者口径 —— 前提是文档先把口径写清）
    - I1、I2、I3、I5（本变更让这些措辞变旧）
  - Acceptance:
    - `flow/Makefile` 不做互斥判断 —— 拦截逻辑只写一份，在 Python 侧（design.md
      的 Risks 一节，以及 `flow/Makefile` 开头「Makefile 里不长流程逻辑」那条）。
  - Touch:
    - flow/Makefile
    - CLAUDE.md
  - Verify:
    - Strategy: evidence-first
    - Reason: 文档与一行变量透传，没有可以先失败的行为 —— 透传本身由 M1 用真实命令观察。
    - M1: `make -n -f flow/Makefile sweep DESIGN=adder32 SKIP_EXISTING_GENERATION=1` 的命令行里出现 `--skip-existing-generation`，同时给两个变量时两个参数都在（Makefile 不拦，由 Python 侧报错）
    - M2: `make -f flow/Makefile help` 的变量清单里有 `SKIP_EXISTING_GENERATION`
    - M3: `CLAUDE.md` 里两个开关各有一行写明它按哪些字段匹配，且不再有「两个容易误用的开关」这种与实际条数不符的措辞
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:2fd765e7d51240f11975bbe767f52356256ccf9768958ae54055d2227a494113
    - M1: `make -n -f flow/Makefile sweep DESIGN=adder32 SKIP_EXISTING_GENERATION=1` 的命令行末尾是 `--skip-existing-generation`；两个变量都给时命令行里 `--skip-existing` 与 `--skip-existing-generation` 都在（Makefile 不拦）。真跑那一条：`make: *** [flow/Makefile:71：sweep] 错误 2`，stderr 以 `FLOW-ERROR: --skip-existing 与 --skip-existing-generation 不能同时给。` 开头。
    - M2: `make -f flow/Makefile help` → `变量: DESIGN(必填) PARAMS LIBERTY SIM PERIOD_NS RUN SKIP_EXISTING SKIP_EXISTING_GENERATION`。
    - M3: `CLAUDE.md:64` 起的一节改成「容易误用的开关：」，两个跳过开关各有一条写明它匹配 `(design, params)` / `(design, params, flow.fingerprint)`，并写明两者都只看记录在不在、不看 `sim.passed`；`CLAUDE.md:54-55` 的命令清单两条并列。原「两个容易误用的开关」这一与实际条数不符的措辞已不存在（`grep` 无命中）。
    - Review:
      - Status: pass
      - Acceptance check: `flow/Makefile` 里只有两行 `$(if …)` 透传，没有任何互斥判断 —— 拦截逻辑只在 `scripts/sweep.py` 一处，与本文件开头「Makefile 里不长流程逻辑」一致。
      - Scope check: 只动了 `flow/Makefile` 与 `CLAUDE.md`。CLAUDE.md 那一节里「扫参维度必须给全」那条原样保留。
      - Findings: none
    - Blocker: none
    - Reauthorizations: none

## 4. 实证不分代

- [x] 4.1 实测本变更不改变流程指纹、不动任何既有记录
  - Mode: diagnose-only
  - Covers:
    - A1（本变更不改变任何既有记录，也不分代）
    - A2（`flow_fingerprint()` 开跑前调一次的开销可忽略）
    - F1（三个文件都不在 `METRIC_MODULES` 里）
  - Touch:
    - none
  - Verify:
    - Strategy: evidence-first
    - Reason: 这是对已完成实现的观察，不产出任何被测行为；它要证的是「什么都没变」，而「什么都没变」没有可以先失败的红。
    - M1: `flow/flow_fingerprint.py --liberty <合并库>` 报出的 `fingerprint` 等于当前代 `sha256:0c80b2af…`，与本变更前逐字相同
    - M2: `git show HEAD:results/experiments.jsonl` 与工作区那份逐字节相同（`cmp`），本变更一行记录都没动
    - M3: `.venv/bin/python3 -m pytest tests/ -q` 全绿，通过条数不少于本变更前的 146
    - M4: `./scripts/fast_check.sh` 以 0 退出
    - M5: `flow_fingerprint(liberty)` 的墙钟耗时实测值记进 Evidence（A2 的 Resolve by）
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:57422a26f5d6db08c307bc595922a30780bab66770fcc4cccd682e2468db862b
    - M1: `.venv/bin/python3 flow/flow_fingerprint.py --liberty ~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib` → `"fingerprint": "sha256:0c80b2af014dec58d721a109709e184a63c59f4e9fe33bb65f832ccab56bb75f"`，与本变更前的当前代逐字相同 —— **没有换代**。F1 成立：`scripts/sweep.py` / `flow/Makefile` / `tests/test_sweep.py` 都不在 `METRIC_MODULES` 的七项里。
    - M2: `cmp <(git show HEAD:results/experiments.jsonl) results/experiments.jsonl` → 无输出（逐字节相同），1269 行。红线 2 未被触碰。
    - M3: `.venv/bin/python3 -m pytest tests/ -q` → `163 passed, 6 warnings in 514.58s`。本变更前是 **149**（`--collect-only --ignore=tests/test_sweep.py` 实测），新增 14 条全在 `tests/test_sweep.py`。任务里写的「146」是授权时凭记忆写的旧数，实测基线是 149；163 ≥ 149，判据成立。
    - M4: `source ~/tools/env.sh; ./scripts/fast_check.sh` → 退出码 0，覆盖摘要九类检查**全部标为已执行**（含 5 个设计的 RTL elaborate、adder32 的 288 个参数组合），没有一条「未执行」。
    - M5: `flow_fingerprint` 那次调用的整进程墙钟 **0.18 s**（`/usr/bin/time`，含解释器启动与读 40 MB 合并库）。A2 的阈值是 2 s，不需要回写 design.md。相对一次动辄几十分钟的扫参可忽略。
    - Review:
      - Status: pass
      - Acceptance check: A1 成立（指纹未变 + 记录逐字节未动），A2 成立（0.18 s），F1 由 M1 直接证实。
      - Scope check: diagnose-only，没有写任何文件；`git status` 显示的改动仅为 1.1/1.2/2.1/3.1 四个任务 Touch 里的 `CLAUDE.md`、`flow/Makefile`、`scripts/sweep.py`、`tests/test_sweep.py` 与本变更自己的 tasks.md。
      - Findings: 任务授权时把测试基线写成 146，实测是 149。判据本身不受影响（163 ≥ 两者），但「凭记忆写基线数」这件事值得记 —— 已在 M3 的 Evidence 里更正。 Discard reason: 已在本任务的 M3 Evidence 里改正并说明来源，无遗留动作。
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "两个容易误用的开关：" —— `CLAUDE.md` 的「常用命令」一节。本变更之后是三个。 Updated by: 3.1
- I2: "`SKIP_EXISTING` 的匹配依据**只有参数组合、不含代码版本** —— 同一组合在不同 commit
  下结果可能不同，跳过就漏掉重测。所以它默认关闭。" —— `CLAUDE.md`。这句话本身仍然成立，
  但它现在是两种口径中的一种，必须与另一种并列写出来，否则读者会以为只有这一种。 Updated by: 3.1
- I3: "make -f flow/Makefile sweep  DESIGN=adder32 SKIP_EXISTING=1   # 续跑中断的扫参"
  —— `CLAUDE.md` 的命令清单。「续跑中断的扫参」在换代重跑的语境下会被读成本变更要解决的
  那件事，而它恰恰不是。 Updated by: 3.1
- I4: "变量: DESIGN(必填) PARAMS LIBERTY SIM PERIOD_NS RUN SKIP_EXISTING"
  —— `flow/Makefile` 的 `help` 目标。 Updated by: 3.1
- I5: "# SKIP_EXISTING=1 跳过记录中已有的组合（续跑中断的扫参）"
  —— `flow/Makefile` `sweep` 目标上方的注释。 Updated by: 3.1
- I6: "python scripts/sweep.py --design adder32 --liberty <path> --skip-existing"
  —— `scripts/sweep.py` 的模块 docstring，用法示例里没有新开关。 Updated by: 1.1
- I7: "skip_existing 是显式开关，默认关闭。" 与其下「匹配依据只有参数组合，**不含代码版本**」
  —— `scripts/sweep.py` 的 `sweep()` docstring。现在有两个开关，docstring 要说清两者。 Updated by: 1.1
- I8: "记录中已有的参数组合，用于 --skip-existing。" —— `scripts/sweep.py` 的
  `existing_combos()` docstring。该函数从此也服务于按代跳过。 Updated by: 1.1

## Expectation Coverage

- E1: 换代重跑被打断后，一条命令只补本代还缺的组合，匹配键含流程指纹。 Covered by: 1.1
- E2: 两个口径不同的跳过开关同时启用必须报错，不得静默择一。 Covered by: 1.1
- E3: 「已有」的判定不看 `sim.passed`，且这一点要写进摘要的口径说明。 Covered by: 1.1, 2.1
- E4: sweep 过滤所依据的指纹与记录实际写入的指纹不一致时必须中止。 Covered by: 1.2
- E5: 覆盖摘要在正常结束与中途失败两条路径上都输出，且给出总数/跳过数/实跑数与匹配口径。 Covered by: 2.1
- E6: 结尾摘要的「本代现有」是重数记录得来的，不是加出来的。 Covered by: 2.1
- E7: 逐组合 `[i/N]` 进度，序号连续且含被跳过的，使中断位置可从日志直读。 Covered by: 2.1
- E8: `--skip-existing` 的语义一个字符都不变。 Covered by: 1.1, 3.1
- E9: 本变更不产生新的一代，既有 1269 行记录一字节不动。 Covered by: 4.1
- E10: `scripts/sweep.py` 第一次有测试（它是唯一能一次写 72 条记录的入口）。 Covered by: 1.1, 1.2, 2.1
- E11: 互斥拦截只实现一份，在 Python 侧；Makefile 只做透传。 Covered by: 3.1
