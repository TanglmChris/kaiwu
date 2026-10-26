# 知识库

RTL 结构选型的知识沉淀。**这里只放"想清楚了的东西"，不放实验数据** —— 数据在
实验记录 `results/<设计根>/experiments.jsonl`，两边靠卡片末尾的「本地实测」一节挂钩。

> **状态（2026-09-27）**：四类 **34 张卡全部写完**。
> 「本地实测」挂上了记录的有 3 张：[`arch-technique/pipelining.md`](arch-technique/pipelining.md)、
> [`arch-technique/precompute-lookahead.md`](arch-technique/precompute-lookahead.md)
> （来自 adder32 扫参）与 [`priority-encode/clz-lzd.md`](priority-encode/clz-lzd.md)
> （来自 `cbb/lzd`），其余 31 张仍为空。`cbb/lzd` 2026-10-02 已删，记录仍可读，源码按记录的 `git_commit` 取（`docs/data-credibility.md` 的 D-29）。
> `designs/adder32` 同日删除，2026-10-14 作为开源演示设计恢复（RTL 按现行规范改写，与删除前逐配置形式等价，内部#305）。
> 挂实测的节奏跟着 cbb 走：每周约 2 个构件，每个构件挂上它对应的卡（内部#62）。

## 为什么先写卡片、后写 RTL

第一轮只铺资料卡，不写 RTL。理由是覆盖面比深度先值钱：做 PPA 优化时最怕的不是"这个电路
写不出来"，而是"根本没想到可以用这个结构"。卡片便宜，写满四类只要几天；RTL 贵，
一个参数化实现加验证要小半天。等卡片铺开、看清楚哪些结构真的可能用上，再挑着补 RTL。

## 目录

```
knowledge/arith/            算术单元（加法器、乘法器、压缩树、除法、CORDIC）
knowledge/storage-flow/     存储与流控（FIFO、skid buffer、反压、CDC、复位）
knowledge/priority-encode/  优先级与编码（找1/找0、CLZ、popcount、仲裁、移位、排序网络）
knowledge/arch-technique/   架构范式与技巧（流水/并行/折叠/预计算 + retiming、门控等）
```

## 卡片模板

每张卡固定这几节，顺序不要变（写脚本汇总的时候靠它）：

```markdown
# <中文名>（English Name）

- **类别**：
- **一句话**：
- **典型用途**：

## 结构
## 关键路径
## PPA 权衡
## 什么时候选它 / 什么时候别用
## 实现要点与坑
## 参数化接口建议
## 出处
## 本地实测
```

几条约定：

- **「关键路径」必须写清随位宽的渐进阶**（O(n) 还是 O(log n)），这是
  决定选型的第一判据。
- **「实现要点与坑」必须包含"这个结构会不会被综合工具优化掉"**。本仓库已经
  踩过一次：`synth -flatten` + ABC 的 `&dch` 会把不同微架构收敛成同一个网表
  （见 `docs/pitfalls.md` 的 P-3）。凡是靠**结构**而非**功能**取胜的电路，
  卡片里都要写明比微架构时要保住它的层级（在 `params.yaml` 的
  `tops:<顶层>:synth:keep_hierarchy:` 声明，不写在 RTL 里；见 P-15、内部#216）。
- **「本地实测」初始留空**，等实现并跑过流程后填 `experiment_id`，形成
  「知识 → 实测」的闭环。没实测过就老实空着，不要填猜测值。
- **「出处」只写核实过的**。宁可没有出处，也不要编造参考文献 —— 编造的引用
  比没有引用更坏，两个月后你回头查会被坑。

## 一条贯穿全库的警告：本地流看不见连线代价

本仓库目前是 yosys + OpenSTA，**没有 LEF、没有布局布线、没有寄生参数**
（见 `docs/toolchain.md`「ASAP7 的几个事实」）。这意味着：

> **连线的面积、延时和功耗在本地流里全部为零。**

后果是本地流会**系统性地高估"用连线换级数"的结构**——Kogge-Stone 这类
连线轨道数 O(N) 的网络，本地测出来会比它在真实版图上好看得多。凡是卡片里
提到"连线代价高"的结构，本地数字都要打问号，等 DC/P&R 到位再回头校准。
这条不是理论顾虑，是这个仓库当前测量能力的硬边界。

## 覆盖计划

打勾的是已经写完的卡。

