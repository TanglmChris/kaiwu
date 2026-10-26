# experiment-record Specification

## Purpose

规定实验记录（2026-10-25 起每个设计根一个 `results/<设计根>/experiments.jsonl`，内部#422）的 schema 与存放契约：一条记录必须自己说清楚它是什么。

这个文件是整个项目的资产 —— 两个月、上百条、最终要拿去和商业工具流做偏差分析。
读它的人不会知道记录产生时的默认参数是什么，所以记录必须**自解释**：`sta` 段带上
测量所用的时钟周期（否则 `slack_ns` 无从解释），带上 `fmax_mhz` 与说明它怎么来的
`fmax_method`，带上一个 `flow` 指纹回答「这条和那条能不能放在一起比」。

两条边界是硬的。**字段只增不改** —— 新增字段不得使既有记录不可用，已有记录不得被
回填或改写；读取工具必须能处理缺字段的老记录（例如缺 `clock_period_ns` 时由
`slack_ns + critical_path_delay_ns` 推导）。**只存测量值，不存导出值** —— 分数依赖
可变的权重配置，把它写进记录等于把一个会变的东西冻进资产。

没有 `flow` 段的记录归入「未知代」，而不是假定它与最新一代同源。

## Requirements

### Requirement: 时序结果必须自解释

一条实验记录的 `sta` 段 MUST 同时携带测量所用的时钟周期，使 `slack_ns` 在不知道
运行时默认参数的情况下也能被解释。

**多时钟设计**：一个标量周期解释不了多时钟的 `slack_ns` —— 读记录的人无从知道
那个 slack 是哪个域的、对着哪个周期。所以多时钟记录 MUST 另外携带
`sta.clocks`：每个时钟一项，带名字、绑定端口、周期，以及该域自己的
`slack_ns` 与 `fmax_mhz`。

既有的三个标量 `sta.clock_period_ns` / `sta.slack_ns` / `sta.fmax_mhz`
MUST 保留且 MUST NOT 改名（「实验记录的字段集合只能单调增长」）：
单时钟时含义一字不变；多时钟时 SHALL 取**最差的那个域**，
使既有的读取路径在多时钟记录上仍然给出一个保守而非误导的值。

某个时钟域**没有域内路径**时（它的触发器只被跨域路径驱动），该域的
`slack_ns` 与 `fmax_mhz` MUST 缺席（`null`），MUST NOT 填 0 或填周期 ——
见 `experiment-trust` 的「无法测得的指标必须缺席，不得以合法值代替」。

#### Scenario: 在非默认周期下运行

- **WHEN** 以 `--period-ns 2.0` 运行一次实验
- **THEN** 写入的记录中 `sta.clock_period_ns` 等于 2.0
- **AND** `sta.slack_ns + synth.critical_path_delay_ns` 等于 `sta.clock_period_ns`

#### Scenario: 多时钟设计的一次实验

- **WHEN** 一个声明了两个时钟的设计跑完一次实验
- **THEN** `sta.clocks` 有两项，各自带 `name` / `port` / `period_ns`
- **AND** 每一项带该域自己的 `slack_ns` 与 `fmax_mhz`
- **AND** `sta.slack_ns` 等于两项中最小的那个 `slack_ns`

#### Scenario: 某个时钟域没有域内路径

- **WHEN** 某个声明的时钟，其域内一条路径都没有
- **THEN** 该项的 `slack_ns` 与 `fmax_mhz` 为 `null`
- **AND** 该项的 `name` / `port` / `period_ns` 仍然存在 —— 时钟被建立过这件事本身是事实
- **AND** 聚合到 `sta.slack_ns` 时该项被跳过，MUST NOT 让 `null` 参与取最小值

#### Scenario: 单时钟设计的记录形态不变

- **WHEN** 一个单时钟设计跑完一次实验
- **THEN** 三个既有标量的取值与本变更之前逐字相同
- **AND** `sta.clocks` 有且只有一项，其 `slack_ns` 等于 `sta.slack_ns`

### Requirement: 记录必须携带可比的性能标量

记录 MUST 携带 `sta.fmax_mhz`，以及一个 `sta.fmax_method` 字段说明该值是**怎么来的**。

`fmax_method` MUST 区分出**这次测量是在什么综合压力下取得的**。同一份 RTL 在
「综合时没有给延时目标」与「综合时按目标周期加压」两种做法下会得到**不同的网表**，
因而得到不同的 `fmax_mhz`；两者 MUST NOT 被当作同一种量放在一起比。

当综合**没有被给定延时目标**时，`fmax_mhz` SHALL 等于
`1000 / synth.critical_path_delay_ns`，`fmax_method` SHALL 为 `"analytic"`。
此时 `fmax_mhz` 的含义是「**未加时序压力**的那一次综合里，关键路径恰好是多长」，
它 MUST NOT 被解读为该实现能达到的最高频率。

当 `fmax_mhz` 由**在一组延时目标上各综合一次、取其中最好者**得到时，
`fmax_method` SHALL 为 `"search:abc-D"`，记录 MUST 同时携带
`synth.delay_target_ps` 说明**是哪一档胜出的**（不加目标胜出时为 `null`）。

被搜索的那组目标 MUST NOT 是一组固定的绝对时间。它 SHALL 由**该设计自己在不加压
时测得的关键路径** `d0` 与一组固定比例推出。理由是实测的：有用区间相对于 `d0`
是稳定的，绝对区间不是 —— 一组在 180–2000 ps 的设计上调出来的绝对目标，
放到 `d0 = 1381 ps` 的设计上会整组落进死区。

进入 `flow.synth_recipe_sha256` 的 MUST 是那组**比例**，MUST NOT 是推出来的皮秒值：
比例是流程的一部分，皮秒值是每个设计各自的。换了比例就是换了流程，记录必须因此分代。
`synth.delay_target_ps` 记的仍 SHALL 是胜出那一档的**绝对皮秒**，因为那才是复现
这次综合所需要传给综合器的值。

搜索 MUST 能证明自己确实搜索过：若整组目标产出的网表**全部**与不加目标时
逐字节相同，该次结果 MUST NOT 记成 `"search:abc-D"`。此时记录取不加目标那一次的结果，
`fmax_method` SHALL 为 `"analytic"`，并 MUST 携带 `synth.search_effective = false`；
至少一档改变了网表时 `synth.search_effective` SHALL 为 `true`。缺这个字段的旧记录读作「未知」。
理由是延时目标可能因工具版本、库或取值而整组失效，而失效时的表现与「搜过了，base 恰好最好」
在结果上无法区分 —— 这件事必须由记录自己说明。2026-10-03 之前这种情况直接报错、不写记录；
关键路径只有百皮秒量级的浅组合因此一条记录都写不出（内部#85），改为放行并标明。

