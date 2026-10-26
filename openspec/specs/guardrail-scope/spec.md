# guardrail-scope Specification

## Purpose
规定护栏必须说出自己实际覆盖了什么，以及「通过」在什么条件下才配叫通过。

这个能力管的不是被检查的东西，而是**检查本身**。它存在的理由是：本仓库的头号
失效模式是「报告的范围大于实际检查的范围」，而这个模式已经三次长在护栏自己身上 ——
`scripts/fast_check.sh` 在部分组合失败时照打 `ok ... (all param combos)`；
`params.yaml` 的 `values` 写错键名时组合展开为空，却拿默认参数跑一次并以 0 退出；
`iverilog` 不在 PATH 时跳过全部 RTL 检查、退出码仍是 0。三次都不报错，
三次都让读者以为有防护。

三条要求各管一段。**成功退出的含义**必须是「声明要做的每一类检查都实际执行了
并且通过」，而不是「没有检查失败」—— 两者的区别恰恰在「一个都没跑」这种情形上。
这与 `experiment-trust` 的「无法测得的指标必须缺席，不得以合法值代替」是同一条
原则的两个应用面：那条管记录里的数字，这条管护栏的退出码，失效方式相同 ——
一个语法合法、看上去正常的值顶替了「没能测」。

**覆盖摘要**必须在通过与失败两条路径上都输出。只在失败时说明范围是不够的：
成功路径才是没人细看的那条，而伤害正是在那里造成的 —— 读者看到一个 `ok` 就
停止追问。摘要也不许用「全部 / all」去描述一个并非全部执行的集合。

**挂载状态**必须自愈或可见。依赖每个工作副本单独配置才能生效的护栏（需要
`core.hooksPath` 才会运行的 git hook 即是）不得依赖使用者记得执行某个一次性步骤 ——
忘记执行的后果恰恰是静默的：hook 没挂载与 hook 跑过并通过，在外部看来完全一样。

## Requirements

### Requirement: 护栏的成功退出必须意味着它声明的检查全部执行并通过

护栏脚本以 0 退出时，MUST 表示它声明要做的每一类检查都**实际执行了**，并且每一类要么通过，要么它的失败项**全部**被登记的豁免覆盖（见「秒级护栏的失败只能经登记的豁免放行」）。
某一类检查因环境原因无法执行时，护栏 MUST NOT 以 0 退出，除非调用方通过一个
具名开关显式接受这次降级。

这与 `experiment-trust` 的「无法测得的指标必须缺席，不得以合法值代替」是同一条
原则的两个应用面：那一条管的是记录里的数字，这一条管的是护栏的退出码。两者的
失效方式相同 —— 一个语法合法、看上去正常的值（`0` / `ok`）顶替了「没能测」，
而下游无法把两者区分开。

#### Scenario: 声明的检查全部执行且通过

- **WHEN** 护栏的每一类检查都执行了并且通过
- **THEN** 退出码 SHALL 为 0

#### Scenario: 某一类检查因缺少工具而无法执行

- **WHEN** 某一类检查所依赖的外部工具不可用，且调用方没有给出具名的降级开关
- **THEN** 退出码 MUST NOT 为 0
- **AND** 输出 MUST 指出缺的是什么工具、如何补上，以及如何显式降级

#### Scenario: 调用方显式接受降级

- **WHEN** 调用方通过具名开关声明接受「工具缺失时继续」
- **THEN** 退出码 MAY 为 0
- **AND** 输出 MUST 标明本次运行是降级的，并逐项列出哪些检查没有执行

#### Scenario: 失败项全部被豁免

- **WHEN** 某一类检查失败，而它的每一条违规都被登记的豁免覆盖，其余检查都通过
- **THEN** 退出码 SHALL 为 0
- **AND** 输出 MUST 把这一类标为「豁免」而不是「ok」，并列出生效的豁免

### Requirement: 护栏必须报告它实际覆盖的范围

护栏 MUST 在每次运行结束时输出一段覆盖摘要，说明这次**实际执行了哪些检查**
以及**哪些没有执行**。该摘要 MUST 在通过与失败两条路径上都输出。

只在失败时说明范围是不够的：成功路径才是没人细看的那条，而「报告的范围大于实际
检查的范围」正是在成功路径上造成伤害 —— 读者看到一个 `ok` 就停止追问。

摘要 MUST NOT 使用「全部」「all」一类的总括词来描述一个并非全部执行的集合。

#### Scenario: 全部检查通过

- **WHEN** 护栏运行结束且没有失败项
- **THEN** 输出 MUST 包含覆盖摘要，逐项说明执行了哪些检查
- **AND** 摘要 MUST NOT 声称覆盖了任何本次未执行的检查

#### Scenario: 一部分检查未能执行

- **WHEN** 护栏跳过了某一类检查
- **THEN** 覆盖摘要 MUST 把该类检查列为未执行，并说明原因
- **AND** MUST NOT 只在日志中间打印一行 `SKIP` 而让结尾看起来像全绿

### Requirement: 护栏的挂载状态必须是自愈的或可见的

依赖每个工作副本单独配置才能生效的护栏（例如需要 `core.hooksPath` 才会运行的
git hook），MUST 有一个机制使该配置在正常工作流中自动补齐，或使其缺失可见。
MUST NOT 依赖使用者记得执行某个一次性步骤 —— 忘记执行的后果恰恰是静默的。

#### Scenario: 新克隆的工作副本

- **WHEN** 仓库被重新克隆，护栏所需的本地配置处于默认（未设置）状态
- **THEN** 进入该工作副本的正常流程 SHALL 补齐该配置，或明确报出它缺失
- **AND** MUST NOT 出现「护栏未挂载」与「护栏运行并通过」在外部表现上一致的情况

### Requirement: 秒级护栏必须机械检查设计根的洁净度

秒级护栏（`scripts/fast_check.sh`）MUST 检查每个设计根（`designs/*/`、`cbb/*/`）
目录下是否只存在 `repo-layout` 声明为「源」或「评审记录」的那两类文件；出现任何其他文件
MUST 失败。`review/` 下允许子目录，只认文档后缀（见 `repo-layout`「每类产物必须归属到明确的一层」）；
`rtl/`、`tb/`、`doc/` 下照旧不许子目录。

判据 MUST 是**目录内容本身**，MUST NOT 是 `git status` 是否干净 ——
被 `.gitignore` 挡住的产物同样是写进了设计根。这与
`repo-layout` 的「每类产物必须归属到明确的一层」里已经写死的判据口径一致：
那条 requirement 已经指定了观察量，但在本变更之前没有任何东西在执行它。

设计根里的每个 `.svg` MUST 有同目录同名的 `.drawio`，否则 MUST 失败。

失败信息 MUST 列出具体路径，并说明该文件应该去哪一层，使人不必回头读契约
就能修。

