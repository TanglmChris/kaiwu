# barrel shifter（对数移位网络 / Funnel Shifter）

- **类别**：优先级与编码
- **一句话**：用 log₂N 级 2:1 mux 做任意位移，每级移 2^k 位 ——
  延时便宜、**连线极贵**，是本仓库当前测量能力最看不准的一类电路。
- **典型用途**：浮点规格化与对齐、变长移位指令（ALU）、
  桶形旋转（CRC、加密）、位域提取、
  非对齐访存的数据拼接、[`round-robin-arbiter.md`](round-robin-arbiter.md)
  的"旋转—仲裁—转回"实现。

## 结构

### 写法 A：对数移位器（log shifter）

移位量 `s[log2N-1:0]`，第 k 级由 `s[k]` 控制、移 2^k 位：

```verilog
wire [N-1:0] lvl0 = s[0] ? {1'b0, x[N-1:1]}      : x;      // >>1
wire [N-1:0] lvl1 = s[1] ? {2'b0, lvl0[N-1:2]}   : lvl0;   // >>2
wire [N-1:0] lvl2 = s[2] ? {4'b0, lvl1[N-1:4]}   : lvl1;   // >>4
...
```

- mux 数：**N·log₂N**（32 位是 160 个 2:1 mux）。
- 级数：**log₂N**（32 位是 5 级）。

### 写法 B：解码 + N:1 mux（交叉开关式）

先把 `s` 解码成 one-hot，再对每个输出位做一个 N:1 的 AND-OR 选择。
级数看起来更少（解码 + 一棵 OR 树），
但**每个输出位都要看到全部 N 个输入位** —— 这是一张 N×N 的交叉开关，
连线是 O(N²)。位宽稍大就不可行，32 位以上基本不用。

### 写法 C：funnel shifter（**推荐的通用件**）

把两个 N 位输入拼成 2N 位，从里面取一个 N 位窗口：

```
{hi, lo}  ->  取 [s + N-1 : s]
```

一个结构同时覆盖：

| 目标 | hi | lo |
|---|---|---|
| 逻辑右移 `x >> s` | `0` | `x` |
| 逻辑左移 `x << s` | `x` | `0`（并把移位量取成 `N-s`）|
| 算术右移 | `{N{x[N-1]}}` | `x` |
| 循环右移 | `x` | `x` |
| 非对齐拼接 | 前一拍数据 | 本拍数据 |

**这是省面积的关键一招**：ALU 里如果左移、右移、算术右移、
旋转各做一个桶形移位器，面积是 4 倍；funnel 只做一个，
外面加一层输入选择 mux。

### 级序与掩码

对数移位器的级序（先移大的还是先移小的）在功能上无所谓，
但在 PPA 上不一样：

- **大步在后**：前几级只在数据内部搬短距离，长线只在最后一级出现。
- **零填充放在前面**做，可以让后面几级少翻转（省动态功耗）。

这类"同功能不同排布"的差异**恰恰是本仓库现在测不出来的**（见下）。

## 关键路径

- 写法 A：**O(log N)** 级 2:1 mux。32 位 = 5 级，非常浅。
- 写法 B：解码 O(log N) + N 输入 OR 树 O(log N)，同阶但常数大。
- 写法 C：和 A 一样，只是输入宽了一倍（第一级的 mux 从 2N 里选）。
- **真实芯片上，这类电路的延时经常不是由级数决定，而是由连线决定**：
  第 log₂N−1 级要把数据搬过半个数据通路，那根线本身就有可观的 RC。

## PPA 权衡

> ⚠️ **这张卡是全库那条警告最典型的受害者。**
> 本仓库是 yosys + OpenSTA，**没有 LEF、没有布局布线、没有寄生参数，
> 连线的面积/延时/功耗恒为零**（见 [`../README.md`](../README.md)）。
> 桶形移位器的成本**主要就在连线上**。所以：
>
> - 本地流会**系统性低估**桶形移位器的代价，
>   并且会**低估写法 B（交叉开关）相对写法 A 的劣势** ——
>   O(N²) 连线在这里根本不计价。
> - 级序、掩码位置这类只影响连线与翻转的优化，本地流几乎测不出差别。
>
> **这类结论在 DC / P&R 到位前一律打问号。** 本地能可信测的只有
> mux 数（面积）和级数。

在这个前提下仍然成立的：

- 面积 N·log₂N vs N²：写法 A 完胜，这个差距是逻辑级的、本地也测得出。
- funnel 相对"每种移位各一个"的面积节省是实打实的（少 2~3 个网络）。
- 动态功耗上桶形移位器天生不友好：**一次移位会让整个数据通路翻转**。
  操作数隔离/门控在这里收益很大，见
  [`../arch-technique/operand-isolation-clock-gating.md`](../arch-technique/operand-isolation-clock-gating.md)。

## 什么时候选它 / 什么时候别用

