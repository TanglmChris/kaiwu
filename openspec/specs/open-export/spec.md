# open-export Specification

## Purpose
私有单仓里哪些文件可以公开、怎么公开（内部#305）：开源集合由白名单声明、默认闭源；泄漏扫描拦住闭源名字；导出器从一个提交导出开源集合到本地目录，导出时改写私有 issue 引用，导出结果要能独立通过检查。建公开仓与推送不在本能力内。

## Requirements

### Requirement: 开源集合由白名单声明，默认闭源

仓库 MUST 用一份白名单文件 `flow/export/manifest.yaml` 声明哪些路径属于开源集合。路径按仓库根相对的 glob 写。
- 没有被白名单匹配的已跟踪文件 SHALL 一律视为闭源。
- 白名单 MAY 用 `exclude` 从已匹配的路径里再排除。
- 白名单只决定集合，MUST NOT 让任何流程命令的行为随之改变。

理由：默认闭源时，新目录不会因为没人想到而被公开（内部#305，用户 2026-10-14 定私有单仓 + 导出公开仓）。

#### Scenario: 新加的目录默认不公开

- **WHEN** 仓库新增一个已跟踪目录 `foo/`，白名单里没有任何一项匹配它
- **THEN** 扫描器列出的开源集合里不含 `foo/` 下的文件

#### Scenario: 排除优先于包含

- **WHEN** 白名单包含 `cbb/**`，同时排除 `cbb/cbb_bin2onehot/**`
- **THEN** 开源集合含 `cbb/cbb_lzd/` 下的文件，不含 `cbb/cbb_bin2onehot/` 下的文件

### Requirement: 泄漏扫描必须能失败

扫描器 `flow/export/leak_scan.py` MUST 对开源集合里每个文件的路径与内容，按清单里的规则逐条匹配，报告每处命中的文件、行号和规则名。
- 规则分两级：
  - `block`：闭源设计名、闭源构件名、本机绝对路径、Slack 等私有 ID；
  - `warn`：如私有 tracker 的 issue 号。
- 有任一 `block` 命中时 MUST 以非零退出；只有 `warn` 命中时 SHALL 以 0 退出并打印计数。
- 扫描对象 SHALL 是某个 git 提交的树（默认 `HEAD`），而不是工作区。导出的就是提交，工作区里没提交的东西不该影响结论。

#### Scenario: 埋入闭源名字

- **WHEN** 开源集合里一个文件含有一条 `block` 规则匹配的字符串
- **THEN** 扫描器以非零退出，输出这处命中的路径、行号与规则名

#### Scenario: 闭源目录里的同名字符串不算

- **WHEN** 同一个字符串只出现在白名单之外的文件里
- **THEN** 扫描器不报告它

#### Scenario: 只有 warn 命中

- **WHEN** 开源集合里只有 `warn` 规则命中
- **THEN** 扫描器以 0 退出，输出每条 warn 规则的命中数

### Requirement: 导出器从提交导出开源集合

导出器 `flow/export/export.py` MUST 从某个 git 提交的树（默认 `HEAD`）里取开源集合，逐文件写到一个本地目录。
- 目标目录 MUST 不存在或为空，否则拒绝导出。
- 改写后的内容 MUST 先按全部 `block` 规则扫一遍；有任一命中时 MUST 以非零退出，并且不写任何文件。
- 二进制文件与符号链接 SHALL 原样导出，可执行位 SHALL 保留。
- 导出器 MUST NOT 在目标目录里建 git 仓库，也 MUST NOT 推送任何东西。

理由：导出的是提交，工作区不影响结论；公开仓的建立与推送是后续阶段的对外动作，要单独批准（用户 2026-10-18）。

#### Scenario: 有 block 命中时什么都不写

- **WHEN** 开源集合里一个文件含有 `block` 规则匹配的字符串
- **THEN** 导出器以非零退出，输出命中的路径、行号与规则名，目标目录不存在或仍为空

#### Scenario: 目标目录非空

- **WHEN** 目标目录里已经有文件
- **THEN** 导出器以非零退出，不改动目录里的任何文件