新增别的取得方式时 MUST 用新的 `fmax_method` 取值，MUST NOT 复用既有取值，
也 MUST NOT 回填既有记录 —— 既有记录的 `"analytic"` 按本定义是**准确**的。

#### Scenario: 开源流下取得 fmax

- **WHEN** 用 yosys 综合（不给延时目标）并用 OpenSTA 分析某个实现
- **THEN** 记录中 `sta.fmax_method` 为 `"analytic"`
- **AND** `sta.fmax_mhz` 与 `1000 / synth.critical_path_delay_ns` 相等（浮点容差内）

#### Scenario: fmax 与所选周期无关

- **WHEN** 对同一个设计分别以 STA 周期 5.0 和 2.0 各跑一次实验
- **THEN** 两条记录的 `sta.fmax_mhz` 相同（浮点容差内）
- **AND** 两条记录的 `sta.clock_period_ns` 不同

#### Scenario: 综合被给定延时目标

- **WHEN** 综合被给定延时目标（例如 `abc -D`），因而产出与不加目标时不同的网表
- **THEN** 该次记录的 `fmax_method` MUST NOT 为 `"analytic"`
- **AND** 它与 `"analytic"` 的记录 MUST NOT 被当作同一种量横向比较

#### Scenario: 用「与所选周期无关」推断综合不是时序驱动的

- **WHEN** 有人以「改 STA 周期不改变结果」为依据，断言本流程的综合不是时序驱动的
- **THEN** 该推断 MUST 被视为无效 —— 综合从未收到过 STA 的周期，这个观察与综合是否
  能被加压无关

#### Scenario: 在一组延时目标上搜索 fmax

- **WHEN** 对一个参数组合在一组延时目标上各综合一次并取最好者
- **THEN** 记录中 `sta.fmax_method` 为 `"search:abc-D"`
- **AND** `synth.delay_target_ps` 为胜出的那一档的绝对皮秒，或在不加目标胜出时为 `null`
- **AND** 记录的 `synth` 与 `sta` 各字段都来自**同一个**胜出的网表

#### Scenario: 两个可达延时相差一个量级的设计

- **WHEN** 对 `d0` 约 300 ps 的设计与 `d0` 约 1400 ps 的设计各跑一次搜索
- **THEN** 两次搜索被给出的绝对延时目标不同，各自落在自己 `d0` 的同一组比例上
- **AND** 两条记录的 `flow.synth_recipe_sha256` 相同 —— 流程没变，变的是设计

#### Scenario: 整组延时目标都不起作用

- **WHEN** 一组延时目标产出的网表全部与不加目标时逐字节相同
- **THEN** 该次搜索 MUST 失败并指出「整组目标都没有改变网表」
- **AND** MUST NOT 写入任何 `fmax_method` 为 `"search:abc-D"` 的记录

#### Scenario: 换掉被搜索的那组延时目标

- **WHEN** 流程被改为按另一组比例推导延时目标
- **THEN** `flow.synth_recipe_sha256` 随之改变
- **AND** 新旧两批记录因指纹不同而落在不同的流程代里

#### Scenario: 整组目标都没有改变网表

- **WHEN** 档位搜索的每一档产出的网表都与不加目标时逐字节相同（例如 d0 只有几十皮秒的浅组合）
- **THEN** 记录照常写入，`synth.search_effective` 为 `false`，`synth.delay_target_ps` 为 `null`
- **AND** `sta.fmax_method` 为 `"analytic"`，MUST NOT 为 `"search:abc-D"`

### Requirement: 已有记录必须保持可读

新增字段 MUST NOT 使既有记录不可用。读取实验记录的工具 MUST 能处理缺少
`sta.clock_period_ns` 的记录：对这类记录，所用周期 SHALL 由
`sta.slack_ns + synth.critical_path_delay_ns` 推导得到。已有记录 MUST NOT 被回填或改写。

读取实验记录的工具 MUST 读全部设计根的记录文件（`results/*/experiments.jsonl`），MUST NOT 只读某一个固定路径；
按设计过滤时以记录的 `design` 字段为准，已删除设计根的记录照样读得到。

#### Scenario: 读取新增字段之前写下的记录

- **WHEN** 打分工具读到一条没有 `sta.clock_period_ns` 的记录
- **THEN** 该记录被正常处理，不报错
- **AND** 其所用周期取 `sta.slack_ns + synth.critical_path_delay_ns`

#### Scenario: 历史文件保持不变

- **WHEN** 任何一次改动完成
- **THEN** 改动前记录库里的每一行 MUST 逐字节仍在某个 `results/<设计根>/experiments.jsonl` 里

#### Scenario: 读已删除设计根的记录

- **WHEN** 读取工具按 `design` 查一个设计根已经删除的顶层
- **THEN** 它 SHALL 从该顶层的记录文件里读到全部历史记录，不因设计根不存在而报错或少读

### Requirement: 记录只存测量值，不存导出值

实验记录 MUST NOT 包含分数。分数依赖可变的权重配置，属于事后导出量。

#### Scenario: 打分配置改变

- **WHEN** `scoring.yaml` 中的权重被修改
- **THEN** `results/*/experiments.jsonl` 无需重新生成
- **AND** 重新运行打分工具即可得到新分数

### Requirement: 记录必须自解释其产出流程

一条实验记录 MUST 携带一个 `flow` 段，用来判断它与另一条记录是否出自同一套
测量流程。`flow` MUST 包含一个 `fingerprint` 标量，以及构成该指纹的各项事实
（至少：综合器与静态时序分析器的版本、**产出活动率的那条链上每一层的版本**、
所用 liberty 的内容哈希、综合与 STA 两段脚本配方的哈希、**把工具输出解析成记录
字段的那部分代码的哈希**）。

`git_commit` 不足以承担这件事：它记的是仓库的版本，而换 PDK、换 Vt/corner、
重新生成合并 liberty 都不改变任何 commit，却会让全部数字整体挪位。

**只哈希交给工具的脚本是不够的。** 同一份工具输出，换一种解析方式就得到不同口径的
字段，而脚本一个字没变。这类改动 MUST 改变指纹。

**只记仿真器可执行文件的版本是不够的。** 动态功耗由 VCD 反标算出，而 VCD 的内容
取决于激励怎么加、时钟怎么走、波形从哪一刻开始转储 —— 这些由**驱动仿真器的那一层**
决定，不是仿真器本身。该层的版本 MUST 进入指纹：换掉它能改变
`sim.total_toggles` 与 `sta.dynamic_power_w`，而仿真器可执行文件一个字节没变。

