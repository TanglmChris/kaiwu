# 踩坑清单

**这个项目的头号失效模式不是"跑不通"，是"跑通了但数字不可信"。** 下面每一条都
**不会报错**：工具正常退出、报告格式正常、数值量级看着也正常，只有盯着数据觉得
不对劲才会发现。门禁检查不出来（`keel gate` 判的是证据齐不齐，不判数字对不对）。

用法：**换库 / 换 PDK / 改 flow / 报一个新数字之前，从头过一遍判据列。**

| | 坑 | 一句话判据 |
|---|---|---|
| P-1 | abc 没有 `-constr`，没有缓冲插入 | `pytest tests/test_synth_electrical.py` |
| P-2 | 合并 liberty 模板顺序错，时序弧被丢 | `python3 tests/test_merge_liberty.py <库.lib>` |
| P-3 | `-flatten` + ABC `&dch` 把结构抹平 | 两个不同架构的 area/delay 逐位相同 |
| P-4 | OpenSTA 单位被 `read_liberty` 重置 | 延时差 1000 倍 |
| P-5 | 功耗没有活动率反标 | `grep "pin activities" runs/<id>/sta/sta.log` 的 N 是否 > 0 |
| P-6 | 参数没命中 generate 分支，空电路 | `cell_count` 与预期量级差一大截 |
| P-7 | 脏工作区跑实验，provenance 是错的 | `git status` 干净再跑 |
| P-8 | 跨流程代横向比较 | `flow.fingerprint` 相同**且**两条记录的设计 RTL 同源 |
| P-9 | 用整份网表 sha256 自证「只改了注释」 | 先 `grep -v '(\* src = '` 再 diff |
| P-10 | `ltp -noff` 在 `dfflibmap` 之后穿过触发器 | 流水级数越多、量出来的单级深度反而越大 |

---

## P-1. 不给 abc `-constr` 就完全没有缓冲插入

**症状**：延时**量级错误**，不是精度损失。一个 `INVx1` 可以硬扛 436 个负载
（194 fF，而它的 `max_capacitance` 只有 46 fF），一个 cell 就占掉关键路径一半以上。
没有任何工具会报错 —— `max_capacitance` 在 liberty 里只是**声明**，
STA 照常外插出一个看似正常的延时。

**成因**：`yosys` 对 `abc -liberty` 有**两套**默认脚本（`yosys -h abc` 原文）。
不给 `-constr` 时只有技术映射；给了才在末尾接上
`buffer; upsize {D}; dnsize {D}; stime -p`。

**修复**：`flow/synth/synth.py` 的 abc 命令带 `-constr flow/synth/abc.constr`。

**判据**：`pytest tests/test_synth_electrical.py`，或对一份真实网表跑
`python tests/test_synth_electrical.py <网表.v>`。

**操作细节**：
- `abc.constr` 只有两行（`set_driving_cell` / `set_load`），**刻意不加注释** ——
  它原样交给 ABC 的 `read_constr`，未必认 `#`。说明写在 `synth.py` 里。
- **换 PDK 必须改 `abc.constr` 里的 cell 名**，否则 ABC 找不到它。
- `set_load` **不是需要调优的旋钮**：实测 0.1 / 0.5 / 1.0 三档结果基本相同。
- 代价：面积普遍涨 4~11%（`upsize` 放大单元），小设计的时序基本不动。

**实测**（2026-09-09）：加上 `-constr` 后一个已删的解压流水设计的关键路径从
12.3168 ns 降到 1.1558 ns（−90.6%）。详见 `docs/data-credibility.md` 的 D-4。

---

## P-2. 合并 liberty 里模板排在 cell 之后，时序弧被静默丢弃

**症状**：**所有以触发器为起点的路径整体消失**。带流水的设计报出来的"关键路径"
其实是"输入到第一级寄存器"；时序单元的 internal power 恒为 0。全程无报错。

**成因**：liberty 自上而下解析。模板定义在引用之后时**解析器不报错**，
只警告一句就把那个时序组丢掉 —— 丢的是那条弧的延时模型。

**修复**：`flow/synth/merge_liberty.py` 排成「全部模板在前、全部 cell 在后」。

**判据**：`python3 tests/test_merge_liberty.py <合并库.lib>`；
或看 OpenSTA 读库时有没有 `table template ... not found` /
`no table models found in timing group`（正常应该是 **0 条**）。

**范围**：**在 `37cb2cb` 之前生成的合并库必须重新生成**，不管哪个 Vt/corner。

**实测**：2026-09-09 SEQ 的 `delay_template_7x7` 被追加在合并库末尾，
OpenSTA 于是没有任何时序单元的 `CLK→Q` 弧。详见 `docs/data-credibility.md` 的 D-2。

契约条款：`openspec/specs/experiment-trust/spec.md`「合并出来的 liberty 必须自洽」
「时序结果必须来自完整的路径集合」。

---

## P-3. `-flatten` + ABC `&dch` 会把不同结构优化成同一个电路

**症状**：两种手写微架构报出**完全一样**的关键路径级数和面积。

**成因**：`yosys synth -flatten` 把整个设计拍平成一个模块再交给 ABC 做技术映射；
ABC 默认的 `-liberty` 脚本里有 `&dch`（choice-based 重综合），对加法器这种简单函数
会直接从布尔功能重新推导电路，把 ripple / CLA / carry-select 三种手写结构
全部收敛成同一个映射结果。

> **2026-10-05 起保层级不再强制**（用户定全仓取消红线 6，内部#216；与 内部#203「小于 2000 行不拆子模块」冲突时选放弃保层级）。
> 下面的现象与判据照旧成立：综合仍不加 `-flatten`，声明了 `keep_hierarchy` 就照施加；不声明时 ABC 可能跨边界重构，
> 读结构对比的数字时要知道这一点（`docs/data-credibility.md` 的读法条）。

**修复**：**不要 `-flatten`**；要比结构时，可以把每个"结构 building block"列进它所属被测顶层的
保层级声明 —— `designs/<设计根>/params.yaml` 的 `tops:<顶层>:synth:keep_hierarchy:`，
由 `flow/synth/synth.py` 在综合脚本里施加。⚠️ 2026-09-21 之前这个意图是写在 RTL 里的
（`(* keep_hierarchy *)` 属性），现在**不许再那么写**：可综合 RTL 不带综合指令
（`openspec/specs/rtl-structure-authority/spec.md`，秒级护栏会当场拒掉）。
声明里的每个名字都必须命中，打错一个当场失败 —— yosys 自己对选不中的模块
**只警告、退出 0**，不校验就是静默少保一层。

