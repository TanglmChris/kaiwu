# 工具链：PDK（ASAP7）、合并 liberty、换 PDK

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

## ASAP7 的几个事实

- 版图是按 4 倍尺度画的：**LEF 里所有尺寸要除以 4** 才是实际物理尺寸；
  liberty（`.lib`）里的时序/功耗数字不受这个缩放影响，直接用。
- 有 SLVT / LVT / RVT 三种阈值电压的 cell，还有 TT / SS / FF 三个 corner。
- **`asap7_snps` 不是本仓库里的目录**（2026-09-04 核实）：README 第 46 行的
  "Synopsys Enablement" 一节只是给了个外链，指向第三方仓库
  `github.com/snishizawa/asap7_snps`。接商业流时需要单独 clone，不是 submodule。
- **DC 要的是 `.db`，不是 `.lib`**：本地目前一个 `.db` 都没有。`.db` 由 `lc_shell`
  （Library Compiler）从 `.lib` 编译而来，所以商业流的第一步是拿
  `~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib` 过一遍 `lc_shell`。

### 哪些子模块拉了、哪些没拉

- 完整 clone：`asap7_pdk_r1p7`（工艺文件）、`asap7_sram_0p0`（SRAM）。
- **`asap7sc6t_26` 和 `asap7sc7p5t_27` 没有拉**：这两个仓库带了大量 GDS，
  哪怕 `--depth 1` 单次 commit 也有好几 GB，走代理慢到不现实。
- `asap7sc7p5t_28`（README 里推荐的主力 7.5-track 库）用
  `git clone --filter=blob:none --sparse` 只拉了 `LIB` 目录
  （NLDM+CCS 两种时序模型，全部 Vt/corner，约几百 MB），
  **2026-09-25 本机（mac mini）补拉了 `LEF` / `GDS` / `techlef_misc`**（内部#4，
  `git sparse-checkout add LEF GDS techlef_misc`，HEAD `472f7b3`，共约 13 MB）。
  这台机器的 sparse 集合现在是 `LIB/NLDM` + 这三个 + `Verilog`（见下）；`CDL` / `qrc` 仍没拉。
  - `LEF/asap7sc7p5t_28_{R,L,SL,SRAM}_1x_220121a.lef`（另有 `scaled/` 下的 4x 版与 `IO_cell/`）；
    R 那份 212 个 `MACRO`，比合并库的 202 个 cell 多出的 10 个是纯物理单元
    （`DECAP*` ×6、`FILLER*` ×2、`TAPCELL*` ×2），不是缺时序模型。
  - `GDS/asap7sc7p5t_28_{R,L,SL,SRAM}_220121a.gds`，文件头是合法的 GDSII HEADER 记录
    （不是 LFS 指针）。
  - `techlef_misc/asap7_tech_{1x,4x}_201209.lef`（tech LEF，`DATABASE MICRONS 1000`）
    与 `example_innovus.tcl`。做 P&R 用 1x 还是 4x，见上面「LEF 尺寸要除以 4」那条。
  - **2026-09-27 补拉 `Verilog`**（内部#22 的门级仿真，`git sparse-checkout add Verilog`，同一 HEAD
    `472f7b3`，约 2 MB）：`asap7sc7p5t_{AO,INVBUF,OA,SIMPLE}_<VT>_TT_201020.v` 与
    `asap7sc7p5t_SEQ_<VT>_TT_220101.v`，只有 TT 一个 corner。`flow/sim/gate_sim.py` 读 RVT 那 5 份，
    零延时仿真下 corner 不影响功能。缺哪一类它会点名报错，不会静默少读。
    **2026-10-03 起它们决定功耗**（gate-level-activity，内部#65）：每条实验对胜出网表跑一次零延时
    门级仿真，波形落在 `runs/<id>/sim_gate/`，功耗用这份 VCD 反标；这 5 份的内容哈希进指纹
    （`flow.cell_models_sha256`），换一份就换代。`make sta RUN=<id>` 默认也读 `sim_gate/` 的 VCD；
    但 `make sweep` 算完功耗就删 VCD（内部#172），要单独重跑 STA 的组合，扫参时给 `KEEP_VCD=1`，或者重跑那个组合。

## 合并 liberty

Liberty 是按 cell family（AO / OA / INVBUF / SEQ / SIMPLE）分开的 `.lib.7z`，
一个 Vt+corner 组合要合并这 5 个文件才够综合用。`flow/synth/merge_liberty.py`
干这个：把其余文件里没见过的块并进**基文件**（`--base`）的 `library{}`，
**排列成「全部 `lu_table_template`/`power_lut_template` 在前、全部 `cell` 在后」**。

