## Context

`adder32` 是仓库里唯一的设计。28 条记录只覆盖 9 个唯一参数组合
（`CARRY_STRUCT` × `PIPE_STAGES`，各 3 档），其余是不同 commit 下的重跑。
知识库刚铺完 34 张卡，其中十来个实验被标注为"纯组合、现有 `flow/` 直接能跑"，
但没有一个能在只有 9 个组合的单一设计上做。

本变更打开 `adder32` 上两个已识别的空维度，同时补上 `params.yaml` 缺的一块契约。

- **F1** — （2026-09-07 读 RTL 核实）`carry_select_adder` 已有 `BLOCK` 参数并带
  `(* keep_hierarchy *)`；`adder_core.v:22` 用 `.BLOCK(4)` 写死，顶层不暴露。
  也就是说 BLOCK 维度只差透传，RTL 本身不用改结构。
- **F2** — （2026-09-07 从 `results/experiments.jsonl` 复核）三种结构的流水加速比
  （切 2 段 / 切 3 段）为 RIPPLE 1.948× / 2.699×、CLA 1.574× / 2.233×、
  CSEL 1.492× / 1.810×，**正好是延时渐进阶 O(n) > O(√n) > O(log n) 的倒序**。
- **F3** — （同上）`(面积增幅)/(加速倍数增幅)` 六个数据点全部落在 0.45~0.63。
- **F4** — （2026-09-07 读 RTL/tb 核实）`adder32.v` 顶层端口写死 32 位、
  `localparam WIDTH = 32`；`tb/test_adder32.py` 硬编码 `MASK32` 与 6 组 32 位定向向量。
- **F5** — `openspec/specs/flow-parameterization/spec.md` 现有条款没有任何关于
  "参数是否参与扫参"的表述 —— 这块契约是缺的，不是被违反的。

F2 是本变更时间点的直接动因：它说明**位宽-延时的渐进阶决定了流水化的收益上限**，
而这条渐进阶（以及知识库 34 张卡「关键路径」小节的全部断言）在本仓库从未被实测过。

## Goals / Non-Goals

**Goals:**

- 给 `params.yaml` 补上"参数不参与全量扫参"的声明能力，并让 `sweep.py` 尊重它。
- 让 `adder32` 的 `WIDTH` 与 `CSEL_BLOCK` 成为可扫参数。
- 保证参数化过程**不改变电路**：历史 9 个组合的综合指标逐位复现。

**Non-Goals:**

- 不改 `results/experiments.jsonl` 的 schema（不新增/改名/删除字段，不改写历史记录）。
- 不给 `params.yaml` 引入任何形式的**参数间依赖表达**（如"BLOCK 仅当 CARRY_STRUCT=CSEL"）。
  `sweep: false` 是一个更弱、更简单的机制，够用即止。
- 不改设计名，不动 `CUT_POLICY`（切点策略），不碰功耗相关的任何东西。
- 不跑本变更之外的实验；本变更只负责把维度打开并验证复现。

## Decisions

- **D1** — `params.yaml` 的参数声明增加可选布尔字段 `sweep`，缺省 `true`；
  `sweep: false` 表示"合法参数，但不进全量叉乘"。
  Basis：用户 2026-09-07 在三个方案（本方案 / 接受 24 条冗余记录 / 另开
  `designs/csel_block/` 设计根）中选定本方案，理由是保持
  `results/experiments.jsonl` 干净且不重复 RTL。

- **D2** — `sweep: false` 参数在扫参组合中取其 `values` 列表的**第一项**，
  且在单次实验里**允许省略**（同样取第一项）。
  Basis：不需要新字段，语义单一；`values` 的顺序本来就是设计作者可控的。
  允许省略是为了让 `CLAUDE.md` 里已有的命令示例
  （`PARAMS="CARRY_STRUCT=CLA PIPE_STAGES=1"`）在新增 `CSEL_BLOCK` 后继续有效 ——
  否则每条命令都要多写一个对 RIPPLE/CLA 毫无意义的参数。

- **D8** — **参与扫参的参数仍然强制给出取值，缺失照旧报错。**
  Basis：2026-09-07 读 `flow/paths.py` 的 `validate_params` 核实，现有实现对
  `missing` 参数是抛 `ParamError` 的，且该函数的 docstring 写明这类校验的动机是
  "RTL 里的分派是 if/else-if 链，没有 else，传错的值只会综合出悬空电路"。
  把"缺失即默认"推广到所有参数会拆掉这个守卫 —— 扫参维度缺失通常是笔误，
  而 `sweep: false` 参数缺失是常态。所以放宽只对后者。