#### Scenario: 设计根下留着上一次仿真的结果文件

- **WHEN** 某个设计根的 `tb/` 下存在 `results.xml`（无论是否被 `.gitignore` 挡住）
- **THEN** 护栏 MUST 失败并列出该路径
- **AND** 失败信息 MUST 指出它应当落在 `runs/<experiment_id>/` 下

#### Scenario: 设计根下只有源文件

- **WHEN** 每个设计根下只有 `spec.md` / `design.md` / `verify.md` / `params.yaml`
  / `REPORT.md` / `rtl/` / `tb/` / `doc/` 这一类契约声明的源，以及 `review/` 下的评审文档
- **THEN** 护栏 MUST 通过
- **AND** 覆盖摘要 MUST 列出这一类检查已执行，并给出检查过的设计根数量

#### Scenario: 评审目录里有证据日志

- **WHEN** 某个设计根的 `review/r1/` 下存在 `run.log`
- **THEN** 护栏 MUST 失败并列出该路径
- **AND** 失败信息 MUST 指出 `review/` 只收文档

### Requirement: 秒级护栏必须扫描可综合 RTL 里的仿真专用构造

秒级护栏 MUST 扫描 `designs/*/rtl/`、`cbb/*/rtl/` 下的 RTL，拒绝仿真专用的
构造进入可综合路径：文件系统与进程调用（`$fopen` / `$fwrite` / `$fclose` /
`$fscanf` / `$fread` / `$fdisplay` / `$system`）、非确定性源（`$random` /
`$urandom`）、外部内容加载（`$readmemb` / `$readmemh`）、波形转储
（`$dumpfile` / `$dumpvars` / `$dumpports`）、DPI 导入导出、`initial` 块、
以及形如 `#<数字>` 的延时。

理由是这些构造进了可综合 RTL 之后，**仿真看到的电路与综合出的电路会当场分家，
而两边都不报错** —— 仿真照常全绿，综合照常出网表，只是两者测的不是同一个东西。
这是本仓库的头号失效模式（「跑通了但数字不可信」）在 RTL 层的形态。

扫描 MUST 先剥掉注释与字符串字面量再做匹配：注释里写着 `$random` 不是违规，
把它算成违规会让护栏变成噪音，而噪音会让人加豁免。

失败信息 MUST 给出文件、行号与命中的构造。

#### Scenario: 可综合 RTL 里出现非确定性源

- **WHEN** 某个设计根的 `rtl/` 下有一份 RTL 用了 `$random`
- **THEN** 护栏 MUST 失败，并给出该文件、行号与命中的构造

#### Scenario: 注释里提到仿真构造

- **WHEN** RTL 的注释或字符串字面量里出现 `$random`、`initial` 等字样，而代码本身没有
- **THEN** 护栏 MUST 通过 —— 这不是违规

#### Scenario: 全部 RTL 都不含仿真专用构造

- **WHEN** 所有设计根的 `rtl/` 都不含上述任何构造
- **THEN** 护栏 MUST 通过
- **AND** 覆盖摘要 MUST 列出这一类检查已执行，并给出扫描过的 RTL 文件数量

### Requirement: 扫参必须报告它这一轮实际覆盖了哪些组合

扫参入口（`scripts/sweep.py`）MUST 在每次运行结束时输出一段覆盖摘要，说明
**这一轮实际跑了哪些参数组合**、**跳过了哪些**、以及**按什么口径判定「已有」**。
该摘要 MUST 在正常结束与中途失败两条路径上都输出。

这是「护栏必须报告它实际覆盖的范围」的同一条原则换了对象：那一条管的是检查，
这一条管的是实验的产出。失效方式相同 —— 一个以 0 退出、看上去正常的运行顶替了
「大部分组合根本没跑」，而下游（`results/<设计根>/experiments.jsonl` 的行数、
`make report` 生成的 `REPORT.md`）无法把「72 条都跑了」与「跳过了 69 条、只跑了 3 条」
区分开。

摘要 MUST NOT 使用「全部」「all」一类的总括词来描述一个并非全部执行的集合。

#### Scenario: 一轮完整扫参

- **WHEN** 扫参跑完了全部参数组合，没有跳过任何一个
- **THEN** 输出 MUST 给出组合总数与本轮实际跑的条数，且两者相等
- **AND** 摘要 MUST 说明本轮没有启用任何跳过开关

#### Scenario: 启用跳过开关、只补了一部分

- **WHEN** 扫参因跳过开关而只跑了组合总数的一部分
- **THEN** 输出 MUST 分别给出组合总数、跳过数、实际跑的条数
- **AND** MUST 说明「已有」的判定口径是什么（按哪些字段匹配）
- **AND** MUST NOT 只在被跳过的每一条上打印一行 `skip` 而让结尾看起来像跑满了

#### Scenario: 扫参中途被打断

- **WHEN** 扫参在跑到一半时因某个组合失败而中止
- **THEN** 已输出的逐组合进度 MUST 足以判断中止在第几个组合
- **AND** MUST NOT 要求回头去数 `results/<设计根>/experiments.jsonl` 才能知道跑到哪了

### Requirement: 判定「已有」的口径不同的跳过开关必须彼此排斥

当扫参提供一个以上的「跳过已有结果」开关，而它们判定「已有」所依据的字段集合
不同时，同时启用两个 MUST 报错退出，MUST NOT 让其中一个静默压过另一个。

理由：这两个开关的输出长得一模一样（都是「跳过 N 条」），差别只在 N 是按什么算
出来的。一方静默胜出时，使用者得到的是一个**不会报错的误解** ——
他以为跳过的是「本代已有的」，实际跳过的是「任何一代跑过的」，于是新一代少了
几十条而没有任何迹象。这与本能力开篇的失效模式同源：报告的范围大于实际的范围。

每个开关的帮助文本 MUST 写明它按哪些字段匹配。

#### Scenario: 同时启用两个口径不同的跳过开关

- **WHEN** 调用方同时给出两个判定口径不同的跳过开关
- **THEN** 扫参 MUST 以非 0 退出，且一个组合都不跑
- **AND** 报错 MUST 说清两者的口径各是什么、该选哪一个

#### Scenario: 只启用其中一个

- **WHEN** 调用方只给出一个跳过开关
- **THEN** 扫参 SHALL 按该开关的口径判定「已有」
- **AND** 覆盖摘要 MUST 写明本轮用的是哪一个口径

### Requirement: 护栏的断言必须是契约，不得是当下恰好为真的事实

测试与护栏里的断言 MUST 表达一条**契约**（某件事必须成立），MUST NOT 表达一条
**当下恰好为真的观察**（某个数现在是多少、某个分支现在恰好胜出）。

区分的判据：问「被测对象在允许的范围内变化时，这条断言还该成立吗」。答案为否的，
它就不是契约 —— 它红的时候不指示缺陷，只指示被测对象动了，而那是允许的。