**适用面比想象的宽**：不止管"多种微架构比 PPA"，**也管"同一份组合逻辑比流水深度"**。
后者的失效模式还不一样 —— 切分点上没有模块边界时，`PIPE_STAGES=0` 那一档会独享
跨段重综合，而有寄存器的档只能各段各自优化，两者的差里于是混进了"失去跨边界优化"
这个与流水无关的反向效应，**曲线的形状是假的**。
所以：**"拿参数枚举结构"的新设计要比结构时，把关键 building block 写进那张声明表**（2026-10-05 起不强制）。

⚠️ **但要知道这个属性目前在本流程下不起作用**（2026-09-09 实测，2026-09-21 复测）：
`flow/synth/synth.py` 本来就不用 `-flatten`，yosys 的 `synth` 不带 `-flatten`
时不内联子模块、`abc -liberty` 也是逐模块调用的，所以声明与不声明，
cell 数与面积逐位相同、层次都完整保留。它是**防止以后有人给 `synth.py` 加
`-flatten` 的护栏**，不是当前测量成立的前提 —— 别把它当成"已经有防护了"就放心，
**真正的防护是那条不加 `-flatten` 的约定**。
这一条同时意味着**它不能用产线数字来验**，见 P-14。

契约条款：`openspec/specs/experiment-trust/spec.md`「功能等价的微架构取值必须产出
可区分的网表」「枚举流水深度的设计必须让各取值面对同一份组合切分」。

---

## P-4. OpenSTA 的单位会被 `read_liberty` 重置

**症状**：延时差 1000 倍 —— 一个"0.6 ns"的门，或者一个"600 ns"的加法器。

**成因**：`read_liberty` 把 command units 重置成 liberty 自己的单位（ASAP7 是 ps）。

**修复**：`set_cmd_units` 必须排在 `read_liberty` / `link_design` **之后**
（见 `flow/sta/run_sta.py` 第 43~49 行，那里有注释）。

**判据**：记数字之前先拿工艺常识核一遍量级。7nm 的一个门是几十 ps，
32 位 ripple 加法器是几百 ps 到 1 ns 量级。

---

## P-5. 功耗必须来自 VCD/SAIF 反标

**症状**：功耗数字存在、看着正常，但描述的是默认活动率，不是这个电路。

**判据**（2026-09-14 收紧）：

```
grep -h "pin activities" runs/<experiment_id>/sta/sta.log
```

`Annotated 0 pin activities.` → 这个数字不是这个电路的。`N > 0` 才算数。

⚠️ **原来的判据「记录里 `dynamic_power_w` 是否来自 VCD」查不出这个缺口。**
`read_vcd` 确实执行了、字段也确实非空 —— 但层次名对不上时一个引脚都没标上，
而 **OpenSTA 不报错**，`report_power` 照常给数字。「`read_vcd` 跑过」
≠「引脚标上了」，这两件事差了 11 倍（D-1 实测 631/633 份 `sta.log` 是
`Annotated 0`）。判据必须落在**标注数**上，不能落在「调了哪个命令」上。

**修复**：
1. `read_vcd` 要带 `-scope <设计名>` —— VCD 的层次是 `<设计名>.<信号>`，
   OpenSTA 在顶层作用域下找的是不带前缀的引脚名。
2. **标注数为 0 时当场报错、不出数**（`flow/sta/run_sta.py::_assert_activity_annotated`，
   在读 `power.json` **之前**跑）。这一条比第 1 条更要紧：第 1 条会被下一次
   改动悄悄破坏，第 2 条会响。
3. 动态功耗**只接受**从 VCD/SAIF 反标算出来的值。仿真通过却没产出 VCD 时
   流程直接报错、不写记录 —— 拿不到活动率就是没有功耗，不是"有一个差一点的功耗"。
   仿真未通过时两个功耗字段写 `null`（那份 VCD 描述的是一次错误的行为）。

契约条款：`openspec/specs/experiment-trust/spec.md`「活动率反标必须被证明真的发生了」
「仿真未通过时不得记录依赖该仿真的指标」「缺少必需输入时必须报出真正的原因」。

**历史影响**：`flow = sha256:c4dacda99…` 之前的**全部**记录都踩了这个坑，
两个功耗字段都不可用 —— 见 `docs/data-credibility.md` 的 D-1 与 D-9。

---

## P-6. 空的或退化的设计照样"通过"

**症状**：一个没命中任何 generate 分支的参数取值综合出几乎什么都没有的电路，
仿真、综合、STA 全过。

**成因**：RTL 里的参数分派是 if/else-if 链、没有 else。

**修复**：扫参维度必须给全（`sweep.py` 有守卫，缺一个就报错）；
记数字之前拿 `cell_count` 核一遍量级。

---

## P-7. 脏工作区跑出来的记录 provenance 是错的

`run_experiment.py` 把 `git rev-parse HEAD` 写进每一条记录。工作区脏着跑，
记录里的 commit 指向的不是产出它的那份代码。

**修复**：**先提交再跑实验**。`commit` 在 `keel/config.yaml` 里是常备授权，
就是为了让这条不成为摩擦。

2026-09-14 起这条有**机械保证**了：`scripts/run_experiment.py::_assert_clean_worktree`
在跑任何工具**之前**检查 `git status --porcelain`，脏了就抛错、不写记录。
唯一放行的路径是这次要追加的那个记录文件 `results/<设计根>/experiments.jsonl`（2026-10-25 之前是单文件 `results/experiments.jsonl`，内部#422）。

补这道守卫的起因就是踩了一次：一个已删的地址换算设计的 3 条记录
（`flow = sha256:0eec5f082…`，`git_commit = 0b34bc8`）是在 10 个文件没提交的
工作区里跑出来的。它们按红线 2 保留，provenance 不可信 —— 见
`docs/data-credibility.md` 的 D-10 末节。

---

## P-8. 跨流程代横向比较

**症状**：Pareto 前沿上出现一个"碾压"其他所有点的假点。

**成因**：`git_commit` 不能标识流程 —— 换 PDK、换 Vt/corner、重新生成合并 liberty
都不会改变任何 commit，却会让全部数字整体挪位。

**修复**：记录带 `flow.fingerprint`（八项事实的 sha256 —— 2026-09-27 之前是七项，`flow/flow_fingerprint.py`
现算）。**指纹不同的记录不能横向比较。** 报告与打分默认只呈现最新一代，
被排除的条数打在 stderr 上；要跨代看得显式加 `--all-generations`。

