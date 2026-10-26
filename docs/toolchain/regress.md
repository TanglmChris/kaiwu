# 工具链：回归、扫参组合与逻辑级数

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

## 自检型 TB 的分层回归（内部#83）

设计迭代时的 SV 自检 TB 回归走仓库内的固定入口，不再靠会话 scratchpad 里的脚本。**`inner` 是设计侧的内循环；`full` 由验证侧在发布之后跑，设计侧提交前不跑**（用户 2026-10-04，内部#149，见 `team/roles/kaiwu-design/README.md`「设计侧的自测范围」）：

```bash
make -f flow/Makefile regress DESIGN=<顶层>            # 内循环（TIER=inner），改完 RTL 先跑
make -f flow/Makefile regress DESIGN=<顶层> TIER=full  # 全量：验证侧在发布之后跑（内部#149）
make -f flow/Makefile regress DESIGN=<顶层> TIER=full SIM=icarus   # 换 Icarus 交叉核对
.venv/bin/python3 flow/verify/regress.py --design <顶层> --tier full --list   # 只看会跑哪些
```

- **清单**：设计根的 `tb/regress.<顶层>.yaml`，两层的组合只写在这一处。格式见 `flow/verify/regress.py` 文件头。
- **去重**：按补齐 TB 默认值（`parameter` 声明）后的完整参数去重。
- **调度**：一个任务池，按上次实测时长降序提交，没实测过的排最前；时长按仿真器分开记在 `runs/regress/<顶层>/durations.<仿真器>.json`。
- **并行度**：默认 4（`JOBS=` 覆盖），与「CPU 预算」那条约定一致。
- **判据**：最后一行 `done` 行必须匹配 `pass`。以下都算失败：没有 `done` 行、编译失败、超时。
- **运行期参数**：清单里 `runtime:` 声明的参数以 `+NAME=值` 传给仿真，编译键相同的作业只编译一次（内部#83 的 C）。
- **仿真器**：默认 Verilator（`verilator --binary --timing`，结构参数用 `-G`），`SIM=icarus` 换 Icarus（内部#83 的 D，用户 2026-10-03 定默认 Verilator）。注意 `make` 的其他目标（cocotb 流程）里 `SIM` 默认仍是 icarus，只有 `regress` 在命令行没给 `SIM` 时取 verilator。TB 要同时能在两种仿真器下跑，有两点写法差异：
  - 随机数要自己播种：Verilator 的 `$urandom(seed)` 不给后续的 `$urandom` 播种，TB 要自带随机数发生器（如 xorshift32）；
  - Verilator 下 `$finish` 之后同一块里的语句照样执行。
- **用时**：各设计的实测见设计根 `doc/process.<顶层>.md`。
- **TB 跟设计分支走**：main 上的 TB 可能比设计分支旧，在 main 上跑 `full` 会因缺参数而编译失败。在设计 worktree 合 main 之后跑。

## 扫哪些组合：叉乘、exclude、sweep_points（内部#138、内部#214）

`params.yaml` 的 `tops:<顶层>:` 下有三样东西决定跑哪些组合。展开与校验只在 `flow/param_exclude.py` 一处实现，fast_check、sweep、`synth.py` 的读入集合三处都调它：

| 声明 | 含义 | 写错时 |
|---|---|---|
| `exclude: [{参数: 值, …}]` | **非法**组合：命中任一项的组合不 elaborate、不扫参 | 键没声明、值不在 values 里、全部被排除，当场点名 |
| `sweep_points: [{name, <全部参数>: 值}]` | **目标点**：声明了就只扫这张表；fast_check 覆盖「叉乘 − exclude」∪ 这些点 | 缺参数、多参数、值不在 values 里、命中 exclude、name 重复、两点相同，当场点名 |
| 参数下 `cross: false` | 不进叉乘：叉乘里只取 `values[0]`，其余取值只经 `sweep_points` 出现 | 其余取值没有任何点覆盖时点名（否则永远 elaborate 不到） |