覆盖范围 MUST NOT 依赖"记得登记"：把哪些函数算作派生逻辑列成一份清单，会在有人
新增一条派生路径却忘了登记时失效 —— 而"忘了"正是这条要求要防的那件事。
覆盖 MUST 以模块为单位，且被覆盖的模块清单本身 MUST 进入该哈希，
使删减清单同样改变指纹。

**指纹按设计算**（用户 2026-10-04，内部#146）：`flow` MUST 包含 `design_recipe_sha256`，即本设计**解析后**交给测量代码的配置值（时钟、时钟分组、时钟端口、仿真数周期用的时钟信号、理想驱动端口、保层级模块；周期由命令行给出时不进哈希）的哈希，并参与 `flow.fingerprint`。把设计配置解析成这些值的代码（`flow/paths.py`）MUST NOT 列进被覆盖的模块清单：它对测量的影响按值进指纹，只为某个设计新增的配置写法不改变其他设计的指纹。计算指纹 MUST 指定设计，不得退回不含设计配方的指纹。配置不同的两个设计的记录因此永远不同代，跨代配对按设计进行。

该哈希 MUST NOT 因**注释、空行或 docstring** 的改动而改变。理由是文档修订频繁
且不改变任何测量结果；若它们也分代，流程代就会被噪声淹没，人就会开始无视代的边界，
这条要求也就失效了。

#### Scenario: 同一套流程下的两次测量

- **WHEN** 在不改动工具、驱动运行时、liberty 与流程脚本的前提下跑两次实验
- **THEN** 两条记录的 `flow.fingerprint` 相同

#### Scenario: 换掉综合库

- **WHEN** 用另一份 liberty（不同 Vt/corner，或重新生成过的合并库）跑同一个设计
- **THEN** 新记录的 `flow.fingerprint` 与旧记录不同
- **AND** `flow` 里记录的 liberty 内容哈希不同

#### Scenario: 改动综合配方

- **WHEN** 综合脚本模板或 abc 约束文件的内容发生变化后再跑实验
- **THEN** 新记录的 `flow.fingerprint` 与变化之前不同

#### Scenario: 只改解析逻辑，不改交给工具的脚本

- **WHEN** 把工具输出解析成记录字段的代码发生变化，而脚本模板与约束文件一个字未变
- **THEN** 新记录的 `flow.fingerprint` 与变化之前不同
- **AND** 两批记录 MUST NOT 被判成同一流程代

#### Scenario: 只换驱动仿真的运行时，不换仿真器

- **WHEN** 驱动仿真器的那一层换了版本，而仿真器可执行文件本身逐字节未变
- **THEN** 新记录的 `flow.fingerprint` 与变化之前不同
- **AND** `flow` 里记录的仿真那一项事实能指出是哪一层不同

#### Scenario: 只改注释或 docstring

- **WHEN** 只修订注释、空行或 docstring，没有改动任何可执行语句
- **THEN** `flow.fingerprint` 保持不变

#### Scenario: 从覆盖清单里删掉一个模块

- **WHEN** 被覆盖的模块清单被缩小
- **THEN** `flow.fingerprint` 随之改变

#### Scenario: 只改一个设计的流程配置

- **WHEN** `ADDER32` 的 `params.yaml` 改了 `sta.clocks`，或 `flow/paths.py` 为它新增了一种时钟写法，其余设计的配置解析结果不变
- **THEN** `ADDER32` 新记录的 `flow.design_recipe_sha256` 与 `flow.fingerprint` 改变
- **AND** `CBB_LZD` 新记录的 `flow.fingerprint` 与变化之前相同

#### Scenario: 计算指纹时没给设计

- **WHEN** 调用方计算流程指纹而没有指定设计
- **THEN** MUST 当场报错，不产出指纹

### Requirement: 缺少流程指纹的记录必须归入未知代

新增 `flow` 段 MUST NOT 使既有记录不可用。读取实验记录的工具遇到没有 `flow` 段的
记录时，MUST 把它归为「未知流程代」，MUST NOT 把它归入任何带指纹的流程代，
也 MUST NOT 回填或改写它。

未知代的记录之间 MAY 按 `git_commit` 再分组：同一个 commit 至少意味着同一份流程
代码，这是对老记录能做到的最好近似。这个近似 MUST 只用于分组，MUST NOT 被当成
指纹使用（同一 commit 下换掉 liberty 不会改变 commit，因此它可能把不同的流程合成
一组）。

#### Scenario: 读到新增字段之前写下的记录

- **WHEN** 读取一条没有 `flow` 段的记录
- **THEN** 该记录被归入「未知流程代」，不报错
- **AND** 它不与任何带指纹的记录归为同一代

#### Scenario: 老记录按 commit 分组

- **WHEN** 一批没有 `flow` 段的记录里存在两个不同的 `git_commit`
- **THEN** 它们被分成两个不同的（未知）流程代

#### Scenario: 历史文件保持不变

- **WHEN** 任何一次改动完成
- **THEN** 没有 `flow` 段的每一行 MUST 逐字节仍在某个 `results/<设计根>/experiments.jsonl` 里

### Requirement: 实验记录的字段集合只能单调增长

`results/*/experiments.jsonl` 中已经出现过的字段名 MUST NOT 被改名，MUST NOT 被删除。
任何变更 MAY 新增字段。这条约束不限于某一次变更，对仓库的全部生命周期成立。

理由是这个文件的价值来自跨月份、跨流程代的可比性，而**改名或删除是不可逆的**：
读取历史记录的工具会静默地读到 `None`，而不是报错。新增字段不同 —— 老记录缺这个
字段是可检测的，工具可以据此走兼容路径（`experiment-record` 的「已有记录必须保持
可读」规定了这一侧）。

嵌套字段（如 `sta.fmax_mhz`、`flow.fingerprint`）与顶层字段同等适用。

#### Scenario: 一次变更给记录加了新字段

- **WHEN** 某次变更让新写入的记录携带一个此前不存在的字段
- **THEN** 该变更被允许
- **AND** 此前写入的记录保持逐字节不变

#### Scenario: 一次变更试图给已有字段改名

- **WHEN** 某次变更把一个已经出现在记录中的字段改成另一个名字
- **THEN** 该变更 MUST 被拒绝
- **AND** MUST NOT 以「同时回填历史记录」作为使其可接受的理由 ——
  回填本身已被「已有记录必须保持可读」禁止

#### Scenario: 一次变更试图删除已有字段

- **WHEN** 某个字段被判断为不再有用，某次变更要把它从新记录中去掉
- **THEN** 该变更 MUST 被拒绝
- **AND** 停止写入该字段的正确做法 SHALL 是让它取 `null`，使字段名继续存在

