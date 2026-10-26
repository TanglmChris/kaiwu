# FSM 编码（One-Hot / Binary / Gray / Johnson）

- **类别**：架构范式与技巧
- **一句话**：状态编码决定的是"次态逻辑和输出译码有多深" ——
  one-hot 用触发器换组合深度，binary 反过来；
  **但你写的编码不一定算数，综合工具默认会重新编码。**
- **典型用途**：所有控制器 —— 握手状态机、总线协议、
  DMA/仲裁控制、启动序列、任何 `always @(posedge clk) case(state)`。

## 结构

N 个状态的四种常见编码：

| 编码 | 触发器数 | 状态判断 | 次态逻辑 | 特点 |
|---|---|---|---|---|
| binary | ⌈log₂N⌉ | 要译码（AND 树）| 较深 | 触发器最少 |
| one-hot | N | **看一根线** | 最浅 | 触发器最多 |
| gray | ⌈log₂N⌉ | 要译码 | 与 binary 相当 | 相邻转移只翻 1 位 |
| johnson | N/2 | 简单译码 | 浅 | 介于两者之间，用得少 |

### one-hot 为什么快

```verilog
// binary：先译码再判断
wire in_state_5 = (state == 3'd5);        // 3 输入 AND

// one-hot：状态位本身就是判断结果
wire in_state_5 = state[5];               // 一根线
```

对**输出逻辑**和**次态逻辑**都成立。状态一多，binary 的译码树就
开始进关键路径，而 one-hot 恒定是一根线。

代价是 N 个触发器而不是 log N 个。**但省下来的组合逻辑经常能抵掉**：
状态数 ≤ 16 时 one-hot 的总面积常常不比 binary 大多少，
有时反而更小。**这是必须实测的地方，不能凭直觉。**

### gray 的两个不同用途

1. **省功耗**：相邻转移只翻一位，状态寄存器和它的扇出翻转少。
   **只有在状态转移确实沿着编码顺序走时才有效** ——
   一个到处乱跳的状态机用 gray 编码毫无意义。
2. **跨时钟域**：多位状态要被另一个时钟域采样时，
   gray 保证任意时刻最多一位在变，避免采到中间态。
   **但这只对"计数式"的顺序转移成立**，任意状态机的 gray 编码
   做不到这个保证。真要跨域传状态，用握手或
   [`../storage-flow/async-fifo.md`](../storage-flow/async-fifo.md)
   的方案，别指望 gray 编码。
   编码转换本身见
   [`../priority-encode/onehot-binary-thermometer.md`](../priority-encode/onehot-binary-thermometer.md)。

## ⚠️ 你写的编码不一定算数（2026-09-07 核实）

yosys 的 `synth` 默认脚本里有 **`fsm`（unless `-nofsm`）**，
它会检测状态机、提取成 `$fsm` 单元、优化，然后 **`fsm_recode` 重新编码**。
`fsm_recode` 的行为（`yosys -h fsm_recode`）：

> 只支持 one-hot 和 binary 两种编码；对**没有 `fsm_encoding` 属性、
> 或属性为 `auto`** 的状态机，用 `-encoding <type>` 指定的方案重编。

所以：

- **RTL 里 `localparam S_IDLE = 3'd0;` 这种手写编码，默认会被推翻。**
- 要保住手写编码，得在状态信号上加属性：
  ```verilog
  (* fsm_encoding = "one-hot" *) reg [3:0] state;
  ```
  或者整体 `synth -nofsm` 关掉这个 pass。
- **gray 和 johnson 在 yosys 里没有原生支持** ——
  只能靠 `fsm_encoding` 属性钉住手写编码（`fsm_encoding = "user"` 一类），
  或者 `-nofsm`。

DC 那边对应的是 `set_fsm_encoding` / `set_fsm_state_vector`，
默认行为也是自己挑。**两边默认都会改，而且挑法不一样** ——
这是一条可预期的本地 vs 参考偏差，属于 `calibration/` 的素材。

**实践结论：想比较 FSM 编码的 PPA，必须先确认工具没有替你重编。**
最简单的验证方法是**数触发器**：写 one-hot 却只综合出 log N 个触发器，
就说明被改了。

## 关键路径

- 次态逻辑：`状态译码 + 输入条件` → one-hot 省掉译码那一段。
- 输出逻辑：Moore 型的输出只依赖状态（one-hot 下是一根线或一个 OR）；
  Mealy 型还要加输入，**Mealy 的输出是组合的，容易成为跨模块的晚到信号**
  （见 [`late-arriving-signal.md`](late-arriving-signal.md)）。
- 状态数 N 增大时，binary 的译码深度按 O(log N) 涨，one-hot 恒定。
  **N ≥ 16 时差距开始明显。**

## PPA 权衡

- **面积**：one-hot 的触发器多 (N − log N) 个，但组合逻辑少。
  ASAP7 里一个 DFF 不便宜（比 FA 大），所以 N 很大时 one-hot 会输。
  **交叉点大概在十几到几十个状态之间，必须实测。**
- **延时**：one-hot 通常赢，尤其状态多、输出多的时候。
- **功耗**：⚠️ 本仓库测不了（`docs/data-credibility.md` D-1）。理论上
  one-hot 每次转移翻 2 位、binary 平均翻 log N/2 位、gray 翻 1 位；
  但状态寄存器只有几位，**真正的功耗在它驱动的那一大片逻辑上**，
  不在状态位本身。**"gray 编码省功耗"这个说法在控制器上通常被高估。**
