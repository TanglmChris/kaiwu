# repo-layout Specification

## Purpose

规定仓库里每一类产物放在哪、归谁、以及为什么那条边界不能松。

三条主线。**设计与可复用构件的布局对等** —— `designs/<name>/` 与 `cbb/<name>/` 用
逐项一致的内部布局，使同一套流程代码无需分支即可驱动两者；两类目录的区别只在
依赖方向（构件被别的设计例化），不在结构。**产物分三层且 git 归属确定** ——
源进版本控制，单次原始产物（网表、VCD、SAIF、STA 报告原文、综合 log）只写
`runs/<experiment_id>/` 且不进版本控制，durable 指标只存
实验记录 `results/<设计根>/experiments.jsonl`。**设计根名等于顶层模块名** —— 流程不提供「设计名与
顶层名不同」的配置项。

最后一条是这份 spec 里唯一一条从流程代码里被提炼上来的：`run_sim.py` 的
`hdl_toplevel=design`、`synth.py` 的 `synth -top {design}`、`run_sta.py` 的
`link_design {design}` 三处都直接拿设计名当顶层名。写进规格是为了让「一个设计根
只测一个顶层」成为显式契约 —— 一个带多个可综合顶层的上游设计搬进来时，必须先
决定哪个顶层是被测量的那个，而不是让流程在某一步静默失败。

## Requirements

### Requirement: 设计与可复用构件的目录布局必须对等

`designs/<name>/` 与 `cbb/<name>/` MUST 使用同一套目录布局，流程 MUST 用同一套
代码路径处理两者。

每个设计根 SHALL 包含：`params.yaml`（可调参数与被测顶层声明）、`rtl/`（RTL 源码）、
`tb/`（验证环境与代码）。

每个**被测顶层** SHALL 在其设计根下各有一套文档，文件名 MUST 带顶层名以区分。哪几份文档由设计根所在的目录决定：

- `designs/` 下的专用设计：`lrs.<顶层>.md`（LRS，逻辑需求规格说明书）、`lld.<顶层>.md`（LLD，逻辑详细设计方案）、`verify.<顶层>.md`；
- `cbb/` 下的通用构件：`spec.<顶层>.md`（精简规格，含实现要点）、`verify.<顶层>.md`。

`designs/` 下的旧格式 `spec.<顶层>.md` / `design.<顶层>.md` 已退役（用户 2026-10-04，内部#134），出现即违规。由记录生成的 `REPORT` 同样 MUST 一个顶层一份。

理由：这些文档描述的都是**某一个被测电路**。把一个 IP 两个方向的内容并进一份，会把接口契约互相淹没；而 Pareto 前沿是在同一个电路的微架构维度上求的，两个不同电路的前沿合进一张表没有意义。专用设计把需求（LRS）与实现（LLD）分开，验证照 LRS 写、实现可以在 LLD 里改；通用小构件规模小，一份精简 spec 足够（用户 2026-10-03）。

#### Scenario: 对一个 CBB 跑 PPA 实验

- **WHEN** 对 `cbb/<name>` 声明的某个顶层运行与 `designs/` 下相同的实验命令
- **THEN** 命令成功执行，不需要为 CBB 单独指定路径或走不同代码分支
- **AND** 写入 `results/<设计根>/experiments.jsonl` 的记录格式与设计的记录格式相同

#### Scenario: 检查工具遍历所有设计根

- **WHEN** 运行 `scripts/fast_check.sh`
- **THEN** `designs/` 与 `cbb/` 下的每个设计根的**每个被测顶层**都被检查
- **AND** 两者使用同一套检查逻辑，只是认的文档名不同

#### Scenario: 一个设计根下有两个被测顶层的文档

- **WHEN** `designs/` 下一个设计根声明了两个被测顶层
- **THEN** 该根下 MUST 有两套 `lrs` / `lld` / `verify` 文档，各自带顶层名
- **AND** `make report` 为每个顶层各刷新一份 `REPORT`

#### Scenario: 通用构件里出现 design 文档

- **WHEN** `cbb/<根>/` 下有 `design.<顶层>.md` 或 `lld.<顶层>.md`
- **THEN** `scripts/fast_check.sh` 的设计根洁净度一项 MUST 失败，并说明通用构件只有 spec 与 verify

### Requirement: 设计根必须按名字唯一解析

流程 MUST 提供按设计名解析设计根的单一入口，搜索的设计树 SHALL 依次为 `designs/`（专用设计）、`cbb/`（通用构件），只有这两棵；开源与闭源的设计根同放其中，开源与否只由开源白名单逐设计根声明（「闭源内容只在闭源设计根下」）。
- 设计根都在仓库根下第二层（`<树>/<根>/`），流程里「设计根的上两级就是仓库根」的假设成立。
- 同一个名字在两处及以上存在时，解析 MUST 报错并指出全部冲突路径，MUST NOT 静默选择其一。

理由：开源还是闭源是设计根的属性，不是目录的属性（用户 2026-10-15，内部#305）。2026-10 曾短暂另设 `ip_designs/`、`ip_cbb/` 两棵闭源树，已收回；设计根深度始终不变，推仓库根的代码与指纹都不受影响。

#### Scenario: 名字只在一处存在

- **WHEN** 以名字 `adder32` 解析设计根，且只有 `designs/adder32/` 存在
- **THEN** 解析返回 `designs/adder32/`

#### Scenario: 名字只在 ip_ 树里存在

- **WHEN** 仓库里出现 `ip_designs/<根>/` 或 `ip_cbb/<根>/`
- **THEN** 它不是设计树，解析 MUST NOT 在其中查找；设计根 MUST 放回 `designs/` 或 `cbb/`

#### Scenario: 名字在两处都存在

- **WHEN** 以名字 `foo` 解析设计根，且 `designs/foo/` 与 `cbb/foo/` 同时声明了它
- **THEN** 解析失败并报错
- **AND** 错误信息同时包含两个冲突路径

#### Scenario: 名字不存在