已经生成好的 RVT/TT 结果在 `~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib`
（2026-09-14 用顺序无关的工具重新生成过；上一份留在同目录的 `.bak`）。

**产物与其余源文件的给出顺序无关**，但**对基文件仍然敏感** —— 基文件的正文是
整段原样保留的（头部、`delay_model`、单位声明、`operating_conditions` 都来自它），
换一个基文件就是另一份 `liberty_sha256`、另一代记录，而这件事不会报错。

所以基文件 **MUST 用 `--base <lib>` 显式给出**，不再是「第一个位置参数」
（2026-09-15，内部#29）。不给 `--base` 的老写法现在当场失败，而不是静默挑一个顶上。
`--canonical-hash` 也因此多了一项 `base`，见下。

同名块在两个**非基**源文件里内容不同时，工具当场报错不产出（挑哪一份取决于
给出顺序，那会把顺序敏感藏起来）。

### 这份合并库是哪一份

`liberty_sha256` 是 `flow` 指纹的事实之一（SS / FF 两角的库另进 `corner_liberty_sha256`，
2026-09-27 起），而合并库不在仓库里、换一个字节就换代（`git_commit` 看不见）。所以哈希记在这：

```
sha256sum ~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib
stat -c '%s' ~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib
```

| 产物 | 字节数 | sha256 | 产出的代 |
|---|---|---|---|
| **当前这份**（2026-09-14 用顺序无关的工具重新生成） | 46152868 | `d9baea75c53f71c4155a7964aa4efd419af078252bca7e638d8dfbab2ebf2a25` | `flow=06f48f38` |
| Linux 旧的（`.bak`） | 46152868 | `a90c2f9030caad579d8eeeece08c931802b9dfa6707fb9233bc588865a48aa2f` | `flow=64bef4e0` |
| Mac 那份 | 46152868 | `5201802dc14c3fa9cefb2272b7bf58654845f500797f81b0c3d86419f306681a` | `flow=64b3c318`（87 条） |

三份的**字节数完全相同、sha256 三个都不同**。原因已经查清：`merge_liberty.py`
逐字保留块内容，2026-09-14 之前它按源文件的**给出顺序**拼接借来的块 —— 同一批
内容换个入参顺序就是另一份哈希。这是**假分代**：语义上同一个库，却被
`liberty_sha256` 判成不可比。

工具已经改成顺序无关（组内按 `(块类型, 块名)` 排序），所以往后同一批源文件
无论怎么给都产出同一份字节。上表前两行就是证据：重新生成前后
`--canonical-hash` 逐字相同，只有 sha256 变了。

### 判定两份合并库是不是只差排列

```
python3 flow/synth/merge_liberty.py --canonical-hash <库.lib>
```

三项各回答一个问题，都对块的排列免疫：

- `canonical` —— **块集合一样吗**。按 `(块类型, 块名)` 排序后哈希全部块。
- `header` —— **头一样吗**。首块之前那段：`delay_model`、单位声明、
  `operating_conditions` 都在那里，同样改变测量结果。
- `base` —— **拿谁当的基文件**。块**之外**的全部文本（`header` 是它的前缀，
  再加块与块之间的属性/注释和收尾）。这一段只来自基文件，ASAP7 的五个家族
  文件各自带着自己的 `library (...)` 名，所以这一项能把基文件认出来。
  它不覆盖基文件自己的块 —— 产物里那些块与借来的块无法区分，要区分就得往
  产物里塞标记，而那会让当前这一代的 `liberty_sha256` 不再能由源文件复现。

当前这份（211 个块：cell 202 / lu_table_template 5 / power_lut_template 4）：

```
canonical 75755e16ebc84119d349bbb5aeacf6bdf27ee7d507b10364966f6a1c421fdff2
header    1f85e7267e5d2ad3c9ad464bdf341064104e1451101c2dac021837b3b49cef8b
base      ccd02d3f8dac04a5c6e84da3c2e9412e0a456af51b3ad52bc50cfe0fb1c35c40
```

三项都相等 → 只差块排列，是假分代；`canonical` 不等 → 库内容真的不同；
只有 `base` 不等 → 换了基文件。
Linux 那两份（`a90c2f90…` 与 `d9baea75…`）实测两值都相等，**证实只差排列**。
Mac 那份 `5201802d…` **2026-09-24 在那台 mac mini 上跑过了**（这份文档换了机器，
那份库现在就在本机 `~/pdk/asap7_merged/` 下），三项与上面记的逐字相同：

```
canonical 75755e16ebc84119d349bbb5aeacf6bdf27ee7d507b10364966f6a1c421fdff2
header    1f85e7267e5d2ad3c9ad464bdf341064104e1451101c2dac021837b3b49cef8b
base      ccd02d3f8dac04a5c6e84da3c2e9412e0a456af51b3ad52bc50cfe0fb1c35c40
```