这类断言的代价不是误报本身，是**误报会训练人去无视它**：一条隔三差五就要重打的
断言，最终会被连同它旁边真正的判据一起跳过。

本仓两次发作：

- 2026-09-14，`test_the_schema_only_grows` 原本断言
  `"register_count" in set(record["sta"]) - set(previous["sta"])`
  （「这个字段是新加的」）。该字段落盘之后差集变空，用例失败，而**数据只是长了**。
  判据改成「全部历史记录字段名的并集都还在」——契约本身。
- 2026-09-16，`test_a_design_an_order_of_magnitude_slower_still_searches` 断言
  「这个设计的 base 最快」。某个闭源设计的 RTL 改了之后
  （d0 1381 ps → 1169.9 ps），`target=351` 以 1162.8 ps 险胜，用例失败，
  而那个用例存在的理由（搜索要跑得完、要给出结论）**一点没受影响**。

当一条判据确实需要锚定一个**测量出来的数**（回归锚点是正当用法），
该断言 MUST 在紧邻处写明：这个数是**什么时候、在哪一份被测对象上**测出来的，
以及**什么情况下应当重打**。没有这三样，后来的人无法区分「它红了是因为出了缺陷」
与「它红了是因为被测对象按计划变了」。

#### Scenario: 被测对象在允许范围内变化

- **WHEN** 被测对象（RTL、数据集）发生一次被许可的变化，而流程本身没有改变
- **THEN** 只表达契约的断言 SHALL 保持绿
- **AND** 因此变红的断言 MUST 被判为「编码了事实而非契约」，并改写成契约形式，
  MUST NOT 只是把数字更新一遍了事

#### Scenario: 判据确实需要一个测量出来的锚点

- **WHEN** 某条判据必须拿一个实测数字当回归锚点
- **THEN** 紧邻处 MUST 写明该数字的测得时间、被测对象的版本，以及重打的条件
- **AND** MUST NOT 只留一个裸数字

### Requirement: 秒级护栏必须检查 spec 端口表与 RTL 一致

`scripts/fast_check.sh` MUST 对每个被测顶层的**每个参数组合**，比对该顶层接口文档的端口表与该组合下 RTL 顶层的实际端口：
- 接口文档：`designs/` 下是 `lrs.<顶层>.md`，`cbb/` 下是 `spec.<顶层>.md`；顶层在 `params.yaml` 声明了 `port_doc` 时是那份文档，覆盖摘要 MUST 写出这些顶层与所用文档；
- 端口表的写法：`repo-layout` 的「spec 的端口表必须能被机械地读出」；
- 端口集合 MUST 相同，每个端口的方向 MUST 相同，位宽表达式按该组合的参数值求出的整数 MUST 等于实际位宽。

任一不一致 MUST 失败，并列出顶层、端口、文档的写法与求值结果、RTL 的实际值，以及出现不一致的参数组合。

实际端口与参数值 MUST 取自同一轮 elaborate 的工具输出，MUST NOT 为此另外调用一遍仿真或综合工具：这一项加在秒级护栏里，代价只能是解析。参数值 MUST 用工具算出的值（含由其他参数算出的 parameter），MUST NOT 在脚本里重新推导 —— 重新推导等于把 RTL 的参数逻辑再写一份，两份会漂移。

以下情形 MUST 失败，MUST NOT 当作通过或跳过：
- 接口文档不存在；
- 找不到端口表；
- 位宽表达式求不出整数；
- 该组合 elaborate 失败而拿不到端口。

elaborate 因工具缺失而整体未执行时，这一项 MUST 与 elaborate 一起列为「未执行」（`护栏的成功退出必须意味着它声明的检查全部执行并通过`）。

理由：设计内部改动不走 OpenSpec（内部#58），接口契约唯一的权威是接口文档。2026-09-27 首次全量比对，6 个顶层里已有 2 个的 spec 过时（某闭源 IP的两个子设计，各有端口与 spec 不符），而之前没有任何东西失败。

#### Scenario: 某一档参数下位宽对不上

- **WHEN** 接口文档把 `din` 的位宽写成 `512`，而 RTL 是 `[32*LANE_NUM-1:0]`，参数组合含 `LANE_NUM=8`
- **THEN** 护栏 MUST 失败，列出 `din`、文档的 `512`、RTL 的 `256` 与 `LANE_NUM=8`

#### Scenario: RTL 有而 spec 没写的端口

- **WHEN** RTL 顶层有端口 `o_pos_z`，端口表里没有
- **THEN** 护栏 MUST 失败并列出 `o_pos_z`

#### Scenario: 方向写反

- **WHEN** 端口表把一个 RTL 输出端口写成 `in`
- **THEN** 护栏 MUST 失败并列出该端口与两边的方向

#### Scenario: 位宽表达式求不出值

- **WHEN** 位宽列写的是「同上」或引用了不存在的参数名
- **THEN** 护栏 MUST 失败并列出该端口与原文

#### Scenario: 专用设计读 LRS

- **WHEN** `designs/<根>` 的 `lrs.<顶层>.md` 端口表与 RTL 一致，根下没有 `spec.<顶层>.md`
- **THEN** 这一项 SHALL 通过

#### Scenario: 全部一致

- **WHEN** 每个顶层的每个组合都一致
- **THEN** 这一项 SHALL 通过，覆盖摘要 MUST 写出检查过的顶层数与组合数

### Requirement: 跳过开关判定「已有」必须包含被测 RTL 的内容摘要

扫参的每一个「跳过已有结果」开关，判定一个组合「已有」时 MUST 要求记录的 `synth.sources_sha256` 等于**本次开跑前**对当前 RTL 算出的读入集合摘要，再叠加该开关自己的其他匹配字段。没有这个字段的记录 MUST NOT 被当作已有。

当前摘要 MUST 用与记录写入时同一个函数算出（`flow/synth/synth.py` 的 `sources_digest(source_files(design))`），MUST NOT 另写一份哈希逻辑 —— 两份会漂移，漂移的方向是「永远配不上」或「永远配得上」，后者正是本要求要消灭的失效。

本轮写出来的记录，其 `synth.sources_sha256` 与开跑前算的摘要不一致时，扫参 MUST 中止并报出两个值：这意味着 RTL 在扫参过程中被改了，本轮补上的记录不属于它以为的那份电路。

覆盖摘要与每个开关的帮助文本 MUST 写出包含 `synth.sources_sha256` 在内的完整匹配键。

理由：流程指纹不含 RTL（RTL 是被测对象，不是流程），所以改了 RTL 不换代。在此之前两个开关都只按参数（与指纹）匹配，改了 RTL 之后的重跑会把最该重跑的那批恰好跳过，覆盖摘要照报「已有 N 条」而看不出异常（`docs/data-credibility.md` 的 D-14，2026-09-16 实撞）。