### Requirement: 记录必须携带域内保持时间余量

一条实验记录的 `sta` 段 MUST 携带 `sta.hold_slack_ns`：这一份网表里**寄存器到
寄存器**路径的最差最小延时（hold）余量，单位 ns。

它与既有的 `sta.slack_ns` 是两个方向的量，MUST NOT 互相替代：`slack_ns` 是
setup（越大越松），`hold_slack_ns` 是 hold（为负即违例）。两者都保留，字段名
都 MUST NOT 改（「实验记录的字段集合只能单调增长」）。

该字段的口径由 `experiment-trust` 的「最小延时分析必须只报告设计内部的路径」
规定：主输入起点与主输出终点的 min 路径不参与取值，因为它们的结果由约束里假设的
到达/要求时刻决定，不由电路决定。

网表里没有寄存器到寄存器的路径时，`sta.hold_slack_ns` MUST 为 `null`，
MUST NOT 填 0（会被读成「刚好卡住」），MUST NOT 填工具的无路径哨兵值。

「没有域内路径」**不等于**「没有时序单元」：单级流水的网表有触发器，但它们只被
`输入端口→reg` 与 `reg→输出端口` 两类路径触及。所以 `sta.hold_slack_ns` 为 `null`
时 `sta.register_count` MAY 大于 0，读记录的一方 MUST NOT 假设两者同进同退。

#### Scenario: 含流水寄存器的设计

- **WHEN** 一次实验的网表里有寄存器到寄存器的路径
- **THEN** 记录中 `sta.hold_slack_ns` 是一个数
- **AND** 它等于那一次运行里域内最差的 min slack

#### Scenario: 纯组合的设计

- **WHEN** 一次实验的网表里一个时序单元都没有
- **THEN** 记录中 `sta.hold_slack_ns` 为 `null`
- **AND** `sta.register_count` 为 0

#### Scenario: 单级流水的设计

- **WHEN** 一次实验的网表里有时序单元，但没有寄存器到寄存器的路径
- **THEN** 记录中 `sta.hold_slack_ns` 为 `null`
- **AND** `sta.register_count` 大于 0 —— 两个字段 MUST NOT 被读成同进同退

#### Scenario: 老记录没有这个字段

- **WHEN** 读取本变更之前写入的记录
- **THEN** 读取方 SHALL 看到该字段缺席，并据此走兼容路径
- **AND** 那些记录 MUST 保持逐字节不变，MUST NOT 被回填

### Requirement: 记录必须区分被测顶层与它所在的设计根

`design` 字段 MUST 是**被测顶层的模块名** —— 送进 `hdl_toplevel` / `synth -top` /
`link_design` 的那个名字。记录 MUST 另带 `design_root` 字段，指出该顶层的源文件
位于哪个设计根。

`design` 的这个含义**不是本次变更引入的**：在「设计根的名字必须等于该设计的顶层
模块名」成立的全部历史里，根名与顶层名被强制逐字相同，所以 `design` 一直同时是两者。
本条只是把其中**一直被流程实际使用的那一半**（顶层）写成显式契约，并为另一半
新增字段。因此 **MUST NOT 回填、改写或重新解释任何历史行的 `design`** ——
它们作为顶层名全部仍然正确。

读取历史记录时，缺席的 `design_root` MUST 回退到该行的 `design`。⚠️ 这个回退对
**当时是独立设计根、后来被并入别处**的那些行给出的是**旧根名**，而那个根已不存在。
回退值因此 MUST 只用于分组与展示，MUST NOT 用于在文件系统上定位源文件；
具体是哪些行、该怎么读，MUST 记在 `docs/data-credibility.md`。

#### Scenario: 同一个设计根下两个顶层各跑一次实验

- **WHEN** 对同一设计根声明的两个顶层各跑一次实验
- **THEN** 两条记录的 `design` 不同、`design_root` 相同
- **AND** 两条记录 MUST NOT 因为共享设计根而被任何工具合并成一条

#### Scenario: 读到一条没有 design_root 的历史记录

- **WHEN** 工具读到一条缺少 `design_root` 的记录
- **THEN** 它 MUST 回退到该行的 `design`，MUST NOT 报错、MUST NOT 跳过该行
- **AND** MUST NOT 用这个回退值去解析设计根目录

#### Scenario: 某个顶层原来是独立设计根

- **WHEN** 读一条 `design` 为某闭源 IP的某个已删子设计（全小写顶层名）、无 `design_root` 的历史记录
- **THEN** 它的 `design` 作为被测顶层名仍然正确，可与新一代同名顶层的记录按
  `design` 分到同一组（跨代仍受「指纹不同不得横向比较」约束）
- **AND** 回退出来的 `design_root` 指向一个已不存在的目录，MUST NOT 据此去读源文件

### Requirement: 记录必须声明这次综合读了哪些源文件

记录 MUST 携带 `synth.sources_sha256`：本次综合实际读入的源文件集合的内容摘要
（文件名与内容都进哈希，与给出顺序无关）。

理由是**读入集合是一条能改变 PPA 的自变量**，而在本条之前它在记录里没有任何痕迹。
实测（2026-09-20，本仓 内部#50）：
同一份 RTL、同一组参数、同一份 liberty，只因为 `rtl/` 目录里多了几个**从不被例化**
的文件，某闭源 IP的一个地址变换子设计的结果在 13 / 33 / 36 / 15 个单元之间变化 ——
最大 2.5 倍，且**确定性可复现**。

它 MUST NOT 进 `flow` 指纹：指纹描述的是**流程**，而读入集合属于**被测对象**
（与 RTL 同侧，见「缺少流程指纹的记录必须归入未知代」的理由段）。
两条记录的 `flow.fingerprint` 相同而 `synth.sources_sha256` 不同时，
它们**不可横向比较**，判据与 RTL 变更同形：只能靠 `git_commit` 加文档。

读取历史记录时，缺席的 `synth.sources_sha256` MUST 当作「未知」，
MUST NOT 当作「与某条已知记录相同」。

#### Scenario: 一次综合写出它的源文件摘要

- **WHEN** 跑完一次实验
- **THEN** 记录的 `synth.sources_sha256` 是本次实际读入的那组文件的摘要
- **AND** 同一组文件以不同顺序给出时摘要相同

#### Scenario: 两条记录指纹相同而源文件摘要不同

- **WHEN** 两条记录的 `flow.fingerprint` 相同、`synth.sources_sha256` 不同
- **THEN** 它们 MUST NOT 被任何工具当作可横向比较的同组记录
- **AND** 差异的来由 MUST 记在 `docs/data-credibility.md`