- 按点名跑（内部#332）：`make exp POINT=<点名>`、`make depth POINT=<点名>`、`make sweep POINTS="<点名> <点名>"`，参数原样取自 `sweep_points` 那一项，不再手抄；点名写错会列出全部点名，`POINT=` 与 `PARAMS=` 不能同时给，`depth` 指定子模块时不认 `POINT=`。
- 目标配置用 `sweep_points` 写，不用 exclude 从叉乘里挑：exclude 的语义是非法；挑出来的那些合法组合也会从快检覆盖里消失。
- `cross: false` 用在「只在目标点里取别的值」的参数上：叉乘不翻倍，快检保持 10 s 级。
- 记录的 `params` 段形状不变，点名不进记录。`SKIP_EXISTING` / `SKIP_EXISTING_GENERATION` 照旧按 params 匹配。
- 读入集合（`synth.sources_sha256`）只探「叉乘 ∪ 点表」。`make exp` 跑一个两者都不含的组合时，若用到没读进来的模块，yosys 会当场报错，不会静默。

## 不写记录地量逻辑级数（内部#111）

写 RTL 时要决定切不切流水，先量级数：

```bash
make -f flow/Makefile depth DESIGN=<顶层> MODULE=<子模块> PARAMS="<参数>=<值> …"
.venv/bin/python3 flow/synth/depth.py --design CBB_LZD --param DAT_W=16 --param MSB_EN=0 --param SCHEME=0
```

- `MODULE` 默认就是 `DESIGN`，可以是它源文件集合里的任一子模块；`PARAMS` 是该模块的参数，不给取 RTL 默认值。
- `POINT=<点名>` 按被测顶层的 `sweep_points` 取全部参数（不能和 `PARAMS` 同给，指定子模块时不认）；`REF=<提交>` 在该提交的临时检出里量（`scripts/at_ref.py`：detached worktree、软链 `.venv`、核干净，输出首行 `ref <完整提交号>`，量完删掉），不用手工建 worktree（内部#332）。
- 综合配方、ABC 约束、liberty 与实验流程相同，级数按 `run_sta` 同一套规则从最坏路径数出；输出级数、到达时间
  （liberty 时间单位，ASAP7 为 ps）、起止点、cell 数，产物在 `runs/depth/<模块>-<参数摘要>/`。
- **不是记录口径**：不施加 `keep_hierarchy`、不仿真、不出功耗，STA 约束是最简的（有 `clk` 就在它上面建时钟，
  否则虚拟时钟；IO 外部延时 0）。数字用来指导设计，报 PPA 仍走 `make exp`。

- **时钟**（内部#167）：量被测顶层时按它的 `sta.clocks` / `clock_groups` 建钟，与正式 STA 同一份声明；量子模块时只看它自己的 `clk` 端口，没有就建虚拟时钟。声明的时钟端口在网表里不存在时报错。
- **不计时序的起点**（内部#154）：量被测顶层时用它的 `sta.static_ports`（与正式 STA 同一份声明，见「静态端口排除在时序分析之外」）；`FALSE_FROM="<模式> …"` 另给（默认 `*rst_n*`，`none` 关掉）。量子模块时端口名与顶层不同（如子模块的 `rst_n` 对顶层的 `top_rst_n`），靠它排除复位与静态配置。
- **多条路径**：`PATHS=N` 按级数降序列出最深的 N 个终点（起点、终点、级数），做整体级数核算用：

  ```bash
  make -f flow/Makefile depth DESIGN=<顶层> MODULE=<子模块> FALSE_FROM="rst_n *_cfg*" PATHS=20
  ```

  `PATHS` 只列最深的 N 个，**不能当验收**：深的那批会占满名额，后面超标的看不见（内部#184：R006 的第二批 31–36 级
  就是这样晚了两天才冒出来）。

- **先定目标配置，再收时序、扫 PPA**（G1，内部#195）：每份目标配置写全结构参数、静态配置的定值、运行时会不会切换，
  写进设计根的 `params.yaml`（`sweep_points`、`sta.scenarios`）与 `ppa.<顶层>.md`；时序验收的格子与 PPA 点都从目标配置推出来，不另起一套。