#### Scenario: 默认闭源的文件不导出

- **WHEN** 一个已跟踪文件没有被白名单 `include` 匹配
- **THEN** 导出目录里没有这个文件

### Requirement: 私有 issue 引用在导出时改写

导出器 MUST 把开源文件说明文字里的私有 issue 引用改写成 `内部#N`，私有仓源文件 SHALL NOT 被改动。
- 裸的 `#N` 改成 `内部#N`。
- 指向私有仓 issue 的 Markdown 链接：链接文字是 `#N` 时整个改成 `内部#N`，否则改成 `<文字>（内部#N）`。
- 裸的私有仓 issue URL（含 `#issuecomment-…` 片段）改成 `内部#N`。
- 只改说明文字：
  - `.md`、`.txt` 改整个文件；
  - `.py` 只改注释与 docstring；
  - Verilog 与 Verilator 配置只改 `//` 之后的部分；
  - 其他文本只改注释部分。
- 代码里的字符串 MUST 原样导出。
- 导出完 MUST 打印每条 `warn` 规则剩余的命中数和所在文件；剩余命中不阻止导出。

理由：用户 2026-10-14 定 issue 留私有、由导出器改写（内部#305 Q1），2026-10-18 定改成「内部#N」、代码字符串原样并报计数。改代码字符串会误伤嵌在字符串里的 Verilog 延时 `内部#1`。

#### Scenario: 注释里的 issue 号被改写

- **WHEN** 开源的 Python 文件注释里写 `（内部#305）`，Verilog 文件的 `//` 注释里写 `内部#12`
- **THEN** 导出后分别是 `（内部#305）` 与 `内部#12`

#### Scenario: 代码里的 # 不被改写

- **WHEN** 开源的 Python 文件在字符串字面量里嵌了 Verilog `内部#1 clk = ~clk;`，Verilog 文件在代码里写 `内部#1`
- **THEN** 导出后这两处与源文件逐字节相同，摘要把 Python 那处计入剩余的 `issue-ref`

#### Scenario: 私有仓链接被去掉

- **WHEN** 开源的 Markdown 文件里有 `内部#7` 和 `规则（内部#30）`
- **THEN** 导出后分别是 `内部#7` 与 `规则（内部#30）`，导出目录里不再出现这两个 URL

### Requirement: 原样导出名单

白名单 MAY 用 `verbatim:`（glob 列表）列出按字节原样导出的开源文件。导出器 MUST NOT 改写这些文件，它们剩余的命中 SHALL 计入摘要。

理由：有的文件以自身字节为键。`flow/equiv/run_equiv.py` 的证明器哈希取整个文件的字节，改一个注释字就会让等价账本全部失效。

#### Scenario: 名单里的文件不被改写

- **WHEN** 白名单的 `verbatim:` 列了 `flow/equiv/run_equiv.py`，这个文件的注释里有 `内部#39`
- **THEN** 导出后它与源提交里的版本逐字节相同

### Requirement: 导出结果自足

一个 `block` 命中为 0 的导出结果，在导出目录里建成 git 仓库、用本机工具链跑 `./scripts/fast_check.sh` 与全量 pytest 时，MUST 都通过。依赖闭源内容的用例 SHALL 以写明原因的方式跳过，MUST NOT 失败。

理由：公开仓的读者只有导出的这些文件；导出之后测不通，说明开源集合缺了东西，或者改写误伤了代码。

#### Scenario: 读闭源记录的用例跳过

- **WHEN** 导出目录里没有 `results/*/experiments.jsonl`
- **THEN** 读这份记录的用例报跳过，原因写明记录闭源、不在导出集合

### Requirement: 开源集合的泄漏只许减少

仓库 MUST 在 `flow/export/leak_baseline.txt` 记一个基线：开源集合 block 命中数的上限。`./scripts/fast_check.sh` MUST 扫 HEAD 提交的开源集合，block 命中数超过基线时失败，并按文件列出比 merge-base 多出来的命中次数（MUST NOT 打印命中的原文）。HEAD 上的基线高于 merge-base 上的基线时 MUST 失败。清单或基线在 merge-base 上存在、而 HEAD 上被删掉或写坏时 MUST 失败，MUST NOT 记为未执行。命中数低于基线时 MUST 提示可以调低的值。

