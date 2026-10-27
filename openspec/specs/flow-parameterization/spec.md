# flow-parameterization Specification

## Purpose

规定参数属于设计、不属于流程。

流程代码不认识任何一个具体设计：它不知道 `adder32` 有 `CARRY_STRUCT`，也不知道
`CBB_LZD` 有 `MSB_EN`。这些全部由设计根自己的 `params.yaml` 声明，流程
只负责读取、叉乘、传递。设计相关的仿真配置同理，由设计声明而非流程内置。

参数取值 MUST 原样落进实验记录 —— 记录里的 `params` 就是这次实验实际用的那组值，
不做归一化、不补默认值。这是「记录自解释」在参数这一侧的体现。

`sweep: false` 是一个逃生口：某些参数只对特定取值组合有意义（例如 `CSEL_BLOCK` 只
对 `CARRY_STRUCT=CSEL` 有意义），进全量叉乘会产生大量无意义组合。标记之后它恒取
第一个取值，要扫就显式 `make exp`。代价是护栏的覆盖面随之缩小，这一点必须被知道
而不是被发现。

除此之外**扫参维度必须给全，缺一个就报错** —— 这个守卫是有意的：默默替你补上一个
默认值，产生的记录会带着一个你以为没在用的参数。

## Requirements

### Requirement: 流程参数必须由 params.yaml 驱动

流程的参数接口 MUST 以设计无关的映射（参数名到取值）传递，MUST NOT 把具体设计的
参数名写进函数签名。可取的参数名与取值范围 SHALL 由该设计根下的 `params.yaml` 声明。
参数声明 MAY 附带控制扫参行为的元数据（见「参数可以被声明为不参与全量扫参」），
该元数据 MUST NOT 使流程代码依赖任何具体设计的参数名。

#### Scenario: 加入一个参数集完全不同的新设计

- **WHEN** 新增一个设计，其 `params.yaml` 声明的参数名与 `adder32` 完全不同
- **THEN** 该设计可以跑完整实验流程
- **AND** `flow/` 与 `scripts/` 下没有任何文件为此需要修改

#### Scenario: 传入 params.yaml 未声明的参数

- **WHEN** 以一个 `params.yaml` 中未声明的参数名发起实验
- **THEN** 流程报错并指出该参数名未被声明
- **AND** 不执行仿真、综合或 STA

#### Scenario: 传入声明范围之外的取值

- **WHEN** 以某个已声明参数的、不在其 `values` 列表内的取值发起实验
- **THEN** 流程报错并列出该参数的合法取值

#### Scenario: 参数声明携带扫参元数据

- **WHEN** 某参数声明中带有 `sweep` 字段
- **THEN** 流程按该字段决定它是否进入全量叉乘
- **AND** 流程代码中不出现该参数的名字字面量

### Requirement: 参数取值必须原样落进实验记录

写入 `results/<设计根>/experiments.jsonl` 的 `params` 段 MUST 包含本次运行的完整参数取值，
其键 SHALL 与流程实际使用的参数名一致。

#### Scenario: 记录可复现一次运行

- **WHEN** 读取任意一条实验记录的 `params` 段
- **THEN** 仅凭该段与 `design` 字段即可重新发起同一次实验

### Requirement: 设计相关的仿真配置必须由设计声明

流程代码 MUST NOT 内嵌任何具体设计的信号命名假设。仿真活动统计所需的时钟信号名
SHALL 由设计自己声明；设计未声明时，流程 MAY 采用一个有文档的约定作为回退，
但回退失败 MUST 报错而不是给出替代值。

**该声明同时是 STA 建立时序环境的依据。** 时钟端口名在流程里 MUST 只有一个
来源：仿真侧按它统计周期数，STA 侧按它 `create_clock`。两处各自写死一个名字
会让「设计改了时钟端口名」这件事只在其中一处生效，而另一处静默走进回退 ——
STA 那一侧的回退尤其危险，工具找不到端口时只报一句警告就建一个虚拟时钟，
照常出数（见 `experiment-trust`）。

设计声明自己**没有时钟**时，STA MUST 显式建立一个不绑定端口的时钟，
MUST NOT 把「按端口名去找、找不到」当作达到同一效果的手段。