**⚠️ 指纹相同只是必要条件，不充分。** 指纹的事实里**没有一项包含设计 RTL** ——
改了设计而没改流程时，两代记录会带着**同一个指纹**并排躺在同一个文件里，而电路
已经不同。2026-09-14 一个已删的地址流水设计（五个配置端口改准静态、不再进流水线，
`PIPE_STAGES=1/2` 的触发器 71/145 → 38/83）就是第一例。

这种情形下判据只能是 `git_commit`，当场可跑：

```bash
# 取出该记录当时的设计 RTL，看它是不是你要比的那一版
git show <记录的 git_commit>:designs/<设计>/rtl/<顶层>.v | sha256sum
# 两条记录的这个哈希相同，才是同一个电路
```

**历史**：记录里有三代数据，跨代差异可以到数量级。2026-09-09 之前的 307 条没有指纹，
一律算「未知代」。详见 `docs/data-credibility.md` 的 D-5；
「同指纹、不同电路」这一类见同文件的 **D-11**。

契约条款：`openspec/specs/experiment-record/spec.md`「记录必须自解释其产出流程」、
`openspec/specs/ppa-scoring/spec.md`「打分必须限定在单一流程代内」、
`openspec/specs/design-report/spec.md`「报告必须限定在单一流程代内」。

---

## P-9. 用整份网表 sha256 自证「只改了注释」会误报

**症状**：只改了 RTL 的注释（或缩进），综合出的网表 sha256 变了。看上去像是
注释真的进了综合结果 —— 于是有人开始查一个不存在的问题，或者反过来，
以为自己的「只改注释」承诺没兑现而把改动撤回。

**成因**：yosys 把**源码位置**写进网表的 `(* src *)` 属性：

```
< (* src = "…/<模块>.v:234.1-338.10" *)
> (* src = "…/<模块>.v:237.1-341.10" *)
```

header 多 3 行，全部行号 +3，整份 sha256 必变。实测（2026-09-15，
已删的地址换算设计，`DW=256`）：`7cb1975a…` → `b624e920…`，而
**非 `(* src *)` 的差异行是 0 条**，`cell_count` 74 / `area_um2` 6.16734 两边一致。

**判据**（这才是正确口径）：

```
diff <(grep -v '(\* src = ' 改前网表.v) <(grep -v '(\* src = ' 改后网表.v)
```

外加 `cell_count` 与 `area_um2` 一并比对。三项都一致才算「综合结果没变」。

**这项差异进不进记录**：不进。实验记录（`results/<设计根>/experiments.jsonl`）的字段集合是
`flow` / `design` / `params` / `sim` / `synth` / `sta` / `ref_metrics`，
**没有网表哈希**。所以「只改注释」不会让任何一条记录变化，也不会换代
（RTL 本来就不在 `flow` 指纹里 —— 它是被测对象，不是流程）。

**适用范围**：凡是要自证「这次改动不影响综合结果」的场合都按这个口径办 ——
改注释、改缩进、改综合脚本里施加的属性（`keep_hierarchy` 之类，另见 P-3 / P-14）、
跨设计根同步拷贝。

**⚠️ 它的判别力被参数空间夹死，而这一点在「三项齐同」的字面里看不出来。**
这个判据只覆盖**实际综合过的那几组参数**。落在扫参空间之外的 `generate`
分支，综合根本不会走到，于是三项必然齐同 —— 不是因为改对了，是因为没测。
实测（2026-09-20，2.6 内联一个已删的压缩模块）：`SEL_CLOSED` 默认 0
且不在 `params.yaml` 里，闭式那条分支（`SEL_K` / `SEL_A0` / `SEL_KW` /
`A_K` / `B_K` 五个 localparam 的全部改动面）**一次都没被综合到**，
31 组三项齐同对这 5 处的判别力是 **0**。补的是等价证明：
当时的 `run_equiv.py` 配对证的正是「按定义」与「闭式」两条分支等价，
三档规模全 PROVED。
**先问「这次改的代码在不在被综合的那几组里」，再看三项齐不齐同。**

来源：内部#34；
实测过程见
`openspec/changes/archive/2026-09-15-make-the-liberty-base-file-explicit-and-fix-two-stale-rtl-headers/design.md`
的 A1。

---

## P-10. `ltp -noff` 在 `dfflibmap` 之后失效，会直接穿过触发器

> 这一条 2026-09-15 写下时编号是 P-9；2026-09-16 合并 main 时与另一条 P-9
> （整份网表 sha256 自证「只改了注释」）撞号，本条让号改为 P-10。**内容一字未改。**
> 2026-09-16 之前写的「P-9」若在讲 `ltp -noff` 穿过触发器，指的就是这一条。

**症状**：量出来的**单级组合深度自相矛盾** —— 流水级数越多，单级反而越深。
一个已删的地址流水设计实测 `PIPE_STAGES` = 0 / 1 / 2 给出 43 / 45 / 47 级：
加了两组寄存器，最深那一级居然比纯组合还长 4 级。

没有任何报错。`ltp` 正常打印一条路径、正常给出 `length=`，数字量级也正常，
只有拿它跟"流水应该让单级变浅"这个常识对一下才会发现不对。

**成因**：`ltp -noff` 只识别 **yosys 内建**的触发器类型（`$_DFF_*` / `$dff` 一族）。
`dfflibmap` 之后，触发器已经是 liberty 单元（ASAP7 这边是
`DFFASRHQNx1_ASAP7_75t_R`），`-noff` 认不出来，于是把它当成一个普通组合单元，
**沿着 D 穿到 Q 继续往下走**。量出来的就不再是"寄存器到寄存器"，而是一条横跨
整条流水线的伪路径。

**判据**：把 `ltp` 打印的那条路径看一眼，有没有经过寄存器实例。

```bash
# 路径里出现寄存器名 => 这个数不是单级深度
yosys -p "...; dfflibmap -liberty $LIB; abc -liberty $LIB -constr ...; \
          flatten; ltp -noff" 2>&1 | grep -A40 'Longest topological path'
#  13: $abc$...$auto$dfflibmap.cc:468:dfflibmap$10673
#  14: \g_reg_a.r_q [21]        <-- 穿过了 REG A，后面还接着 26 级
```

**修复**：**先把触发器单元删掉，再 `ltp`**。删掉之后图在寄存器边界上断开，
剩下的最长拓扑路径就是真正的寄存器到寄存器深度。

```bash
yosys -p "...; dfflibmap -liberty $LIB; abc -liberty $LIB -constr ...; \
          opt_clean; setattr -mod -unset keep_hierarchy; flatten; opt_clean; \
          delete t:DFFASRHQNx1_ASAP7_75t_R; \
          ltp"
```