- **WHEN** 以一个所有设计树里都没有的名字解析设计根
- **THEN** 解析失败并报错，错误信息列出已声明的顶层

#### Scenario: 扩树不改变现有设计的指纹

- **WHEN** 设计树名单在两棵与四棵之间变化（2026-10 先扩后收）
- **THEN** 每个现有顶层的 `flow.fingerprint` 与 `flow.design_recipe_sha256` 逐字不变

### Requirement: 每类产物必须归属到明确的一层

仓库中的产物 MUST 归属于以下四层之一，且每层的 git 归属是确定的：

- **源**：`spec.md` / `design.md` / `verify.md` / `params.yaml` / `rtl/` / `tb/`，以及设计根自己的 lint 豁免 `waivers.vlt`、仿真构建专用豁免 `sim_waivers.vlt`（内部#312）与本地 CBB 副本名单 `local_cbb.txt`（都与 `params.yaml` 同级，可选；`local_cbb.txt` 见 `rtl-structure-authority`「模块名必须全大写」，内部#305） — MUST 进版本控制
- **评审记录**：设计根的 `review/` 下，一次评审一个子目录，只收文档（`.md`、`.diff`、`.patch`、`.html`、`.svg`、`.drawio`，`.svg` 要有同名 `.drawio`） — MUST 进版本控制；流程工具 MUST NOT 往里写。评审留下的日志、JSON、脚本等非文档证据 MUST NOT 进 `review/`
- **单次原始产物**：网表、VCD、SAIF、STA 报告原文、综合 log、**测试框架的结果文件** — MUST 写入
  `runs/<experiment_id>/`，且 MUST NOT 进版本控制
- **durable 指标**：MUST 只存在于 `results/<设计根>/experiments.jsonl`

单次原始产物 MUST NOT 写入设计根目录内部。

判定「有没有写进设计根」MUST 以**该目录下有没有新增文件**为观察量，
MUST NOT 以 `git status` 是否干净为观察量。被 `.gitignore` 挡住的产物同样是
写进了设计根 —— 用 git 的视野去检查这条，会让契约在被违反时照样通过。

**「新增文件」不区分它是谁的产物。** 解释器写的字节码缓存（`__pycache__/`）、
编辑器的临时文件、测试框架的结果文件，在这条约束下是同一类东西：它们都不是
契约声明的「源」，都留在设计根里。这条 MUST NOT 开例外白名单 —— 一旦开了，
判据就从「目录里有没有别的东西」退化成「目录里有没有**我认得的**别的东西」，
而下一个漏进来的产物恰恰是没人认得的那个。工具产生的缓存 MUST 由调用方
把它重定向到设计根之外（例如 `PYTHONPYCACHEPREFIX`），而不是被豁免。

这条约束 MUST 有一个机械判据在执行（见 `guardrail-scope` 的
「秒级护栏必须机械检查设计根的洁净度」）。只写在契约里而没有东西查它，
与没有这条约束的可观察后果完全相同。

#### Scenario: 扫描多个参数组合

- **WHEN** 对同一个设计扫描 N 个参数组合
- **THEN** 产生 N 个互不覆盖的 `runs/<experiment_id>/` 目录
- **AND** 设计根目录下没有新增任何文件（**是否被 `.gitignore` 挡住不作数**）

#### Scenario: 仿真产出测试框架的结果文件

- **WHEN** 一次仿真产出测试框架的结果文件（如 cocotb 的 `results.xml`）
- **THEN** 该文件 MUST 落在本次运行的 `runs/…/` 目录下
- **AND** 设计根的 `tb/` 目录下 MUST NOT 出现它

#### Scenario: 导入测试台产生了字节码缓存

- **WHEN** 仿真或测试导入了设计根 `tb/` 下的 Python 测试台，解释器要写字节码缓存
- **THEN** 缓存 MUST 落在设计根之外
- **AND** 设计根下 MUST NOT 出现 `__pycache__/`
- **AND** 护栏 MUST NOT 因为「它只是缓存」而放行它

#### Scenario: 检查产物是否泄漏进版本控制

- **WHEN** 一次实验运行结束后执行 `git status --porcelain`
- **THEN** 输出中不包含 `runs/` 下的任何路径

#### Scenario: 设计根带自己的 lint 豁免

- **WHEN** `designs/<根>/waivers.vlt` 存在
- **THEN** 它 SHALL 算作源文件，设计根洁净度检查 MUST NOT 把它当成不该存在的东西

#### Scenario: 设计根带自己的仿真豁免

- **WHEN** `<设计根>/sim_waivers.vlt` 存在
- **THEN** 它 SHALL 算作源文件，设计根洁净度检查 MUST NOT 把它当成不该存在的东西

#### Scenario: 设计根带自己的本地 CBB 副本名单

- **WHEN** `designs/<根>/local_cbb.txt` 存在
- **THEN** 它 SHALL 算作源文件，设计根洁净度检查 MUST NOT 把它当成不该存在的东西

#### Scenario: 设计根带评审记录

- **WHEN** `<设计根>/review/<某次评审>/` 下只有 `.md`、`.diff`、`.html` 与成对的 `.svg` / `.drawio`
- **THEN** 它们 SHALL 算作评审记录，设计根洁净度检查 MUST 通过

#### Scenario: 评审记录里夹着证据日志

- **WHEN** `<设计根>/review/` 下出现 `.log`、`.json`、`.sh`、`.zip` 之类的文件
- **THEN** 设计根洁净度检查 MUST 失败并列出该路径

### Requirement: 设计根可以携带上游权威文档

设计根 MAY 包含一个 `doc/` 子目录，存放该设计的上游权威规格（算法推导、几何表、
版本历史等）。`doc/` 的内容 MUST 进版本控制，MUST NOT 被任何检查脚本或门禁
当作完成判据。

例外：顶层用 `port_doc` 声明的过渡端口表（「spec 的端口表必须能被机械地读出」）参与端口比对。