→ **三份合并库只差块排列，`5201802d…` 与 `d9baea75…` 是同一个库的两种排法**，
`flow=64b3c318` 与它之后各代之间的那一道由 `liberty_sha256` 划出的界，在**库这一项
上**是假分代（内部#28）。

同一天的第二条证据更直接：拿 `~/pdk/asap7_merged/extracted/` 下那五份源文件，
用现在这版顺序无关的 `merge_liberty.py` 在**这台 Mac 上**重新合并一次，产出
`d9baea75…` **逐字节相同** —— 也就是说这台机器随时能把库这一项对回到当前代。

⚠️ 但**「库是假分代」不等于「那些记录可以横向比」**：`flow` 指纹当时有七项事实，
`64b3c318` 那一代与后来各代之间 `yosys` 与 `sim` 也不同（那台 Mac 是
`Yosys 0.69+24`，Linux 那几代是 `0.68+182`）。红线 4 仍然照办，只是理由从
「三项都不同」收窄成「工具版本不同」。

⚠️ 它 **不能当 P-2 的判据**：它复用 `merge_liberty` 自己的切块函数，用被测代码
验证被测代码测不出解析本身的偏差。「定义先于引用」仍归
`tests/test_merge_liberty.py` 那个独立正则管。它的成立条件是**比较两份文件**——
同一份解析器的偏差在两边抵消。

换 Vt/corner（比如 SS 角做 setup 分析）：

```
cd ~/pdk/asap7/asap7sc7p5t_28
uvx py7zr x LIB/NLDM/asap7sc7p5t_AO_<VT>_<CORNER>_nldm_*.lib.7z <解压目录>
# 对 AO/OA/INVBUF/SEQ/SIMPLE 各做一次，然后：
python3 <本仓根>/flow/synth/merge_liberty.py \
    -o <输出.lib> \
    --base <解压出来的 SIMPLE 那份 .lib> \
    <另外 4 个解压出来的 .lib，顺序随意>
```

⚠️ **那个 `*` 在一个组合上会展开成两个文件，而挑哪个取决于 shell 的排序。**
`LIB/NLDM/` 下 61 个 `.lib.7z` 里只有一处重复：

```
asap7sc7p5t_SIMPLE_RVT_FF_nldm_211120.lib.7z   337081 bytes
asap7sc7p5t_SIMPLE_RVT_FF_nldm_250407.lib.7z   237302 bytes
```

偏偏是 **SIMPLE**，也就是**基文件**所在的族 —— 基文件的正文整段原样进产物，
换一份就是另一个 `liberty_sha256`、另一代，而 `merge_liberty.py` **不会报错**
（它只在**非基**源文件之间同名块内容不同时报错）。所以做 RVT/FF 时
**必须写全文件名 `…_250407.lib.7z`，不要用通配符**（`211120` 那份是上游认过的
错误提取，见下），并用 `--canonical-hash` 的 `base` 项核一遍
（RVT_FF 的 `base` = `826f076acbd33e83…`）。
本仓一直只用 TT，没踩到过（本仓 内部#4）。

### 其他 Vt/corner 实测过了（2026-09-20）

以前这一段是推断（「`merge_liberty.py` 修好之后对它们同样成立，但没有实测」）。
现在实测了两组，**两个轴各动一次**：

| | `RVT_SS`（只换 corner） | `SLVT_FF`（Vt 与 corner 都换） | 在用的 `RVT_TT` |
|---|---|---|---|
| 字节数 | 46268613 | 45641201 | 46152868 |
| sha256 | `73725efa3304a9fc…` | `b09b9511bdc1af50…` | `d9baea75c53f71c4…` |
| P-2 判据 | 过 | 过 | 过 |
| OpenSTA 读库告警 | 10 × Warning 1212，模板类 **0** | 同 | 10 × Warning 1212 |
| 顺序无关 | — | 两种顺序产出同一份字节 | 已知 |

**告警分布逐类相同这一点要特意核。** 只看「模板类 0 条」不够 —— 那只证明没触发
P-2；要判断这份库与在用的那份同质，得看它有没有**多出**别的告警。