- **移位量是变量** → 桶形移位器，没有别的选择。
- **移位量是常数** → **别用**，常数移位在 RTL 里就是改接线，零成本。
  参数化设计里要小心别让常数走进变量移位的通路。
- **移位量取值只有少数几个**（比如 0/8/16/24） → 一个小 mux，
  别铺整张 log 网络。
- **需要多种移位模式** → funnel（写法 C）。
- **吞吐不够、面积紧** → 分多周期做（每周期移固定步），
  面积降到 O(N)，见
  [`../arch-technique/folding-time-multiplex.md`](../arch-technique/folding-time-multiplex.md)。
- **round-robin 仲裁的"旋转"** → 先算算账：两个桶形移位器
  （N·log N 的 mux ×2）通常比两棵固定优先级树（O(N)）贵，
  见 [`round-robin-arbiter.md`](round-robin-arbiter.md)。

## 实现要点与坑

- **移位量超范围必须定义。** `s` 有 log₂N 位时天然不会超；
  但接口上给了更宽的 `s`（比如 ALU 的 8 位移位量对 32 位数据），
  就必须显式饱和：`s >= N` 时逻辑移位出全 0、算术右移出全符号位。
  漏掉这条的表现是"只有大移位量才错"，随机激励打不中，**要定向测**。
- **Verilog 的 `>>>` 只有在操作数被声明为 `signed` 时才是算术右移。**
  `wire [31:0] x; x >>> s` 是**逻辑**右移。这是经典 bug，
  显式写 `{{N{x[N-1]}}, x} >> s` 更不会错。
- **工具对 `x << s` / `x >> s` 做得很好** —— 综合出来的就是一张对数移位网络。
  所以这里同样要留 `TOOL` 对照组，**先测再决定要不要手写**
  （和 `../arith/comparator.md`、[`find-first-one.md`](find-first-one.md)
  是同一批实验）。
- **要比较写法 A/B/C 就必须保层级（`params.yaml` 的 `keep_hierarchy:`）。** 三者功能等价，
  `-flatten` + ABC 的 `&dch` 会把它们收敛成同一个网表
  （`docs/pitfalls.md` 的 P-3）。
- **别在移位器输出上直接接长组合链。** 它本身浅（5 级），
  很容易被误当成"便宜"，然后在后面又挂一个加法器和一个比较器。
- **功耗测量注意**：桶形移位器的活动率对激励极度敏感
  （移位量随机 vs 大部分为 0，差好几倍）。跑功耗实验时激励分布要写进
  `verify.md`，否则数字没法横向比。这一条和 `docs/data-credibility.md` 里的
  D-1（功耗反标）是两回事，但会叠加。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module SHIFTER #(
    parameter DAT_W  = 32,
    parameter SCHEME = 0,         // 0 LOG | 1 XBAR（解码+N:1） | 2 FUNNEL | 3 TOOL（直接写 >> / <<）
    parameter MODES  = "ALL"      // ALL（左/右/算术/旋转） | RIGHT_ONLY 等
)(
    input  [DAT_W-1:0]           i_dat,
    input  [DAT_W-1:0]           i_fill,   // FUNNEL 时的高半边；其余模式内部生成
    input  [$clog2(DAT_W)-1:0]   i_shamt,
    input  [1:0]                 i_op,     // 00 SLL / 01 SRL / 10 SRA / 11 ROR
    output [DAT_W-1:0]           o_dat
);
    localparam SCHEME_LOG    = 0;
    localparam SCHEME_XBAR   = 1;
    localparam SCHEME_FUNNEL = 2;
    localparam SCHEME_TOOL   = 3;
```

`MODES` 单独拿出来是为了量化 funnel 的核心论点：
**"支持 4 种移位"相对"只支持 1 种"的面积增量，
funnel 应当远小于四张独立网络。**

## 出处

- Weste, N. & Harris, D., *CMOS VLSI Design*, 4th ed., Addison-Wesley, 2010 ——
  datapath 一章的移位器结构（对数移位器与 funnel shifter）。
- Ercegovac, M.D. & Lang, T., *Digital Arithmetic*, Morgan Kaufmann, 2004 ——
  浮点对齐/规格化里移位器的位置与代价。
- Hennessy, J. & Patterson, D., *Computer Architecture: A Quantitative Approach* ——
  funnel shifter 在通用 ALU 中复用的动机。**未逐行核实，引用前自行确认。**

## 本地实测

暂无，**并且这张卡的实测价值天然受限** —— 桶形移位器的主要代价在连线，
本地流看不见。可信的实验只有两个：

1. `SCHEME = LOG / XBAR` 的**面积**对比（N·log N vs N²，纯逻辑级，本地可信）。
2. `MODES = ALL / RIGHT_ONLY` 下 `FUNNEL` 的**面积节省**（复用论点，本地可信）。

延时和功耗的对比等 DC / P&R 到位再做。