换 PDK 要换 `delete` 后面的单元名（`stat -liberty` 打印的直方图里找那个
`mapped N $_DFF*_ cells to \<名字> cells` 的名字）。另一条路是**在 `dfflibmap`
之前**量 —— 那时触发器还是 `$_DFF_*`，`-noff` 认得，但级数不是技术映射后的，
不能和映射后的数字混用。

**实测**（2026-09-15，同一个已删的闭源设计，ASAP7 RVT/TT 合并 liberty）：

| 位宽参数 | `PIPE_STAGES` | `ltp -noff`（错） | `delete` + `ltp`（对） |
|---|---|---|---|
| 12 | 0 | 43 | 43 |
| 12 | 1 | 45 | 33 |
| 12 | 2 | 47 | 27 |

`PIPE_STAGES=0` 两种量法一致 —— 那一档**本来就一个触发器都没有**，`-noff`
认不认得无所谓。差异只在有寄存器的档位上出现，而那恰恰是唯一需要单级深度的场合。

**⚠️ 哪些已经提交的数字不受影响。** 那个设计的 `verify.md` 与
`spec.md`（设计根已删，见 git 历史）在 2026-09-15 之前记的 `43 / 41 / 43`（`PIPE_STAGES=0` 的总深度）
与三个 step 各自的 `12 / 24 / 14` **全部仍然有效**：前者是 `PIPE_STAGES=0`，
后者是三个纯组合模块单独综合，两种情形里都**没有触发器**，`-noff` 无从出错。
受这个坑影响的只会是"拿同一个脚本去量带流水的形态"，而在发现它之前本仓从未
量过那个数 —— 也正因为从未量过，「单级组合深度」这个口径是 2026-09-15 才补进
`verify.md` 的。

契约条款：`openspec/specs/formal-equivalence/spec.md`
「组合深度的测量必须在触发器边界上断开」。


---

## P-11. 用脚本统计「依赖关系」时只看直接引用，两个方向的错会互相抵消

**症状**：统计出来的数字与结论看起来完全自洽，而结论是错的。

**实例**（2026-09-20，本仓 内部#46 的 2.6）：要统计 `generate` 块内哪些
`localparam` 依赖 genvar（依赖的只能内联，不依赖的可以上提到模块作用域）。
第一版脚本对每个 `localparam` 的定义式做 `re.findall(r"\b[A-Za-z_]\w*\b")`，
与本文件声明的 genvar 名求交集。结论：**36 处全部依赖 genvar，一处都上提不了。**

这个结论进了 design.md 的 F2，并据此向用户提了「全部内联 vs 只改使用点少的」
的选择题 —— 也就是说，**一个错误的前提进入了需要用户拍板的决策**。

**成因**：`localparam` 会互相引用，依赖是**传递**的：

```
localparam UP   = (lv < L);          // 直接引用 lv   -> 判对
localparam K    = UP ? lv : (…);     // 直接引用 lv   -> 判对
localparam STEP = 1 << K;            // 只引用 K      -> 判成「可上提」❌
localparam SEL_KW = SEL_K;           // 只引用 SEL_K  -> 判成「可上提」✓ 但理由是错的
```

`STEP` 借道 `K` 依赖 `lv`，被漏判；`SEL_KW` 真的不依赖，被正确判出但淹没在
噪声里。两个方向的错各有几处，**总数仍然是 36**，而「全部依赖」这个结论
与「一处都上提不了」这个后果互相印证，看不出破绽。

**判据**：取传递闭包，不要取直接引用。种子是 genvar 名，反复扩张到不动点：

```python
tainted = set(genvar_names)
for _ in range(10):                      # localparam 链不会深到哪里去
    for name, body in decls:
        if name in tainted: continue
        if set(re.findall(r"\b[A-Za-z_]\w*\b", body)) & tainted:
            tainted.add(name)
```

重算结果：**32 处依赖，4 处不依赖**（一个已删模块里的 4 个
localparam，上面例子里的 `SEL_KW` 是其中之一）。

**适用范围**：凡是用脚本统计 `x = f(y)` 形定义链上的依赖关系 —— RTL 的
`localparam` / `parameter`，Python 的模块导入图，Make 的目标依赖。
**「直接引用」不是「依赖」的同义词，而按前者统计出来的数字读起来一样自洽。**
更一般的一条：一个统计口径给出的总数对得上、结论也自洽，不构成口径正确的证据；
要证的是口径本身，不是它的输出好不好看。

来源：内部#46。

## P-12. `read_verilog -defer` 会改变综合结果 —— 它不是一个「只影响解析时机」的开关

**症状**：同一份源文件、同一组参数、同一份 liberty、同一条 yosys 脚本，
只给 `read_verilog` 加上 `-defer`，面积就变了，且**确定性可复现**。

**实例**（2026-09-20，本仓 内部#50 的修法选型）：

| 读入集合 | `-defer` | 已删的地址流水设计面积（µm²） |
|---|---|---|
| 目录里全部 7 份 | 否 | 69.4737 |
| 依赖闭包 4 份 | 否 | **69.6924** |
| 依赖闭包 4 份 | 是 | **69.7361** |

两个自变量各自都动了数字：读入集合 +0.31%，`-defer` 再 +0.063%。
连跑两次逐位相同，网表逐字节不同。已删的解压流水设计同向：393.3101 → 394.3307。

**判据命令**：

```bash
# 同一组源文件跑两遍，只差 -defer，比面积与网表字节
yosys -q -s without_defer.ys && cp netlist.v /tmp/a.v && cp stats.json /tmp/a.json
yosys -q -s with_defer.ys    && cp netlist.v /tmp/b.v && cp stats.json /tmp/b.json
cmp /tmp/a.v /tmp/b.v ; grep -o '"area":[^,]*' /tmp/a.json /tmp/b.json
```

**为什么会踩到**：`-defer` 的用途是「参数化模块先别 elaborate，等被例化时再说」。
这听上去纯属解析阶段的事，于是很容易被当成一个安全的开关顺手加上 ——
本仓差点就这么干了：按「本次参数的依赖闭包」取源文件时，yosys 会在
**读进来但这次用不到的模块的默认参数形态**上失败
（`ERROR: Module \ripple_adder referenced in module \adder_core ... is not part
of the design`），而 `-defer` 正好绕开它。绕是绕开了，代价是给每一条记录
叠了一个会动数字的因子。

**修复/规避**：不要为了绕过 elaborate 失败而加 `-defer`。本仓的选择是让读入
集合取**该顶层在全部声明取值下的并集**（`flow/synth/synth.py::source_files`）——
并集里必定含有每个模块默认参数形态所需要的一切，于是根本不会触发那个失败。