同理，**STA 按理想驱动建模的那些输入端口** SHALL 由设计自己声明。流程 MUST NOT
在代码里写死任何具体端口名。未声明时流程 MUST 按"全部输入端口都由约定的驱动单元
驱动"处理，MUST NOT 自行猜测哪个端口是复位。

#### Scenario: 设计声明了时钟信号名

- **WHEN** 设计在自己的配置中声明了时钟信号名
- **THEN** 活动统计使用该名字
- **AND** STA 用同一个名字建立时钟
- **AND** 流程代码中不出现任何具体设计的信号名字面量

#### Scenario: 设计未声明时钟信号名

- **WHEN** 设计未声明时钟信号名
- **THEN** 流程按有文档的约定推导一个名字
- **AND** 该名字在 VCD 中不存在时报错（见 experiment-trust）

#### Scenario: 纯组合设计没有时钟

- **WHEN** 设计声明自己没有时钟
- **THEN** 活动统计跳过周期计数，`cycles` 为 `null`
- **AND** STA 显式建立一个不绑定端口的时钟
- **AND** 命令成功，不报错

#### Scenario: 设计改了时钟端口名

- **WHEN** 设计把时钟端口改名并在配置里同步声明
- **THEN** 仿真侧与 STA 侧同时跟着改
- **AND** 两侧 MUST NOT 出现只有一侧生效的情形

#### Scenario: 设计声明了按理想驱动建模的端口

- **WHEN** 设计声明某些输入端口按理想驱动建模
- **THEN** STA 不给这些端口设置驱动单元，其余输入端口照常设置
- **AND** 流程代码中不出现任何具体设计的端口名字面量

#### Scenario: 设计没有声明任何理想驱动端口

- **WHEN** 设计未声明该项
- **THEN** 全部输入端口（时钟除外）都被设置为由约定的驱动单元驱动
- **AND** 流程 MUST NOT 按名字猜测哪个端口是复位

### Requirement: 参数可以被声明为不参与全量扫参

`params.yaml` 中的每个参数 MAY 携带一个布尔字段 `sweep`（缺省为 `true`）。
`sweep: false` 的参数 MUST 仍然是合法参数名（可以显式指定取值、取值范围照常校验），
但 MUST NOT 参与 `sweep.py` 构造的全量参数叉乘。

动机是"只对某些其他参数取值有意义"的参数：把它放进叉乘会产生大量
参数标签不同、实际电路相同的冗余记录，污染 `results/<设计根>/experiments.jsonl`。

#### Scenario: 扫参时跳过被标记的参数

- **WHEN** 某设计的 `params.yaml` 中有一个参数标记为 `sweep: false`
- **AND** 对该设计发起一次全量扫参
- **THEN** 生成的参数组合数等于其余参数（`sweep` 为真的那些）取值个数的乘积
- **AND** 每个组合中该参数取其 `values` 列表的第一项

#### Scenario: 被标记的参数仍可显式指定

- **WHEN** 以显式取值发起单次实验，该取值属于某个 `sweep: false` 参数的 `values` 列表
- **THEN** 实验正常执行
- **AND** 该取值原样落进记录的 `params` 段

#### Scenario: 被标记的参数取值仍受校验

- **WHEN** 以某个 `sweep: false` 参数的、不在其 `values` 列表内的取值发起实验
- **THEN** 流程报错并列出该参数的合法取值
- **AND** 不执行仿真、综合或 STA

### Requirement: 只有不参与扫参的参数可以省略取值

发起单次实验时，`sweep: false` 的参数 MAY 省略取值，此时流程 SHALL 取其
`values` 列表的第一项。参与扫参的参数（`sweep` 缺省或为真）MUST 仍然强制给出取值，
省略 MUST 报错。无论取值来自显式给出还是默认，写入记录的 `params` 段
MUST 包含该设计声明的全部参数键。

放宽只针对 `sweep: false` 参数，是因为它们通常只对其他参数的某些取值有意义，
强制每条命令都写出来没有信息量；而扫参维度的缺失往往是笔误，
保留"缺一个就报错"的守卫。