- **转述时序数要带口径**（G2，内部#195、内部#207）：写「参数组 × 场景」，写明是组合单元数还是报告行数，每组附最深路径的起点 → 终点；
  参数组按参数取值命名，不用排布名命名（排布由场景定值决定，同一组参数可以量两个场景）。
- **时序验收：顶层一次综合，超过预算的终点数 = 0**（内部#184，用户 2026-10-05）：

  ```bash
  make -f flow/Makefile depth DESIGN=<顶层> PARAMS="…" BUDGET=30
  ```

  **`BUDGET` 是组合单元数**（内部#207，用户 2026-10-05 定「30 级」= 30 个组合单元）：一条路径上组合单元的个数，
  ABC 插的缓冲与反相器照算；不算起点寄存器的 CLK / Q 与终点的 D / 输出端口。它和报告行数（下面「级数」那条的口径，
  即记录里的 `critical_path_stages`）差一个常数：寄存器起点时行数 = 组合单元数 + 3，输入端口起点时 + 2。
  这一口径写在契约 `openspec/specs/logic-depth/spec.md`「预算按组合单元个数比，报告行数另计」，原则见 `docs/spec-writing.md` 第 8 节（内部#286）。
  **2026-10-05 之前**（内部#207 落地前）`BUDGET` 比的是报告行数，`BUDGET=30` 实际只放行约 27 个组合单元。
  给了 `BUDGET` 就列出**全部**组合单元数超过它的终点，不受 `PATHS` 截断：总数、按「起点模块 → 终点模块」（实例层次前两级）
  分组的个数与最深的组合单元数 / 报告行数（两种数都列，避免和以前的数混淆）、每组最深的 3 条；每个终点最深一条的完整引脚序列在 `runs/depth/…/over_budget.tsv.gz`（每终点只留一条并 gzip，内部#225；原来一份约 50 MB）。
  两次结果按终点集合比：`.venv/bin/python3 flow/synth/depth_compare.py <A> <B>`（tsv.gz 或 depth 产物目录），列出消失 / 新出现的终点、
  共有终点的组合单元数变化、最深起止点是否换了；两次要用同一个 `BUDGET`。
  同一终点的路径按模块并排比（内部#340）：加 `--composition`，列共有终点里模块构成变了的（总数不变、只是单元在模块之间挪了的也列）；
  或用 `--endpoint <终点>` 只看指定终点；`--levels 3` 把模块再往下分一级（例如把 RDAT 本体和它里面的 ECC CBB 分开）。
  每个终点一张表：模块、A 个数、B 个数、差值，合计等于该终点记下的组合单元数。数据取 tsv 第 5 列的路径引脚，不重跑 STA；
  旧版 depth 的产物没有这一列，要重跑。有超标终点时
  退出码为 1，可以直接当判据。
  - **按验收场景分开量**（内部#189，PM 2026-10-05）：几种排布由静态输入选择、互斥时，不分场景会把永远不会同时激活的组合
    路径算进来误报。在该顶层的 `params.yaml` 声明 `sta.scenarios`，每项 `{name, case: {端口: 值}, by: R.<编号>}`
    （`by` 是 LRS 里担保这个输入是静态的需求，fast_check 核它有定义、端口是输入、值不超位宽）。声明了场景，
    `make depth` 综合一次，每个场景用 `set_case_analysis` 给这些输入定值各跑一遍 STA，逐场景打印；**任一场景**超标就
    退出 1。各场景的报告是 `runs/depth/…/checks.<场景>.rpt`、`over_budget.<场景>.tsv.gz`。没声明就照旧量一遍。
    **场景可以限定适用的参数组合**（内部#198，用户 2026-10-05 定）：加
    `when: {参数: 值 | [值, …]}`，各键之间是「与」，值列表是该参数的「或」；键与值都要在 params.yaml 里声明过。
    只量本组合匹配的场景；没写 `when` 的对所有组合适用。`when` 用到的参数要在 `PARAMS` 里给出，不补默认值。
    没有适用场景时照旧不定值量一遍，输出里写明。例：
    `- {name: case_a, case: {cfg_mode: 1, …}, by: R.021, when: {WIDTH: 64}}`。
    同一份声明（解析在 `flow/paths.py::scenarios`）也用于正式 STA（sta-scenarios，用户 2026-10-05 定选项 A）：
    记录的 `sta.scenarios` 写本组合**适用的**每个场景定值后的时序与 analytic fmax（TT 一层，SS / FF 在 `corners`）
    及它的 `when`，列出的就是这个组合量了哪些场景；未声明或没有适用场景为 `[]`。
    主字段 `sta.fmax_mhz` 等**不变**，仍是不定值的那次 STA，即各场景最坏；场景延时大于主字段时写记录前报错。