#### Scenario: 改了 RTL 之后续跑

- **WHEN** 记录里某个组合已有一条本代记录，但它的 `synth.sources_sha256` 与当前 RTL 算出的不同，且调用方开了任一跳过开关
- **THEN** 这个组合 MUST 被重跑，不得跳过

#### Scenario: RTL 没改的续跑

- **WHEN** 某个组合已有一条记录，`synth.sources_sha256` 与当前相同、且该开关的其他匹配字段也相同
- **THEN** 这个组合 SHALL 被跳过

#### Scenario: 旧记录没有摘要字段

- **WHEN** 某个组合的记录都早于 2026-09-20、没有 `synth.sources_sha256`
- **THEN** 它 MUST NOT 被当作已有

#### Scenario: 扫参中途 RTL 被改

- **WHEN** 开了跳过开关，本轮写出的某条记录的 `synth.sources_sha256` 与开跑前算的不同
- **THEN** 扫参 MUST 中止并报出两个摘要值

#### Scenario: 覆盖摘要写明匹配键

- **WHEN** 以任一跳过开关运行
- **THEN** 覆盖摘要 MUST 列出包含 `synth.sources_sha256` 的完整匹配键与本次的摘要前缀

### Requirement: 秒级护栏必须机械检查 RTL 书写风格

秒级护栏 MUST 对 `designs/*/rtl/*.v`、`cbb/*/rtl/*.v` 与 `flow/templates/*.v` 中不在
`flow/lint/style_legacy.txt` 里的文件检查下列十四项（`rtl-structure-authority` 的书写风格约定里
能机械判定的部分，`add-rtl-coding-style` 的 D16；第 11–14 项是同一份契约「RTL 的书写约定」的四条，内部#101）：