#### Scenario: 省略一个不参与扫参的参数

- **WHEN** 发起实验时给出了全部扫参维度的取值，但省略了某个 `sweep: false` 参数
- **THEN** 该参数按其 `values` 第一项取值
- **AND** 写入的记录 `params` 段包含该设计声明的全部参数键

#### Scenario: 省略一个扫参维度

- **WHEN** 发起实验时省略了某个参与扫参的参数
- **THEN** 流程报错并指出缺少哪些参数取值
- **AND** 不执行仿真、综合或 STA

### Requirement: 合并 liberty 的基文件必须显式指定且可验证

合并多份 liberty 时，作为**基文件**的那一份 MUST 由命令显式指定，
MUST NOT 由参数位置隐式决定。

理由是基文件的正文整段原样进入产物，它还带着 `delay_model`、单位声明、
`operating_conditions` —— 换一个基文件就是另一份产物、另一个 `liberty_sha256`，
也就是另一代记录。而这件事**不会报错**：合并照常成功，产物照常可用，
只是与此前全部记录不可横向比较。靠一句文档约定「某某放第一个」来防它，
失效方式是静默的。

产物的内容摘要 MUST 能区分出**基文件是哪一份**，使「这份库是怎么合出来的」
可验证而不是可推测。

工具 MUST NOT 自己替使用者挑基文件（例如按文件名排序取第一个）：
选谁是一个有后果的决定，交给排序等于把它藏起来。

#### Scenario: 合并时没有指定基文件

- **WHEN** 调用合并命令但没有给出基文件
- **THEN** 命令 MUST 失败并说明缺的是什么
- **AND** MUST NOT 从位置参数里挑一个顶上

#### Scenario: 两次合并只换了基文件

- **WHEN** 对同一批源库合并两次，只把基文件换成其中另一份
- **THEN** 两次产物的内容摘要在**基文件那一项上不同**
- **AND** 使用者因此能判定手上的库是用哪一份合出来的，不必比对整份文件

#### Scenario: 非基源库的给出顺序变了

- **WHEN** 对同一批源库合并两次，基文件相同而其余源库的给出顺序不同
- **THEN** 两次产物逐字节相同
- **AND** 内容摘要的每一项都相同

### Requirement: 设计可以声明多个时钟，跨域约束必须显式

设计 SHALL 能在自己的配置里声明**多个**时钟，每个时钟带名字、绑定的端口与周期。
流程 MUST 为每一个声明的时钟建立时序约束，MUST NOT 只建第一个。

周期 MUST 显式给出：写数字，或写 `cli` 表示取命令行的 `--period-ns`（内部#138，用户 2026-10-04）。缺省、`null` 或其他字符串 MUST 报错，MUST NOT 补默认值。同源、同频、同相的时钟（如经门控派生的时钟）写 `period_ns: cli` 并与主时钟放进同一分组，按同步路径定时。

**跨时钟域路径的处理方式 MUST 由声明决定，MUST NOT 由工具默认行为决定。**
设计 SHALL 能声明时钟分组；未声明分组时，流程 MUST 按**每个时钟自成一组、
组间互为异步**处理。

理由是实测的（OpenSTA 3.1.0，2026-09-15）：不设分组时，跨异步域的路径会被
当作真实路径参与 setup 分析，`worst_slack` 取自一条 `clk_a` 发、`clk_b` 收的
路径，required time 用的是 `clk_b` 的边沿 —— 而异步域之间的边沿关系是任意的，
这个数不说明电路的任何性质。工具不会报错，照常给出 `slack (MET)`。
这与「无触发器的实现必须证明其时序结果来自真实路径」是同一类失效：
有数字、不报错、不成立。

默认取「互为异步」而不是「全同步」：多时钟设计里跨域路径需要同步器是常态，
把它们当同步路径分析会产出一批假违例，而假违例会逼人加豁免。
默认取保守的那一侧 —— 少报优于多报一个不成立的数。

#### Scenario: 设计声明了两个时钟但没有声明分组

