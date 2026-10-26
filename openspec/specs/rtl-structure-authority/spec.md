# rtl-structure-authority Specification

## Purpose
规定 RTL 里的结构**谁说了算** —— 哪些结构该由设计者写进 RTL，哪些该留给综合器，
以及降低组合深度的手段允许落在哪一层。

这个能力管的是**代码为什么长这样**，不是它算得对不对（那是
`formal-equivalence` 与 `experiment-trust` 的事）。它存在的理由是：手写归约结构
与调综合配方这两件事，**做了之后都能拿出「深度降了」的数字**，而两者的寿命完全
不同 —— 前者若真是架构决策，换任何工具都成立；后者是某个工具某个版本上的行为，
换工具可能反号，却会留下一个看上去同样漂亮的实验记录。

判据只有一条，两条 requirement 都从它推出来：**换一个综合器，这段代码（这次改动）
的理由是否仍然成立。** 成立的才属于 RTL；不成立的属于配方，而配方一动
`flow` 指纹就变，既有记录全部不可横向比较（P-8）—— 那个代价远大于它买到的级数。

与 `formal-equivalence` 的分工：那条管「改完之后还等不等价」，本条管「这个改法
该不该在 RTL 里做」。一次结构重排要同时过两关：理由站得住（本条），
且对一份**未同步修改的**参考实现逐位等价（那条）。

## Requirements

### Requirement: 手写归约结构只在它是架构决策时允许

RTL 中手写的归约结构（CSA / 3:2 压缩树、进位选择、平衡加法树、显式进位链）
MUST 只在该结构**本身构成架构决策**时出现；纯粹为了让某一个综合器产出更好的
网表而手写的结构 MUST NOT 进入 RTL。

判据只有一条：**换一个综合器，这段代码的理由是否仍然成立。**

- 构成架构决策的例子：需要在冗余的 `(sum, carry)` 对处切开流水级，
  就必须显式停在两个操作数上 —— 不写出这棵树就没有可以打拍的中间量，
  任何工具下都一样。
- 不构成架构决策的例子：多操作数求和本来可以写成 `+` 链，改写成手写树只为
  少几级。这种收益是某个工具在某个版本上的行为，换工具可能反号。

本仓库两个方向的实例都测过，都要留在 RTL 头注释里：六项移位相加上手写 CSA 树
是 23 级 / 31.565700 µm²，输给 `+` 链的 20 级 / 30.340980 µm²；而
`q % 15` 的 nibble 和手写 3:2 树是 12 级、`+` 链是 14 级，**但两者所在流水级的
深度都是 15 级** —— 那 2 级一级也换不到。

#### Scenario: 手写结构是流水切分点

- **WHEN** RTL 中出现手写的归约结构
- **AND** 该结构产出的中间量被寄存器采样，或被跨模块边界送出
- **THEN** 它 SHALL 被允许
- **AND** 该处头注释 MUST 写明它是架构决策而非调优，并说明不写会导致什么

#### Scenario: 手写结构只为换取级数

- **WHEN** RTL 中出现手写的归约结构
- **AND** 它产出的中间量没有跨越任何寄存器或模块边界
- **THEN** 它 MUST 被替换回工具可自行归约的写法（如 `+` 链）
- **AND** 替换前后的级数与面积 MUST 实测记录，而不是估计

### Requirement: 深度优化不得依赖综合配方

以降低组合深度为目的的改动 MUST 落在 RTL 的结构或代数形式上，
MUST NOT 通过修改综合/映射配方（ABC 选项、延迟目标、脚本顺序）达成。

两条理由。其一，配方是工具专有的，换工具即失效。其二，配方一变 `flow` 指纹
就变，`results/*/experiments.jsonl` 里已有的记录全部不可横向比较（P-8），
一次配方调整的代价远大于它买到的级数。

本仓库实测：在 `-constr` 路径下 `abc -D 50` / `-D 20` / `-D 5` 的输出**逐字节
相同**（21 级 / 100.193760 µm²），延迟目标根本没被读取 —— 这条路不但不该走，
而且走不通。

#### Scenario: 用综合配方换深度

- **WHEN** 一条改动通过调整综合或映射配方来降低组合深度
- **THEN** 它 MUST NOT 被采纳为深度优化
- **AND** 若配方确有独立理由必须改，该改动 MUST 单独成条，
  并在 `docs/data-credibility.md` 中声明受影响的记录代次

#### Scenario: 用结构重排换深度

- **WHEN** 一条改动通过把逻辑挪过寄存器边界、或用代数恒等式改写表达式来降低深度
- **THEN** 它 SHALL 被采纳
- **AND** 等价性 MUST 由一份**未同步修改的**参考实现逐位证明
  （见 `formal-equivalence`），而不是只靠改动前后自比

### Requirement: 准静态配置不得在流水级之间穿线

准静态配置（几何、基址、模式码一类**不随传输变化**的输入）的解码与钳位
MUST 发生在流水线之外 —— 顶层或调用方。流水级模块 MUST 只接收**已经解码好**的值，
并且 MUST NOT 把配置再输出给下一级。

判据是一句话：**一个模块的输出口里，不应该出现它的调用方本来就有的东西。**

理由有三条，都不是风格问题：