**边界**：这条说的不是「`-defer` 有 bug」，而是「它属于会改变 PPA 的流程改动」。
真要用它，就当成换代处理：`flow/synth/synth.py` 在 `METRIC_MODULES` 里，
改了就换指纹，上一代记录不可与之横向比较（红线 4）。

---

## P-13. 跨全仓的文本改写会静默换代 —— 因为工具脚本是以**字符串**存在代码里的

**症状**：一次「只改注释和标识符」的批量改写，`git diff --stat` 上看不出碰过
测量代码，重跑出来的记录却换了指纹，于是新旧记录不能自动配对。

**实例**（2026-09-21，本仓 内部#46 的 2.1）：
把 30 个模块名改成大写。规划时核过「`METRIC_MODULES` 里一个文件都不会被改到」，
结论是不换代。实际换了：`sha256:5792722d…` → `sha256:08e2aa1d…`。

根因是 `flow/sta/run_sta.py` 把 OpenSTA 的 tcl 整段存成一个**普通字符串字面量**
`STA_TCL_TEMPLATE`，改名脚本把模板内部三行**注释**里的 `adder32` 一起改了
（「实测 adder32 上差 0.196 ns」）。于是两项事实同时变：
`sta_recipe_sha256`（直接哈希模板文本）与 `metrics_code_sha256`
（AST 哈希 —— 字符串字面量算内容，不是 docstring）。

逐文件核对 AST 哈希：七个 `METRIC_MODULES` 里**只有 `run_sta.py` 变了**，
另外六个改的全是注释与 docstring，AST 哈希逐字未变 ——
`flow_fingerprint.py` 的 `_strip_docstrings` 完全按设计工作。
**漏的不是它：一段以字符串形式内嵌的工具脚本，它的注释就是内容。**

**判据命令**（改写之前记下，改写之后再跑一次，比字符串）：

```bash
source ~/tools/env.sh
.venv/bin/python3 -c "
from flow.flow_fingerprint import flow_fingerprint, metrics_code_sha256, sta_recipe_sha256, synth_recipe_sha256
import os
lib = os.path.expanduser('~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib')
print('fingerprint ', flow_fingerprint(lib)['fingerprint'])
print('metrics_code', metrics_code_sha256())
print('sta_recipe  ', sta_recipe_sha256())
print('synth_recipe', synth_recipe_sha256())"
```

变了就是换代，**不管 diff 看起来多无害**。哪一项变了直接指向原因：
`sta_recipe` / `synth_recipe` 是模板文本，`metrics_code` 是那七个文件的 AST。

**修不修**：不修。`flow_fingerprint.py` 的取舍写得很清楚 ——「宁可让『给
abc.constr 加一行』也分出一代，太粗比太细危险得多」。把模板注释排除出哈希
需要一个「tcl 注释」的词法器，而它自己的 bug 会让真正的改动漏网；
何况改口径本身还要再换一代。**正确的处置是改写之前跑一遍上面那条命令，
心里有数**，并在换代时按 `docs/data-credibility.md` 记账（那次记在 D-20）。

### 另一半：同一个「改注释」，在**证明器**那边代价差四个数量级

本仓有两套哈希，对注释的态度**正好相反**，而代码里没有任何地方把它们并排写出来：

| | 哈希什么 | 改一行注释的后果 | 为什么这么定 |
|---|---|---|---|
| `flow_fingerprint.metrics_code_sha256()` | 七个 `METRIC_MODULES` 的 **AST**（`_strip_docstrings` 先剥掉 docstring） | **不换代**，一条记录都不用重跑 | 不能为了一句注释重跑 120 条实验 |
| `flow/equiv/run_equiv.py` 的 `RECIPE_FILES` | 它**整份文件的字节** | **全部账目失效**（2026-09-25 起 32 条） | 覆盖边界（「证的是组合等价」「带寄存器的顶层不在射程内」）就写在注释里，改了正是最该有人重看一遍的时候 |

两条取舍各自都对，合起来的效果却是：**同一个动作在两个子系统里代价差四个
数量级** —— 一边是 0，一边是一轮全量重证（2026-09-21 实测：串行 5976 秒，
`-j 9` 也要 1179 秒）。

⚠️ 还有第三条路，它连「改了代码」都不需要：**账目也键被证 RTL 的字节**。
所以改 `designs/*/rtl/` 下任何一份被证的源文件 —— 哪怕只是删掉一个属性、
改一行注释 —— 都会让相关账目失效，而 `flow_fingerprint` 完全不动
（RTL 是被测对象，不是流程，所以改 RTL **不换代**）。2026-09-21 实撞：
18 份 RTL 删 `keep_hierarchy` 属性，`run_equiv.py` 一个字节没动，
**20 条账目失效 15 条**。

**判据命令**（动手之前记下，动完再跑一次，比字符串）：

```bash
source ~/tools/env.sh
.venv/bin/python3 -c "
import sys; sys.path.insert(0, '.')
from flow.flow_fingerprint import metrics_code_sha256
from flow.equiv.run_equiv import recipe_sha256, stale_entries, PAIRS
print('metrics_code', metrics_code_sha256())
print('equiv_recipe', recipe_sha256())
for d in sorted(PAIRS):
    print('失效账目', d, len(stale_entries(d)))"
```

三个数各自指向不同的代价：

- `metrics_code` 变了 → **换代**，要全量重跑实验（几十分钟到一小时）。
- `equiv_recipe` 变了 → **全部账目失效**（2026-09-25 起 32 条），要全量重证（`-j 9` 约 20 分钟）。
- 两个都没变而「失效账目」非 0 → 改的是**被证的 RTL**，只有相关设计要重证。

**都没变而你确实改了东西**，说明改的是这三套哈希都不看的部分
（`scripts/` 下的工具、文档、测试）—— 那是好消息，但要确认它真的是。

---

## P-14. 「为将来准备的护栏」不能用产线数字来验 —— 它不承重，所以拆了也零差异

**症状**：一次改动号称「只是换了个施加方式」，产线上逐字段零差异，于是判定搬家成功。
可它其实**根本没施加上**，只是当前流程恰好不需要它，所以两边都一样。

**实例**（2026-09-21，本仓 内部#46 的 2.2）：
`keep_hierarchy` 从 RTL 搬进综合流程。第一版实现把 `setattr -mod -set keep_hierarchy 1`
放在 `hierarchy` **之前**，产线九个组合零差异 —— 但把声明**整个清空**再跑，
九个组合的 `cell_count` / `area_um2` 也**一个都不变**。因为综合脚本不加 `-flatten`，
模块边界本来就在（P-3 的 ⚠️ 段），这个属性在产线上不承重。
**任何实现，包括完全不施加，都能拿到零差异。**