**2026-09-25 改为 12 份全部常驻**（用户定，推翻 2026-09-21 的「不常驻、要用时现生成」）：
RVT / LVT / SLVT / SRAM × TT / SS / FF，放在 `~/pdk/asap7_merged/asap7sc7p5t_<VT>_<CORNER>.lib`，
各约 46 MB。当时不常驻的理由仍然成立一半 —— 它们是**要跟着 PDK 版本走的派生物**，
没有任何东西会提醒你它过期了；所以下表记着每一份的 sha256，换 PDK 时对着重生成。
**RVT/FF 的基文件用 `SIMPLE_RVT_FF_nldm_250407`，不用 `211120`**：上游
`asap7sc7p5t_28` 的 `66eaebc`（2025-04-30）明写「Corrected three wrongly extracted
SIMPLE_RVT_FF Liberty files」，新增的就是 250407 那份；旧那份没删，所以通配符会同时命中两份。
判据：`211120` 头部是 `nom_temperature : 25; nom_voltage : 0.7`（TT 的工况），而同角的
AO / OA / INVBUF / SEQ 四族都是 `0` / `0.77`；`250407` 与它们一致。两份都是 56 个 cell。
合并产物的工况已核：`nom_temperature : 0; nom_voltage : 0.77`。

每份都按上面的步骤生成并逐项验过：P-2「定义先于引用」0 处、OpenSTA 读出 202 个 cell、
告警只有 10 × Warning 1212（与在用的 `RVT_TT` 逐类相同）。LVT_TT 与 SLVT_FF 两份与
2026-09-20 那次的实测**逐字节相同**（重现性），RVT_SS 同样。

| 库 | 字节数 | sha256 |
|---|---|---|
| `RVT_SS` | 46268613 | `73725efa3304a9fcfe3250a0767a0b01cc2711ec5b6049766808281d0fbf88db` |
| `RVT_FF` | 45456101 | `4f57ddfbcde6248b2bbbc399c332518eb6f76e4488ba204c5537d0be4353a91c` |
| `LVT_TT` | 46049460 | `f7d572409fdb188da396bbed0150b7ab8d07c081de24574420258fa38084b6f6` |
| `LVT_SS` | 46071746 | `e1137cd2cee49d5eac90ff7960a2ec307ea6ed24dc9bb59b5eed7087bd92035a` |
| `LVT_FF` | 45898136 | `f21f3216809469159400c28ebcef4fc60189590a2aa4653dad2a2463c71d8c4c` |
| `SLVT_TT` | 45878315 | `89b546da2e4fd23652173f5df151d37110f6b89c5b957943de95341181c14e37` |
| `SLVT_SS` | 45768570 | `b752e10a6c64c1cc31a4a6955357636fd7f5e0dcfa059eceb4547b481cf118c1` |
| `SLVT_FF` | 45641201 | `b09b9511bdc1af505c0ea648f763efd19e2e7403e5dba7ca8d6713c812bcc093` |
| `SRAM_TT` | 46201357 | `38da69db92c3530d7f12a71e18f96d1546fc1c8310e6386f3a2b3e2d0f64144c` |
| `SRAM_SS` | 46293482 | `7de2795795b899fb98b7c51da533b4776618d72c37ce6ef43675d8a02b171fc7` |
| `SRAM_FF` | 46114080 | `a42f7c764af83ae30ec76bb8a4adfc68a9b4b4d281c4b9bfb6b116f70d8460f9` |

⚠️ 它们**与在用的 `RVT_TT` 不是同一代**（`liberty_sha256` 不同，红线 4）：拿它们
跑出来的数不能与现有记录并排比，只能自成一组。流程默认仍用 `RVT_TT`，换库要显式
`LIBERTY=`。本仓 内部#4。

基文件取 SIMPLE 是现有这份合并库的既成事实（它的 `library` 名就是
`asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120`）。换成别的家族做基不会报错，但会产出
另一个 `liberty_sha256` —— 也就是另一代，与现有记录不可横向比较（红线 4）。
合并完用 `--canonical-hash` 的 `base` 项核一遍用的是哪一份。

⚠️ **模板顺序不是风格问题，排错了会静默丢时序弧** —— 见 `docs/pitfalls.md` 的 P-2。
换库之后先跑那一条的判据再信任何数字。

## 换 PDK 时要一起改的地方

按依赖顺序，漏一处就是静默错数：

1. `flow/synth/abc.constr` 里的 `set_driving_cell` cell 名（P-1）
2. 重新合并 liberty 并跑 `tests/test_merge_liberty.py`（P-2）
3. OpenSTA 的单位口径（P-4）
4. `flow/synth/synth.py` 的 YOSYS_TEMPLATE 里 `dfflibmap -dont_use` 的单元名（内部#176）：要排除的是「同功能里面积不是最小、只因输出极性被选中」的触发器，新库里先看 `dfflibmap` 实际映射成了什么
5. `flow/synth/area.py` 的 `GATE_UNIT_CELL`（折算门数的单元，现为 `NAND2x1_ASAP7_75t_R`，内部#174）：换成新库里 NAND2 X1 那一档，面积由流程从 liberty 现读
6. 换库会改变 `flow` 指纹 → 新旧记录自动分代，**不要跨代比**（P-8）