### arith/ 算术单元
- [x] 并行前缀加法器家族（Sklansky / Kogge-Stone / Brent-Kung / Han-Carlson / Knowles）
- [x] 部分积压缩（Wallace 树 / Dadda 树 / 3:2 与 4:2 压缩器）
- [x] Booth 编码（radix-2 / radix-4 / radix-8）
- [x] 进位保存累加（CSA accumulator，多操作数求和）
- [x] 除法器（restoring / non-restoring / SRT）
- [x] 常数乘法（移位加、CSD 编码）
- [x] CORDIC
- [x] 比较器与绝对值

**`arith/` 已写完（8/8）。** 从这一类浮现出两个跨卡片的判断，值得先验证再往下写：

1. **"手写结构 vs 交给工具"的分界线在哪，目前是未知数。** 常数乘法、比较器
   这类电路综合工具优化得很好，手写多半打不过；压缩树、前缀加法器则必须手写
   加 `keep_hierarchy` 才留得住结构。这条线画在哪里会决定优化时间该投在
   哪里，而它**可以用很便宜的实验测出来**（纯组合、无握手）：建议把
   `constant-multiplication.md` 和 `comparator.md` 的 `SCHEME = TOOL` 对照组
   作为第一批 RTL 实验。
2. **多周期设计会逼流程泛化。** 除法器和 CORDIC 都需要握手和 `done`，
   而现有 `flow/sim` 和记录里的 `cycles` 语义是按组合/短流水加法器设计的。
   这件事迟早要做，但**不要和某个具体设计的调试混在一起做**。

### storage-flow/ 存储与流控
- [x] 同步 FIFO（计数器法 vs 指针法）
- [x] 异步 FIFO（格雷码指针 + 两级同步）
- [x] skid buffer（valid-ready 全流水不丢拍的关键件）
- [x] credit-based 流控
- [x] CDC 同步器族（两级触发器 / 脉冲同步 / 握手 / 异步 FIFO 的选型）
- [x] 复位策略（异步复位同步释放）
- [x] 乒乓与循环 buffer

**`storage-flow/` 已写完（7/7）。** 三个跨卡片的结论：

1. **这一类的实验前提是仿真驱动要先支持 valid-ready。** skid buffer、
   credit 流控都必须用握手激励才测得出来，而现有 `flow/sim` 和记录里的
   `cycles` 语义是按组合/短流水加法器设计的（见 内部#7）。
   这件事在 `arith/` 结尾也提过一次，两类都指向它，**该做了**。
2. **本类里 PPA 实验价值排序很清楚**：credit 流控最高
   （"反压路径与链路长度解耦"可直接量化），skid buffer 次之
   （插入前后的关键路径差），复位策略第三（成本极低，FIFO 构件的存储阵列复位开关 `RST_EN` 就是这个维度）；
   CDC 和乒乓最低 —— 前者的正确性根本不体现在 PPA 数字上，
   后者的核心对比依赖 SRAM 宏而本仓库没接。
3. **有两处触到了当前流程的硬边界**，见 内部#23 与 内部#24：
   异步 FIFO 需要多时钟约束（`run_sta.py` 写死单个 `clk` 端口）；
   复位策略需要 recovery/removal 检查（`run_sta.py` 只做 `-path_delay max`）。

### priority-encode/ 优先级与编码
- [x] 找首个 1 / 找首个 0（优先编码器，含 `x & -x` 技巧）
- [x] 前导零计数 CLZ / LZD
- [x] popcount（压缩树法 vs 查表法；公开初版不含此卡）
- [x] barrel shifter（对数移位网络）
- [x] 固定优先级仲裁
- [x] round-robin 仲裁（mask + 双优先级树的经典实现）
- [x] 排序网络（bitonic / odd-even）
- [x] 独热与二进制互转、thermometer 码

**`priority-encode/` 已写完（8/8）。** 三个跨卡片的结论：

1. **这一类是"现在就能跑"的实验池 —— 8 张卡里 7 张是纯组合。**
   `arith/` 和 `storage-flow/` 的结尾都指向同一个前提（仿真驱动要先支持
   握手和多周期），而本类基本不依赖它：找首个 1、CLZ、popcount、
   barrel shifter、固定优先级仲裁、排序网络、编码转换全是组合逻辑，
   现有 `flow/` 直接能跑。**唯一的例外是 round-robin 仲裁**
   （掩码是状态，且 `ready` 语义要握手激励）。
   在流程泛化之前，本类是唯一能持续产出记录的来源。