加了 `-flatten` 的对照当场分出四种结果（`ADDER32 W=64 SKLANSKY`）：

| 写法 | cells | area µm² |
|---|---|---|
| RTL 里写 `(* keep_hierarchy *)`（搬家之前） | 647 | 64.41444 |
| `hierarchy` **之后** `setattr`（最终实现） | 647 | 64.41444 |
| `hierarchy` **之前** `setattr`（第一版，❌） | 650 | 64.54566 |
| 完全不标 | 546 | 32.90706 |

**根因（顺带是 yosys 的一个陷阱）**：`hierarchy` 把参数化模块换成 `$paramod…`
派生副本，并把泛型模块当 unused 删掉 —— **在它之前挂的属性跟着一起没掉**。
10 个模块里只有无参数的 `PREFIX_NODE` 幸存。而 RTL 里的属性不受影响，因为那是 AST
的一部分。派生副本的名字是 `$paramod$<hash>\<名字>` 或 `$paramod\<名字>\WIDTH=…`，
所以施加必须用两头带 `*` 的含式模式；`hierarchy` 之后顶层自己也被改名，
`synth -top <原名>` 会报 `Module not found`，所以 `synth` 不带 `-top`。
全程 yosys 退出 0，`select -assert-any` 也全部命中（那时泛型模块还在）。

**判据**：**在这个东西唯一起作用的条件下做对照**，不要在它不承重的产线上验。
对 `keep_hierarchy` 就是加 `-flatten` 跑一次 A/B；更一般地：
先问「如果这个护栏根本没装上，产线数字会变吗」，答案是「不会」时，
产线数字就没有判别力，零差异是**平凡的**，必须另找判据。

**适用面**：本仓还有别的「为将来准备」的东西 —— `abc.constr` 的边界条件在某些设计上
也可能不承重。同样的问法对它们都成立。

---

## P-15. 新增一个 building block 时忘了写进保层级声明 —— 没有任何东西会失败

> 2026-10-05 起保层级不再强制（内部#216）。这一条只对**选择**保层级、要比结构的设计有用：声明了一部分、漏了新加的那个，
> 一样不会有任何东西失败。

**症状**：加了一个新的 building block 之后，架构对比的差异**突然变小**
（几种结构的 area/delay 开始互相靠拢）。综合正常、护栏正常、测试正常。

**成因**：2026-09-21 起「哪些模块要保住层级」由 `params.yaml` 声明
（`tops:<顶层>:synth:keep_hierarchy:`），与 RTL 分了家。流程只校验**一个方向**
——「声明了但没命中」当场失败；反过来「该声明却没声明」它查不出来，
因为流程不认识任何具体设计，无从判断哪个模块像 building block
（`openspec/specs/flow-parameterization/spec.md`）。
RTL 里没有属性是**合规**的，所以秒级护栏也不会响。

**这是一个已知缺口，不假装解决。** 契约里把它写成约定：
`openspec/specs/rtl-structure-authority/spec.md` 的「新增一个需要保住层级的模块」
—— 新 building block MUST 出现在它所属被测顶层的声明里，
MUST NOT 用「在 RTL 里加属性」绕过去。

**判据命令**（加了新模块之后跑一遍，看新名字在不在「未声明」里）：

```bash
source ~/tools/env.sh
.venv/bin/python3 -c "
import re, sys
from flow.paths import keep_hierarchy_modules
from flow.synth.synth import source_files
for top in sys.argv[1:]:
    decl = set(keep_hierarchy_modules(top))
    mods = set()
    for f in source_files(top):
        mods |= set(re.findall(r'^\s*module\s+([A-Za-z_][\w\$]*)', f.read_text(), re.M))
    print(top, '未声明的模块:', sorted(mods - decl - {top}))
" ADDER32 CBB_LZD CBB_BIN2ONEHOT CBB_ONEHOT2BIN   # 声明了 keep_hierarchy 的顶层：git grep -l "keep_hierarchy:" -- '*/params.yaml' '*/*/params.yaml'
```

基线（2026-10-15 在上面四个顶层上复跑，2026-09-21 那次结论相同）：**只有 `ADDER32` 的 `FLAT_LOOKAHEAD` 未声明**，其余为空。
`FLAT_LOOKAHEAD` 是 `CLA_ADDER` 内部把进位展开成 AND-OR 树的那一层，
它**本来就该让 ABC 自由优化**（被比较的结构是 `CLA_ADDER` 这一层，不是它）。
输出里多出任何别的名字，都要当场判断它是不是被比较的结构之一。
⚠️ 判据给的是**候选**，不是答案 —— 哪些模块必须保住层级是实测出来的
（`designs/adder32/rtl/prefix_node.v` 记着 2026-09-08 那次：标在「网络」那一层不够，
必须标到算子上），列表只负责让你不漏看。

---

## P-16. 拿 `experiments.jsonl` 里的一条记录当综合基线，会把加压搜索的结果当成不加压的

**症状**：改了流程代码之后跑一次普通综合，与记录里同一组参数的那条比，
`cell_count` / `area_um2` 差出百分之几，于是判定「改动引入了回归」。
查半天读入集合、liberty、yosys 版本、`git diff`，全都干净。

**成因**：记录里的那条**不是**普通综合的产物。`flow/synth/search.py` 的加压搜索
会在一组延时目标上各综合一次、取最好的那一档写进记录，所以它的
`synth.delay_target_ps` 是一个具体皮秒数、`sta.fmax_method` 是 `"search:abc-D"`；
而手边随手跑的 `run_synth` 不加压，`delay_target_ps` 是 `null`、
`fmax_method` 是 `"analytic"`。**两者本来就不该相等**，差的是加压，不是回归
（`docs/data-credibility.md` 的 D-7 是同一件事的读法面）。

**判据**：把记录当基线之前，先看它这两个字段：

```bash
.venv/bin/python3 -c "
from flow import records
for r in records.load():
    if r['experiment_id'] == '<要当基线的那条>':
        print(r['synth'].get('delay_target_ps'), r['sta'].get('fmax_method'))"
```

**决定性的是 `delay_target_ps`，不是 `fmax_method`**：
非 `null` 说明记录里的网表产自**加压**那一档，不能与不加压的 `run_synth` 比。
`fmax_method` 是 `search:abc-D` 但 `delay_target_ps` 为 `null` 的记录**可以比** ——
那说明搜索里赢的就是不加压那一档（`flow/synth/search.py::pick_best` 平手取不加压），
记录下来的 `cell_count` / `area_um2` 正是不加压的那一份。
⚠️ 这个组合很常见，别看见 `search:abc-D` 就以为不能比。