- **WHEN** 设计声明了两个时钟，未声明 `clock_groups`
- **THEN** 流程为两个时钟各建一个时钟约束
- **AND** 两个时钟被声明为互相异步，跨域路径不参与 setup 分析
- **AND** 记录 MUST 能看出跨域路径是被排除的（见 `experiment-trust`）

#### Scenario: 设计声明了时钟分组

- **WHEN** 设计把若干时钟声明在同一组里
- **THEN** 同组内的时钟之间按同步处理，跨域路径照常分析
- **AND** 不同组之间按异步处理

#### Scenario: 单时钟设计不受影响

- **WHEN** 设计只声明一个时钟（或沿用既有的单时钟声明形式）
- **THEN** 建立的约束与本变更之前逐字相同
- **AND** 记录中三个既有标量的含义一字不变

#### Scenario: 声明的时钟端口在网表里不存在

- **WHEN** 某个声明的时钟，其端口在网表里找不到
- **THEN** 流程 MUST 报错
- **AND** MUST NOT 退回隐式虚拟时钟后照常出数

#### Scenario: 门控派生的时钟取命令行周期

- **WHEN** 设计声明 `core_clk` 与 `core_cg_clk` 两个时钟，`period_ns` 都写 `cli`，并放在同一个 `clock_groups` 里
- **THEN** 流程为两个时钟都按 `--period-ns` 建立约束
- **AND** 两个域之间的路径按同步路径分析

#### Scenario: 周期写成了不认识的字符串

- **WHEN** 某个时钟的 `period_ns` 写成 `same`
- **THEN** 流程 MUST 报错，并说明只能写数字或 `cli`

### Requirement: 每个扫参维度必须声明它改的是功能还是实现

`params.yaml` 里每个**进全量扫参**的参数（即未标 `sweep: false` 的）
MUST 声明 `role`，取值只有两个：

- `microarch` —— 改的是**同一个功能**的实现方式。功能与吞吐不变，
  换的是怎么做。同一条 Pareto 前沿上比较它们是有意义的。
- `scale` —— 改的是**功能本身**：每拍处理多少数据、地址空间多大、
  总线多宽。不同取值之间比较绝对面积/延时是同义反复。

`sweep: false` 的参数不参与前沿，MUST NOT 要求声明。

判据是一句话：**换一个取值之后，这个电路做的活是不是一样多？**
一样多是 `microarch`，不一样多是 `scale`。

这条声明住在 `params.yaml` 而不是报告生成器里，因为「这个参数改的是功能还是
实现」是**设计的性质**，报告生成器无从知道。本仓的证据：`adder32` 的 `WIDTH`
把前沿变成同义反复已经很久，没有任何人发现 —— 前沿照样生成、照样有输出。
把这张对照表维护在生成器里，等于让下一个新设计根重复同一件事。

#### Scenario: 一个进扫参的参数没有声明 role

- **WHEN** 某参数未标 `sweep: false` 且没有 `role`
- **THEN** 读取该声明的工具 MUST 报错并指名是哪个设计的哪个参数
- **AND** MUST NOT 回退到任何默认值

缺省值会**静默**地把一个规模旋钮当成微架构旋钮，产出一张看起来正常的前沿表。
这与本仓 D-1（Annotated 0 不报错）同形：跑通了、有输出、没人问输出是不是在
回答一个有意义的问题。报错是有意的，与「扫参维度必须给全，缺一个就报错」（P-6）
同源。

#### Scenario: 标了 sweep: false 的参数没有声明 role

- **WHEN** 某参数标了 `sweep: false` 且没有 `role`
- **THEN** 这 SHALL 被接受

它不参与全量叉乘，因此不会出现在前沿里，声明它的角色没有意义。

#### Scenario: role 的取值不是这两个之一

- **WHEN** 某参数的 `role` 既不是 `microarch` 也不是 `scale`
- **THEN** 读取该声明的工具 MUST 报错并列出合法取值

### Requirement: 保住层级的模块表必须由设计按被测顶层声明，且声明必须逐个命中

综合时要保住层级的模块表 SHALL 由设计在 `params.yaml` 里**按被测顶层**声明。
流程代码 MUST NOT 内嵌任何具体设计的模块名。