1. 出现 tab。
2. 出现非 ASCII 字符。
3. 头注释缺少五字段之一，或 `File` 不是本文件名、`Module` 不是本文件声明的模块、`Spec` 指向的文件不存在。
4. 文件声明的 `module` 不是恰好一个，或文件名不是模块名的小写加 `.v`。
5. 出现 `casex` 或 `casez`。
6. 一个 `case` … `endcase` 里没有 `default`（嵌套的 `case` 各自判）。
7. 时序 always 块（敏感表含 `posedge`）里 `<=` 的目标名不以 `_r` 或 `_<n>ff` 结尾（拼接目标逐个判）。
8. always 块没有块名，或块名不以 `BLK_` 开头；always 内的 for 块名不以 `BLK_FOR` 开头。
9. generate 里的条件块或 for 块没有块名，或条件块名不以 `GEN_` 开头、for 块名不以 `GEN_FOR` 开头。
10. 例化名不以 `U_<当前模块名>_` 开头，或不以 `_<被例化模块名>` 结尾（D7）；例化的是同一设计根里 `flow/lint/local_cbb.txt` 列出的本地 CBB 副本时，改判例化名不是 `U_<共享 CBB 名>[_<功能>]` 的全大写形态，或以隔离后缀结尾（`rtl-structure-authority` 的命名第 4 条）。
11. 出现 `` `default_nettype ``。
12. `wire` / `reg` 的定义里带赋值（定义到 `;` 之间出现单独的 `=`）。
13. 出现 `localparam integer`。
14. `generate` … `endgenerate` 之间定义 `localparam`。

除第 2 项外，匹配前 MUST 先剥掉注释与字符串字面量。

豁免清单 MUST 被双向核对：清单里的路径不存在，或该文件十四项全部通过，护栏 MUST 失败并要求移出。

失败信息 MUST 给出文件、行号（能给时）与违反的是哪一项；覆盖摘要 MUST 给出检查的文件数与豁免的文件数。

#### Scenario: 一个合约定的新文件

- **WHEN** 一个新 RTL 文件十项全部合约定
- **THEN** 护栏 SHALL 通过，覆盖摘要把它计入检查的文件数

#### Scenario: 一个新文件违反其中一项

- **WHEN** 一个不在豁免清单里的 RTL 文件违反十项中的任一项
- **THEN** 护栏 SHALL 失败，并指出文件、行号与违反的项

#### Scenario: 注释里提到 casez

- **WHEN** 一个文件只在注释里写了 `casez`
- **THEN** 这一项 SHALL NOT 失败

#### Scenario: 豁免文件已合规

- **WHEN** 豁免清单里的一个文件十项全部通过
- **THEN** 护栏 SHALL 失败，并要求把它从清单里删掉

#### Scenario: 冻结的黄金参照

- **WHEN** `flow/equiv/frozen/` 下的文件不合书写风格
- **THEN** 这一项 SHALL NOT 扫描它 —— 它不在扫描范围内

#### Scenario: 例化名用了序号

- **WHEN** `FOO_BUF` 里例化 `CBB_LZD`，例化名写成 `U_CBB_LZD_2`
- **THEN** 护栏 SHALL 失败，并给出应有的形态 `U_FOO_BUF_<功能>_CBB_LZD`

#### Scenario: 本地 CBB 副本的例化名

- **WHEN** 某设计根 `rtl/` 里例化名单内的 `cbb_lzd_foo`
- **THEN** 例化名 `U_CBB_LZD_ZERO_DET` SHALL 通过
- **AND** 例化名 `U_CBB_LZD_ZERO_DET_FOO` 与 `U_FOO_BUF_ZERO_DET_CBB_LZD` SHALL 失败

#### Scenario: 以隔离后缀形态结尾的大写模块不放宽

- **WHEN** 某模块例化一个名字以 `_FOO` 结尾的大写模块（如 `CBB_SYS_FOO`）
- **THEN** 例化名 SHALL 按 D7 以 `_CBB_SYS_FOO` 结尾，以 `_CBB_SYS` 结尾 SHALL 失败

#### Scenario: generate 里定义 localparam

- **WHEN** 一个 RTL 文件在 `generate` 块内写了 `localparam W = i + 1;`
- **THEN** 护栏 SHALL 失败，指出文件、行号与第 14 项

### Requirement: 秒级护栏必须检查每个设计根都能被流程解析

秒级护栏 MUST 用流程自己的解析入口（`flow/paths.py`）对 `designs/` 与 `cbb/` 下的全部设计根建一次
顶层索引；任一设计根让索引报错时护栏 MUST 失败并转述错误。覆盖摘要 MUST 报出设计根总数与其中
规格先行的个数。

理由是护栏自己按 `params.yaml` 遍历设计根，看不到会让流程解析报错的根：2026-09-28 一个只放了规格的根
让内循环从 5 个失败涨到 62 个，而护栏报的是通过（内部#74）。

#### Scenario: 一个设计根会让流程解析报错

- **WHEN** 某个设计根有 `rtl/` 而没有 `params.yaml`
- **THEN** 护栏 SHALL 失败，并指出是哪个根、缺什么

#### Scenario: 规格先行的设计根

- **WHEN** 某个设计根只有 `spec.*.md`
- **THEN** 这一项 SHALL 通过，并在摘要里把它计入规格先行的个数

### Requirement: 秒级护栏必须机械检查 RTL 命名约定

秒级护栏（`scripts/fast_check.sh`）MUST 对 `designs/**/*.v` 与 `cbb/**/*.v` 里的每一个模块
检查 `rtl-structure-authority` 的「模块接口与参数必须遵守统一命名约定」，并检查每个
`params.yaml` 的参数键；MUST NOT 扫描 `flow/equiv/frozen/`。`params.yaml` 顶层声明了 `role: ip` 的设计根，
其中的模块改按「IP 设计根的模块端口与参数按 IP 级约定命名」检查；端口扫描 MUST 跳过 `function` / `task`
体。覆盖摘要 MUST 报出检查了多少个模块、多少个参数、多少个端口，以及其中多少个模块按 IP 级约定检查。

#### Scenario: 全部合规

- **WHEN** 所有模块与 `params.yaml` 都合约定
- **THEN** 这一项 SHALL 通过，并在覆盖摘要里报出模块 / 参数 / 端口的个数

#### Scenario: 有一处不合规

- **WHEN** 任意一个模块的一个参数或端口不合约定
- **THEN** 护栏 SHALL 以非零退出
- **AND** 输出 MUST 列出每一处违规的文件、模块、名字与违反的条款

### Requirement: 秒级护栏必须机械检查结构枚举取整数且每个编号都有名字

秒级护栏 MUST 对 `designs/**/*.v` 与 `cbb/**/*.v` 检查 `rtl-structure-authority` 的「结构枚举参数必须
取整数」中可判定的部分：`SCHEME` / `*_SCHEME` 的默认值是整数字面量。并 MUST 对每个 `params.yaml`
检查 `flow-parameterization` 的「结构枚举参数的每个编号都必须有名字」。「分派链对每个合法取值写显式
判断」由 elaborate 检查的非法取值用例守，不靠文本匹配猜。

#### Scenario: 编号缺名字

- **WHEN** 某个 `params.yaml` 的 `SCHEME` 声明了 `values: [0, 1, 2]`，而 `labels` 只有 0 与 1
- **THEN** 护栏 SHALL 失败，并指出设计、参数与缺名字的编号

### Requirement: 秒级护栏必须检查 LRS 与 LLD 的结构与需求追溯

`scripts/fast_check.sh` MUST 对 `designs/` 下每个被测顶层，检查 `repo-layout`「专用设计的 LRS 与 LLD 必须有必填节与需求追溯」的全部条款：
- LRS、LLD 文件存在；
- 必填节齐全；
- R 编号格式正确、只定义一次、至少一条；
- 追溯表存在，覆盖全部 R，没有悬空引用；
- `params.yaml` 的参数都在参数表里；
- 断言编号唯一、正文引用的断言都有定义；
- 版本表升序；
- RTL 顶层的端口不能只写在规划端口表里。
- LRS 的代码块里没有框线或箭头字符（字符画结构图）。

任一不满足 MUST 失败，并点名顶层、文件与缺的节或编号。

覆盖摘要 MUST 写出检查过的顶层数与需求条数。

#### Scenario: 过渡清单里的根

- **WHEN** 有人仍在已删除的 `flow/lint/doc_legacy.txt` 里登记 `designs/<根>`，根下还是 spec / design
- **THEN** 护栏 SHALL 不再跳过它：按 LRS / LLD 检查并失败，点名缺的 LRS / LLD 与不该存在的旧文档（旧格式已退役，内部#134）

### Requirement: 秒级护栏必须检查 lint 豁免没有过时

`scripts/fast_check.sh` MUST 把 `flow/lint/waivers.vlt` 与每个设计根的 `waivers.vlt` 一起交给 lint，并逐条检查这些文件里的 `lint_off`：
- `-file` 的通配在 `designs/*/rtl/` 与 `cbb/*/rtl/` 下 MUST 至少匹配一个文件；
- 有 `-match` 且其中有引号括起的标识符时，这个标识符 MUST 至少在一个匹配到的文件里按单词边界出现。

任一不满足 MUST 失败，并点名豁免文件、行号与原因。覆盖摘要 MUST 写出检查过的豁免文件数与条数。

理由：豁免是对 lint 的有意放行，它指向的文件或信号不在了，放行就没有对象；留着它会在下一次有人写出同名信号时静默放过真问题（内部#109）。

#### Scenario: 豁免的信号已删除

- **WHEN** `waivers.vlt` 里有 `-file "*/foo_buf.v" -match "*'stale_flag'"`，`foo_buf.v` 里已经没有 `stale_flag`
- **THEN** 护栏 MUST 失败并点名这一行

#### Scenario: 设计根带自己的豁免

- **WHEN** `designs/foo/waivers.vlt` 豁免了 `foo.v` 里的一个未用信号
- **THEN** lint SHALL 按这份豁免放行，覆盖摘要 SHALL 把这份文件算进去

### Requirement: 秒级护栏的失败只能经登记的豁免放行

`scripts/fast_check.sh` 中按文件定位违规的检查段，失败时 MUST 读 `flow/check_waivers.yaml`。每条豁免 MUST 写明检查段、文件 glob、本仓 issue 号、到期条件与登记时放行的违规条数 `count`，缺任一项 MUST 失败。一条违规只有在它的路径匹配同一检查段某条豁免的 glob 时才算被豁免；一条豁免本次匹配到的违规条数 MUST 等于它的 `count`，多了（同一文件里出现了新违规）或少了（修掉了一部分、余量会藏住以后的新违规）这一段都 MUST 失败，并写出登记数与本次数；认不出路径的违规行 MUST 按未豁免处理。一段里只要有一条违规未被豁免，这一段 MUST 失败。

理由：红灯要么修掉，要么留下谁、为什么、到什么时候的记录；不按整段豁免，是为了不把同一段里新出现的违规一起放过（内部#254，用户 2026-10-12 定）。按文件匹配仍会放过同一文件里新加的违规（内部#330：`1ac5b5e0` 的一处新违规因此漏过，直到豁免失效才挡住），所以再按条数卡住。

#### Scenario: 违规全部在豁免的文件里

- **WHEN** `style` 段报出 `designs/foo/rtl/a.v` 的两条违规，豁免文件登记了 `check: style`、`files: designs/foo/rtl/a.v`、`count: 2`
- **THEN** 这一段 SHALL 标为豁免，不使退出码非 0

#### Scenario: 同一段里有不在豁免内的违规

- **WHEN** 同上，另有一条违规在 `designs/foo/rtl/b.v`
- **THEN** 这一段 MUST 失败，且输出 MUST 区分哪些行被豁免、哪些没有

#### Scenario: 豁免缺字段

- **WHEN** 一条豁免没有写 `issue`
- **THEN** 护栏 MUST 失败并点名这一条

#### Scenario: 豁免的文件里多出一条新违规

- **WHEN** 豁免登记 `count: 2`，本次同一文件报出 3 条违规
- **THEN** 这一段 MUST 失败，输出写明登记 2 条、本次 3 条

#### Scenario: 豁免的违规修掉了一部分

- **WHEN** 豁免登记 `count: 2`，本次同一文件只报出 1 条违规
- **THEN** 这一段 MUST 失败，并要求把 `count` 改成 1

### Requirement: 秒级护栏必须检查失败豁免没有过时

一条豁免本次运行没有放行任何违规时，护栏 MUST 失败并点名它。豁免还在放行违规、且能查到挂的 issue 已关闭时，护栏 MUST 打一行提示点名该 issue，MUST NOT 因此失败（内部#291，用户 2026-10-13 定：修复交付即关、还没进本分支时不能卡住基于 main 的分支）；挂着失败豁免的 issue 在删豁免的提交进 main 之后才关。查不到 issue 状态时 MUST 提示「未核 issue 状态」，不得静默。

#### Scenario: 违规已修好，豁免还在

- **WHEN** 豁免登记的 `style` 段在 `designs/foo/rtl/a.v` 上已没有违规
- **THEN** 护栏 MUST 失败，并点名这条豁免已过时

#### Scenario: issue 已关，修复还没进本分支

- **WHEN** 豁免仍在放行 `designs/foo/rtl/a.v` 上的违规，而挂的 issue 已关闭
- **THEN** 护栏 MUST NOT 因此失败，输出 MUST 有一行提示点名该 issue

#### Scenario: 离线

- **WHEN** 查询 issue 状态失败
- **THEN** 输出 MUST 有一行说明本次没有核 issue 状态

### Requirement: 推 main 前的合并检查有一键入口，缺工具时失败

仓库 MUST 提供 `scripts/merge_check.py --base <提交> --head <提交>`：在 head 的临时检出里跑 `./scripts/fast_check.sh` 与 pytest（并发取自 `flow/budget.py`，默认 4，见「本机重活有并发上限，大活排队」），在 base 与 head 的临时检出里各收一次 `pytest --collect-only` 的用例 ID，输出三项结论（fast_check 退出码、pytest 通过 / 失败 / 跳过数、用例 ID 删去、新增与改名的清单），跑完删掉临时检出。三项里任一项不合格（fast_check 非 0、pytest 有失败或跳过、用例 ID 有删去）MUST 以非 0 退出。

用例 ID 按「文件::函数」（去掉参数化的 `[…]` 部分）分组比：同一组里删去的个数不多于新增的个数时，删去的 MUST 记为改名（逐条列出旧 → 新），不算删去；删去多于新增、或整个函数没了，那一组删去的 ID MUST 照算删去。分组配对之后仍算删去的 ID，若新增里有一条只是文件路径不同、其余（`函数[参数]`，含类名）逐字相同，MUST 记为搬家（逐条列出旧 → 新），不算删去；一条新增只配一次。

pytest 的范围按 base..head 的改动定，输出首行 MUST 写明用的是哪种：

- **全量**（默认）：`pytest tests/`。
- **轻量**：改动的每个路径都是 `*.md` / `*.drawio` / 图片（`.png` `.svg` `.jpg` `.jpeg` `.gif`），且第一段目录是 `designs` `cbb` `docs` `knowledge` `team` 之一（base 与 head 树相同也算）时，只跑一张固定的文档测试清单。清单里任一文件在 head 上不存在时 MUST 回退全量并说明。`--full` MUST 强制全量。轻量模式的 fast_check MUST 带 `--docs-only`。

`./scripts/fast_check.sh --docs-only` 是具名开关：不跑 RTL lint，覆盖摘要 MUST 把 lint 逐顶层列为未执行并写明原因（只改文档）；elaborate、端口表比对与其余检查 MUST 照跑，退出码按它们定。

跑 pytest 之前，head 的临时检出里 MUST 先放入调用方 worktree 的读入集合缓存（`runs/.source_sets/`）；缓存条目按内容核键，不符的照常重算。

通过（退出 0）的结果 MUST 按「base 树、head 树、模式、跑检查的脚本、EDA 工具与 Python 环境」记在 git 公共目录下，所有 worktree 共用。同一组输入再跑时 MUST 直接复用：打印复用了哪次（时间、在哪个 worktree 跑的、base / head 提交）和当时的三项结论，退出 0，不排队拿 `cpu-heavy`、不建临时检出。未通过的结果 MUST NOT 记录、MUST NOT 复用。`--no-cache` MUST 跳过复用。

`./scripts/fast_check.sh --rev <提交>` MUST 在该提交的临时检出里跑，输出写明提交号。

两者在补过 `~/tools/env.sh` 之后 EDA 工具仍不在 PATH 时 MUST 失败，MUST NOT 静默跳过（不带 EDA PATH 的 pytest 会跳过一百多条用例）。

理由：项目经理每次推 main 都手工拼这三项，比 base 的用例 ID 还要临时建 worktree、软链 `.venv`（内部#344）。10-19 到 10-20 的 43 h 里 merge_check 占全部会话命令耗时的 26%，有同一份内容在两个 worktree 各验一遍、只改文档也跑全量 986 条的情况；用户 10-20 定复用通过的结果、只改文档走轻量（内部#379）。新检出里没有读入集合缓存，带 `-n` 的 pytest 开跑前要单核预热约 9 分钟（内部#384）；用户 10-21 定把缓存带进检出、轻量模式不跑 lint。参数化用例的参数文字一改（如开源清理把参数里的名字换成中性写法），ID 就跟着变，以前一律算删去，内部#383 推 main 时 6 处只能按例外放行；用户 10-21 定同一函数内自动配对（内部#385）；拆 `tests/test_fast_check.py`（281 条用例）时大半用例换文件，用户 10-21 定补跨文件搬家的配对（内部#336）。

#### Scenario: head 删掉了一条用例

- **WHEN** head 相对 base 少了一个用例 ID，其余全过
- **THEN** 脚本以非 0 退出，并点名那个用例 ID

#### Scenario: 按提交跑 fast_check

- **WHEN** `./scripts/fast_check.sh --rev abc123`
- **THEN** 跑的是 `abc123` 的检出，输出首行写明完整提交号

#### Scenario: 同一份内容第二次跑

- **WHEN** 对同一组 base / head 已有一次通过的结果，另一个 worktree 再跑 merge_check
- **THEN** 脚本打印「复用」与那次的时间、worktree、三项结论，退出 0，不拿 `cpu-heavy`

#### Scenario: 失败的结果不复用

- **WHEN** 上一次同一组 base / head 的检查失败，修掉之前再跑一次
- **THEN** 脚本照常检查，不复用

#### Scenario: 只改了设计文档

- **WHEN** base..head 只改了 `designs/<根>/lrs.<顶层>.md`
- **THEN** 输出首行是「模式：轻量（只改文档，1 个文件）」，pytest 只跑文档测试清单

#### Scenario: 文档之外还改了别的

- **WHEN** base..head 改了 `docs/toolchain.md` 和 `scripts/merge_check.py`
- **THEN** 输出首行是「模式：全量」

#### Scenario: 只改文档时 fast_check 不跑 lint

- **WHEN** 轻量模式跑 head 上的 fast_check
- **THEN** fast_check 带 `--docs-only`，覆盖摘要把 RTL lint 列为未执行，elaborate 与端口表比对照跑

#### Scenario: 临时检出带上读入集合缓存

- **WHEN** 调用方 worktree 的 `runs/.source_sets/` 里有缓存文件
- **THEN** head 的临时检出里 pytest 开跑时，同名文件已经在检出的 `runs/.source_sets/` 下

#### Scenario: 参数化用例的 ID 改名

- **WHEN** head 里 `tests/test_x.py::test_a` 的 2 个参数化 ID 文字变了，个数不变
- **THEN** 用例 ID 一行写「删 0、增 0、改名 2」并逐条列出旧 → 新，这一项合格

#### Scenario: 同一函数删多于增

- **WHEN** `tests/test_x.py::test_a` 删了 2 个参数化 ID、只新增 1 个，或整个 `test_a` 没了
- **THEN** 那一组删去的 ID 照算删去，脚本以非 0 退出并点名

#### Scenario: 用例搬到另一个文件

- **WHEN** `tests/test_a.py::test_x[p]` 在 head 里变成 `tests/test_b.py::test_x[p]`，其余不变
- **THEN** 用例 ID 一行写「删 0、增 0、改名 0、搬家 1」并列出旧 → 新，这一项合格

### Requirement: 评审开工的机械检查有一键入口

仓库 MUST 提供 `scripts/review_prep.py --rev <被评提交> --top <顶层> [--prev <上一轮被评提交>]`，在被评提交的临时检出里完成评审开工的机械检查，输出一张能贴进评审清单「所评版本」表的 Markdown，跑完删掉临时检出：

- 被评提交自己的 fast_check 退出码与 lint 摘要；
- 不带豁免的 lint 告警按类别计数：默认参数一行，被评提交的 fast_check 参数组合一行。命令 MUST 与 fast_check 的 lint 相同，只是去掉豁免文件；
- 给了 `--prev` 时，lint 豁免相对上一轮的新增、删除，以及只换了 `-file` 的；
- LRS / LLD（CBB 为 spec）的版本、行数、SHA256。

源文件、参数组合、设计根 MUST 用被评提交自己的流程代码取，MUST NOT 用当前检出的代码去算旧提交。

理由：评审每轮手工凑这套命令，踩过 verilator 不在 PATH、zsh 不展开源文件列表；手跑的 lint 口径还和 fast_check 不一样，rtl-r2 因此多报 3 条 UNUSEDPARAM（内部#196）。

#### Scenario: 复现 rtl-r2 的所评版本表

- **WHEN** `--rev <rtl-r2 的被评提交> --top <顶层> --prev <上一轮被评提交>`
- **THEN** 表里的 LRS / LLD 版本、fast_check 结论（组合数、豁免条数）、默认参数的无豁免 lint 条数（`--no-param-chk` 时与手填表逐类相同）、豁免增减（新增、删除、换文件）与 rtl-r2 的手填表逐项相同（实测数见 内部#196）

#### Scenario: 跑完不留检出

- **WHEN** 脚本跑完，不管被评提交的 fast_check 过没过
- **THEN** `git worktree list` 里没有它建的临时检出

### Requirement: 本机重活有并发上限，大活排队

流程工具的并发默认 MUST 是 4，环境变量 `KAIWU_JOBS` 可调，MUST NOT 按核数满开。涉及的工具：fast_check 的 lint / elaborate、merge_check 里的 pytest、review_prep 的逐组合 lint。

大活 MUST 排队：`make iodeps` / `regress` / `sweep`、merge_check（全量模式）、review_prep 开跑前，经 `flow/budget.py` 等 1 分钟负载不超过核数（`KAIWU_MAX_LOAD` 可调）、内存压力不高于「正常」（macOS `kern.memorystatus_vm_pressure_level`），再拿 keel 共享资源租约 `cpu-heavy`，跑完释放。等满 `KAIWU_WAIT_MIN` 分钟仍拿不到时，MUST 以非 0 退出并写明在等谁；keel 不在 PATH 时 MUST 失败，MUST NOT 悄悄不排队就跑。

租约存在本仓的 git 公共目录，排队范围是本仓的所有 worktree；文档 MUST NOT 把它写成机器级隔离。别的仓的重活不经这把锁，由 `flow/cpu_watch.py` 巡检点名（见「全机 CPU 有巡检，超载点名到会话」）。

持有租约期间 MUST 定期续租（默认每 30 分钟，`KAIWU_RENEW_MIN` 可调），大活跑得比租期长时锁也不丢；续租失败 MUST 打印告警，命令照常跑完，结束时照样释放。

merge_check 的轻量模式（只改文档，判据见「推 main 前的合并检查有一键入口，缺工具时失败」）MUST NOT 拿 `cpu-heavy`：它只串行跑文档用例清单与带 `--docs-only` 的 fast_check，占用很小；开跑前按下面 fast_check 同样的办法等负载。

fast_check 开跑前 MUST 等 1 分钟负载降到 `KAIWU_MAX_LOAD` 以下，期间每 30 秒打印「等负载」；最多等 `KAIWU_FASTCHECK_WAIT_MIN` 分钟（默认 10），等满打印说明后照跑。fast_check 不拿 `cpu-heavy`；已在大活里（`KAIWU_HEAVY_HELD=1`）或设了 `FAST_CHECK_NO_LOAD_WAIT=1` 时不等。

理由：多个会话同时按核数满开 fast_check、`pytest -n auto`、合并检查，10 核的机器负载到过 94，交换区几乎用满，前台卡住（内部#359，用户 10-19）。10-20 几个会话同步后同时推送，pre-push 的 fast_check 叠到负载 79（内部#382）；租约固定 3 小时、不续租，长扫参会被别人回收租约（内部#375）；用户 10-21 定加续租、fast_check 等负载、跨仓不做。只改一行文档的轻量合并检查也进锁，曾排在别人的全量回归后面约 40 分钟（内部#440，用户 10-26 定开单）。

#### Scenario: 别人正在跑大活

- **WHEN** 另一个会话持有 `cpu-heavy`
- **THEN** `make iodeps` 每 30 秒重试并打印持有者；对方释放后开跑；等满时限仍没拿到就退出 3

#### Scenario: 默认并发

- **WHEN** 不设 `KAIWU_JOBS` 跑 fast_check
- **THEN** 同时运行的 lint / elaborate 不超过 4 个

#### Scenario: 大活跑得比租期长

- **WHEN** 一个大活持有 `cpu-heavy` 跑了超过一个续租间隔
- **THEN** `flow/budget.py` 已经对同一资源再 acquire 过，其他会话仍拿不到锁；续租失败时打印「续租失败」，命令不中断

#### Scenario: 负载高时推送

- **WHEN** 1 分钟负载高于 `KAIWU_MAX_LOAD` 时 pre-push 跑 fast_check
- **THEN** fast_check 打印「等负载」并等待，负载降下来后才开始第一项检查；等满上限后照跑并说明

#### Scenario: 只改文档的合并检查

- **WHEN** 另一个会话持有 `cpu-heavy`，merge_check 走轻量模式（base..head 只改文档）
- **THEN** merge_check 不去拿 `cpu-heavy`，照常跑完；同样的提交带 `--full` 时仍等锁，等满时限退出 3

### Requirement: 全机 CPU 有巡检，超载点名到会话

仓库 MUST 提供 `flow/cpu_watch.py`：采样全机负载与各进程 %CPU，沿父进程链把进程归到工作区根（本仓的上一级，由 git 公共目录推出，`KAIWU_WATCH_ROOT` 可覆盖；不写死目录名）下的仓或 worktree，kaiwu 仓的 worktree 换成 keel chat 角色名，打印「谁在占」的表。给 `--post <群>` 时，负载连续两次采样超过门槛 MUST 在该群点名合计至少一个核的归属，同一归属 30 分钟内 MUST NOT 重复点名。脚本 MUST NOT 终止、暂停或调整任何进程的优先级。

理由：用户 2026-10-19 要一个能管全机 CPU 的人，定由 kaiwu-flow 兼管、只点名不动进程（内部#359）。工作区目录计划改名，用户 2026-10-25 定所有仓都不应依赖这个名字，默认根改为由仓库推出。

#### Scenario: 工作区目录改名之后

- **WHEN** 工作区目录改了名，没有设 `KAIWU_WATCH_ROOT`
- **THEN** cpu_watch 的归因范围是本仓 git 公共目录的上两级，照样把各 worktree 名下的进程归到角色名

#### Scenario: 持续超载

- **WHEN** 两次采样的 1 分钟负载都超过核数，某个 worktree 名下进程合计 250% CPU
- **THEN** 群里出现一条点名消息，写明该 worktree 的角色名、250%、最重的命令；30 分钟内再超载也不再点它

#### Scenario: 临时检出的归属

- **WHEN** merge_check 在系统临时目录的检出里跑 pytest
- **THEN** 这些进程记到启动 merge_check 的那个 worktree 名下

### Requirement: 评审复核有两提交的规格差分入口

仓库 MUST 提供 `scripts/spec_diff.py --from <提交> --to <提交>`：直接从两个提交读规格文档（不建检出），按顶层比 R 定义、接口表（名-方向-位宽）、图注、设计断言、节标题的增删改，并列出文档引用而该提交里不存在的图片文件，输出一张表。给 `--same <项,…>` 时，列出的项有任何差异 MUST 以非 0 退出。

理由：评审答复轮要证明「声称没动的东西确实没动」，以前评审方每轮手写脚本比，口径不一（内部#213 F-a、G11，内部#228）。

#### Scenario: 答复轮声称没动 R 与接口表

- **WHEN** `spec_diff.py --from <上一轮被评提交> --to <答复提交> --same R,接口表`，而答复提交改了一条 R 的条文
- **THEN** 退出 1，表里点名这条 R 的编号与前后两行

#### Scenario: 图片丢了

- **WHEN** 答复提交的 LRS 引用了 `doc/x.svg`，而该提交里没有这个文件
- **THEN** 表里「图片文件」一项列出 `doc/x.svg` 为缺

### Requirement: 秒级护栏同一份内容只检查一次

`scripts/fast_check.sh` 通过（退出 0）的结果 MUST 按「HEAD 树、相对本地 `main` 的 merge-base、参数、EDA 工具与 Python 环境」记在 git 公共目录下，所有 worktree 共用。工作区干净（没有未提交的改动，设计根下也没有被忽略的散落文件）且没设 `FAST_CHECK_ALLOW_MISSING_TOOLS` 时，同一组输入再跑 MUST 直接复用：打印「复用」与那次的时间、worktree、HEAD 树，再原样打印当时的覆盖摘要，不等负载、不跑其余检查。未通过的结果 MUST NOT 记录、MUST NOT 复用。`--no-cache` MUST 跳过复用。

例外：结论依赖**当前分支名或提交历史**、而不只依赖树的检查——「记录与报告」那几项（`flow/check/fc_record_branches.py`）——MUST NOT 复用：命中缓存时照样实跑，打印在「本次实跑」下，失败则退出 1；记进缓存的覆盖摘要 MUST NOT 含它们。

复用的覆盖摘要是那次实际执行的检查：同一组输入上它们的结论不变，「通过」仍然意味着声明的检查都执行过并通过（见「护栏的成功退出必须意味着它声明的检查全部执行并通过」）。

理由：快进到别人已经验过的提交时，pre-push 把整套重跑一遍；几个会话同时同步、同时推送时就叠成高负载（内部#382，用户 10-21 定复用）。同一棵树可以挂在不同分支、不同历史上，按分支放行与 git_commit 可达这几项复用会被跳过（内部#432）；它们是秒级的，实跑不费负载。

#### Scenario: 快进到验过的提交再推送

- **WHEN** 另一个 worktree 已经在同一 HEAD 树、同一 merge-base 上跑通过 fast_check，本 worktree 工作区干净
- **THEN** fast_check 打印「复用」与当时的覆盖摘要，不调用 iverilog / verilator；「记录与报告」几项按本 worktree 的分支与提交实跑，通过则退出 0

#### Scenario: 工作区不干净

- **WHEN** 有未提交的改动，或设计根下有被忽略的散落文件
- **THEN** fast_check 照常检查，不复用、不记录

#### Scenario: 换了分支名再跑

- **WHEN** 在 main 上通过并记下后，同一提交切到分支 `worktree-y` 再跑
- **THEN** 输出里「记录与报告的来源」写的是 `worktree-y`，不出现回放的「当前分支 main」

#### Scenario: 树相同、历史不同

- **WHEN** 白名单分支上「改一处、再按那个提交写一条记录」通过并记下，之后把它 squash 成 main 上的一个提交放到另一个分支（同一棵树、同一个 merge-base）
- **THEN** 命中缓存，但「记录的 git_commit 可达 HEAD」实跑失败，fast_check 退出 1