**正确做法**：A/B 要跑在**同一条代码路径**上。改动前后各跑一次同样的入口
（`git stash push flow/` 切回旧代码跑一次，再 `git stash pop` 跑一次），
比这两次；不要拿历史记录当其中一侧。


---

## P-17. pre-push 护栏跑在**另一个环境**里，工具链不在它的 PATH 上

**症状**：`git push` 被 pre-push 挡下来，报 `iverilog 不在 PATH：RTL elaborate
一个组合都没能检查`。而同一个终端里手跑 `./scripts/fast_check.sh` 十一项全过。

**成因不是「hook 不继承环境」** —— 它继承的恰恰是**调用 `git push` 的那个进程**的
环境。问题在于本仓的工具链要**显式** `source ~/tools/env.sh`（yosys / iverilog /
verilator 在 `~/tools/oss-cad-suite`，OpenSTA 在 `~/tools/OpenSTA-src/build`），
而 `~/.zshrc` 里**只** source 了 `~/synopsys_env.sh`，没有 source 它。
于是：

- 手跑 `fast_check.sh` 之前你通常已经 source 过了 → 十一项全过；
- 从一个**没 source 过**的 shell 发 `git push`（新开的终端、脚本、
  非交互 shell、编辑器/IDE 里的 git、agent 的每一次命令调用）→ hook 里
  `command -v iverilog` 是空的 → elaborate 一个组合都没跑。

同一台机器、同一份代码、同一个 hook，**结果取决于发 push 的那个 shell 的历史**。

**修复**（发 push 之前在**同一个 shell 里** source）：

```bash
source ~/tools/env.sh && git push
```

⚠️ **不要用那两条逃生口来通过 push**，`fast_check.sh` 给的另外两条是：

```
FAST_CHECK_ALLOW_MISSING_TOOLS=1 ./scripts/fast_check.sh   # 显式降级
git push --no-verify                                        # 绕过 hook
```

它们的用途是「我知道这台机器上没有 iverilog，而且我接受这次不检查 RTL」，
**不是**「PATH 没设好」的解法。在本机用它们等于把
`guardrail-scope` 的第一条（「护栏的成功退出必须意味着它声明的检查全部执行
并通过」）当场废掉 —— 而且废得看不出来：`--no-verify` 连一行输出都没有。

**为什么这条值得记**：护栏这次**报对了** —— 它说的是「未执行」而不是「通过」，
`FAIL` 那一行明写「一个组合都没能检查」，覆盖摘要里那一项也列在「未执行」下。
这正是 `guardrail-scope` 那条要求存在的理由，而它能报对**是因为有人特意这么写的**：
`scripts/fast_check.sh` 默认在缺工具时**失败**，只有显式给
`FAST_CHECK_ALLOW_MISSING_TOOLS=1` 才降级成警告。

**换成常见的写法就会静默**：绝大多数 `fast_check` 式脚本遇到
`command -v <tool>` 为空时会 `echo "skipping"` 然后 `continue`，退出 0。
那样每一次从没 source 过的 shell 发的 push 都是绿的，而 RTL **一个组合都没
elaborate 过** —— 正好是本文件开头那句「跑通了但数字不可信」的护栏版本。
所以这一条的教训不在「记得 source」，在**「护栏缺了依赖时默认该失败，
降级必须是显式的、并且写在覆盖摘要里」**。

---

## P-18. 护栏在 bash 3.2 上中途夭折，**退出码却是 0**（2026-09-24，mac mini）

**症状**：`source ~/tools/env.sh` 之后跑 `./scripts/fast_check.sh`，只打出一行
`ok    python compileall`，接着两行 bash 报错，然后就结束了 —— 没有覆盖摘要、
没有 FAIL、**`echo $?` 是 0**：

```
ok    python compileall (flow/, scripts/)
./scripts/fast_check.sh: line 105: declare: -A: invalid option
./scripts/fast_check.sh: line 113: ADDER32: unbound variable
```

十一项检查跑了一项，退出码与「十一项全过」一模一样。

**判据**：

```bash
bash --version | head -1          # macOS 自带的是 3.2.57，不是 4/5
source ~/tools/env.sh && ./scripts/fast_check.sh | wc -l   # 只有个位数行 = 夭折了
grep -n 'declare -A' scripts/fast_check.sh                 # 3.2 没有关联数组
```

**成因**是两层叠在一起：

1. `declare -A`（关联数组）是 bash 4 的东西，macOS 自带 `/bin/bash` 是 3.2。
   它在 3.2 上**不是当场报错退出**，而是打一句 `invalid option` 接着跑，
   到下一行 `${top_fail[$top]}` 把顶层名当算术展开、撞上 `set -u` 才夭折。
2. 那次夭折发生在 `while ... done <<< "$combos"` 里，而 **bash 3.2 在这条路径上
   把退出状态丢成 0**。最小复现（与脚本同形）：

```bash
/bin/bash -c 'set -u; declare -A m=() 2>/dev/null
  while read -r l; do : "${m[$l]:=0}"; done <<< "X"; echo 到不了这里'; echo $?
# -> unbound variable，然后 0
```

**为什么一直没人看见**：要同时满足两个条件才现形 —— 机器上**有** iverilog
（没有的话在它之前就按 P-17 报 FAIL 退出了）**且** bash < 4。写这段代码的机器
bash 是 4/5，这台机器平时又因为没 source `env.sh` 而走 P-17 那条路。
`tests/test_fast_check.py` 里那二十条行为用例全带 `@needs_iverilog`，
在没 iverilog 的机器上整批跳过 —— 静默地。

**修复**（2026-09-24）：

- 逐顶层统计改成三条平行的**下标**数组 + 线性查找（`_top_slot`），不用关联数组；
- 加一个**完成哨兵**：`finished=0` + `trap ... EXIT`，没跑到末尾就按 90 退出。
  哨兵**不读 `$?`** —— bash 3.2 夭折之后连 `$?` 都取不可靠（trap 里写
  `rc=$?` 会自己再炸一次 unbound variable，实测）；
- 两条回归用例**故意不带** `@needs_iverilog`：一条扫源码里不许再出现
  `declare -A`（整行注释不算），一条注入一句必然夭折的语句、验证退出码不是 0。

**教训**：护栏的「退出 0」不能由 shell 的退出状态担保 —— 夭折路径上它不可靠。
要由「**跑到了末尾**」这件事本身担保。这与 P-17 是同一条契约
（`openspec/specs/guardrail-scope/spec.md`：护栏的成功退出必须意味着它声明的
检查全部执行并通过）的两面：P-17 是**缺依赖**时不许静默通过，这一条是
**自己崩了**时不许静默通过。P-17 那次护栏报对了，这一次没有。