`doc/` 可以放 draw.io 图：`.drawio` 源文件与由它导出的 `.svg`，平放在 `doc/` 下。每个 `.svg` MUST 有同目录同名的 `.drawio`。截图、渲染图等其他图片格式 MUST NOT 放进设计根。

动机是从外部仓库搬进来的成熟设计通常带着一份比 `spec.md` 长一个数量级的算法
文档。把它塞进 `spec.md` 会淹没接口契约；把它丢掉则丢掉了这个设计唯一的
权威描述。`spec.md` 仍然是本仓库口径的接口/参数契约，`doc/` 是它引用的上游依据。

#### Scenario: 带 doc/ 的设计根跑检查

- **WHEN** 一个设计根含有 `doc/` 且 `spec.md` / `design.md` / `verify.md` /
  `params.yaml` / `rtl/` / `tb/` 齐备
- **THEN** `scripts/fast_check.sh` 通过
- **AND** 该设计可以正常跑完整实验流程

#### Scenario: doc/ 与 spec.md 冲突

- **WHEN** `doc/` 中的描述与设计根的 `spec.md` 就同一件事给出不同说法
- **THEN** 以 `spec.md` 为准（它描述的是本仓库实际综合、实际测量的那个顶层）
- **AND** 该冲突 MUST 在 `spec.md` 中显式记下，MUST NOT 靠读者自己发现

#### Scenario: SVG 没有源文件

- **WHEN** `designs/<根>/doc/arch.svg` 存在，`doc/arch.drawio` 不存在
- **THEN** 洁净度检查 MUST 失败并点名 `arch.svg`

### Requirement: 跨设计根复制的源文件必须逐字节相同

同一个文件名出现在**多个设计根的同一层**（`rtl/` 或 `tb/`）时，各份内容
MUST 逐字节相同，且这一条 MUST 由自动检查覆盖。

理由是复制的失效方式是**漂移**，而漂移之后两个设计根测的是两个不同的东西 ——
记录里看不出来。这对 RTL 与验证代码同样成立：

- **RTL 漂移** —— 两个设计根测的是两个不同的电路，而 `params` 段、
  `flow.fingerprint`、`git_commit` 全都一模一样。
- **黄金参考模型漂移** —— 两个 TB 拿两个不同的期望值去比，各自"全绿"。
  这比 RTL 漂移更隐蔽：RTL 漂移至少会让 PPA 数字对不上，模型漂移连数字都不产生。

要避免复制，正确做法 SHALL 是把该文件搬进 `cbb/` —— 那棵树就是为「被多方需要的
构件」准备的。**MUST NOT** 用「让检查忽略这一对」的方式解决。

#### Scenario: 一个模块同时被两个设计根需要

- **WHEN** 同一个 `.v` 文件名出现在两个 `designs/*/rtl/` 下
- **THEN** 自动检查比对两份内容
- **AND** 内容不同时检查失败，并同时报出两份的路径与各自的摘要

#### Scenario: 两个设计根共用同一份黄金参考模型

- **WHEN** 一个设计的 TB 需要另一个设计的 TB 已经写过的独立参考模型
- **AND** 该模型以同名文件的形式复制进了第二个设计根的 `tb/`
- **THEN** 自动检查以与 RTL 相同的判据比对两份内容
- **AND** 内容不同时检查失败 —— 两个 TB 拿着两个不同的期望值各自全绿，
  是这个仓库最难发现的一类失效

#### Scenario: 检查报告它实际比对了多少组

- **WHEN** 运行 `scripts/fast_check.sh`
- **THEN** 覆盖摘要里写明比对了多少组同名文件
- **AND** 一组都没比对到时 MUST NOT 报告为通过 —— "没有同名文件"与
  "检查没跑起来"在输出上必须可区分

### Requirement: 设计根可以声明多个被测顶层

设计根 MUST 通过 `params.yaml` 显式声明它的**被测顶层集合**。集合里的每个顶层
MUST 对应 `rtl/` 下一个可独立综合的模块，并且 MUST 各自带一份完整的参数声明
（`sim` / `sta` / `params`）。流程 MUST 按**顶层名**而不是根目录名解析被测对象。

顶层名 MUST 在整个 `designs/` + `cbb/` 范围内全局唯一。同一个顶层名在两个设计根下
被声明时，解析 MUST 报错并指出两处，MUST NOT 静默选择其一。

这条替换了原来的「设计根的名字必须等于该设计的顶层模块名」。原来那条把
「一个 IP 的两个方向」逼成两个设计根，而那两个根之间只能靠逐字节相同的文件拷贝
保持一致 —— 拷贝的失效方式是漂移，而漂移在记录里看不出来。收根之后这类拷贝消失，
`跨设计根复制的源文件必须逐字节相同` 那条检查因此应当报 **0 组**；
**该检查 MUST 保留** —— 它防的是这类拷贝再次出现，而不是当前有没有。

`params.yaml` 的形态 MUST 统一，**不得**「单顶层用旧形态、多顶层用新形态」两种并存：
只有一个被测顶层的设计根（如 `adder32`）同样 MUST 用 `tops:` 声明它。
理由是两种形态意味着两条解析路径，而只有一条会被日常使用，另一条的失效是静默的。

#### Scenario: 一个设计根声明两个被测顶层

- **WHEN** 一个设计根在 `params.yaml` 的 `tops:` 下声明了两个顶层
- **THEN** 对其中任一顶层发起实验，仿真 / 综合 / STA / 记录全链路成功
- **AND** 两个顶层各自使用自己声明的 `sim` / `sta` / `params`
- **AND** 两次实验写出的记录带同一个 `design_root`、不同的 `design`

#### Scenario: 顶层名在两个设计根下重复声明

- **WHEN** 两个设计根的 `tops:` 里出现同一个顶层名
- **THEN** 解析报错并指出两处声明
- **AND** MUST NOT 静默选择其一，MUST NOT 产生实验记录

#### Scenario: 声明的顶层在 RTL 目录下不存在