**按顶层声明而不是按设计根**：一个设计根可以挂多个被测顶层，而每个顶层综合时
只读入**它自己的依赖闭包**（`experiment-trust` 的「综合读入的源文件集合必须是
该顶层的依赖闭包」）。按设计根声明时，其中一部分模块在某个顶层的闭包里根本不存在，
于是流程只能接受「声明的 ∩ 读进来的」——**而那恰好让打错的模块名也被放行**。
按顶层声明时每个名字都必须命中，判据是干净的。

**声明 MUST 逐个命中。** 施加属性之后，流程 MUST 确认声明里的每一个模块都真的
存在于本次综合的设计中；有一个没命中就 MUST 失败，并指名是哪一个。
这条不是洁癖：yosys 对选择不到的模块**只打一句警告、退出码 0**（实测
`Warning: Selection "X" did not match any module.`），于是一个打错的模块名会让
那一层**静默地不再被保住**，而综合照常完成、PPA 数字照常写进记录 ——
差异要到有人拿两代数字对比时才可能被注意到，而那时已经分不清是设计变了还是护栏漏了。

未声明该项的顶层 SHALL 按「不保任何层级」处理。流程 MUST NOT 猜测哪些模块
看起来像 building block。

#### Scenario: 顶层声明了要保住层级的模块

- **WHEN** 某个被测顶层在 `params.yaml` 里声明了模块表
- **THEN** 综合 SHALL 对表内每个模块施加保层级属性
- **AND** 流程代码中不出现任何具体设计的模块名字面量

#### Scenario: 声明里有一个模块不在本次综合的设计里

- **WHEN** 声明的模块名拼错，或它不在该顶层的依赖闭包里
- **THEN** 综合 MUST 失败，并指名是哪一个模块没命中
- **AND** MUST NOT 以「yosys 只警告」为由继续
- **AND** MUST NOT 把声明静默缩小成「声明的 ∩ 读进来的」

#### Scenario: 顶层没有声明模块表

- **WHEN** 某个被测顶层未声明该项
- **THEN** 综合不施加任何保层级属性
- **AND** 流程 MUST NOT 按名字或结构猜测哪些模块该被保住

### Requirement: 流程列出的每个仿真器都必须对全部参数组合可用

流程入口（`run_sim.py` / `run_experiment.py` / `sweep.py` 的 `--sim`、`flow/Makefile` 的 `SIM`）
列出的每个仿真器 MUST 对每个被测顶层的全部扫参组合构建、仿真并产出 VCD。一个列在取值里却跑不通的
仿真器 MUST NOT 留在取值里 —— 它看起来是一个可用的旋钮，而它的失败只在有人去拧的那一刻才出现。

仿真器告警的豁免 MUST 与 lint 同一纪律：逐条登记，每条带 `-file` 与 `-match`（消息里的具体
标识符）并写明理由；MUST NOT 整条规则关掉（如 `-Wno-UNOPTFLAT`），MUST NOT 把告警整体降级为
非致命（如 `-Wno-fatal`）。与 lint 相同的告警 SHALL 读同一份豁免文件，不另抄一份。
豁免 MUST NOT 写进 RTL（`rtl-structure-authority`）。

仿真器产出的波形与别的单次原始产物一样 MUST 落在本次运行的 `runs/…/` 目录下，
MUST NOT 落在设计根内（`repo-layout` 的「每类产物必须归属到明确的一层」）。

#### Scenario: 用 verilator 跑进位链是按位向量的设计

- **WHEN** 以 `--sim verilator` 仿真 `ADDER32` 的 `CARRY_STRUCT=RIPPLE`
- **THEN** 构建不因 `UNOPTFLAT` 退出，TB 通过，产出非空 VCD

#### Scenario: verilator 的波形位置

- **WHEN** 以 `--sim verilator` 仿真任一被测顶层
- **THEN** VCD 在本次的构建目录下
- **AND** 设计根下没有新增任何文件（判据是目录内容，不是 `git status`）

#### Scenario: 豁免之外的新告警

- **WHEN** 一个未登记的 verilator 告警出现（哪怕与已登记的同规则、同文件，只是换了信号）
- **THEN** 构建失败，不被既有豁免吞掉