merge-base 取 HEAD 与 main 的：本地 `main` 落后于 `origin/main`（是它的祖先）时 MUST 用 `origin/main`，因为各 worktree 共用的本地 main 平时没人让它前进（内部#448）。拿 merge-base 的树做逐文件对比时，那棵树对不上当前清单（例如清单里的替换源在那棵树里还不存在）MUST NOT 让检查崩溃：照旧按命中数判，改为按文件列出命中最多的文件。

理由：泄漏扫描不在门禁里时，开源集合的 block 命中一天内从 98 涨到 2363，清了还会再涨（内部#365，用户 10-20 定先做门禁）。

#### Scenario: 新提交往开源路径写了闭源名字

- **WHEN** 基线 100，HEAD 的提交在 `tests/test_x.py` 里新增 3 处 block 命中，合计 103
- **THEN** fast_check 失败，列出 `tests/test_x.py +3`，不打印那几行

#### Scenario: 本地 main 落后于远端 main

- **WHEN** 本地 `main` 停在旧提交，分支合了更新的 `origin/main`，又新增了 block 命中
- **THEN** merge-base 按 `origin/main` 求，按文件列出相对它多出来的命中

#### Scenario: merge-base 的树对不上当前清单

- **WHEN** 当前清单里的替换源在 merge-base 的树里不存在，命中数又超过基线
- **THEN** 检查照旧失败，按文件列出命中最多的文件，MUST NOT 以异常退出

#### Scenario: 分支删掉基线文件

- **WHEN** merge-base 上有 `flow/export/leak_baseline.txt`，分支把它删了
- **THEN** fast_check 失败，说明门禁不能靠删文件绕过（10-20 kaiwu-layout 复核发现）

#### Scenario: 分支把基线调高

- **WHEN** merge-base 上基线是 100，分支把它改成 120
- **THEN** fast_check 失败，说明基线只许调低

### Requirement: 替代文件

白名单 MAY 用 `substitute:` 写一组「发布路径 → 源路径」，两者都是仓库根相对的具体路径，不是 glob。对其中每一项：
- 发布路径 SHALL 属于开源集合，内容取源路径在同一提交里的内容。发布路径本身是否被 `include` 匹配、是否被 `exclude` 排除，都不影响这一点。
- 源路径 MUST NOT 以自己的名字出现在开源集合里，即使被 `include` 匹配到。
- 泄漏扫描与导出 MUST 都按顶替后的内容处理：扫描命中按发布路径报告，导出文件写在发布路径，可执行位跟随源路径。
- 源路径在该提交的树里不存在时，扫描器与导出器 MUST 以非零退出，并说明是哪一项；MUST NOT 跳过这一项继续。
- 同一个源路径 MUST NOT 对应多个发布路径；发布路径与源路径也 MUST NOT 相同。违反时白名单视为无效，以非零退出。

理由：有些文件仓内要保留完整版，开源版换一份内容（内部#394：`docs/data-credibility.md` 的通用版，用户 2026-10-21 定）。顶替时发布路径不变，开源集合里的引用就都不用改；`CLAUDE.md`、`keel/config.yaml` 的开源版（内部#305 P3）用同一个机制。

#### Scenario: 闭源文件由通用版顶替

- **WHEN** 白名单没有 include `docs/a.md`，`substitute:` 写了 `docs/a.md: docs/a.open.md`，`docs/a.open.md` 也被 `include` 匹配
- **THEN** 开源集合里有 `docs/a.md`，内容等于该提交里 `docs/a.open.md` 的内容；开源集合里没有 `docs/a.open.md`

#### Scenario: 扫描的是顶替后的内容

- **WHEN** 仓内 `docs/a.md` 含 `block` 规则匹配的字符串，它的源 `docs/a.open.md` 不含
- **THEN** 扫描器对 `docs/a.md` 报 0 处命中；反过来，源里含命中时，扫描器按 `docs/a.md` 和源里的行号报告