- **WHEN** `tops:` 里声明的某个顶层在该设计根的 `rtl/` 下找不到同名模块
- **THEN** 流程报错
- **AND** MUST NOT 产生实验记录

#### Scenario: 只有一个被测顶层的设计根

- **WHEN** 一个设计根只测一个顶层
- **THEN** 它的 `params.yaml` 仍然 MUST 用 `tops:` 声明该顶层
- **AND** 流程 MUST NOT 提供「省略 `tops:` 时以根目录名为顶层」的回退

### Requirement: 产物的归属不得依赖调用入口

「每类产物必须归属到明确的一层」这条约束 MUST 由**流程侧自己**保证，
MUST NOT 依赖调用方走某一条特定入口。

同一条纪律有两条执行路径而只有一条落实时，失效方式是**间歇性**的：走 `make`
时干净，直接调 Python 模块时脏。而后者恰恰是取证、调试、写测试时最常走的那条。
2026-09-20 实撞两次（本仓
内部#53）：`PYTHONPYCACHEPREFIX`
只在 `flow/Makefile` 里 export，于是任何绕开 make 的调用都在
`designs/<root>/tb/` 下留一个 `__pycache__`。

流程侧设置这类环境默认值 SHALL 用「没设过才设」的形式，
MUST NOT 覆盖调用方已经给定的值。

#### Scenario: 绕开 make 直接调用流程模块

- **WHEN** 直接执行 `flow/sim/run_sim.py`（或把它当库调用）
- **THEN** 设计根下 SHALL NOT 出现任何新增文件
- **AND** 判据 MUST 是目录内容，不是 `git status`

#### Scenario: 调用方已经设过该环境变量

- **WHEN** 调用方（例如 `flow/Makefile`）已经设置了该变量
- **THEN** 流程 SHALL 沿用调用方给的值，不覆盖

### Requirement: spec 的端口表必须能被机械地读出

每个被测顶层的接口文档 MUST 含一张端口表，覆盖该顶层 RTL 的全部端口，且能被脚本无歧义地读出。接口文档在 `designs/` 下是 `lrs.<顶层>.md`，在 `cbb/` 下是 `spec.<顶层>.md`。

- 表头 MUST 含「方向」列、「信号」或「端口」列、「位宽」或「宽度」列；列的顺序不限，其他列不限。文档里**所有**满足这个条件的表合起来是端口表：LRS 的接口按类型分节（时钟与复位、数据通道、配置与控制、状态输出、存储器、DFX 等），每节一张表。同一端口 MUST NOT 出现在两张表里。其他表 MUST NOT 同时用这三类列名。
- 每行 MUST 只写一个端口。端口名 MAY 用反引号包起来。MUST NOT 把多个端口合写成一行（如 `o_pos_x/y/z`），也 MUST NOT 用「同上」。
- **一个接口一张表**：端口行之下 MAY 紧跟它的字段行，字段行的「方向」一格 MUST 留空（「信号」写字段名，「位宽」写字段宽度）。方向为空的行不参与端口比对。
- 方向 MUST 是 `in`、`out`、`inout` 之一。
- 位宽 MUST 是一个能用该顶层的参数值求出整数的表达式：整数、参数名（含由其他参数算出的 parameter）、`+ - * /`、括号、`$clog2(...)`。MAY 用反引号包起来。

- **规划端口**：还没有 RTL 的端口 MAY 写在表头含「规划信号」「方向」「位宽」的表里，这类表不参与端口比对。规划端口表 MAY 列现有端口的规划形态（与正式端口表同名）。端口有了 RTL 之后 MUST 写进正式端口表（表头改回「信号」）：RTL 顶层的端口只出现在规划端口表里时，护栏 MUST 失败并点名，提示把它移进正式端口表。

- **集成期的过渡端口表**：被测顶层的 RTL 还在逐个并入模块、端口与最终接口不同时，MAY 在 `params.yaml` 声明 `tops:<顶层>:port_doc: <相对设计根的路径>`（如 `doc/track.<顶层>.md`）。声明了的，端口比对 MUST 读这份文档里的端口表（写法同上），不读 LRS；这时 LRS 只写最终接口。文件 MUST 在设计根里且存在。集成完成后 MUST 删掉这个键。

理由：设计内部改动不开 OpenSpec change（内部#58），接口文档是接口契约唯一的权威描述；只有能被机械读出，才能被机械检查（`guardrail-scope` 的「秒级护栏必须检查 spec 端口表与 RTL 一致」）。约定按列名而不按列序定位，是为了接受现有两种表头，不为格式统一改文档。

#### Scenario: 合写的端口行

- **WHEN** 端口表里有一行写成 `o_pos_x/y/z`，宽度写 `X_W`/`Y_W`/`Z_W`
- **THEN** 这张表不符合约定；要拆成三行，每行一个端口、一个位宽表达式

#### Scenario: 位宽依赖参数

- **WHEN** 端口位宽随参数变化，例如 `32*LANE_NUM`
- **THEN** 位宽列 MUST 写这个表达式，MUST NOT 写某一档参数下的数值（如 `512`）

#### Scenario: 接口按类型分成几张表

- **WHEN** LRS 的接口一节分成「时钟与复位」「数据通道」两小节，各有一张端口表
- **THEN** 两张表的端口合起来 SHALL 与 RTL 比对；只写在第二张表里的端口 SHALL 被比到

#### Scenario: 端口有了 RTL 但还写在规划表里

- **WHEN** `s_foo_vld` 只写在「规划信号」表里，正式端口表没有它，RTL 顶层已经有这个端口
- **THEN** 护栏 MUST 失败并点名 `s_foo_vld`，提示把它移进正式端口表

#### Scenario: 集成期按过渡端口表比对

- **WHEN** `params.yaml` 声明 `port_doc: doc/track.FOO.md`，RTL 顶层的端口与这份文档的端口表一致，与 LRS 不一致
- **THEN** 端口比对 SHALL 通过，覆盖摘要 MUST 写明 FOO 按 `doc/track.FOO.md` 比对

