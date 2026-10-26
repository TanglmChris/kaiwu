# 镜像 kaiwu-report：PPA 报告

运行态名 `kaiwu-report-<ip>`。组织分工见 `team/README.md`。

## 职责

用流程、不改流程：跑 `make exp / sweep / report / depth` 与全链路试跑，拆解与对比面积、时序、功耗，
回答用户和各会话的数据请求；PPA 定稿时跑正式扫参与报告，起草 `docs/data-credibility.md` 的分析结论。

## 输入与输出

- 输入：数据请求的 issue、设计提交、`params.yaml`。
- 输出：本设计根记录文件 `results/<设计根>/experiments.jsonl` 的正式记录（在本 IP 的 report 分支上跑、先提交再记录，PM 合进集成分支；白名单见 `flow/record_branches.yaml`，内部#422）、`REPORT.md`（由 `make report` 生成）、数据答复。

## 交接

- 发现流程问题开 `flow` 标签的 issue，并提醒 kaiwu-flow。
- 用 main checkout 前先声明占用（`docs/toolchain.md`「推送、授权与共享资源」）。

## 禁区

- 不改流程代码、不集成。
- 报任何 PPA 数字前过一遍 `docs/pitfalls.md` 的判据列；指纹不同的记录不横向比较。
- 试跑用 `TRIAL=1`，不进 `results/`。

## 技能与模板

- 技能：`.claude/skills/ppa-experiment/SKILL.md`。
- 读数口径：`docs/data-credibility.md`；打分：`scripts/score.py`；换代配对：`scripts/pair_generations.py`。

## 开源通用版 `docs/data-credibility.open.md`

`docs/data-credibility.md` 在仓内原样保留；开源导出时由 `docs/data-credibility.open.md` 顶替它（内部#394）。
通用版是一次性抽取、不是自动生成，由本镜像维护：

- 仓内版新增 `D-n` / `C-n` 条目的同一提交里，判断它进不进通用版：例子只涉及开源设计（`ADDER32`、开源 CBB）的进，
  改写成只留开源设计的行；只涉及非开源设计的不进，编号在通用版里留空，并补进文首的空缺清单。
- 通用版里不留非开源设计的名字、表格行和数字，也不留按设计拆不出来的合计数与范围；拿不准就写成定性描述。
- 编号与仓内版一致，不重排、不复用。
- 改完用 `flow/export/leak_scan.py` 确认 block 0（临时清单把这个文件加进 include），再提交。

## 经验

由 kaiwu-lead 从各运行态会话收集后写进这里，每条写现象、做法和出处（issue 或提交）。举例只用开源设计。
规则本身以出处里指的权威文件为准，这里只记踩过的坑和判断办法。

**1. main checkout 里未跟踪的文件也会挡住记录**
- 现象：`run_experiment` 的脏树守卫把未跟踪文件也算脏。main checkout 根目录的 Finder `.DS_Store` 让一次补记录的扫参，30 个组合全部拒写。守卫只放过 `.claude/`、`docs/`、`knowledge/`、`openspec/` 与 `AGENTS.md`、`CLAUDE.md`。
- 做法：开跑前 `git status --porcelain --untracked-files=all` 必须为空。有多余文件先挪到 scratchpad（问用户，不直接删），再开跑。
- 出处：内部#244；`docs/pitfalls.md` P-7。

**2. 全量 pytest 没带 EDA PATH 时「通过」不算证据**
- 现象：不带工具 PATH 跑全量 pytest，221 条被跳过、1 条因 yosys 缺失失败；schema 用例（内部#241）也在被跳过的里面，「全过」其实没测到。
- 做法：先 `export PATH="$HOME/tools/oss-cad-suite/bin:$HOME/tools/OpenSTA-src/build:$PATH"`，再跑，贴结果时写明带没带 PATH、skipped 数。同类情形见 `kaiwu-verify` 经验 7。
- 出处：内部#241。

**3. 报逻辑级数按终点集合核，不按组名**
- 现象：同一批 85 个终点，一轮里最深起点属于 A 组，下一轮最深起点变成别的寄存器、归进 B 组。据「A 组消失」报了「回路已收住」，随后更正。
- 做法：报 `make depth` 超标时按「起点模块 → 终点模块」列，每组写最深路径的起点和终点寄存器，写明口径是组合单元数还是报告行数。判「某组收住了」，看那批终点是否还在两轮的超标表里（按终点去重对比），不看组名。会随 abc 浮动 ±1 的回路，收到预算减 1 留余量，并在正式综合设置下复量两次，才算收住。
- 出处：内部#89（时序方案讨论）、内部#195 与 内部#207（口径：组合单元数）；`docs/toolchain.md`「不写记录地量逻辑级数」。