1. **端口表会说谎。** 转发一旦发生，下游模块的端口就长得像「从上一级来的载荷」，
   而它实际上是准静态配置。某个设计里一个子模块的头注释因此被迫写成
   「wired straight from the top-level ports (i_cfg_a / i_cfg_b **through step1's clamp**)」——
   要用一句注释解释端口不是它看起来的样子，那个端口就已经错了。
2. **它反过来约束流水切分。** 配置被 step1 转发之后，「step1 与 step3 之间能不能
   插寄存器」就多了一条与载荷无关的限制：打了拍的配置和没打拍的配置会在 step3 撞车。
   本仓的头注释里已经写着「base 和两个钳位后的配置必须**不经流水线**到达 step3，
   打拍或改配置前不排空会产生看起来合法的错地址」—— 那是转发带来的坑，不是设计固有的。
3. **解码规则会被复制。** 钳位寄生在某一级里，另一级要用就只能转发或重写。
   两条路都在制造「改了码域却漏掉一处」的机会。

本条**不**禁止流水级模块消费配置。step1 用钳位后的 `cfg_w` / `cfg_c` 算
`hole_sh` / `col_msk`，step3 用同一对值算移位量 —— 两者都是**消费**，是对的。
错的只有「step1 把它算出来的钳位结果输出给 step3」这一件事。

与「准静态输入不进流水线」（`experiment-trust`）的分工：那条管的是
**配置要不要打拍**（不打），本条管的是**配置从哪条路到达它的消费者**
（从调用方直达，不借道别的流水级）。两条都成立时，配置才既不占触发器、
也不牵制切分点。

#### Scenario: 一个流水级把配置转发给另一个流水级

- **WHEN** 某个流水级模块的输出端口里出现准静态配置（原样转发，或只做了解码/钳位后转发）
- **AND** 该输出的消费者是另一个流水级模块
- **THEN** 该输出端口 MUST 被删除
- **AND** 解码/钳位 MUST 上移到调用方，由调用方把结果**分别**送给两个消费者
- **AND** 两个消费者的端口 MUST 声明它们收的是**已解码**的值，而不是原始配置码

#### Scenario: 一个流水级只消费配置、不转发

- **WHEN** 某个流水级模块接收准静态配置并只在自己内部使用
- **AND** 它的输出端口里没有该配置（无论原样还是解码后）
- **THEN** 它 SHALL 被允许
- **AND** 该模块的端口 MUST NOT 需要一句「其实这不是从上一级来的」的注释来解释自己

### Requirement: RTL 的书写约定，以及「纯语法改写」的判据

`designs/**/*.v` MUST 遵守下列书写约定：

1. MUST NOT 出现 `` `default_nettype ``（任何取值）。
2. `wire` / `reg` 的**定义**里 MUST NOT 带赋值；定义与 `assign` MUST 分开写。
3. MUST NOT 使用 `localparam integer`；只用 `localparam`。
4. MUST NOT 在 `generate` 块内定义 `localparam`。依赖 genvar 而无法上提的，
   MUST 内联到每个使用点。

这四条是用户 2026-09-17 给的约定，本条款只负责把它们写成可判定的形式，
并规定**怎么证明改写没有改变电路**。

**判据是网表相同，不是「看起来没改逻辑」。** 这四条按定义是纯语法改写：
改完之后同一组参数综合出的网表 MUST 与改写前相同。这比等价证明更强 ——
等价只保证功能一样，网表相同则连结构都没动。

「相同」是**三项齐同**：`cell_count`、`area_um2`、以及**去掉 `src` 位置属性之后**
的网表字节。⚠️ 不能取原始字节：yosys 把 `(* src = "文件:行.列-行.列" *)` 写进
网表（实测某闭源 IP的一个子设计一份网表里 776 处），那是**源码位置不是电路**。
删掉文件开头一行指令会让后面每个行号位移，于是原始字节必然不同，而电路一个门
都没变。判据取「电路相同」而不是「文件相同」；三项一起取，是因为只比去 src 的
字节会漏掉 liberty 侧的面积口径变化，只比 cells/area 又漏掉同数量不同连接。

若某个设计的三项不齐同，那就**不是**纯语法改写，MUST 查清楚差异的来源，
并按跨 RTL 分界的口径在 `docs/data-credibility.md` 记一条
（与 D-14 / D-15 / D-17 同形）。

⚠️ **冻结的黄金参照不适用本条款。** `flow/equiv/frozen/` 下的副本按定义是
参数化之前那份代码的逐字节复制品，改它等于把判据改成与被测对象一致。
它由 `designs/<design>/verify.md` 的 sha256 表守着。

#### Scenario: 按约定改写之后网表逐字节相同

- **WHEN** 一次改动只做本条款列出的四类改写
- **AND** 改写前后同一组参数各综合一次
- **THEN** 两次的 `cell_count`、`area_um2`、去 `src` 属性后的网表字节 SHALL 三项齐同
- **AND** 该事实 MUST 作为这次改写的主要验收证据
- **AND** 比较 MUST NOT 取网表的原始字节 —— `src` 属性记的是源码行号，改写必然移动它

#### Scenario: 改写之后网表不同

- **WHEN** 改写前后那三项不齐同
- **THEN** 这次改动 MUST NOT 被当作纯语法改写
- **AND** 差异的来源 MUST 查清楚
- **AND** 受影响的记录 MUST 在 `docs/data-credibility.md` 里记一条 RTL 分界

#### Scenario: genvar 依赖的 localparam

- **WHEN** `generate` 块内的 `localparam` 依赖 genvar，无法上提到模块级
- **THEN** 它 MUST 被内联到每一个使用点
- **AND** MUST NOT 以「上提不了」为由保留

#### Scenario: 冻结的黄金参照

- **WHEN** `flow/equiv/frozen/` 下的文件违反上列任何一条
- **THEN** 它 SHALL 保持原样
- **AND** 本条款 MUST NOT 被用作修改它的理由

### Requirement: 模块名必须全大写

`designs/`、`cbb/` 下 `**/*.v` 里每一个 `module` 声明的名字 MUST 全部由大写字母、
数字与下划线组成（`[A-Z][A-Z0-9_]*`）。例化点 MUST 同步。

**唯一的例外是设计根里的本地 CBB 副本**（用户 2026-10-09 定，内部#246、内部#258）：把共享 CBB 拷进某个
设计根、加后缀隔离的副本，文件名与模块名一律小写（`<设计根>/rtl/cbb_lzd_foo.v` 声明
`module cbb_lzd_foo`，`_foo` 是隔离后缀）。哪些文件是本地副本由名单逐行列出（仓库根相对路径）：全仓的 `flow/lint/local_cbb.txt`，加上各设计根自带的 `<设计根>/local_cbb.txt`（kaiwu 拆分，内部#305：名单随设计根进闭源树），两处取并集；
不按目录或名字模式推断 —— 设计根的顶层文件名也可能形如 `cbb_*_foo`，它不是副本。
名单里的路径 MUST 存在且在某个设计根的 `rtl/` 下；它声明的模块名 MUST 等于文件名去掉 `.v`。

这是用户 2026-09-17 给的第五条书写约定（本仓
内部#46 的 2.1）。目的是让读代码的人
**一眼分清模块名与信号名** —— 两者在例化语句里挨着出现，全小写时要靠位置去分。

它与前四条书写约定**性质不同，不得按「纯语法改写」处理**：前四条不改变任何标识符，
本条改变**顶层模块的名字**，而顶层模块名就是 `results/<设计根>/experiments.jsonl` 的 `design`
字段取值（见 `experiment-record` 的「记录必须区分被测顶层与它所在的设计根」）。
所以改顶层名 MUST 被当作一次**记录序列的分界**处理，判据见下面的 Scenario。

设计根目录名 MUST NOT 随之改变。`repo-layout` 自 2026-09-21 起已允许根名与顶层名
不同，本条款正是它的第一个真实用例：`designs/adder32/` 这个根挂顶层 `ADDER32`。

#### Scenario: 一份 RTL 里出现小写模块名

- **WHEN** `designs/**/*.v` 里有一个 `module` 声明的名字含小写字母
- **THEN** 检查 SHALL 失败，并指出是哪个文件的哪个模块
- **AND** 报错 MUST 给出应当改成的名字

#### Scenario: 本地 CBB 副本用小写名

- **WHEN** `flow/lint/local_cbb.txt` 列了 `designs/foo/rtl/cbb_lzd_foo.v`
- **AND** 该文件声明 `module cbb_lzd_foo`
- **THEN** 检查 SHALL 通过

#### Scenario: 本地 CBB 副本的模块名与文件名不一致

- **WHEN** 名单里的 `cbb_lzd_foo.v` 声明的模块名不是 `cbb_lzd_foo`
- **THEN** 检查 SHALL 失败，并给出应当的模块名

#### Scenario: 不在名单里的小写模块

- **WHEN** 一份不在名单里的 RTL 声明了含小写字母的模块名，即使名字形如 `cbb_*_foo`
- **THEN** 检查 SHALL 按全大写的规则失败

#### Scenario: 名单里的路径失效

- **WHEN** `flow/lint/local_cbb.txt` 列的某个路径不存在，或不在设计根的 `rtl/` 下
- **THEN** 检查 SHALL 失败，并指出这一行

#### Scenario: 改名波及被测顶层

- **WHEN** 一次改名改到了某个被测顶层的模块名
- **THEN** 该顶层在 `results/<设计根>/experiments.jsonl` 里的历史记录 MUST NOT 被回填改写
- **AND** 新旧两个名字 MUST NOT 被任何工具自动合并成一条序列
- **AND** 大小写映射与分界提交 MUST 记在 `docs/data-credibility.md`

#### Scenario: 改名不改变电路

- **WHEN** 一次改名只改模块名与例化点
- **AND** 改名前后同一组参数各综合一次
- **THEN** `cell_count` 与 `area_um2` SHALL 相同
- **AND** 网表字节 MUST NOT 被要求相同 —— 模块名本身写在网表里，它必然不同

#### Scenario: 设计根自带的名单

- **WHEN** `<设计根>/local_cbb.txt` 列了该根 `rtl/` 下的 `cbb_x_y.v`，且该文件声明 `module cbb_x_y`
- **AND** `flow/lint/local_cbb.txt` 不含这一行
- **THEN** 检查 SHALL 通过

#### Scenario: 设计根名单越界

- **WHEN** `<设计根>/local_cbb.txt` 列了另一个设计根下的路径
- **THEN** 检查 SHALL 失败，并指出这一行

### Requirement: 可综合 RTL 不得携带综合指令属性

`designs/**/*.v` 与 `cbb/**/*.v` MUST NOT 携带面向综合工具的指令属性 ——
`(* keep_hierarchy *)`、`(* dont_touch *)`、`(* keep *)` 及同类。
保住层级、禁止优化这类**意图**由流程按设计的声明施加，不写在 RTL 里。

这是用户 2026-09-17 给的第六条书写约定（本仓
内部#46 的 2.2），
与前五条同源：RTL 描述电路，不描述某个工具该怎么处理它。

**它与前五条的性质不同，不得直接删除。** 前五条是纯语法改写，删掉即可；
这一条删掉会**改变测量口径**：`docs/pitfalls.md` 的 P-3 记着 2026-09-08 的实测 ——
没有 `keep_hierarchy` 时 ABC 的 `&dch` 会把 ripple / CLA / carry-select 三种手写
结构收敛成同一个映射结果，架构对比整条失效。（保层级本身 2026-10-05 起不再强制，内部#216；声明了就照施加。）
所以本条款要求的是**搬家**：RTL 里删除，同时由流程施加等价的属性，
且改动前后的综合结果 MUST 逐字段相同。

**粒度是实测出来的，MUST 原样保留。** `designs/adder32/rtl/prefix_node.v` 记着
2026-09-08 的实测：只标「前缀网络」那一层时，ABC 把 64 位 Sklansky 那棵 6 层树
重构掉了；要保住树的拓扑必须标在**算子**（`PREFIX_NODE`）上。
搬家 MUST NOT 借机调整粒度 —— 搬完之后被保住的模块集合与搬之前**逐个相同**。

⚠️ **冻结的黄金参照不适用本条款**，理由与前五条相同（`flow/equiv/frozen/`
是参数化之前那份代码的逐字节复制品）。等价证明本身不受影响：
`flow/equiv/run_equiv.py` 的脚本在 flatten 之前先 `setattr -mod -unset
keep_hierarchy`，两侧都被抹平。

#### Scenario: RTL 里出现综合指令属性

- **WHEN** `designs/**/*.v` 或 `cbb/**/*.v` 里出现 `keep_hierarchy` 之类的属性
- **THEN** 秒级护栏 SHALL 失败，并指出是哪个文件的哪一行
- **AND** 报错 MUST 指向该意图应当声明的地方（该顶层的 `params.yaml`）

#### Scenario: 属性从 RTL 搬进流程

- **WHEN** 一次改动只把 `keep_hierarchy` 从 RTL 移到流程的声明里
- **AND** 改动前后同一组参数各综合一次
- **THEN** 被保住层级的模块集合 SHALL 逐个相同
- **AND** 两次的 `cell_count`、`area_um2` SHALL 相同，去 `src` 属性后的网表 SHALL 只在
  **模块头属性行的先后次序**上不同 —— 属性挂上的时机变了，`hdlname` / `dynports` /
  `keep_hierarchy` 的排列跟着变，而单元与连接一个都没动（2026-09-21 实测）
- **AND** 若不齐同，这次改动 MUST NOT 被当作搬家 —— 差异来源 MUST 查清楚

#### Scenario: 新增一个需要保住层级的模块

- **WHEN** 新写一个 building block，而它的层级必须保住才能测出架构差异
- **THEN** 该模块 MUST 出现在它所属被测顶层的声明里
- **AND** MUST NOT 以在 RTL 里加属性的方式达到同一效果

### Requirement: RTL 文件的版面、头注释与注释语言

`designs/*/rtl/*.v`、`cbb/*/rtl/*.v` 与 `flow/templates/*.v` MUST 遵守下列版面约定
（用户 2026-09-29 定，出处见 `add-rtl-coding-style` 的 D1–D4）：

1. 缩进 4 空格，MUST NOT 出现 tab。
2. 文件 MUST 只含 ASCII 字符；注释一律英文。
3. 文件 MUST 以五字段横幅头开始，字段依次为 `File`（文件名）、`Module`（本文件的模块名）、
   `Purpose`（一句话）、`Spec`（仓内存在的规格文件路径，后面可以跟括号里的章节号）、`Language`，上下各一行 `//====`：

   ```verilog
   //=============================================================================
   // File    : cbb_lzd.v
   // Module  : CBB_LZD
   // Purpose : Synchronous FIFO with vld/rdy handshake, depth FIFO_DEP_N
   // Spec    : cbb/cbb_lzd/spec.CBB_LZD.md
   // Language: Verilog-2001 (assertions are SVA, compiled only under CBB_ASSERT_ON)
   //=============================================================================
   ```

   头注释 MUST NOT 带作者、日期、修改记录或编号长节 —— 这些由 git 与 `design.*.md` 承担。
4. 注释只做逻辑分隔：正文按逻辑块用 `//---- <name>` 一行分段，段序为 function（有时）、
   localparam、信号声明、各逻辑段、参数检查、断言。例化 MUST NOT 单独成段，按数据流顺序就近放在用到它的
   逻辑段里；大模块分 PART 时段名写 `//---- <PART> PART: <name>`。设计理由 MUST 写进该设计根的
   `design.*.md`，不写进 RTL。

#### Scenario: 新文件里有中文注释

- **WHEN** 一个不在豁免清单里的 RTL 文件含非 ASCII 字符
- **THEN** 秒级护栏 SHALL 失败，并指出文件与行号

#### Scenario: 头注释的模块名与文件内容不符

- **WHEN** 头注释的 `Module` 与文件里 `module` 声明的名字不同，或 `File` 不是本文件名，或 `Spec` 指向的文件不存在
- **THEN** 秒级护栏 SHALL 失败，并指出是哪个字段

### Requirement: 一个文件一个模块，文件名取模块名的小写

上述范围内的每个 `.v` 文件 MUST 恰好声明一个 `module`，文件名 MUST 是该模块名的小写加 `.v`
（`CBB_LZD` 在 `cbb_lzd.v`）。

#### Scenario: 一个文件里写了两个模块

- **WHEN** 一个 RTL 文件声明了两个 `module`
- **THEN** 秒级护栏 SHALL 失败，并列出两个模块名

#### Scenario: 文件名与模块名不对应

- **WHEN** `cbb_lzd.v` 里声明的是 `CBB_LZD_CORE`
- **THEN** 秒级护栏 SHALL 失败，并给出应当的文件名

### Requirement: 寄存器、流水级与状态机的命名

RTL MUST 遵守下列命名（用户 2026-09-29 定，D6、D11；D7 于 2026-09-30 修订）：

1. 寄存器以 `_r` 结尾；流水级与打拍寄存器一律 `_1ff`、`_2ff`……，不分带不带逻辑。
2. 寄存器 D 端的组合逻辑信号以 `_pre` 结尾（`x_r <= x_pre`），只在把组合逻辑单独抽出时才起这个名；
   简单的 if/else 更新 MAY 直接写在 always 块里。
3. 状态机的当前状态叫 `st_r`、次态叫 `st_pre`，状态常量为带位宽的 `localparam [W-1:0] ST_<NAME>`。
4. 例化名写 `U_<当前模块名>_<功能>_<被例化模块名>`（`U_FOO_BUF_S_CMD_CBB_LZD`），MUST NOT 用序号。
   例外：同一设计根里例化 `flow/lint/local_cbb.txt` 列出的本地 CBB 副本时，例化名写
   `U_<共享 CBB 名>` 或 `U_<共享 CBB 名>_<功能>`（例化 `cbb_lzd_foo` 写 `U_CBB_LZD_ZERO_DET`）；
   共享 CBB 名是副本模块名去掉最后一段隔离后缀再转大写。例化名 MUST 全大写、MUST NOT 以隔离后缀
   结尾（用户 2026-10-09 定，内部#258）。
5. MUST NOT 再用 `r_`、`s<n>_`、`u_` 前缀。
6. 块名一律大写（D19）：generate 里的条件块写 `GEN_<NAME>`，generate 里的 for 块名以 `GEN_FOR` 开头；
   always 块 MUST 命名，块名以 `BLK_` 开头，always 内的 for 块名以 `BLK_FOR` 开头。同一作用域里有多个
   循环时后接 `_<NAME>` 区分。

#### Scenario: always 块没有块名

- **WHEN** 一个 always 块的 `begin` 后面没有块名，或块名不以 `BLK_` 开头
- **THEN** 秒级护栏 SHALL 失败，并指出文件与行号

#### Scenario: generate 里的 for 块名不对

- **WHEN** generate 里的 for 块名不以 `GEN_FOR` 开头，或 always 里的 for 块名不以 `BLK_FOR` 开头
- **THEN** 秒级护栏 SHALL 失败，并指出文件、行号与块名

#### Scenario: 时序块里的目标不带寄存器后缀

- **WHEN** 一个时序 always 块里 `<=` 的目标名既不以 `_r` 也不以 `_<n>ff` 结尾
- **THEN** 秒级护栏 SHALL 失败，并指出文件、行号与信号名

#### Scenario: D 端组合逻辑写在 always 块里

- **WHEN** 寄存器的更新是简单的 if/else，直接写在 always 块里，没有单独的 `_pre` 信号
- **THEN** 这 SHALL 是合约定的写法

### Requirement: 时序逻辑、组合逻辑与复位的写法

RTL MUST 遵守下列写法（用户 2026-09-29 定，D8–D12）：

1. 时序块写 `always@(posedge clk,negedge rst_n)`，复位条件写 `if(rst_n == 1'b0)`，复位值用复制写法
   `{W{1'b0}}`；每个分支都有 `begin` / `end`，`end else if` 写在同一行。端口显式写 `input wire` /
   `output wire`；端口列表与参数列表都写前导逗号（D18）。
2. 寄存器如无必要 MUST NOT 复位（D26）：只有复位后的值会被读到、决定行为的状态（valid、计数、状态、
   指针等）用异步低有效复位；数据寄存器、打拍寄存器、只在某个 valid 为 1 时才被读的状态不复位，
   单独写在只有 `posedge clk` 的 always 块里。
3. 组合逻辑用 `assign`；`always @(*)` 只用于 `case`（状态机次态、多路译码），块首先给全部输出赋默认值。
4. 每个 `case` MUST 带 `default`；MUST NOT 使用 `casex` 与 `casez` —— 优先译码写成 `assign` 的
   与或逻辑，或例化 `CBB_LZD`。
5. 状态机用二段式或三段式。
6. 多选一写成与或结构 `{W{sel_a}} & a | {W{sel_b}} & b`，续行按第 7 条写；位段位置先定义成
   localparam 再用 `+:` 取。
7. 对齐（D23）：相邻几行的 `=` / `<=` 对齐成一列；多行表达式的续行把运算符放在行首、对齐到表达式的起点，
   不对齐到 `=` 那一列；规则的逻辑（与或多选一、同形的加减或比较项）各行的运算符、括号与操作数按列对齐，
   首行按需补空格；不成规则的表达式不为对齐补空格；声明与端口列表按列对齐。
8. 行内空格（D24）：只在 `=` / `<=`、逻辑与算术运算符、比较运算符两边加空格（`if(rst_n == 1'b0)`）；
   `if(`、`always@(`、位宽、复制与拼接里不加空格，拼接的逗号后不加空格。
9. for 循环下标（D22）：generate 里用 `gi`、`gj`……，always 里用 `bi`、`bj`……。
10. CBB（`cbb/`）内部尽量不例化其它模块，结构在本模块内展开；例外在该 CBB 的 `design.*.md` 写明理由（D25）。
11. function（D27）：放在文件开头的 `//---- function` 段；函数名以 `f_` 开头、小写；只写 elaboration 期的
    常量函数，至少一个 `input`，输入与局部变量用 `integer`，每个分支带 `begin` / `end`。

#### Scenario: case 没有 default

- **WHEN** 一个 `case` … `endcase` 里没有 `default` 分支
- **THEN** 秒级护栏 SHALL 失败，并指出文件与 `case` 所在行

#### Scenario: 用了 casez

- **WHEN** RTL 代码（剥掉注释与字符串之后）里出现 `casex` 或 `casez`
- **THEN** 秒级护栏 SHALL 失败

#### Scenario: 数据寄存器带了复位

- **WHEN** 一个只存数据的寄存器写在带 `negedge rst_n` 的 always 块里
- **THEN** 这 SHALL 被 review 判为不合约定 —— 「数据」与「控制」的区分不能机械判定，不进秒级护栏

### Requirement: 断言写在文件末尾并与规格的断言表对号

RTL 里的断言 MUST 放在文件末尾的 `` `ifdef CBB_ASSERT_ON `` … `` `endif `` 里，全仓只用这一个宏
（D13）：

1. 并发断言写 `A<n>_<NAME>: assert property (@(posedge clk) disable iff(rst_n == 1'b0) ...) else $error("A<n>: ...");`，
   `A<n>` MUST 与该模块规格断言表的编号一致。
2. 环境假设用 `assume property`，标签 `M<n>_<NAME>`。
3. 没有时钟的纯组合模块用 `always @(*)` 里的立即断言 `if(...) $error("A<n>: ...");`。
4. 参数合法性检查（非法 `SCHEME`、位宽不合法等）MUST NOT 写成断言（D20）：写成 generate 条件块里
   elaboration 期的 `$error("<模块名>: <说明>")`，块名 `GEN_<参数名>_CHK`，只用常量字符串，整段放在断言段
   之前的 `` `ifdef CBB_PARAM_CHK_ON `` … `` `endif `` 里，全仓只用这一个宏；MUST NOT 用 `initial` + `$display`
   或例化不存在的模块。
5. 按参数选结构的 generate 条件链，每个分支 MUST 显式列出它覆盖的合法取值，不写兜底 `else`（D20）。

#### Scenario: 不定义 CBB_ASSERT_ON 时

- **WHEN** 综合或 fast_check 读 RTL，没有定义 `CBB_ASSERT_ON`
- **THEN** 断言段 SHALL 被预处理器整段跳过，综合出的网表与没有断言时相同

#### Scenario: 参数非法

- **WHEN** 定义了 `CBB_PARAM_CHK_ON`，一个模块以非法参数例化
- **THEN** iverilog、verilator、yosys 的 elaboration SHALL 报出该模块的 `$error` 提示并失败

#### Scenario: 不定义 CBB_PARAM_CHK_ON 时参数非法

- **WHEN** 没有定义 `CBB_PARAM_CHK_ON`，一个模块以非法 `SCHEME` 例化
- **THEN** 分派链一个分支都不生成，lint SHALL 报出没有驱动或没有使用的信号；这时不保证有专门的提示

### Requirement: 模块头、内部命名与例化版式

RTL MUST 遵守下列写法（用户 2026-09-30 审某闭源 IP的缓冲模块时定，D28–D35）：

1. 模块内部的信号与 localparam 名字不缩写；同一概念全文件只用一个词。端口命名里已约定的通用缩写
   （`vld`、`rdy`、`dat`、`addr`、`len`、`cnt`、`msk`、`ofs`、`gnt` 等）照用，不另造新缩写（D28）。
2. 尺寸一律按 bit；位宽（含 log2 类）叫 `_W`，MUST NOT 叫 `_LG`；按字节的量在名字里写明 `BYTE`。IP 设计根里
   个数与表项数叫 `_NUM`、FIFO 深度叫 `*_FIFO_DEPTH`；CBB 与 PPA 实验顶层按统一命名约定用 `_N`（D29）。
3. 多字段打包过 CBB 时先求和得 `<X>_PLD_W`，字段从高位起按端口顺序排；全部字段都用到时用一条拼接赋值
   拆包，只用部分字段时才定义 `<X>_PLD_<F>_BIT`；过 TPI 之后这一级的信号加 `tpi_` 前缀（D30）。
4. 一个 always 块里只写一个顶层 `if` 或一个 `case`（D31）；同一个循环范围的逻辑只写一个 generate for（D32）。
5. 例化的参数段与端口段左右括号各成一列；用不到的输出口悬空写 `.o_x ()`，MUST NOT 接没人用的线（D33）。
6. 多路与或选择写成一个 `assign`，每一路 `{ }` 内字段一行一个、前导逗号竖排（D34）。
7. 模块头的参数按用途分组、每组 `//---- <group>` 起头；默认值 MUST NOT 写定宽，按编码给出的模式参数除外；
   每个参数同行注释写合法取值。端口先 S 侧后 M 侧、按通道分组，配置、控制与状态放在最后（D35）。

#### Scenario: 一个 always 块里有两个并列的 if

- **WHEN** 一个 always 块里先后写了两个互不嵌套的 `if`
- **THEN** 这 SHALL 被 review 判为不合约定，拆成两个 always 块 —— 不进秒级护栏

#### Scenario: CBB 的输出用不到

- **WHEN** 例化 `CBB_LZD` 只用到 `o_dec`，没用到 `o_enc`
- **THEN** `o_enc` SHALL 写成 `.o_enc ()` 悬空，lint 的 `PINCONNECTEMPTY` 视为已知

### Requirement: 参数片段可以用 include 引入

参数列表 MUST 写前导逗号（`,parameter X = ...`），好让模块用 `` `include `` 把一组参数声明插进
参数列表、把一组参数透传插进例化。流程统一传 include 目录之前（内部#76），新文件 MUST NOT
实际使用参数片段（D14）。

#### Scenario: 流程还不支持 include 目录时用了参数片段

- **WHEN** 内部#76 未完成，一个新 RTL 文件 `` `include `` 了参数片段
- **THEN** 这个改动 MUST NOT 合入 —— 综合与 fast_check 都找不到片段文件

### Requirement: 书写风格对新文件强制，旧文件只能移出豁免清单

新文件 MUST 遵守本能力的书写风格约定。2026-09-29 之前已有的 47 个 RTL 文件列在
`flow/lint/style_legacy.txt`，清单 MUST 只减不增（D15）：

1. 清单里的文件不再存在，或已经完全合规时，秒级护栏 MUST 失败，要求把它移出清单。
2. 新文件 MUST NOT 加进清单。
3. 迁移由 内部#75 跟踪；迁移按本能力
   「纯语法改写」的判据证明电路没变。

#### Scenario: 旧文件迁移完成

- **WHEN** 清单里的一个文件改到完全合规
- **THEN** 秒级护栏 SHALL 失败，并提示把它从清单里删掉

#### Scenario: 清单里的文件被删掉或改名

- **WHEN** 清单列出的路径已不存在
- **THEN** 秒级护栏 SHALL 失败，并指出这一条

### Requirement: 模块接口与参数必须遵守统一命名约定

`designs/**/*.v` 与 `cbb/**/*.v` 里**每一个**模块（不只被测顶层）的参数与端口 MUST 遵守下列约定
（用户 2026-09-27 定）。`flow/equiv/frozen/` 下的冻结黄金参照不适用本条款。

**参数**（`parameter`、`localparam`，以及 `params.yaml` 里的参数键）：

1. MUST 全部由大写字母、数字与下划线组成，MUST NOT 是单个字母。
2. 表示位宽的参数 MUST 以 `_W` 结尾；主数据位宽 MUST 叫 `DAT_W`。名字 `WIDTH`，以及以 `W`
   结尾但不以 `_W` 结尾的名字，MUST NOT 出现。
3. 表示个数的参数 MUST 以 `_N` 结尾；取值只有 0 / 1 的开关 MUST 以 `_EN` 结尾。
4. 枚举结构的参数 MUST 叫 `SCHEME`（取值见「结构枚举参数必须取整数」）；流水级数 MUST 叫 `PIPE_STAGES`。

**端口**：

1. 除 `clk`、`rst_n` 与多时钟构件的 `<域>_clk` / `<域>_rst_n`（`<域>` 为小写字母数字，只限输入，如 `wr_clk`、`rd_rst_n`）外，输入 MUST 以 `i_` 开头、输出 MUST 以 `o_` 开头，其余部分为小写
   `[a-z][a-z0-9_]*`。MUST NOT 使用 `inout`。
2. valid/ready 握手：上游侧 MUST 是 `i_vld` / `o_rdy`，下游侧 MUST 是 `o_vld` / `i_rdy`；
   多个通道时写成 `i_<通道>_vld` 等。`vld` MUST 只用于握手语义。
3. 端口名按 `_` 切开后，MUST NOT 含有 `valid`、`ready`、`data`、`din`、`dout`、`count`
   这几个词；它们分别写作 `vld`、`rdy`、`dat`、`dat`、`dat`、`cnt`。主数据口 SHOULD 是
   `i_dat` / `o_dat`；多操作数的算术单元可以用操作数名（`i_a` / `i_b`）。

机械检查（`guardrail-scope` 的「秒级护栏必须机械检查 RTL 命名约定」）覆盖参数的第 1、2 条与端口的
全部条款；参数的第 3、4 条是语义约定（名字里看不出一个参数是不是个数），由评审守，检查 MUST NOT
为它们猜测。

改参数名会改变 `results/<设计根>/experiments.jsonl` 里 `params` 段的**键**，所以与「模块名必须全大写」
同形：MUST 被当作一次**记录序列的分界**处理，老记录不回填，映射表写进
`docs/data-credibility.md`（读法见 `experiment-record` 的「`params` 的键换过一次名」）。

#### Scenario: 一个参数名不合约定

- **WHEN** 某个模块声明了 `parameter WIDTH`、`parameter DW`、`parameter W` 或 `parameter N_LANES`
- **THEN** 检查 SHALL 失败，并指出文件、模块与参数名
- **AND** 报错 MUST 说明违反的是哪一条

#### Scenario: 一个端口名不合约定

- **WHEN** 某个模块有端口 `x`、`din`、`i_valid` 或 `o_data_pos`
- **THEN** 检查 SHALL 失败，并指出文件、模块与端口名
- **AND** 报错 MUST 给出应当写成的缩写（如 `valid → vld`）

#### Scenario: 多时钟构件的时钟与复位口

- **WHEN** 一个异步 FIFO 有输入端口 `wr_clk`、`wr_rst_n`、`rd_clk`、`rd_rst_n`
- **THEN** 检查 SHALL 放行它们
- **AND** 输出端口叫 `rd_clk`、或输入端口叫 `wr_clock` / `WR_clk` 时 MUST 仍报违规

#### Scenario: 冻结的黄金参照

- **WHEN** `flow/equiv/frozen/` 下的文件不合本约定
- **THEN** 它 SHALL 保持原样，检查 MUST NOT 扫描它
- **AND** 需要与新端口名对接时 MUST 通过 `flow/equiv/wrappers/` 下的包装件完成

#### Scenario: 改名不改变电路

- **WHEN** 一次改动只按本约定改参数名与端口名（含例化点）
- **AND** 改名前后同一组（映射后的）参数各跑一次实验
- **THEN** 两次记录的测量字段 SHALL 逐字段相同
- **AND** 网表字节 MUST NOT 被要求相同 —— 端口名写在网表里，它必然不同

### Requirement: 结构枚举参数必须取整数，非法取值必须在 elaboration 失败

`designs/**/*.v` 与 `cbb/**/*.v` 里名为 `SCHEME` 或以 `_SCHEME` 结尾的参数，默认值 MUST 是非负整数
字面量，MUST NOT 是字符串（用户 2026-09-29 定）。编号按**设计**定一套：按该设计 `params.yaml` 里
`values` 的顺序从 0 起，同一设计里透传这个参数的模块 MUST 沿用同一套编号。只有两种选择的结构维度
MUST 写成 `_EN` 开关，而不是取 0 / 1 的 `SCHEME`。

用到它的模块 MUST 用具名 `localparam` 写分支条件，MUST NOT 与裸数字比较；分派链 MUST 对每一个合法
取值写显式判断，MUST NOT 写兜底 `else`，MUST NOT 静默落进某一个合法结构。非法取值的报错写成
`` `ifdef CBB_PARAM_CHK_ON `` 里 generate 条件块的 `$error`（`rtl-structure-authority` 的参数合法性检查写法，
`add-rtl-coding-style` D20），MUST NOT 例化不存在的模块。

`flow/equiv/frozen/` 下的冻结黄金参照不适用本条款。改取值与改参数名同形：记录里 `params` 的取值随之
改变，MUST 被当作一次记录序列的分界（读法见 `experiment-record`）。

#### Scenario: 字符串取值的结构枚举

- **WHEN** 某个模块声明了 `parameter SCHEME = "CLA"` 或 `parameter CPA_SCHEME = "KS"`
- **THEN** 护栏 SHALL 失败，并指出文件、模块与参数名
- **AND** 报错 MUST 说明结构枚举要取整数

#### Scenario: 非法的结构编号

- **WHEN** 定义了 `CBB_PARAM_CHK_ON`，以一个不在 `values` 里的整数例化某个设计（例如 `LZD` 的 `SCHEME = 7`）
- **THEN** iverilog、verilator 与 yosys 的 elaboration SHALL 各自失败，并报出该模块的 `$error` 提示
- **AND** 不定义宏时 MUST NOT 生成任何一个合法结构的分支

#### Scenario: 数字化不改变电路

- **WHEN** 一次改动只把某个设计的结构枚举从字符串换成按本条款编号的整数
- **AND** 数字化前后同一组（按编号映射后的）参数各综合一次
- **THEN** 两次的 `cell_count` 与 `area_um2` SHALL 逐项相同

### Requirement: IP 设计根的模块端口与参数按 IP 级约定命名

声明为 IP 的设计根里，IP 顶层与只在该 IP 里用的私有子模块 MUST 按下列约定命名；它是「模块接口与参数
必须遵守统一命名约定」对这类模块的例外，两条冲突时以本条为准（用户 2026-09-29 定，D17、D18）：

1. 通道端口用 `s_`（从端，上游进来的通道）/ `m_`（主端，送往下游的通道）前缀，如 `s_cmd_addr`、
   `m_cmd_tag`；前缀按通道不按方向（`s_cmd_rdy` 是输出）。配置与边带信号（`clk`、`cfg_mode`）不加前缀；
   非通道口用 `i_` / `o_` 时 MUST 与方向一致。
2. 参数按 IP 级约定命名，允许带子模块前缀（`SUB_FIFO_DEPTH`、`S_CMD_MODE = 2'b00`），只要求全大写、
   不单字母。
3. 可复用 CBB 与 PPA 实验顶层 MUST NOT 使用本条，仍按统一命名约定。
4. 一个设计根是不是 IP MUST 由它显式声明，MUST NOT 按目录推断 —— IP 与 PPA 实验顶层同在 `designs/` 下。
   声明写在设计根 `params.yaml` 的顶层：`role: ip`（D19）；不写即为非 IP，`role` 取其它值 MUST 让护栏失败。

#### Scenario: IP 私有子模块的通道端口

- **WHEN** IP 设计根里一个只被该 IP 例化的子模块，输入通道端口叫 `s_cmd_addr`
- **THEN** 这 SHALL 合约定，不要求 `i_` 前缀

#### Scenario: IP 例化一个可复用 CBB

- **WHEN** IP 例化 `CBB_LZD`
- **THEN** `CBB_LZD` 的端口 SHALL 仍是 `i_src_vld` / `o_dst_dat` 这类统一命名，IP 在例化点把自己的 `s_` / `m_` 信号接上去

#### Scenario: IP 通道里反方向的握手口

- **WHEN** 声明了 `role: ip` 的设计根里，`FOO_BUF` 的输出端口叫 `s_cmd_rdy`
- **THEN** 这 SHALL 合约定 —— 前缀按通道，不按方向

#### Scenario: 没有声明 IP 的设计根用了 s_ 前缀

- **WHEN** 一个没有 `role: ip` 的设计根里，模块的输入端口叫 `s_cmd_addr`
- **THEN** 护栏 SHALL 失败，要求 `i_` 前缀

#### Scenario: role 拼错

- **WHEN** 设计根 `params.yaml` 写了 `role: IP`
- **THEN** 护栏 SHALL 失败，并指出 `role` 只许取 `ip`

#### Scenario: function 的输入

- **WHEN** 一个模块里的 `function f_h_col` 声明了 `input integer dat_w`
- **THEN** 命名检查 SHALL NOT 把 `dat_w` 当成模块端口

### Requirement: RTL 模块按 2000 行拆分

RTL 的模块拆分按下面两条并列的原则（内部#203 Q3，用户 2026-10-05 定；口径 2026-10-05 23:46 补充，内部#210）：

- **行数**：按一个上层**连同它的全部子模块**的总行数算。总行数小于 2000 行的上层 SHALL 把只被它例化的子模块并进来，不再包子模块；总行数达到 2000 行的上层 MAY 保留子模块。
- **功能独立**：功能独立的模块（能单独复用、单独验证）MAY 保持独立，即使它很小。

两类模块 SHALL 保持独立，不并：
- `params.yaml` 的 `memory_models` 声明的存储模型（如 FOO_META_SRAM）：流程靠它是独立模块来单列存储面积、换 PDK 时替换（内部#174、内部#181）；
- 被两个及以上上层例化的共用模块：并进去会变成多份代码，只留一份。

保层级不是不并的理由（与已取消的红线 6 冲突时用户选放弃保层级，内部#216）；要比结构的算子按上面两条原则判。由评审检查，不做机械检查。

#### Scenario: 小算子并进上层

- **WHEN** 一个 23 行的算子模块只被一个 300 行的模块例化，两者合计不到 2000 行，算子也不是功能独立的构件
- **THEN** 它 SHALL 并进那个模块，不再单独成模块；原先为它写的 `keep_hierarchy` 声明同一提交删掉

#### Scenario: 总行数超过 2000 的上层保留子模块

- **WHEN** 一个 1853 行的上层连同子模块合计超过 3500 行
- **THEN** 它 MAY 保留子模块

#### Scenario: 共用模块与存储模型不并

- **WHEN** 一个模块被两个上层例化，或它是 `memory_models` 声明的存储模型
- **THEN** 它 SHALL 保持独立

### Requirement: 位复制的计数是表达式时必须加括号

`designs/*/rtl/*.v`、`cbb/*/rtl/*.v` 与 `flow/templates/*.v` 里，复制运算的计数是带运算符的表达式时 MUST 写成 `{(W+1){x}}`，MUST NOT 写成 `{W+1{x}}`；计数是单个标识符或数字时不加（用户 2026-10-13 定，内部#286；rtl-r2-05、rtl-r3-03）。秒级护栏的书写风格段 MUST 检查，违规可按文件登记豁免。

#### Scenario: 裸表达式计数

- **WHEN** RTL 剥掉注释与字符串后出现 `{DAT_W/8{wdat_mix_emit}}`
- **THEN** fast_check 的 style 段 SHALL 失败，并指出文件与行号

#### Scenario: 合规写法

- **WHEN** 写成 `{(DAT_W/8){wdat_mix_emit}}` 或 `{DAT_W{1'b0}}`
- **THEN** 本条 SHALL NOT 报错

### Requirement: 带参数的被测顶层必须有参数合法性检查块

`params.yaml` 声明的每个被测顶层，其模块有 `parameter` 时 MUST 含 `` `ifdef CBB_PARAM_CHK_ON `` 检查块，按 LRS / spec 参数表的约束（取值范围、参数间关系）做 elaboration 期检查（用户 2026-10-13 选 B11 (b)，内部#286）。只被上层例化、参数由上层检查后传入的子模块 MAY 不带。秒级护栏 MUST 检查检查块存在；检查是否覆盖了每条约束由评审看。

#### Scenario: 顶层缺检查块

- **WHEN** 某个被测顶层带参数，但它的模块文件里没有 `` `ifdef CBB_PARAM_CHK_ON ``
- **THEN** fast_check 的 style 段 SHALL 失败，并点名该顶层与文件

#### Scenario: 子模块不查

- **WHEN** `foo_buf_cmd.v` 没有检查块，它不是被测顶层
- **THEN** 本条 SHALL NOT 报错