### Requirement: 结构枚举参数的每个编号都必须有名字

`params.yaml` 里名为 `SCHEME` 或以 `_SCHEME` 结尾的参数 MUST 带 `labels:`，把每个编号映射到一个
大写名字（`labels: {0: RIPPLE, 1: CLA}`）。`labels` 的键集合 MUST 与 `values` 完全相同，名字 MUST
在该参数内互不相同（用户 2026-09-29 定）。

`labels` 只给人读：流程 MUST 原样把编号转发给 RTL 并写进记录，MUST NOT 把名字写进 `params`，
也 MUST NOT 接受以名字代替编号的取值。

#### Scenario: 以名字发起实验

- **WHEN** 以 `--param SCHEME=CLA` 发起 `ADDER32` 的实验
- **THEN** 流程 SHALL 以「取值未在 params.yaml 中声明」拒绝
- **AND** MUST NOT 按 `labels` 反查成编号

#### Scenario: 编号与名字对不上

- **WHEN** `labels` 多出或缺少 `values` 里的某个编号，或两个编号同名
- **THEN** 秒级护栏 SHALL 失败（`guardrail-scope`）

### Requirement: 参数组合可以被声明为排除

`params.yaml` 的 `tops:<顶层>:` 下 MAY 有 `exclude:`，是一组部分赋值的列表（如 `- {MODE: 1, WIDTH: 64}`）。一个参数组合与其中任一项的全部键值相同，就是被排除的组合（内部#138，用户 2026-10-04）。

- `scripts/fast_check.sh` 的 elaborate / lint 与 `scripts/sweep.py` 的全量扫参 MUST NOT 展开被排除的组合；两处的覆盖摘要 MUST 写明排除了几个组合。
- 写错的排除项 MUST 让 fast_check 与 sweep 当场报错并点名该项：键不是该顶层声明过的参数、值不在该参数的 `values` 里、全部组合都被排除。
- 校验与匹配 MUST 只有一处实现（`flow/param_exclude.py`），两处调用；它 MUST NOT 列进 `METRIC_MODULES`：它只决定跑哪些组合，不决定组合怎么测。
- 显式给出全部参数的单次实验不受 `exclude` 约束。

「流程列出的每个仿真器都必须对全部参数组合可用」里的「全部扫参组合」指排除之后的组合。

理由：LRS 规定的参数间约束（如 `MODE=1` 只配 (`WIDTH`, `DEPTH`) = (128, 8)）在逐参数列取值的 `params.yaml` 里写不出来，叉乘会展开非法组合，拿去 elaborate、lint、扫参；RTL 里的参数检查只在 `CBB_PARAM_CHK_ON` 下生效，fast_check 不定义它，所以不会失败。

#### Scenario: 排除非法组合

- **WHEN** 顶层声明 `WIDTH: [64, 256]`、`MODE: [0, 1]`，`exclude: [{MODE: 1, WIDTH: 64}]`
- **THEN** fast_check 与 sweep SHALL 只展开 3 个组合，摘要写明排除 1 个

#### Scenario: 排除项写错

- **WHEN** `exclude` 的某一项写了没声明的参数 `MODE_X`，或取值 `WIDTH: 128` 不在 `values` 里
- **THEN** fast_check 与 sweep MUST 报错并点名这一项

#### Scenario: values 收窄后排除项过期

- **WHEN** `WIDTH` 的 `values` 从 `[64, 256]` 收窄成 `[256]`，`exclude` 里还有 `{MODE: 1, WIDTH: 64}`
- **THEN** fast_check 与 sweep MUST 报错并点名这一项

#### Scenario: 全部组合都被排除

- **WHEN** `exclude: [{MODE: 1}, {MODE: 0}]`
- **THEN** fast_check 与 sweep MUST 报错

### Requirement: 静态端口可以排除在时序分析之外，但必须由设计需求保证

设计 MAY 在 `params.yaml` 的 `tops:<顶层>:sta:static_ports:` 声明一组输入端口，在 STA 中按 false path 或 multicycle 处理（内部#154，用户 2026-10-04）。每一项 MUST 写明：
- `ports`：端口名或通配；
- `kind`：`false_path`，或 `multicycle` 并给出 `cycles`（≥ 2）；
- `by`：接口文档里保证这些端口可以这样处理的需求编号（例如「配置只在空闲时改，改后 N 拍内不被采用」）。