#### Scenario: 源文件不存在

- **WHEN** `substitute:` 写了 `docs/a.md: docs/missing.md`，该提交里没有 `docs/missing.md`
- **THEN** 扫描器与导出器都以非零退出，输出里点名 `docs/missing.md`；导出目录不写任何文件

### Requirement: 闭源设计根的标识符自动进 block 扫描

白名单写了 `closed_vocab:` 段时，扫描器 MUST 从被扫提交里的**闭源设计根**自动抽出一张闭源词表，作为一条 block 规则 `closed-vocab` 参与扫描：
- 闭源设计根：`closed_vocab.roots` 的 glob（缺省为 `designs/*` 与 `cbb/*`）匹配到的目录中，没有任何已跟踪文件属于开源集合的那些。
- 抽词：闭源根 `rtl/` 下 RTL 文件（`.v`、`.sv`、`.vh`、`.svh`）去掉注释后的模块名、参数名（`parameter` / `localparam`）、模块头端口表里的端口名；闭源根下代码文件（`.py`、`.v`、`.sv`、`.sh`、`.tcl`）的文件名（第一个 `.` 之前的部分）。
- 词表 SHALL 去掉：开源设计根按同样规则抽出的词；短于 `closed_vocab.min_len`（缺省 4）的词；`closed_vocab.allow` 里的词；与 `closed_vocab.allow_patterns` 中任一正则整词匹配的词。
- 匹配：开源集合每个文件的路径与每一行，按标识符（`[A-Za-z_][A-Za-z0-9_]*`）切词后与词表求交，大小写敏感；有交集即记一处 `closed-vocab` 的 block 命中。
- 泄漏门禁（`leak_ratchet.py`）与导出器 MUST 把 `closed-vocab` 与其他 block 规则同等对待。
- 正样本自检：每个从 RTL 抽出的词 MUST 能被同一个切词器在它的来源文件里切出来；不满足时，或闭源根 `rtl/` 下有 RTL 却一个词也没抽出时，扫描器 MUST 以退出 2 报错，点名出问题的词或根，MUST NOT 当作 0 命中继续。
- 没写 `closed_vocab:` 段的白名单，扫描行为与本要求之前相同。

理由：内部#409 两轮评审都是人工从闭源设计里抽词扫出的漏网名字（L1–L8、私有回归脚本名），手写正则每次只补上一个名字。用户 2026-10-26 定改为从闭源设计自动抽词。

#### Scenario: 闭源根的端口名出现在开源文件里

- **WHEN** `cbb/cbb_secret/` 没有文件进开源集合，其 `rtl/` 下模块头声明了端口 `o_secret_col`；开源文件 `flow/a.py` 第 2 行写了 `o_secret_col`
- **THEN** 扫描器报 `flow/a.py:2: closed-vocab [block]` 并以退出 1 结束

#### Scenario: 开源根也定义的词不算命中

- **WHEN** 闭源根与开源根 `cbb/cbb_open/` 的 RTL 都声明了参数 `DAT_W`，开源文件里写了 `DAT_W`
- **THEN** 这一处不算 `closed-vocab` 命中

#### Scenario: 豁免表里的词不算命中

- **WHEN** 闭源根的端口 `s_cmd_rdy` 出现在开源文件里，`closed_vocab.allow_patterns` 有一条整词匹配它的正则
- **THEN** 这一处不算 `closed-vocab` 命中

#### Scenario: 闭源根的代码文件名出现在开源文件里

- **WHEN** 闭源根下有 `tb/secret_regress.py`，开源文件写了 `secret_regress --sva`
- **THEN** 扫描器对这一行报 `closed-vocab` 命中

#### Scenario: 自检失败

- **WHEN** 闭源根 `rtl/` 下有 RTL，但抽出的词有一个不能被切词器在来源文件里切出来（或一个词也没抽出）
- **THEN** 扫描器以退出 2 结束，输出点名该词或该根，不报「可导出」

#### Scenario: 导出器带上闭源词表