#### Scenario: 端口行下面跟字段行

- **WHEN** 端口表里 `s_cmd_pld` 一行之下有两行方向为空的字段行 `.addr`、`.len`
- **THEN** 端口比对 SHALL 只比 `s_cmd_pld`，两行字段行不算端口

### Requirement: 被测顶层可以声明对 cbb 构件的依赖

被测顶层 MAY 在 `params.yaml` 的 `tops:<顶层>:deps:` 下列出它例化的构件，每项写**构件的顶层名**（如 `CBB_LZD`）。流程 MUST 按下面的规则处理。

- **方向**：每项 MUST 是构件树（`cbb/`）下某个设计根声明过的顶层，MUST NOT 指向专用设计树（`designs/`）下的顶层。
  - 构件自己也 MAY 声明 `deps`（只能指向构件树），依赖按传递闭包展开。
  - 依赖成环时 MUST 报错。
- **读入集合**：该顶层的候选源文件 SHALL 是本根 `rtl/*.v` 加上闭包里每个依赖根的 `rtl/*.v`。
  - 读入集合仍 SHALL 是这些候选在全部声明取值下的存活模块闭包，与没有依赖时的口径相同。
  - 读入集合的缓存 MUST 随任何一个候选文件的内容变化而失效。
- **声明必须用上**：闭包里某个依赖根的文件一个都没进读入集合时，流程 MUST 报错并点名该依赖，MUST NOT 静默忽略。
  - 例化了但没声明的构件，MUST 像其他缺失模块一样报错。
- **护栏同口径**：`scripts/fast_check.sh` 对该顶层每个参数组合做 elaborate 与 lint 时，MUST 读入同一组候选文件。
- **不写即不变**：没有 `deps` 的顶层，候选文件、读入集合与 `synth.sources_sha256` MUST 与本要求加入之前逐字节相同。

理由：
- 专用设计树只放由构件组装出来的 IP（`cbb/README.md`），而流程与护栏以前只读设计根自己的 `rtl/`。于是 IP 要例化构件，只能靠拷贝（会漂移），或靠目录里碰巧有什么。
- 读入集合是能改变 PPA 的自变量（本仓 内部#50），必须由声明与例化关系确定。
- 依赖的内容已经由 `synth.sources_sha256` 按文件名与内容记进每条记录，所以记录 schema 不必新增字段。

#### Scenario: IP 例化构件

- **WHEN** 一个专用设计的顶层声明 `deps: [CBB_LZD, CBB_BIN2ONEHOT]`，且 RTL 例化了这两个构件
- **THEN** 仿真、综合、STA 与 `fast_check` 都读入这两个构件根 `rtl/` 里被例化到的文件
- **AND** 记录的 `synth.sources_sha256` 覆盖这些构件文件的内容

#### Scenario: 依赖指向 ip_cbb

- **WHEN** `deps` 里有一项是闭源构件（白名单里没有它的设计根）
- **THEN** 它与开源构件同等解析：构件都在 `cbb/` 下，开源与否不影响依赖解析

#### Scenario: 构件改了

- **WHEN** 已有读入集合缓存之后，被依赖构件的某个 `rtl/*.v` 内容变了
- **THEN** 下一次解析读入集合时缓存失效、重新计算
- **AND** 用改后的构件跑出的记录，其 `synth.sources_sha256` 与改前不同

#### Scenario: 声明拼错或过期

- **WHEN** `deps` 里有一项不是任何构件树设计根声明的顶层
- **THEN** 解析报错并指出该名字，MUST NOT 产生实验记录
- **WHEN** `deps` 里有一项存在，但它的模块在任何声明取值下都没被例化
- **THEN** 解析报错并指出该依赖

#### Scenario: 依赖指向 designs

- **WHEN** `deps` 里有一项是 `designs/` 下的顶层
- **THEN** 解析报错。IP 之间共用的模块应当搬进构件树（「跨设计根复制的源文件必须逐字节相同」）

#### Scenario: 没有依赖的设计

- **WHEN** 一个顶层没有写 `deps`
- **THEN** 它的读入集合与 `synth.sources_sha256` 与本要求加入之前相同

### Requirement: 设计根可以先只有规格

既没有 `params.yaml` 也没有 `rtl/` 的设计根是**规格先行**的设计根：电路还没写，规格先进仓。
它是「设计与可复用构件的目录布局必须对等」里「每个设计根 SHALL 包含 `params.yaml`、`rtl/`、`tb/`」
的唯一例外。规格先行的根 MUST 至少有一份 `spec.*.md`、`lrs.*.md` 或 `doc/` 下的文件；流程按顶层名解析时
MUST 跳过它，MUST NOT 因它报错。

有 `rtl/` 却没有 `params.yaml` 的根**不是**规格先行，那是漏写了被测顶层声明，解析 MUST 照旧报错。

#### Scenario: 只放了规格的设计根

- **WHEN** `designs/<根>/` 下只有 `lrs.<顶层>.md`，没有 `params.yaml` 与 `rtl/`
- **THEN** 任何按顶层名解析的流程命令 SHALL 照常工作，不因这个根报错

#### Scenario: 有电路却没有声明

- **WHEN** 一个设计根有 `rtl/`，没有 `params.yaml`
- **THEN** 解析 MUST 报错并指出缺少 `params.yaml`

### Requirement: 参数片段的位置与 include 目录

被 `` `include `` 引用的参数片段 MUST 放在设计根的 `rtl/inc/` 下，扩展名 `.vh`。流程 MUST 把该顶层的
设计根与它 `deps` 传递闭包里各 cbb 根的 `rtl/inc/`（存在的）作为 include 目录交给综合、RTL 仿真、
等价证明与秒级护栏的 elaborate 和 lint；片段 MUST NOT 作为独立的源文件交给工具。

#### Scenario: 模块引用了自己设计根的参数片段

- **WHEN** `designs/<根>/rtl/x.v` 写了 `` `include "x_param.vh" ``，片段在 `designs/<根>/rtl/inc/`
- **THEN** 综合、RTL 仿真、fast_check 的 elaborate 与 lint 都 SHALL 找到它，不需要任何声明