2. **本类反复撞上同一个问题：手写结构 vs 交给工具。**
   `find-first-one`、`popcount`、`barrel-shifter`、
   `onehot-binary-thermometer` 四张卡都在正文里写了"先测 `TOOL` 档再决定"。
   这正是 `arith/` 结尾提的第 1 条，而**本类的载体更便宜**。
   建议把 `arith/` 的 `comparator` / `constant-multiplication` 和本类的
   `popcount` / `find-first-one` 打包成同一批实验一次测完 ——
   这条分界线画在哪里会决定优化时间该投在哪里。

3. **两张卡的核心结论本地测不了，但另两张卡正好能当流程的检验器。**
   `barrel-shifter` 和 `sorting-network` 的成本主要在置换式长连线，
   而本地流连线代价恒为零（见上面的全库警告），这两张卡本地只有
   mux 数/比较器数和级数可信。反过来，`popcount` 和 `sorting-network`
   有很强的先验——**不同写法的面积本来就该不同**（比较器数 24 / 19 是已知的），
   所以"测出来三档全同"是个明确的信号：**`keep_hierarchy` 没生效，
   先查流程再看数**。本类里这是最便宜的一次流程自检。

### arch-technique/ 架构范式与技巧
- [x] 流水化（cut-set 与级平衡）
- [x] 并行展开与 C-slow
- [x] 折叠 / 时分复用（面积换吞吐）
- [x] 预计算与前瞻
- [x] 反压范式对比（valid-ready / credit / stall 链）
- [x] retiming（工具能做什么、不能做什么）
- [x] 操作数隔离与时钟门控
- [x] 资源共享
- [x] FSM 编码（one-hot / binary / gray）
- [x] 晚到信号后置（late-arriving signal）
- [x] 逻辑复制解 fanout

**`arch-technique/` 已写完（11/11），四类 34 张卡全部铺完。**
这一类和前三类不同：前三类写的是"电路长什么样"，这一类写的是
"**同一个电路，工具和流程会对它做什么**"。所以它的结论大量落在
本仓库的具体工具行为上，三条：

1. **本地流程比想象中"不作为"，这既是缺陷也是资产。**
   已核实（2026-09-07，yosys 0.68+182 / OpenSTA）：
   `synth` **没有 `-retime`**，且 `flow/synth/synth.py` 的 `abc -liberty`
   **不带 `-dff`**（ABC 连触发器都看不到）→ **完全没有 retiming**；
   yosys **没有时钟门控插入 pass**；`run_sta.py` 的
   `set_input_delay 0` 宣布**没有晚到信号**。
   后果是 [`arch-technique/pipelining.md`](arch-technique/pipelining.md)
   测到的"级数 vs fmax"是**纯 RTL 的干净结果**，不含工具重定时的成分 ——
   **本地流的很多"干净"来自它不够聪明**，而接 DC 之后这些干净会立刻消失。
   这批"可预先声明、之后用 DC 验证的偏差"是 `calibration/` 最好的素材。

2. **反过来，工具在几个地方会悄悄抹掉你的结构意图，而且不报警告。**
   除了已知的 ABC `&dch`（`docs/pitfalls.md` 的 P-3），本轮又核实两条：
   `opt_merge` 会把**手工复制的高扇出驱动合并回一份**
   （[`logic-replication.md`](arch-technique/logic-replication.md)）；
   `fsm_recode` 会把**手写的状态编码推翻重编**
   （[`fsm-encoding.md`](arch-technique/fsm-encoding.md)，
   要靠 `(* fsm_encoding *)` 属性或 `-nofsm` 钉住）。
   **三处的共同排查手法都是"数单元/数触发器"** ——
   数量对不上就说明结构没保住，此时所有对比数据作废。

3. **`docs/data-credibility.md` 的 D-1（功耗反标失效）让整整一张卡失去意义。**
   [`operand-isolation-clock-gating.md`](arch-technique/operand-isolation-clock-gating.md)
   的全部价值都在功耗那一列上，本地现在只能当 checklist 用。
   而 [`backpressure-paradigms.md`](arch-technique/backpressure-paradigms.md)
   是**第四次**指向"仿真驱动要先支持 valid-ready"这个前提
   （前三次：`arith/` 的除法器/CORDIC、`storage-flow/` 的 skid/credit、
   本类的折叠）。**四类知识里有三类的核心实验都停在这一件事上。**