#### Scenario: 读到一条没有源文件摘要的历史记录

- **WHEN** 工具读到一条缺少 `synth.sources_sha256` 的记录
- **THEN** 它 MUST 把该值当作「未知」，MUST NOT 报错、MUST NOT 跳过该行
- **AND** MUST NOT 推定它与任何一条带摘要的记录读了同一组文件

### Requirement: `design` 取值换过一次大小写，两个名字指同一个电路

2026-09-21 起，被测顶层的模块名由全小写改为全大写（`rtl-structure-authority` 的
「模块名必须全大写」）。`design` 字段存的就是顶层模块名，所以**同一个电路在这个
分界的两侧有两个取值**：`adder32` 与 `ADDER32`，某闭源 IP的几个子设计同样如此，
以此类推。

读记录的工具 MUST 把它们当作**两条各自独立的序列**：

- MUST NOT 把两侧的记录按 `(design, params)` 配对之后相减 —— 它们配不上，
  而「配不上」在这里不表示「没测过」。
- MUST NOT 自动做大小写归一化后合并。合并出来的序列会跨过一次 RTL 改名，
  而那次改名虽然不改变电路，却与它同时发生了别的事（本变更同时重证了等价账本、
  重跑了一代记录），把它们当成一条连续序列会把两件事混在一起。
- 人在文档里说明之后，MUST 可以横向比较：本变更实测改名前后 `cell_count` 与
  `area_um2` 相同（改名不改变电路），所以这个分界**不降低任何记录的可信度**，
  它只是让自动配对失效。

#### Scenario: 工具读到两个大小写不同但同指一个电路的 design

- **WHEN** 一个工具同时读到 `design` 为 `adder32` 与 `ADDER32` 的记录
- **THEN** 它 SHALL 把两者当作不同的 `design` 分别成组
- **AND** MUST NOT 报错、MUST NOT 跳过任何一侧
- **AND** MUST NOT 自动归一化合并

#### Scenario: 人要跨这个分界比 PPA

- **WHEN** 有人要把改名前后的数字并排比
- **THEN** `docs/data-credibility.md` MUST 已经给出大小写映射与分界提交
- **AND** 该条目 MUST 说明改名本身不改变电路（`cell_count` / `area_um2` 实测相同）

### Requirement: 记录必须携带慢角与快角的时序与功耗

综合 MUST 仍只按主 liberty（TT）进行；对胜出的那一份网表，流程 MUST 另在同一 Vt 的 SS 与 FF 角
各做一次静态时序与功耗分析，使用与 TT 相同的 VCD 反标，结果写进 `sta.corners.SS` 与 `sta.corners.FF`。
既有的 `sta.*` / `synth.*` 字段 MUST 保持原含义（TT 的数），MUST NOT 被改写成任何一角的数。

每一角 MUST 自带它的 PVT（电压、温度，取自该角 liberty 的库头）与 `fmax_method`。
不带 PVT 的角结果会被误读：ASAP7 的 SS 角在 100 °C、FF 角在 0 °C，静态功耗跟温度走，不跟快慢走。

角所用 liberty 的内容哈希 MUST 进入 `flow` 指纹，且 MUST 作为新增的一项事实，
MUST NOT 并进既有的 `liberty_sha256`（那会改变一个既有字段的含义）。

主 liberty 不是一个可推出兄弟角的 TT 库时，`sta.corners` MUST 为空对象、指纹那一项为空对象；
能推出而文件缺失时 MUST 报错，MUST NOT 静默少测。

#### Scenario: 一次正常的实验

- **WHEN** 以 `asap7sc7p5t_RVT_TT.lib` 跑一次实验
- **THEN** 记录有 `sta.corners.SS` 与 `sta.corners.FF`，各带 `pvt`、`slack_ns`、`hold_slack_ns`、`critical_path_delay_ns`、`dynamic_power_w`、`static_power_w`
- **AND** SS 的关键路径延时不短于 TT，FF 的不长于 TT
- **AND** 既有 `sta.slack_ns` 等字段仍是 TT 的数

#### Scenario: 换掉 SS 角的库

- **WHEN** 只替换 SS 角的 liberty 内容，TT 与 FF 不动
- **THEN** `flow.fingerprint` 改变，`flow.liberty_sha256` 不变

#### Scenario: 兄弟角的库缺失

- **WHEN** 主 liberty 名为 `…_TT.lib`，而同目录下没有对应的 `…_SS.lib`
- **THEN** 实验在写记录之前失败，并点名缺失的文件

#### Scenario: 老记录没有角的字段

- **WHEN** 读取本变更之前写入的记录
- **THEN** 读取方看到 `sta.corners` 与 `flow.corner_liberty_sha256` 缺席
- **AND** 那些记录逐字节不变，不被回填

### Requirement: 读入集合摘要必须包含参数片段

`synth.sources_sha256` MUST 把该顶层 include 目录（`repo-layout`「参数片段的位置与 include 目录」）下的
全部 `.vh` 一起算进摘要。没有 include 目录的顶层，摘要 MUST 与引入本条之前逐字节相同。

理由是片段改了参数就改了电路，摘要不变的话，跳过开关会把最该重跑的组合跳过（D-14 同形）。

#### Scenario: 只改了参数片段

- **WHEN** 一个顶层只有 `rtl/inc/` 下的某个 `.vh` 改了
- **THEN** 它的 `synth.sources_sha256` SHALL 改变

### Requirement: 记录必须说明活动率反标到了哪一层

每条带动态功耗的记录 MUST 携带 `sta.activity_annotation`：`pins`（OpenSTA 报告标注上活动率的引脚数）、
`port_bits`（被测顶层全部端口的位数之和）、`scope`（`pins <= port_bits` 时为 `ports`，否则为 `internal`）。
缺这个字段的历史记录 MUST 当作「未知」。

理由是只有端口被反标时，内部节点的活动率是 OpenSTA 按概率传播出来的，看不到毛刺与相关性；
结构之间的动态功耗排名在这种口径下不能当结论用（内部#65），而以前记录里看不出是哪种口径。
`gate-level-activity` 起功耗由门级 VCD 反标，新记录的 `scope` 是 `internal`；它与 `ports` 的记录
MUST NOT 横向比较动态功耗。

#### Scenario: RTL 仿真的 VCD 只对上了端口

- **WHEN** 一次实验的标注引脚数不超过被测顶层的端口位数
- **THEN** 记录的 `sta.activity_annotation.scope` SHALL 是 `ports`

#### Scenario: 门级 VCD 标到了内部引脚