- **WHEN** 白名单写了 `closed_vocab:`，开源文件里有闭源根的模块名
- **THEN** 导出器以非零退出，导出目录不写文件

### Requirement: 闭源词表可纳入 git 历史里删掉的闭源设计根

白名单的 `closed_vocab:` 写了 `history: true` 时，闭源词表 MUST 还包括：被扫提交的 git 历史里已删掉、在被扫提交的树里不存在、位于 `roots` 匹配的设计根下的文件，各取最近一次删除前的那一版，按「闭源设计根的标识符自动进 block 扫描」的抽词规则抽出的词。
- 这些文件所在的根，若在被扫提交里仍有文件属于开源集合，或匹配 `closed_vocab.history_open_roots` 中的某个 glob，其历史文件 MUST NOT 进词表。
- 自检对历史 RTL 同样要求抽出的每个词都能被切词器在来源文件里切出来；历史文件抽不出词时 MUST NOT 报错。
- 没写 `history: true` 时，词表与本要求之前相同。

理由：内部#409 第一轮的漏网名字大多取自已删的子设计，只看现在的树抽不到（内部#438）。用户 2026-10-26 定把历史纳入。

#### Scenario: 已删闭源设计的端口名出现在开源文件里

- **WHEN** `cbb/cbb_gone/` 曾有 `rtl/gone_core.v`（端口 `o_gone_col`），后来整个目录被删除；开源文件写了 `o_gone_col`；白名单 `closed_vocab: {history: true}`
- **THEN** 扫描器报 `closed-vocab` 命中；不写 `history: true` 时不报

#### Scenario: 历史上的开源根不进词表

- **WHEN** 已删的 `cbb/old_open/` 列在 `history_open_roots` 里，它的端口名出现在开源文件里
- **THEN** 不算 `closed-vocab` 命中；不列时算

#### Scenario: 现在仍开源的根的已删文件不进词表

- **WHEN** `cbb/cbb_open/` 现在有文件进开源集合，它曾有一个已删文件 `rtl/old.v`（端口 `o_was_open`），开源文件写了 `o_was_open`
- **THEN** 不算 `closed-vocab` 命中

#### Scenario: 历史文件抽不出词不报错

- **WHEN** 已删的闭源根里只有一份只含注释的 RTL
- **THEN** 扫描器不报自检失败

### Requirement: 开源预检一条命令

仓库 MUST 提供 `flow/export/open_check.py --ref <提交>`，按顺序完成评审要跑的机械检查，并打印一张逐项结论表（ok / FAIL / warn）：
- 导出（含泄漏扫描）：调 `export.py`，block 命中或白名单无效即 FAIL；
- 悬空引用：目标是 `openspec/changes/archive/` 下的闭源文件或目录时，「闭源归档引用」一项 FAIL，逐条列出，不中断后面的步骤；其余悬空引用只报 warn。归档路径里带 `*` 的按被扫提交的树展开，匹配到的全是闭源内容才算；别处的通配不展开；
- 死链：只报 warn，不影响退出码；
- `--quick` 到此为止，另外把导出目录 `git init -b main` 并提交一次；
- 完整模式继续：照 `docs/quickstart.md` 第 1 步在导出目录里从零建 venv、装 `requirements.txt`，MUST NOT 复用或软链已有的 venv；EDA 工具不在 `PATH` 时补 `~/tools/env.sh`，仍缺即以退出 2 结束；子进程以激活该 venv 的 `PATH` 跑 `./scripts/fast_check.sh` 与 `pytest tests/ -m 'not flow'`；
- pytest 合格 MUST 同时满足：退出 0、无失败、无错误、有通过，且每条跳过的原因都含「不在导出集合」；
- 完整模式 MUST 经 `flow/budget.py` 拿 `cpu-heavy`。
任一 FAIL 退出 1，全部合格退出 0。

理由：内部#409 各方手跑导出目录的检查，方法不一、步骤会漏；预检之后引入的回归（Q2）没人在冻结前重跑，软链现成 venv 又漏了 quickstart 第 1 步（Q1）（内部#441 R4）。