### Requirement: 删除设计根时历史记录保留，读法必须写明

删除一个有实验记录的设计根时，它的记录文件 `results/<设计根>/experiments.jsonl` MUST NOT 被删除或改写（红线 2）；`docs/data-credibility.md` MUST 新增一条【读法】，写明删了哪些顶层、删除提交、读当时的 RTL 要按记录里的 `git_commit` 去取，以及报告与打分工具对这些顶层的行为。

#### Scenario: 读一条已删顶层的记录

- **WHEN** 有人读到一条 `design` 是已删顶层的记录
- **THEN** `docs/data-credibility.md` SHALL 有一条【读法】告诉他设计根已删、去哪个提交找当时的 RTL

#### Scenario: 删除设计根的提交

- **WHEN** 一个提交删除了 `designs/<根>/` 或 `cbb/<根>/`
- **THEN** `results/<根>/experiments.jsonl` SHALL 原样留在仓里

### Requirement: 出 PPA 记录之前验证方案必须声明已验证

每份 `verify.<顶层>.md` MUST 恰好有一行验证状态，整行是下面两种写法之一：

- `验证状态：已验证（<TB 路径或证据>）`
- `验证状态：未验证`

`scripts/run_experiment.py` 在跑任何工具之前 MUST 检查被测顶层的这一行。以下情况 MUST 拒绝，不写记录，并说明原因与状态行的格式：

- `verify.<顶层>.md` 不存在；
- 没有状态行，或状态行不止一行；
- 写的是 `未验证`；
- 写的是 `已验证`，但后面没有依据。

`scripts/fast_check.sh` MUST NOT 因验证状态为 `未验证` 而失败：文档与 RTL 可以先后写，出数之前写明验证即可。

理由：出自没有验证方案的电路的记录，是「跑通了但数字不可信」的一种（内部#68）。用显式状态行而不按正文判断，是因为各文档表达「未验证」的写法不统一，按正文猜会漏判。

#### Scenario: 未验证的顶层跑实验

- **WHEN** 某顶层的 `verify.<顶层>.md` 写着 `验证状态：未验证`，对它运行 `make exp`
- **THEN** `run_experiment` MUST 在跑任何工具之前失败，`results/<设计根>/experiments.jsonl` SHALL 不增加任何行

#### Scenario: 已验证但没写依据

- **WHEN** 状态行是 `验证状态：已验证`，后面没有任何文字
- **THEN** `run_experiment` MUST 失败，原因 MUST 说明缺依据

#### Scenario: 已验证并写了依据

- **WHEN** 状态行是 `验证状态：已验证（tb/test_X.py 全参数组合）`
- **THEN** 这一项检查 SHALL 通过

#### Scenario: 新建设计根后运行秒级检查

- **WHEN** 新建设计根，`verify.<顶层>.md` 照模板写 `验证状态：未验证`
- **THEN** `scripts/fast_check.sh` SHALL 不因此失败

### Requirement: 专用设计的 LRS 与 LLD 必须有必填节与需求追溯

`designs/` 下每个被测顶层的 LRS 与 LLD MUST 满足以下各条。

**LRS 的 9 个必填节**（`## ` 二级标题，可带编号，内容可以是「不适用」），模板按这个顺序排：
- 文档信息（也可以叫「修订记录」）、概述、配置与应用场景、术语、参数、接口；
- 功能描述、异常与 DFX、性能需求。

配置项、控制项与状态项的定义（取值、复位值、生效时机）写在「接口」里对应类型的端口表中。「配置与应用场景」每个场景单独成小节（配图示）；对外前提不按场景散写，统一归成对前级、对后级、对配置值、对软件、对参数组合五类，写在共用前提小节里。

LRS 只写给读者的最终规格：第 1 章之前只留修订记录；结论进展标记（【定】【暂定】【待定】【过渡】）、确认记录（「用户某日确认」）、开发进展 MUST NOT 写在 LRS，写在设计根的跟踪文档 `doc/track.<顶层>.md`。全仓规范 `docs/spec-writing.md` 的通用规则默认成立，LRS 不写也不引用；只对本设计成立的前提把内容直接写进 LRS。除 `doc/` 下的图之外，LRS 里的引用 MUST 只指向 LRS 自身（节、R 号、表），MUST NOT 引用全仓规范、设计根里的其他文档或提交号（用户 2026-10-04，内部#126）。结构图 MUST 用 draw.io 图，MUST NOT 用代码块里的字符画。LRS 里每处图片引用（`![…](…)`，代码块外）之后的第一个非空行 MUST 是以 `**图 ` 开头的图注（内部#137，用户 2026-10-04）。

**LLD 的 5 个必填节**（内部#203，用户 2026-10-05 定 Q1 选 A），模板按这个顺序排，按模块组织：
- 文档信息（也可以叫「修订记录」）、概述（也可以叫「设计概述」，含需求追溯表）、框图与模块划分；
- 之后每个子模块一节，各按功能概述（含模块框图）、接口说明（顶层接口 LRS 已有可不写）、功能描述（含用了哪些 CBB，必要处画图）、子模块（有则递归展开，无则写 NA）；顶层主要是连线，用图，不另写顶层功能；
- DFX（实现）、设计断言（RTL 里的断言，每条标对应的 R）。