- **WHEN** 功耗由胜出网表的零延时门级仿真 VCD 反标
- **THEN** 记录的 `sta.activity_annotation.scope` SHALL 是 `internal`

### Requirement: `params` 的键换过一次名，映射表是唯一合法的跨分界配对方式

`unify-rtl-naming` 起，`params` 段的 5 个键按 `rtl-structure-authority` 的命名约定改名：
`WIDTH→DAT_W`（`ADDER32`、`LZD`）、`CARRY_STRUCT→SCHEME`、`CSEL_BLOCK→CSEL_BLK_W`
（`ADDER32`）、`DW→DAT_W` 与一个字数参数
（后两项属于已删除的闭源设计）。同一个电路在分界两侧的 `params` 键不同。

读记录的工具 MUST 把两侧当作各自独立的参数组合：

- MUST NOT 自动按映射合并。与 `design` 的大小写不同，这里是换词，自动合并会把两个
  碰巧同名、含义不同的参数配到一起。
- 需要跨分界配对时（例如证明改名零差异），映射 MUST 由调用方**显式**给出
  （`scripts/pair_generations.py --param-map 旧=新`），并且只对给出的键生效。
- 分界不降低任何记录的可信度：改名前后测量字段逐字段相同由本变更实测证明
  （`rtl-structure-authority` 的「改名不改变电路」）。

#### Scenario: 工具读到分界两侧的记录

- **WHEN** 一个工具同时读到 `params` 含 `WIDTH` 与含 `DAT_W` 的 `ADDER32` 记录
- **THEN** 它 SHALL 把两者当作不同的参数组合分别成组
- **AND** MUST NOT 报错、MUST NOT 跳过任何一侧、MUST NOT 自动合并

#### Scenario: 显式映射后配对

- **WHEN** 调用方给出 `--param-map WIDTH=DAT_W --param-map CARRY_STRUCT=SCHEME`
- **THEN** 工具 SHALL 只把这两个键在旧侧改名后再配对
- **AND** 映射后仍配不上的组合 MUST 被点名报出，不许消失在计数里

### Requirement: `params` 里结构枚举的取值换过一次，取值映射同样只能显式给出

同一个分界上，`params.SCHEME` 的**取值**从字符串换成按设计编号的整数（`rtl-structure-authority` 的
「结构枚举参数必须取整数」）：`ADDER32` 的 `RIPPLE`…`BRENT_KUNG` → `0`…`5`，`LZD` 的
`OKLOBDZIJA`…`TOOL` → `0`…`6`。键不变、取值变，同一个电路在分界两侧的 `params` 依然不同。

读记录的工具 MUST 把两侧当作不同的参数组合；需要跨分界配对时，取值映射 MUST 由调用方显式给出
（`scripts/pair_generations.py --value-map 参数:旧=新`），只对给出的参数与取值生效，与
`--param-map` 同时使用时先改键、再改取值。

#### Scenario: 只给键映射、不给取值映射

- **WHEN** 调用方对 `ADDER32` 只给出 `--param-map CARRY_STRUCT=SCHEME`
- **THEN** 旧侧 `SCHEME: "CLA"` 与新侧 `SCHEME: 1` SHALL 配不上
- **AND** 配不上的组合 MUST 被点名报出

#### Scenario: 键映射与取值映射都给出

- **WHEN** 调用方同时给出 `--param-map CARRY_STRUCT=SCHEME` 与 `--value-map SCHEME:CLA=1`
- **THEN** 工具 SHALL 把旧侧先改键、再改取值后配对
- **AND** 未被映射覆盖的旧取值 MUST 保持原样，不许按名字猜编号

### Requirement: 记录必须携带门级仿真的结论

每条记录 MUST 携带 `sim.gate_passed`：胜出网表的零延时门级仿真（同一个 TB）是否通过。
RTL 仿真没通过时不跑门级仿真，取 `null`。2026-10-03 之前的记录没有这个字段，读作「未知」。

理由是动态与静态功耗来自门级仿真的 VCD，读记录的人要能看出功耗缺席是因为哪一层仿真没过。

#### Scenario: 门级仿真通过

- **WHEN** RTL 仿真与门级仿真都通过
- **THEN** 记录的 `sim.gate_passed` 为 `true`，功耗字段有值

#### Scenario: RTL 仿真未通过

- **WHEN** RTL 仿真存在失败用例
- **THEN** 不跑门级仿真，记录的 `sim.gate_passed` 为 `null`

### Requirement: 门级仿真读的单元模型必须进入指纹

`flow` 段 MUST 携带 `cell_models_sha256`：门级仿真读入的单元 Verilog 模型文件（按文件名排序）的
「文件名 + 内容」哈希，并参与 `flow.fingerprint`。产出门级仿真的代码（`flow/sim/gate_sim.py`）
MUST 在 `METRIC_MODULES` 里。

理由是单元模型不在仓库里，换一份不改任何 commit，却会改变门级 VCD，进而改变功耗 —— 与 liberty 同理。

#### Scenario: 换了单元模型

- **WHEN** 门级仿真读的单元模型文件内容变了，其余不变
- **THEN** `flow.cell_models_sha256` 与 `flow.fingerprint` 都随之改变

### Requirement: 记录必须携带按层次拆开的面积

每条新写入的记录 MUST 携带 `synth.area_breakdown`（内部#174，用户 2026-10-05），内容全部是测量值：
- `gate_unit`：折算门数用的单元名，以及该单元在综合 liberty 里的面积；
- `sequential_area_um2`：整个设计的时序单元面积；
- `hierarchy`：综合后保留的模块实例，至少展开到被测顶层下的第 2 级。每行写路径、模块名、实例数、面积（已乘实例数）、单元数（含下层）、时序单元面积；每一层的胶合逻辑单列一行；
- `memory_models`：设计声明的存储模型模块，以及它们在整个设计里按实例数累计的面积与时序面积。

`hierarchy` 每一层的子行面积加胶合行 MUST 等于父行面积；顶层那一行 MUST 等于 `synth.area_um2`。门数、组合逻辑面积、扣除存储模型后的面积是导出值，MUST NOT 写进记录，由报告现算。

存储模型由设计在 `params.yaml` 的 `tops:<顶层>:synth:memory_models:` 声明。声明的名字不是该顶层读入的源文件里的模块时，写记录前拆面积 MUST 报错。

理由：只有顶层面积时，看不出面积花在哪里；行为模型的 SRAM 综合成触发器会撑大逻辑面积；门数口径不写明，就会出现按 NAND2xp33 折出偏大约 1.5 倍的数。

#### Scenario: 层次面积自洽

- **WHEN** 一个带子模块的设计跑完实验
- **THEN** 记录的 `synth.area_breakdown.hierarchy` 每一层子行加胶合行等于父行，顶层等于 `synth.area_um2`