闭源归档一项升 FAIL：开源文本引用外人打不开的归档 change 及其证据，`fd6385ef` 上有 19 处、另有 10 处通配写法当时认不出（用户 10-27 定，内部#444）。

#### Scenario: 悬空引用按 warn 列出

- **WHEN** 开源文件写了闭源目录里的 `cbb/cbb_secret/tb/secret_regress.py`、或只写了文件名 `secret_regress.py`
- **THEN** 结论表的悬空引用一项是 warn，列出该文件与行号；退出码不因此变化

#### Scenario: 死链按 warn 列出，模板占位不报

- **WHEN** 导出的 Markdown 里有 `[a](missing.md)` 与 `[b](doc/<图名>.svg)`
- **THEN** 死链一项列出 `missing.md`，不列 `doc/<图名>.svg`

#### Scenario: 读闭源文件之外的跳过判失败

- **WHEN** 导出目录里的 pytest 有一条跳过，原因是工具不在 PATH
- **THEN** pytest 一项 FAIL

#### Scenario: 导出失败时整体失败

- **WHEN** 开源集合里有 block 命中
- **THEN** 导出一项 FAIL，以退出 1 结束，不再跑后面的步骤

#### Scenario: 引用闭源归档判失败

- **WHEN** 开源文件写了闭源的 `openspec/changes/archive/2026-01-01-secret-change/evidence/pair.txt`
- **THEN** 「闭源归档引用」一项 FAIL，列出该文件与行号，以退出 1 结束；死链与 git init 照样执行

#### Scenario: 通配写法按展开结果判

- **WHEN** 开源文件写了 `openspec/changes/archive/*-secret-change/evidence/`（匹配到的全是闭源）、`openspec/changes/archive/*-open-change/design.md`（匹配到开源归档）与 `cbb/**`（匹配到开源文件）
- **THEN** 只有第一处列进「闭源归档引用」；后两处既不 FAIL 也不进悬空引用

### Requirement: 开源评审按泄漏类清单

开源评审（内部#409 第二部分的各评审方）MUST 按下面的泄漏类逐类给结论，不只按「扫了哪些词」。每类由所列自动检查兜住；标了「人工」的，评审方 MUST 另做那一步。

| 泄漏类 | 自动检查 | 人工 |
|---|---|---|
| 本机路径（家目录、工作区目录名、记忆目录的编码路径） | `leak_scan` block：`abs-path`、`home-path` | — |
| 闭源 IP 名、角色名、群名 | `leak_scan` block：按 IP 名的 `closed-*` 规则 | 新 IP 开工时 chief 通知 layout 加名字规则 |
| 闭源设计的标识符（参数、端口、模块名，含已删设计） | `leak_scan` block：`closed-vocab`（含 `history`）及手写规则 | 各 IP 的 PM 按领域术语扫 |
| 闭源设计的文件名（脚本、TB） | `closed-vocab` 的代码文件名、手写规则 | — |
| 私有仓名与链接 | 导出器改写 issue 链接；`leak_scan` warn：`private-repo*` | 逐条看 `private-repo-link` |
| 私有提交号 | 无 | 看改动里 7–12 位十六进制串，REPORT 的来源提交号除外 |
| 派生自闭源数据的文件（REPORT、拷真实闭源文件的夹具） | `open_check`：悬空引用、导出目录 pytest | 核 REPORT 与当前记录同代 |
| 悬空引用、死链 | `open_check`：引用闭源归档（`openspec/changes/archive/**`）FAIL，其余 warn | 逐条看 warn |
| 文档能照着跑通 | `open_check` 完整模式 | — |
| 非技术语境（白名单 `competition` 规则所列的词） | `leak_scan` block：`competition` | chief 整体口径 |

理由：内部#409 每轮漏的都是一整类（文件名、REPORT、私有提交号），评审判据只列了要扫的词（内部#441 R3）。

#### Scenario: 评审结论覆盖每一类

- **WHEN** 一位评审方在冻结提交上给出「通过」
- **THEN** 结论里对表中与其角度相关的每一类都有一句结论或指向 `open_check` 的结果