- **D3** — `CSEL_BLOCK` 的 `values` **必须以 4 打头**（`[4, 2, 8, 16]`）。
  Basis：4 是 F1 里写死的历史值；由 D2，`values[0]` 就是扫参默认值，
  只有把 4 放第一位，扫参出来的 9 个老组合才可能复现历史记录（见 D6）。

- **D4** — `WIDTH` 是**普通扫参维度**（参与叉乘），`values = [8, 16, 32, 64]`。
  Basis：`WIDTH` 对三种结构 × 三种流水级数都有独立意义，叉乘不产生冗余；
  这与 `CSEL_BLOCK` 的情况本质不同。4 个点按 2 的幂分布，便于拟合渐进阶。

- **D5** — 不改设计名 `adder32`，在 `designs/adder32/spec.md` 里写明
  `WIDTH` 默认 32、名字是历史沿革。
  Basis：`results/experiments.jsonl` 里 28 条记录的 `design` 字段都是 `adder32`，
  改名会让这些记录指向一个不存在的设计根，而按 `CLAUDE.md` 历史记录不回填改写。

- **D6** — **首要验收项是历史复现** —— 在 `WIDTH=32, CSEL_BLOCK=4` 下，
  9 个老参数组合的 `cell_count` / `area_um2` / `critical_path_delay_ns` /
  `critical_path_stages` 必须与历史记录**逐位相同**。
  Basis：参数化只应改变可配置性，不应改变电路。若不复现，说明 RTL 提参过程
  引入了结构变化，则此前所有跨结构结论（含刚修正的 F2）作废 ——
  这比本变更本身重要得多，所以它是验收项而不是"顺便检查一下"。

- **D7** — 跑任何实验前工作区必须干净并已提交。
  Basis：`CLAUDE.md`「记录实验前先提交」——`run_experiment.py` 会把
  `git rev-parse HEAD` 写进记录，脏工作区跑出的记录 provenance 是错的。

## Hidden Knowledge / Assumptions

- **A1** — `WIDTH` 变小时（8/16），`PIPE_STAGES=2` 的分段仍然合法
  （`NSEG=3`，`SEGW=WIDTH/3`，末段吃余数；`WIDTH=8` → 段宽 2/2/4）。
  Basis：读 `adder32.v` 的 generate 逻辑推得，未实跑。
  Resolve by：任务里对全部 `WIDTH × CARRY_STRUCT × PIPE_STAGES` 组合跑
  `./scripts/fast_check.sh` 的 elaborate 检查。

- **A2** — tb 现有的 50 个随机向量在 `WIDTH=64` 下仍有足够覆盖。
  Basis：定向用例覆盖了全 1、进位溢出、交替位模式等边界，随机只是补充；
  位宽变化不改变这些边界的性质。
  Owner：`designs/adder32/verify.md`（若日后发现覆盖不足，在那里调整并记录）。

- **A3** — `CSEL_BLOCK` 大于段宽时（如 `WIDTH=8, PIPE_STAGES=2, BLOCK=16`）
  `carry_select_adder` 退化为单块（`NBLOCKS=1`）而非报错。
  Basis：读 RTL 的 `NBLOCKS = (WIDTH+BLOCK-1)/BLOCK` 与 `HI` 的钳位推得，未实跑。
  Resolve by：同 A1 的 elaborate 检查。

## Risks / Trade-offs

- **参数化改变了电路而没被发现** —— 最严重的风险。缓解：D6 的逐位复现验收，
  且必须在打开新维度**之前**先验证（先提参、先复现，再扩 `values`）。
- **`sweep.py` 的改动影响所有设计** —— 目前只有 `adder32` 一个设计，
  影响面可控；spec 的 scenario 用"组合数 = 其余参数取值个数之积"来锁定行为，
  不依赖具体设计。
- **`sweep: false` 是个弱机制，将来可能不够用** —— 如果以后真需要
  "参数 A 仅当参数 B 取某值时有效"，本机制表达不了。这是有意的取舍
  （Non-Goals 已写明）：先用最简单的东西，等真出现第二个用例再谈抽象，
  符合 `CLAUDE.md`「脚本不做过度设计」。
- **组合数增长** —— `WIDTH` 加进叉乘后全量扫参从 9 组变成 36 组。
  单次实验耗时不变，只是总时长 ×4；`SKIP_EXISTING` 可用于续跑。

## Open Questions

- **Q1** — 4 个位宽点（8/16/32/64）是否足以分辨 O(n) / O(√n) / O(log n)？
  Basis：未跑过位宽维度，无先验。
  Resolve by：跑完后看数据 —— 若三条曲线在 log-log 上的斜率区分不开，
  **已授权的回退是补测 `WIDTH=128`**（只需在 `params.yaml` 的 `values` 里加一项，
  不触及本变更的任何其他产物）。因此本问题不阻塞任何任务。