用户的原话是「正式 STA 也排除，但你要在设计上就保证这里可以设 false_path 或 multicycle」。所以排除 MUST 能追溯到设计需求：`by` 不是接口文档里有定义的需求，或某个模式一个 RTL 输入端口都匹配不到，`scripts/fast_check.sh` MUST 失败。正式 STA 运行时，某个模式在网表里匹配不到端口 MUST 报错，MUST NOT 静默放过。

正式 STA 与 `flow/synth/depth.py` MUST 用同一份声明。解析后的声明 MUST 进入该设计的 `design_recipe_sha256`。没有声明的设计生成的 STA 脚本 MUST 与引入本要求之前逐字相同。

理由：全局静态配置到输出的路径会占住最坏路径，挡住真正的关键路径（某闭源 IP上，一条静态配置端口到输出的 44 级路径挡住了内部 85 级），而它在实际中没有时序意义。但「这个端口是静态的」是对设计行为的断言，只有设计需求能担保；流程不替设计判断。

#### Scenario: 静态配置端口按 false path 排除

- **WHEN** 顶层声明 `static_ports: [{ports: [cfg_*], kind: false_path, by: R.901}]`，LRS 定义了 `R.901`
- **THEN** 正式 STA 对匹配 `cfg_*` 的输入端口发 `set_false_path -from`
- **AND** 最坏路径不再从这些端口起

#### Scenario: 没有需求担保

- **WHEN** 某一项的 `by` 写的是 LRS 没有定义的 `R.999`
- **THEN** fast_check MUST 失败并点名这一项

#### Scenario: 模式匹配不到端口

- **WHEN** 某一项的 `ports` 写成 `drma_*`，没有任何输入端口匹配
- **THEN** fast_check MUST 失败；正式 STA 运行时 MUST 报错

#### Scenario: 没有声明的设计不受影响

- **WHEN** 设计没有声明 `static_ports`
- **THEN** 正式 STA 生成的 tcl 与以前逐字相同

### Requirement: 扫参可以按显式点表进行

`params.yaml` 的 `tops:<顶层>:` 下 MAY 有 `sweep_points:`，是显式扫参点的列表。每项 MUST 有在该顶层内唯一的 `name`，并 MUST 给全该顶层声明的全部参数（含 `sweep: false` 的）、不多不少；每个值 MUST 在该参数的 `values` 里；任一项 MUST NOT 命中 `exclude`；两项的参数 MUST NOT 完全相同。写错时 fast_check 与 sweep MUST 当场报错并点名该项。

声明了 `sweep_points` 时，`scripts/sweep.py` MUST 只跑这张表里的点，覆盖摘要写明按点表跑了几个点。fast_check 的 elaborate / lint MUST 覆盖这些点。记录的 `params` 段形状不变，点名 MUST NOT 进记录。

理由：目标配置是少数几个合法点，用 `exclude`（语义是非法组合）从叉乘里挑，会把合法组合从快检覆盖里去掉，也写不干净（内部#214、内部#206）。

#### Scenario: 按点表扫参

- **WHEN** 顶层声明 4 个 sweep_points
- **THEN** sweep SHALL 只跑这 4 个点，每条记录的 `params` 等于该点去掉 `name`

#### Scenario: 点表写错

- **WHEN** 某一项缺一个声明过的参数、取值不在 `values` 里、命中 exclude、`name` 重复或与另一项参数完全相同
- **THEN** fast_check 与 sweep MUST 报错并点名这一项

### Requirement: 参数可以声明为不进叉乘

参数 MAY 声明 `cross: false`。fast_check 的叉乘、`flow/synth/synth.py` 探读入集合的叉乘，以及没有 `sweep_points` 时 sweep 的叉乘，MUST 只取它 `values` 的第一项。它其余的每个取值 MUST 至少出现在一个 sweep_point 里，否则 fast_check 与 sweep MUST 报错并点名这个取值。fast_check 的 elaborate / lint 与读入集合 MUST 覆盖叉乘与 sweep_points 的并集。