## P-19. 在设计根下跑 pytest 留下 `.pytest_cache`，推送被「设计根下只有源文件」拒（2026-10-05，验证会话）

**症状**：在 `designs/<根>/tb/` 之类的目录里直接跑 pytest，之后推送时 pre-push 的 fast_check 报
「设计根下只有源文件」失败，点名一个 `.pytest_cache/` 目录。代码本身没问题，拒推的是 pytest 自己留下的缓存。

**判据**：

```bash
find designs cbb -name .pytest_cache -type d    # 有输出就会被拒
```

**修复**：从仓库根跑 pytest，或者加 `-p no:cacheprovider`；已经留下的，推送前删掉自己 worktree 里的那几个目录。
`.gitignore` 忽略它没用：这项检查看的是工作区里的文件，不是 git 跟踪的文件。

## P-20. `synth -hieropt`（`opt_hier`）碰上例化里的空输出连接 `.y( )` 就报错退出（2026-10-05，yosys 0.69+24，内部#205）

**症状**：跨层次传常数的综合在 `OPT_HIER` 这一步退出：

```
ERROR: Port y connected on instance u1 not found in module $paramod\sub\W=… or width is not matching
```

**成因**（2026-10-05 用 report 的最小复现核实）：RTL 里写成 `.y( )` 的输出，在 yosys 里是例化上的一条**空连接**
（RTLIL 里写作 `connect \y { }`）。`opt_hier` 把没人用的输出端口从模块里删掉之后，这条空连接还挂在例化上，
于是报「端口不存在」。与参数无关，**也与「多个例化共用一个模块」无关**：`uniquify` 之后照样报。源码里干脆不写
这个端口（省略连接）就不报。正式口径不用 `-hieropt`，不受影响。

**判据**：

```bash
yosys -q -p "read_verilog <文件>; hierarchy -top <顶层>; proc; write_rtlil a.il" && grep -c 'connect \\[^ ]* { }' a.il   # > 0 就会撞
```

**绕法**：在 `opt_hier` 之前删掉例化里的空连接，不改 RTL。做法是 `write_rtlil` 导出，删掉 cell 块里形如 `connect \<端口> { }`
的行，再 `read_rtlil` 读回来。删的是「什么都没接」的连接，语义不变（2026-10-05 在复现上与展平综合做 SAT 等价核对通过）。

## P-21. 保层级综合时 abc 逐模块映射，子模块输出在父模块里按 0 到达，跨边界的重构会被撤销（2026-10-05，design_sub，内部#168 / 内部#231）

**症状**：把一段逻辑从父模块挪进子模块（或反过来），想把关键路径拆短。单独量子模块，级数下降了；回到顶层量，级数没变，甚至回到原值。
实例：`c5071794` 把 RDAT 的 poison 并入改到子模块里，顶层仍是 31 级；改成寄存掩码之后才收住（内部#168）。

**成因**：正式口径保层级（`flow/synth/synth.py` 文件头，P-3），abc 一次只映射一个模块。它在父模块里看不到子模块输出的真实到达时间，
按 0 到达处理，所以按时序做的结构选择在边界两侧各算各的。跨边界「挪一段组合逻辑」不改变路径上的总级数。

**判据**：改前改后都在**顶层**量，单独量子模块的数字不作数：

```bash
make -f flow/Makefile depth DESIGN=<顶层> PARAMS="…" BUDGET=<预算>   # 不带 MODULE=，看路径的起止点
```

子模块单独量下降、顶层同一终点不降，就是撞上了这一条。

**修复**：要拆短跨边界的路径，就在路径上加寄存器（掩码 / 选择信号提前一拍算好），不靠在模块之间挪组合逻辑。

## P-22. yosys `opt_merge` 会合并 D、时钟、复位都相同的寄存器，复制寄存器分扇出白做（2026-10-05，design_sub，内部#231）

**症状**：为了分扇出，把一个寄存器复制成几份，RTL 里各驱一部分负载。综合后网表里只剩一份，扇出和延时都没变，也没有任何告警。

**成因**：`synth` 里的 `opt_merge` 把输入完全相同的单元并成一个。寄存器只要 D、时钟、复位（含复位值）都相同就会被合并。
给 reg 加 `(* keep *)` **挡不住**：2026-10-18 在 yosys 0.69+24 上实测，两个相同寄存器加了 `(* keep *)`，综合后仍只剩 1 个。

**判据**：看综合后的触发器个数是否等于 RTL 里复制的份数。最小复现（`dup` 是两个相同寄存器，`dup2` 把其中一个的复位值改成 1、D 改成 `~d`）：

```bash
yosys -p "read_verilog dup.v; synth -top dup; select -count t:*DFF*"     # 1 objects.  （加 (* keep *) 也是 1）
yosys -p "read_verilog dup2.v; synth -top dup2; select -count t:*DFF*"   # 2 objects.
```

在真实设计上，对复制的寄存器名 `select -count` 一下，少于份数就是被合并了。

**修复**：让几份寄存器在 yosys 看来不一样：复位值不同，或者 D 取反存、输出再取反。只靠改名或加 `keep` 不行。

## P-23. 形式等价：不带复位的寄存器证不出复位那一拍；k-induction 证不了长程协议不变量（2026-10-05，design_sub，内部#168 / 内部#231）

**症状**：两份 RTL 做 `equiv_make; equiv_simple; equiv_induct`，`equiv_status` 留下未证的点：

- 一类落在**不带复位的寄存器**上。改动本身没碰它们，原因是复位那一拍两侧的初值都是未定的 X。
- 另一类依赖跨很多拍的协议前提，比如 RDAT「回送期间条目不被写」。k-induction 的步数够不到，证不出来。

**判据**：`equiv_status` 列出的未证点，逐个看属于哪一类：

```bash
yosys -p "…; equiv_make gold gate eq; hierarchy -top eq; async2sync; equiv_simple -seq 5; equiv_induct -seq 5; equiv_status"
```

未证点都是无复位寄存器，就是第一类。落在协议相关的条目 / 状态寄存器上，就是第二类。

**修复**：

- 第一类：两侧的 `rst_n` 都接成常 1 再证，让比较从复位之后开始。或者只把这些点交给同种子仿真比较（TB DONE 行的 `sig=`）。
- 第二类：**不要**把「k-induction 证不出、但我认为成立」的改法交出去。改成不依赖该前提的写法，再证。实例：`8a2fde6` 因此没有交付，改成 `98ca3025`，回送拍改从条目的下一拍值取。