#### Scenario: 门数单位写在记录里

- **WHEN** 读一条新记录
- **THEN** `synth.area_breakdown.gate_unit` 给出单元名 `NAND2x1_ASAP7_75t_R` 和它在综合 liberty 里的面积

#### Scenario: 存储模型名写错

- **WHEN** `memory_models` 声明了一个读入源文件里不存在的模块名
- **THEN** 拆面积时报错并点名，不写记录

### Requirement: 声明了验收场景的设计，记录必须携带按场景的时序

每条新写入的记录 MUST 携带 `sta.scenarios`（内部#189 后续，用户 2026-10-05 定选项 A）。设计在 `params.yaml` 的 `tops:<顶层>:sta:scenarios:` 声明验收场景，每项 `{name, case: {静态输入端口: 值}, by: R.xxx, when?: {参数: 值 | [值, …]}}`；`by` 是接口文档里担保该输入静态的需求。`when`（内部#198，用户 2026-10-05 定）限定场景适用的参数组合：组合匹配 `when` 的全部键才适用，值列表表示该参数取其中任一值；没写 `when` 的场景对所有组合适用。对这个参数组合适用的每个场景，流程 MUST 用同一份胜出网表、把 `case` 里的输入定值（`set_case_analysis`）各跑一遍 STA，TT 与每个兄弟角各一遍，写入该场景的时序字段、analytic fmax 与它的 `when`。不适用的场景 MUST NOT 量、不写进记录。未声明场景、或没有适用场景的组合写 `[]`。

`when` 的键不是 params.yaml 声明的参数、或值不在该参数的 values 里时，解析 MUST 报错。

`sta.fmax_mhz` 等既有主字段的含义 MUST NOT 改变：它们仍来自不定值的那次 STA，即各场景最坏。每个场景每个角的关键路径延时 MUST 不大于主字段同角的值（容差 `SAME_PATH_TOL_NS`），否则写记录前报错。

理由：互斥排布由静态输入选择时，不定值的 STA 会把永远不会同时激活的组合路径算进来；只看主 fmax 看不到每种排布自己的频率，改主 fmax 的含义又违反记录只增字段的契约。一份目标配置只对应一种排布时，量它不用的排布既浪费，又会让验收误报。

#### Scenario: 场景剪掉互斥路径

- **WHEN** 一个声明了两个场景的设计跑完实验，其中一个场景把深链定值剪掉
- **THEN** 记录的 `sta.scenarios` 有两项，被剪的场景关键路径延时与级数小于主字段，另一个场景不大于主字段；主字段与不声明场景时相同

#### Scenario: 未声明场景

- **WHEN** 一个没有声明场景的设计跑完实验
- **THEN** 记录的 `sta.scenarios` 为 `[]`，其余字段与改动前逐字相同

#### Scenario: 场景声明写错

- **WHEN** `sta.scenarios` 的某项缺 `by`、`by` 不是需求编号、名字重复、`case` 为空，或 `when` 的键 / 值不在 params.yaml 的声明里
- **THEN** 解析时报错并点名，不跑工具、不写记录

#### Scenario: 场景只量适用的参数组合

- **WHEN** 两个场景各写了 `when`，分别匹配两份参数组合，对其中一份跑实验或 depth
- **THEN** 只量它匹配的那个场景，记录的 `sta.scenarios` 只有那一项并带它的 `when`

### Requirement: 按需记录参考口径

正式实验带 `REFERENCE=1`（`run_experiment --reference`）时，记录 MUST 携带 `reference` 字段（内部#202，用户 2026-10-05 定）；不带时为 `null`。参考口径的定义：同一份 RTL、同一组参数，把本组合**唯一**适用的验收场景的 `case` 里的输入在顶层接成常数，跨层次传播常数（`synth -hieropt`），`keep_hierarchy` 声明的模块照保层级，映射与 ABC 配方与正式口径相同，ABC 延时目标取正式口径胜出的那一档。

`reference` 内容全部是测量值：所用场景名与 `case`、延时目标、综合（单元数、面积、按层次拆开的面积）、TT 与兄弟角的时序（含关键路径级数、起止点、analytic fmax）、depth（最深级数、预算、超预算终点数）、等价证明结论。参考网表 MUST 与接了同样常数的 RTL 网表做等价证明，除非设计声明了 `tops:<顶层>:equiv: false`（用户 2026-10-06 定等价证明可选，内部#232）：声明了的，不做等价，`equiv` 记 `SKIPPED`，参考的面积、时序与 depth 照常写。做了等价而结论不是 PROVED（UNDECIDED、FAILED）时，`reference` MUST 只留 `scenario`、`case`、`delay_target_ps`、`equiv` 与证明日志的路径，MUST NOT 写参考的面积、时序与 depth；正式口径的字段照写（PM 转用户同意，内部#202）。功耗不量。

适用场景不是恰好一个时，MUST 报错。设计在 `tops:<顶层>:synth:reference_ports:` 声明了端口模式时，这些模式匹配到的每个顶层输入 MUST 在该场景的 `case` 里有定值，否则报错。

正式口径的字段 MUST NOT 因为开了 `REFERENCE=1` 而改变。

理由：SoC 把这些配置输入接成常数后，商用工具会做边界优化，正式口径（输入不定、层次不跨）高估面积；但参考值的口径与正式值不同，混在一起会被当成同一种数比较。放在同一条记录里，出处（提交、指纹、RTL 摘要、延时目标）与正式值完全对齐，只差这一件事。

#### Scenario: 参考口径只差接常数

- **WHEN** 一个声明了场景的设计以 `REFERENCE=1` 跑完实验，场景把一条只在另一种排布下用的深链定值剪掉
- **THEN** 记录的 `reference.synth.area_um2` 小于 `synth.area_um2`，`reference.equiv` 为 PROVED，正式口径的字段与不开 `REFERENCE` 时相同

#### Scenario: 没开 REFERENCE

- **WHEN** 普通实验或 sweep
- **THEN** 记录的 `reference` 为 `null`

#### Scenario: 参考网表证不过等价

- **WHEN** 参考网表与接了常数的 RTL 等价证明的结论是 UNDECIDED
- **THEN** 记录照写，正式口径的字段与不开 `REFERENCE` 时相同；`reference` 只有 `scenario`、`case`、`delay_target_ps`、`equiv: UNDECIDED` 与日志路径，没有 `synth`、`sta`、`depth`

#### Scenario: 设计声明不做等价

- **WHEN** 设计声明了 `equiv: false`，以 `REFERENCE=1` 跑完实验
- **THEN** 不调等价证明；`reference.equiv` 为 `SKIPPED`，参考的 `synth`、`sta`、`depth` 照常写