展开与校验 MUST 只有一处实现（`flow/param_exclude.py`），fast_check、sweep、synth 三处调用。

理由：只在目标点里取其他值的参数进叉乘，组合数成倍爆炸，快检与读入集合都扛不住；又不能让某个取值永远不被 elaborate（内部#214）。

#### Scenario: 不进叉乘的参数不放大快检

- **WHEN** 两个参数各 2 个取值，另有一个 `cross: false` 的参数 `values: [2, 16]`，sweep_points 里有一项取 16
- **THEN** fast_check SHALL 展开 4 个叉乘组合加 1 个点，共 5 个，不是 8 个

#### Scenario: 取值永远不被覆盖

- **WHEN** `cross: false` 的参数 `values: [2, 16]`，没有任何 sweep_point 取 16
- **THEN** fast_check 与 sweep MUST 报错并点名 16

### Requirement: 单条实验、扫参与量级数可以按扫参点名取参数

`make exp` 与 `make depth` MUST 接受 `POINT=<sweep_points 的 name>`，`make sweep` MUST 接受 `POINTS="<name> <name> …"`。参数 MUST 原样取自该顶层 `params.yaml` 的 `sweep_points` 里那一项（去掉 `name`）。点名不存在时 MUST 报错并列出该顶层所有点名；`POINT=` 与 `PARAMS=` 同时给 MUST 报错。

理由：只跑部分扫参点时，要从 params.yaml 手抄几十个参数，抄错了没有东西拦（内部#332）。

#### Scenario: 按点名跑单条实验

- **WHEN** `make exp DESIGN=<顶层> POINT=<点名>`
- **THEN** 实验用的参数与 params.yaml 里那个点名的一项逐个相同

#### Scenario: 点名写错

- **WHEN** `POINT=pt_b9`，而该顶层没有这个点
- **THEN** 命令报错，并列出 `pt_a1`、`pt_a0`、`pt_b1`、`pt_b0`

### Requirement: 量级数可以冻结到一个提交

`make depth` MUST 接受 `REF=<提交>`：在临时的 detached worktree 里检出该提交（共用仓库的 `.venv`），在那里量，量完删掉临时 worktree。输出 MUST 写明被量的提交号；临时 worktree 检出后不干净时 MUST 报错不量。

理由：量某个提交的级数，以前要手工建 detached worktree、软链 `.venv`（内部#332）。

#### Scenario: 按提交量

- **WHEN** `make depth DESIGN=X REF=abc123`
- **THEN** 量的是 `abc123` 的 RTL，输出里有 `abc123` 的完整提交号，结束后临时 worktree 不在了

### Requirement: 仿真子进程必须用跑流程的那个解释器

流程的入口（`scripts/sweep.py`、`scripts/exp.py`、`tests/conftest.py`）MUST 在启动仿真之前，把当前解释器所在目录放到进程 `PATH` 的最前面，让仿真器起的子进程（例如 Verilator 生成的 makefile 调用的 `#!/usr/bin/env python3` 脚本）找到的 `python3` 就是跑流程的这个解释器。这一步 MUST NOT 写在 METRIC_MODULES 里的文件中：它不改任何测量值，不应该换代。

理由：cocotb runner 按当前解释器设好了 Python 环境，子进程却按 `PATH` 找 `python3`。不激活 venv 时，在 macOS 上找到的是系统自带的 3.9，它拿到 3.11 的标准库就崩（内部#442，开源导出里不激活时 `tests/test_sim_verilator.py` 挂 2 条）。

#### Scenario: 不激活 venv 直接跑

- **WHEN** 用 `.venv/bin/python3` 跑 `scripts/sweep.py`、`scripts/exp.py` 或 pytest，而 `PATH` 里排在前面的 `python3` 是另一个解释器
- **THEN** 仿真子进程找到的 `python3` 是 `.venv/bin` 里的那个

#### Scenario: 已经激活

- **WHEN** 当前解释器的目录已经在 `PATH` 最前面
- **THEN** `PATH` 不变，重复调用不会叠加