- **参考口径（内部#202，用户 2026-10-05 定「两种口径都报」）**：`make -f flow/Makefile exp DESIGN=… PARAMS="…" REFERENCE=1`
  在正式流程之后另量一份参考值，写进**同一条记录**的 `reference`（不开为 `null`，sweep 不开）。
  - 口径：同一份 RTL、同一组参数，把本组合**唯一**适用场景的 `case` 在顶层接成常数，`synth -hieropt` 跨层次传常数、
    删掉用不到的逻辑；声明了 `keep_hierarchy` 的照保；映射与 ABC 配方与正式口径相同，延时目标取正式口径胜出的那一档。
    `opt_hier` 撞空输出连接的问题按 P-20 绕开（删掉 RTLIL 里的空连接）。实现在 `flow/synth/reference.py`。
  - 量：综合（面积、单元数、按层次的面积）、TT / SS / FF 时序（含关键路径级数与起止点、analytic fmax）、depth（预算 30 个组合单元，内部#207）。
    功耗不量。参考网表与接了常数的 RTL 做网表等价（**可选**，用户 2026-10-06 定，内部#232：设计在 `tops:<顶层>:equiv: false`
    声明不做时，`reference.equiv` 记 `SKIPPED`，照常报数，报告「等价」列写「未经等价验证」；
    事后的 `netlist_equiv.py` 也跳过声明了的设计；选中的记录全部被跳过时结论写 SKIPPED、退出 3，与「一条都没选中」的 1 分开，内部#333）。做了而结论不是 PROVED（UNDECIDED / FAILED）时正式记录照写，
    `reference` 只留场景、`case`、延时目标、`equiv` 与证明日志路径（`runs/<id>/equiv_reference/equiv.log`），
    不报参考的面积与时序，报告里标「未证等价（…），不报数」（内部#202，PM 转用户同意）。
  - 设计可在 `tops:<顶层>:synth:reference_ports:` 声明必须接常数的端口模式（如 `[cfg_*]`）：
    场景的 `case` 漏定一个就报错。
  - 成本：多一次综合、三个角的 STA、一次 depth、一次网表等价（大设计单进程可到几 GB，内部#188）。**单条串行跑**：
    sweep 不开它；跑 `REFERENCE=1` 的那段时间不和扫参或别的等价证明并行（两路等价叠起来约 15 GB）。
  - 量**被测顶层**，不量分模块：模块边界会截断跨模块路径，各模块单独都不超、到顶层才超的那批只有顶层看得见。分模块量只作调试。
  - 「级数」（`stages`、`PATHS` 的列表、记录里的 `critical_path_stages`）按正式 STA 报告的同一套规则数报告行数
    （起点寄存器的 CLK 与 Q、每个组合单元的输出、终点的 D 或输出端口各算一行），口径不变；与 `BUDGET` 比的是
    组合单元数，见上面「时序验收」。
  - **近似，不是穷举**：OpenSTA 按延时给每个终点挑路径，级数最深的那条未必是延时最长的那条。这里每个终点看延时
    最坏的 3 条、取级数最大的。级数深但延时短的路径（例如全是快单元）理论上可能漏掉。