「框图与模块划分」一节里各表行的第一格中，用反引号写的大写标识符（如 `` `FOO_MUX` ``）是模块名；每个模块名 MUST 出现在 LLD 某个 `##` 或更深一级的标题里。没有这样名字的行（分组行、说明行）不查。小模块另列一张表：表头第一格是「小模块」的表里的模块不单开节，在表里一行写清功能、所在模块与用到的 CBB，不受上一条约束（内部#239，用户 2026-10-06）。死锁与冒险分析整个设计只写一处：标题含「死锁」的节 MUST 至多一个。参数化实现、综合与 PPA 预期、时序原则与时序参数取舍不写在 LLD，写在设计根的 `param.<顶层>.md`、`ppa.<顶层>.md`、`timing.<顶层>.md`。验证要点（覆盖关注点等）写在 `verify.<顶层>.md`。过程信息（确认记录、实测现状、开发进展）与 LRS 一样不写在 LLD，写在跟踪文档。

只检查 `## ` 级的必填节；子模块各节的展开格式由模板给出，不做机械检查。

**需求编号**：
- 需求在 LRS 里以加粗的 `**R.<三位数字>**` 定义（如 `**R.001**`），可以写在任何一节；不加粗的 `R.001` 是引用。
- 每个编号 MUST 只定义一次。
- 已删除的需求 MUST 整条从 LRS 删掉，编号与原因记在跟踪文档；编号只增不复用。
- LRS MUST 至少定义一条需求。

**需求追溯**：
- LLD 中第一张表头含「需求」列的表是追溯表，该列每格写一个或多个 R 编号。
- 追溯表 MUST 覆盖 LRS 定义的全部 R。
- 追溯表 MUST NOT 引用 LRS 没有定义的 R。
- LLD 全文（`## ` 标题以「文档信息」或「修订记录」开头的那一节除外）出现的每个 `R.<三位数字>`，无论加不加粗，MUST 在 LRS 有定义（内部#140，用户 2026-10-04）。

**参数表**：
- LRS「参数」一节里第一列为「参数」的表合起来是参数表，每行第一格是参数名（MAY 用反引号）。
- `params.yaml` 里该顶层 `params:` 声明的每个参数 MUST 出现在参数表里。参数表 MAY 多列 RTL 里的其他参数。

**断言编号**：
- LLD「设计断言」一节里各表数据行的第一格定义断言编号 `A<数字>`（第一列叫「断言」或「编号」都可以），每个编号 MUST 只定义一次。
- LRS 与 LLD 正文引用的 `A<数字>` MUST 都有定义。

**版本表**：LRS 与 LLD 里第一列为「版本」的表，各行的 `v<主>.<次>` MUST 按数值升序。

「配置与应用场景」逐个场景写用途、对应的配置与外部可见的差别（配图示），另有一个共用前提小节按五类写对外前提与参数合法组合；问题清单在主线 issue 跟踪，LRS 不设集中的开放问题节（用户 2026-10-03）；各条的结论进展记在跟踪文档（用户 2026-10-04）。

理由：需求与实现分开之后，「哪条需求没人实现」「LLD 说实现了一条不存在的需求」都不会让任何东西失败，除非编号可被机械地对齐（用户 2026-10-03 定编号与检查口径）。

#### Scenario: 缺一节

- **WHEN** 某个 LRS 没有「性能需求」这一节
- **THEN** `scripts/fast_check.sh` MUST 失败并点名缺的节

#### Scenario: 重号

- **WHEN** LRS 里 `**R.003**` 定义了两次
- **THEN** 护栏 MUST 失败并点名 `R.003`

#### Scenario: 有需求没有追溯

- **WHEN** LRS 定义了 `R.005`，LLD 的追溯表里没有它
- **THEN** 护栏 MUST 失败并点名 `R.005`

#### Scenario: 追溯表引用不存在的需求

- **WHEN** LLD 的追溯表写了 `R.009`，LRS 没有定义它
- **THEN** 护栏 MUST 失败并点名 `R.009`

#### Scenario: LLD 缺设计断言

- **WHEN** 某个 LLD 没有「设计断言」这一节
- **THEN** 护栏 MUST 失败并点名「设计断言」

#### Scenario: 模块划分表里的模块没有自己的节

- **WHEN** 模块划分表列了 `FOO_MUX`，LLD 没有一个标题含 `FOO_MUX`
- **THEN** 护栏 MUST 失败并点名 `FOO_MUX`

#### Scenario: 小模块写在小模块表里

- **WHEN** 「框图与模块划分」里表头第一格为「小模块」的表列了 `FOO_META_SRAM`，LLD 没有一个标题含 `FOO_META_SRAM`
- **THEN** 护栏 SHALL 不因此失败

#### Scenario: 死锁分析写了两处

- **WHEN** LLD 有两个标题含「死锁」的节
- **THEN** 护栏 MUST 失败并点名这两个标题

#### Scenario: LLD 缺功能设计

- **WHEN** 某个 LLD 没有「功能设计」「参数化实现」「综合与 PPA 预期」「子模块详述」这四节
- **THEN** 护栏 SHALL 不因此失败

#### Scenario: 缺配置与应用场景

- **WHEN** 某个 LRS 没有「配置与应用场景」这一节
- **THEN** 护栏 MUST 失败并点名「配置与应用场景」

#### Scenario: params.yaml 的参数没列进参数表

- **WHEN** `params.yaml` 声明了 `DEP_N`，LRS 的参数表里没有它
- **THEN** 护栏 MUST 失败并点名 `DEP_N`

#### Scenario: 引用了不存在的断言

- **WHEN** LLD 正文写「见 A12」，设计断言表里没有 `A12`
- **THEN** 护栏 MUST 失败并点名 `A12`

#### Scenario: 版本表顺序错

- **WHEN** 版本表里 `v1.14` 排在 `v1.13` 前面
- **THEN** 护栏 MUST 失败并点名这两个版本

#### Scenario: 旧节名与新节名

- **WHEN** 一个 LRS 的第 3 节标题是「术语与约定」，另一个是「术语」
- **THEN** 两个 SHALL 都算有「术语」这一必填节

#### Scenario: 第 0 节叫修订记录

- **WHEN** LRS 的第 0 节标题是「修订记录」，没有「文档信息」
- **THEN** 护栏 SHALL 算它有这一必填节

#### Scenario: 字符画结构图