#### Scenario: 常数没定全

- **WHEN** 设计声明了 `reference_ports: [cfg_*]`，适用场景的 `case` 漏了一个匹配的输入
- **THEN** 跑参考口径前报错并点名那个端口，不写记录

### Requirement: RTL 仿真失败时只写失败记录，不往下跑

一次实验的 RTL 仿真有失败用例时，流程 MUST 立即停止，不综合、不跑 STA，并写一条失败记录：`sim.passed` 为 `false`，`sim.gate_passed` 为 `null`；`synth` 与 `sta` 两段保留全部字段名，取值一律为 `null`（含 `sta.corners`、`sta.scenarios`、`synth.area_breakdown`），只有 `synth.sources_sha256` 照常写（读入集合摘要不用综合就能算，扫参的两个跳过开关按它匹配）；`reference` 为 `null`。命令 MUST 以非 0 退出。读记录的工具 MUST 能读这类记录，不因 `null` 报错。

理由：仿真没过，后面测出来的是一份错误电路的 PPA，白跑几分钟到几十分钟（内部#304 实撞：仿真 86 ns 挂了，综合与 STA 照跑）。失败本身是事实，要留下记录；字段名照留，遵守「实验记录的字段集合只能单调增长」里「停止写入一个字段的正确做法是让它取 `null`」。

2026-10-18 之前，仿真失败的记录照样带综合与 STA 的数（当时 4 条）；读法见 docs/data-credibility.md。

#### Scenario: RTL 仿真失败

- **WHEN** 一组参数的 RTL 仿真有失败用例
- **THEN** 不调用综合与 STA，记录的 `sim.passed` 为 `false`，`synth`、`sta` 各字段为 `null`（`synth.sources_sha256` 除外）
- **AND** `make exp` 以非 0 退出

#### Scenario: 读到失败记录

- **WHEN** 扫参摘要、报告、打分或换代配对读到一条 `synth` / `sta` 全为 `null` 的失败记录
- **THEN** 它们照常运行，把这条记成仿真失败，不当成有数的记录参与比较

### Requirement: 实验记录按设计根分文件存放

每条实验记录 MUST 追加到它所属设计根的记录文件 `results/<设计根>/experiments.jsonl`，MUST NOT 写进其他设计根的文件或 `results/experiments.jsonl`。
设计根取记录的 `design_root` 字段。没有这个字段的历史记录（那段历史里设计根名被强制等于顶层名）在搬迁时按顶层整组归属：一个顶层的全部历史行 MUST 进同一个文件，取该顶层带 `design_root` 的最后一条记录的设计根，一条都没有时取 `design`。同一顶层的记录在文件内 MUST 保持原相对顺序：读者靠「后追加的最新」挑同一参数组合的最新记录。
记录文件 MUST NOT 因为设计根被删除而删除。

写入路径 MUST 由一个统一入口按设计解析；METRIC_MODULES 里的模块 MUST NOT 因为这条要求被修改（改它们会开启新的流程代）。

理由：几个 team 的集成分支同时往一个文件末尾追加，合并时每次都冲突，而手工解冲突正是红线 2 最容易被破坏的场合。一个设计根只归一个 team，按设计根分文件以后，跨 team 的合并不再碰同一个文件（用户 2026-10-25 定，内部#422）。

#### Scenario: 跑一次正式实验

- **WHEN** 对设计根 `cbb_popcount` 下的顶层跑 `make -f flow/Makefile exp`
- **THEN** 记录 SHALL 追加到 `results/cbb_popcount/experiments.jsonl`
- **AND** 其他记录文件 MUST 不变

#### Scenario: 扫参中途的脏树守卫

- **WHEN** 扫参写完第一条记录、本设计根的记录文件因此出现未提交改动
- **THEN** 脏树守卫 SHALL 把这个文件当作本次追加的目标放行，后续组合照常运行

### Requirement: 历史记录按设计根搬迁且逐字节守恒

`results/experiments.jsonl` 里的记录 MUST 按上一条的设计根规则搬进各自的记录文件，然后删除 `results/experiments.jsonl`。搬迁 MUST 满足：
- 每一行逐字节不变，不重新序列化；
- 每个记录文件内各行保持在原文件中的相对顺序；
- 原文件的行与全部新文件的行一一对应，不多不少；
- 搬迁可以重复执行：原文件再次出现时（例如合并带来了别处追加的行），只把记录文件里还没有的行逐字节补进去，然后删除原文件。

搬迁之后，读取工具对每个设计给出的结果（`gen_report.py` 生成的报告、`score.py` 的分数）MUST 与搬迁之前逐字节相同。

#### Scenario: 一次性搬迁

- **WHEN** 对含 3464 行的 `results/experiments.jsonl` 执行搬迁
- **THEN** 各记录文件行数之和 SHALL 等于 3464，每一行都能在原文件里逐字节找到
- **AND** `results/experiments.jsonl` 不再存在

#### Scenario: 合并后旧文件又出现

- **WHEN** 搬迁合入之后，合并又带来一个含新增行的 `results/experiments.jsonl`
- **THEN** 再执行一次搬迁 SHALL 只补那些新增行，已经搬过的行不重复，然后删除原文件

#### Scenario: 旧文件不得残留

- **WHEN** 已提交的树里存在 `results/experiments.jsonl`
- **THEN** `scripts/fast_check.sh` MUST 失败，并提示执行搬迁

### Requirement: 已提交记录的 git_commit 必须是 HEAD 的祖先

`scripts/fast_check.sh` MUST 检查：`HEAD` 上每个记录文件里每条记录的 `git_commit` 都是 `HEAD` 的祖先。有任何一条不是时 MUST 失败，并列出记录文件、`git_commit` 与条数。
这条检查在所有分支上都跑，包括 main 和集成分支，MUST 在覆盖摘要里出现。

理由：记录的 `git_commit` 来自产出它时的 `HEAD`。集成分支上产生的记录要能在合进 main 以后照样找到代码，就要求合并只用 merge 或快进；rebase 或 squash 会把那个提交从历史里拿掉，记录本身看不出来。把它做成机械检查，provenance 就不再靠约定。

#### Scenario: 集成分支 squash 进 main

- **WHEN** 一个带新记录的集成分支被 squash 合进 main
- **THEN** main 上的 `fast_check.sh` MUST 以非零退出，并指出哪些记录的 `git_commit` 不可达

#### Scenario: 集成分支 merge 进 main

- **WHEN** 同一个分支用 merge 或快进合进 main
- **THEN** 这条检查 SHALL 通过
