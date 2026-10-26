# 常数乘法（移位加 / CSD / 多常数共享）

- **类别**：算术单元
- **一句话**：乘数是常数时整个乘法器都可以拆掉，换成几个移位和加减法；
  用 CSD 编码能把加法器个数压到最少。
- **典型用途**：FIR / IIR 滤波器抽头、FFT 旋转因子、色彩空间转换、
  定点缩放、任何"乘一个固定系数"的地方。

## 结构

`y = 13 · x`。13 = `1101₂` = 8 + 4 + 1，所以

```
y = (x << 3) + (x << 2) + x        // 两个加法器，零个乘法器
```

移位在硬件里是**免费的**（只是接线），所以代价 = 非零位的个数 − 1 个加法器。

**CSD（Canonical Signed Digit）**把这个进一步压缩。允许数字取 `{0, +1, −1}`，
并要求**任意两个相邻位不能同时非零**。这样每个常数有唯一表示，且**非零位数最少**。

关键在于长串的 1 可以折叠：

```
15 = 1111₂        → 三个加法器
15 = 10000₂ − 1   → CSD: 1 0 0 0 -1  → 一个减法器：(x << 4) − x
```

n 位数的 CSD 表示平均非零位数约 n/3，而普通二进制是 n/2 —— **平均省三分之一的加法器**。

**多常数共享（MCM，Multiple Constant Multiplication）**：要同时算
`7x, 11x, 13x` 时，可以先算一个公共子表达式再复用。这类问题是 NP-hard，
但有成熟的启发式算法，滤波器设计工具都在用。

## 关键路径

- 加法器个数 = 非零数字数 − 1，这些加法器排成**树**而不是链，
  所以延时是 O(log(非零位数))，通常只有两三级。
- 对比通用乘法器的 O(log n) 压缩树 + O(log n) CPA，常数乘法通常**快一个档次**。

## PPA 权衡

- **面积**：断崖式下降。32×32 通用乘法器几千个门，常数乘法通常几个加法器。
- **延时**：显著下降。
- **功耗**：同样断崖式下降。
- 这是本卡列表里**收益/代价比最高的一条技巧**，没有之一。
- 唯一代价：常数一旦要变就得重新综合，失去了运行时灵活性。

## 什么时候选它 / 什么时候别用

- **系数在综合期已知** → 一定用。
- **系数只有少数几种取值** → 每种做一份，用 mux 选，通常仍然比通用乘法器省。
- **系数运行时任意可变** → 用不了，老实上乘法器。
- **系数可变但变化不频繁**（比如配置寄存器） → 权衡：可重构常数乘法器是
  一个真实的研究方向，但复杂度高，多数场合不值。

## 实现要点与坑

- **综合工具已经会做基本的常数折叠。** 写 `y = 13 * x`，DC 和 yosys 都会
  自动展开成移位加，**不需要你手写**。所以：
  - 手写 CSD 的价值主要在**工具做不好的地方**：多常数共享、
    特别长的常数、以及你想精确控制加法器树形的时候。
  - **务必先测一遍工具的自动结果再决定要不要手写**。本仓库的原则是
    数字说话，这条尤其适用 —— 手写了不一定更好。
- **加法器树的形状影响延时**：把 `a+b+c+d` 写成 `(a+b)+(c+d)` 而不是
  `((a+b)+c)+d`。工具通常会帮你平衡，但在关键路径上值得手工确认。
- **位宽增长**：每个加法器的输出比输入宽 1 位，要算清最终位宽，
  或者明确定义截断/舍入规则。定点设计里舍入策略往往比乘法本身更容易出错。
- **负系数**用减法器，硬件代价和加法器一样。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module CONST_MULT #(
    parameter DAT_W  = 16,
    parameter CONST  = 13,
    parameter SCHEME = 1        // 0 NAIVE_SHIFT_ADD | 1 CSD | 2 TOOL（直接写 * 让工具做）
)(input [DAT_W-1:0] i_dat, output [DAT_W+$clog2(CONST)-1:0] o_dat);
    localparam SCHEME_NAIVE_SHIFT_ADD = 0;
    localparam SCHEME_CSD             = 1;
    localparam SCHEME_TOOL            = 2;
```

`SCHEME = 2`（TOOL）这一档很重要 —— 它就是"直接写 `CONST * i_dat`"，
用来做**对照组**。本仓库的实验设计里，这类"人写 vs 工具做"的对照
应该成为习惯，而不是只比人写的几种变体。

## 出处

- [An Introduction to Canonical Signed Digit Representation](https://www.allaboutcircuits.com/technical-articles/an-introduction-to-canonical-signed-digit-representation/)
  — All About Circuits 技术文章。CSD 的定义、转换算法和例子，入门够用。
- [Canonic Signed Digit (CSD) Representation of Integers](https://www.dsprelated.com/showarticle/1030.php)
  — Neil Robertson, DSPRelated。带可运行的转换代码，适合直接拿来生成系数。
- [Optimally Solving the MCM Problem Using Pseudo-Boolean Satisfiability](https://arxiv.org/pdf/1011.2685)
  — 多常数乘法的最优解法（arXiv 公开）。想了解 MCM 问题本身的难度和
  现有方法边界，从这篇的相关工作一节切入。

## 本地实测

暂无。**建议作为早期实验之一**：`SCHEME` 三档（朴素移位加 / CSD / 交给工具）
在同一个常数上对比，实验成本极低（组合电路、无需握手），
而且能顺便回答一个对整个项目都重要的问题：**yosys 的自动优化有多强？**
这个答案会影响后面所有"要不要手写结构"的判断。