- **本地触发器驱动档位有限**（本库 `DFFHQNx1/x2/x3` + `DFFHQx4`，
  非反相输出只有 x4 一档）：状态位扇出大时驱动能力受限，
  这会放大 one-hot 的优势（每根状态线的扇出更小）。

## 什么时候选它 / 什么时候别用

- **状态少（≤16）、时序紧、输出多** → one-hot。
- **状态很多（≥64）、面积紧、时序松** → binary。
- **状态转移是顺序推进的计数器型** → gray 值得一试（省翻转）。
- **要跨时钟域传状态** → **别靠编码解决**，用握手或异步 FIFO，
  见 [`../storage-flow/cdc-synchronizers.md`](../storage-flow/cdc-synchronizers.md)。
- **只有 2~3 个状态** → 怎么编都一样，别花时间。
- **状态机其实是个计数器**（线性推进、没有分支）→ 别写成 FSM，
  写成计数器 + 译码，工具处理得更好。

## 实现要点与坑

- **`case` 必须有 `default`。** 没有 `default` 时：
  仿真里非法状态给出 X 并卡死，综合出的电路给出某个确定的次态。
  **仿真通过不代表电路对**，这是 FSM 最经典的 RTL/门级不一致来源。
  one-hot 编码的非法状态尤其多（2^N 个编码里只有 N 个合法）。
- **安全状态机（safe FSM）**：`default: state <= S_IDLE;` 让电路从任何
  非法状态都能恢复。**但优化器会把"不可达状态"的逻辑删掉**，
  于是恢复逻辑消失。DC 有 `set_fsm_minimize false` 之类的开关；
  yosys 这边 `fsm_opt` 也会做状态最小化。**要保住恢复逻辑就得关掉 FSM pass。**
- **别把数据通路的寄存器写进状态里。** 常见错误是把一个计数器
  塞进状态编码，状态数爆炸，`fsm_extract` 提取出一个巨大的 `$fsm`，
  综合时间和结果都变差。**状态机只放控制，计数放计数器。**
- **一段式 / 二段式 / 三段式**：本质是"次态逻辑、状态寄存器、输出逻辑"
  怎么分块写。**对综合结果影响很小**（工具都能处理），
  但对可读性和 Mealy/Moore 的清晰度影响很大。二段式（时序块 + 组合块）
  是通用的稳妥选择。
- **保层级（`params.yaml` 的 `keep_hierarchy:`）在这里不管用。** FSM 重编码是 `fsm` pass 干的，
  发生在模块内部，模块边界拦不住它。**要控制编码只能用
  `fsm_encoding` 属性或 `-nofsm`。**

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module CTRL #(
    parameter STATE_N = 8,
    parameter SCHEME  = 0          // 0 ONEHOT | 1 BINARY | 2 GRAY
)(
    input clk, rst_n,
    input  [3:0] i_ev,
    output [7:0] o_ctrl
);
    localparam SCHEME_ONEHOT = 0;
    localparam SCHEME_BINARY = 1;
    localparam SCHEME_GRAY   = 2;
    (* fsm_encoding = "user" *) reg [STATE_W-1:0] state;   // 钉住手写编码
```

**`fsm_encoding` 属性是这个参数化能否成立的前提** ——
不加的话三档综合出来会是同一个东西，
和 `docs/pitfalls.md` 的 P-3是同一类失败：**测出来的差异是假的。**

## 出处

- De Micheli, G., *Synthesis and Optimization of Digital Circuits*,
  McGraw-Hill, 1994 —— 状态编码与状态最小化。
- Cummings, C.E., "Coding And Scripting Techniques For FSM Designs With
  Synthesis-Optimized, Glitch-Free Outputs," SNUG, 2000 ——
  一段式/二段式/三段式写法与 glitch-free 输出。
  **未逐行核实，引用前自行确认。**（同作者的其他 SNUG 论文见
  [`../storage-flow/async-fifo.md`](../storage-flow/async-fifo.md) 的出处，
  那几篇是核实过的。）
- yosys 的行为由 `yosys -h synth`、`yosys -h fsm_recode` 输出核实
  （2026-09-07，yosys 0.68+182）。

## 本地实测

暂无。**这张卡有一个门槛很低但价值很高的实验**：

拿一个状态数可参数化的控制器，扫 `STATES = 4/8/16/32/64` ×
`ENCODING = ONEHOT/BINARY`，测**面积和关键路径**，找出交叉点。
这回答一个每次写控制器都会遇到的问题：**多少个状态以内 one-hot 是免费的？**

三条注意：

1. **先验证 `fsm_encoding` 属性真的生效**（数触发器：one-hot 应当有
   `STATES` 个状态触发器，binary 只有 `log2(STATES)` 个）。
   数量对不上就说明工具重编了，此时所有对比数据作废。
2. 这个设计**有时钟和状态**，不是纯组合，
   但它**不需要 valid-ready 握手**（自驱动的状态转移就够），
   所以**不被 内部#7 那条流程前提挡住** —— 现有 `flow/` 能跑。
   这一点和 `../priority-encode/round-robin-arbiter.md` 不同。
3. 功耗那一列不可用（D-1），所以"gray 省功耗"这条**测不了**，
   本轮只能测 ONEHOT/BINARY 的面积-延时交叉点。