- **WHEN** LRS 的一个代码块里用 `┌─┐` `──▶` 画了结构图
- **THEN** 护栏 MUST 失败并点名文件与行号，提示改用 draw.io 图

#### Scenario: 图没有图注

- **WHEN** LRS 里 `![框图](doc/top.svg)` 的下一个非空行是正文而不是 `**图 1-1** …`
- **THEN** 护栏 MUST 失败并点名文件与行号

#### Scenario: LLD 正文引用已删除的需求

- **WHEN** LLD 的某个子模块节写「见 R.015」，LRS 没有定义 `R.015`（已删除，记在跟踪文档）
- **THEN** 护栏 MUST 失败并点名 `R.015` 与 LLD 的行号；同一编号只写在 LLD 修订记录里时 SHALL 不报

### Requirement: 设计根的参数、PPA 与时序文档

`designs/` 下每个被测顶层 MUST 在设计根与 `lrs.<顶层>.md` 同级有 `param.<顶层>.md`、`ppa.<顶层>.md`、`timing.<顶层>.md` 三份文档（内部#203，用户 2026-10-05 定 Q2 选 A），内容不适用时写一句「不适用」与原因。
- `param` 写参数如何改变结构、派生量、参数合法性检查与参数裁剪（如某参数为 0 时整块不综合）。
- `ppa` 写保层级的 building block、关键路径与面积的预期。
- `timing` 写时序原则、流水切点与时序参数的取舍（内部#199）。

模板在 `flow/templates/design-root/`。fast_check MUST 检查三份文档存在、缺一份点名；LLD 还是旧结构（带「子模块详述」这一 `##` 节）时只提示，按新结构重写后缺了 MUST 失败。

#### Scenario: 缺时序文档

- **WHEN** 设计根有 `lrs.TOP.md` 与新结构的 `lld.TOP.md`，没有 `timing.TOP.md`
- **THEN** 护栏 MUST 失败并点名 `timing.TOP.md`

### Requirement: verify 计划必须有全仓通用验证项表

每个 `verify.<顶层>.md`（`designs/` 与 `cbb/` 都算）MUST 有一张表头第一格为「通用规范」的表，含 6 行：握手保持、valid 不依赖 ready、汇聚口屏蔽、活性、写数据不等命令、功能不依赖打拍配置；每行的「覆盖」格 MUST 非空，没有握手接口的构件写「不适用」加原因（用户 2026-10-13 定，内部#286；模板 `flow/templates/design-root/verify.md`）。秒级护栏 MUST 检查，违规按文件可在 `flow/check_waivers.yaml` 登记豁免。

#### Scenario: 缺表

- **WHEN** 某个 `verify.<顶层>.md` 没有「通用规范」表
- **THEN** fast_check 的 doc 段 SHALL 失败，违规行以该文件路径开头（不缩进），可被豁免放行

#### Scenario: 缺行或覆盖格为空

- **WHEN** 表里少了「活性」一行，或「握手保持」一行的覆盖格是空的
- **THEN** fast_check SHALL 失败并点名缺的行

### Requirement: 握手规则的例外必须标出处

LRS 与 LLD 正文里「握手前可以改 / 撤回」一类句子 MUST 在同一行标「例外」并注出处（issue 号或文档名），否则秒级护栏 MUST 失败（用户 2026-10-13 定由提示转致命，内部#286；原为 内部#284 的提示 H1）。违规行以 `路径:行号:` 开头、不缩进，可按文件登记豁免。

#### Scenario: 没标出处

- **WHEN** LRS 某行写「对端在握手前可以改 flg」而同一行没有「例外」与出处
- **THEN** fast_check 的 doc 段 SHALL 失败，并指出文件与行号

#### Scenario: 标了出处

- **WHEN** 同一行写「对端握手前会改 flg（例外，出处：内部#264）」
- **THEN** 本条 SHALL NOT 报错

### Requirement: 闭源内容只在闭源设计根下

闭源设计（含闭源 CBB）的一切内容——RTL、测试台、设计文档、评审记录、设计专属的豁免与名单、设计专属的测试——MUST 只放在该闭源设计根下。开源与闭源的设计根同放 `designs/`（专用设计）与 `cbb/`（构件）；一个设计根是开源还是闭源 MUST 只由开源白名单（`flow/export/manifest.yaml`）逐设计根声明，默认闭源，MUST NOT 靠目录区分（用户 2026-10-15）。设计根之外的文件（`flow/`、`scripts/`、`tests/`、`docs/`、`knowledge/`、`openspec/specs/` 等）MUST NOT 含闭源设计的名字或内容，需要举例时用开源设计。

例外是历史，留私有、不改写、不进开源白名单：`results/*/experiments.jsonl` 的已有记录，与 `openspec/changes/`（含 `archive/`）。

切换之后新产生的、专属某个闭源设计的 change 与评审 MUST 放进该设计根，不在例外内。

#### Scenario: 在流程文档里举例

- **WHEN** `docs/` 或 `openspec/specs/` 需要一个设计当例子
- **THEN** MUST 用开源设计（如 `CBB_LZD`、`ADDER32`）；讲闭源设计的真实历史时写「某闭源 IP」并留 issue 号

#### Scenario: 读一条切换前的历史

- **WHEN** 归档 change 或旧记录引用一个后来搬过的路径（2026-10 闭源评审记录收进设计根；闭源设计根曾短暂在 `ip_designs/`、`ip_cbb/` 下，后搬回）
- **THEN** 按归档里 2026-10-15 闭源切换与搬回的两份 change 的脚本里的映射表读，历史文本本身不改
- **AND** 映射表 MUST NOT 写进开源内容（它列着闭源路径）

#### Scenario: 新增一个闭源设计

- **WHEN** 新建一个闭源设计根
- **THEN** 它建在 `designs/` 或 `cbb/` 下，与开源设计根同列
- **AND** 开源白名单（`flow/export/manifest.yaml`）MUST NOT 包含它
