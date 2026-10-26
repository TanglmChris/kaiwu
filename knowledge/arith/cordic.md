# CORDIC（坐标旋转数字计算机）

- **类别**：算术单元
- **一句话**：用一串固定角度的伪旋转逼近任意旋转，每步只需要移位和加减法，
  于是三角函数、开方、对数、除法全都不需要乘法器。
- **典型用途**：sin/cos、atan2、向量取模、极坐标↔直角坐标、
  FFT 旋转因子、开方、指数/对数、矩阵旋转（Givens）。

## 结构

想把向量 `(x, y)` 旋转角度 θ。CORDIC 的做法是把 θ 拆成一串固定角度的和：

```
θ ≈ Σ dᵢ · arctan(2⁻ⁱ),   dᵢ ∈ {−1, +1}
```

之所以选 `arctan(2⁻ⁱ)` 这些角度，是因为旋转这些角度时的迭代式里
**只出现 2⁻ⁱ 的乘法，也就是移位**：

```
x[i+1] = x[i] − dᵢ · y[i] · 2⁻ⁱ
y[i+1] = y[i] + dᵢ · x[i] · 2⁻ⁱ
z[i+1] = z[i] − dᵢ · arctan(2⁻ⁱ)      // z 是剩余角度，查一张常数表
```

每步只有**两次移位、三次加减**，没有乘法器。

两种模式决定 `dᵢ` 怎么选：

- **旋转模式**：让 `z → 0`，即 `dᵢ = sign(z[i])`。输出是旋转后的向量
  → 得到 `sin`/`cos`。
- **向量模式**：让 `y → 0`，即 `dᵢ = −sign(y[i])`。输出是模长和角度
  → 得到 `atan2` 和 `sqrt(x²+y²)`。

Walther（1971）把它统一推广到三种坐标系：**圆周**（三角函数）、
**线性**（乘除法）、**双曲**（sinh/cosh/exp/ln/sqrt），
同一套硬件改几个参数就能算这一大类函数 —— 这是 CORDIC 真正强大的地方。

**增益必须补偿**：伪旋转不保长，每步把模长放大 `sqrt(1+2⁻²ⁱ)`，
n 步累积到常数 **K ≈ 1.64676**。因为是常数，通常预先把输入乘以 1/K
（用 `constant-multiplication.md` 的移位加，仍然不需要乘法器）。

## 关键路径

- **n 位精度需要约 n 次迭代**，这是 CORDIC 的根本代价：**延时 O(n)**。
- 每次迭代：一次加减法 O(log n)（或用 carry-save 做成 O(1)）。
- 三种实现形态：
  - **折叠（迭代）**：一套硬件跑 n 个周期。面积最小，吞吐 1/n。
  - **展开（unrolled）**：n 级串起来，纯组合。延时长但可以任意插流水。
  - **展开 + 流水**：每级一个寄存器，**吞吐 1/周期，延时 n 个周期**。
    这是高吞吐场景的标准做法。

注意展开后每一级的移位量是**编译期常数**，所以是纯接线，不需要桶形移位器
—— 这是展开版比迭代版省的一大块（迭代版需要一个真正的可变移位器）。

## PPA 权衡

- **面积**：迭代版极小（两个加法器 + 一个移位器 + 一张 ROM）。
  展开流水版是 n 倍面积。
- **延时**：O(n)，比查表法慢，比多项式逼近慢。
- **功耗**：迭代版峰值功率低但周期多；流水版反之。
- **对比查找表**：查表 O(1) 但面积随精度指数增长，超过 12～16 位就不现实。
- **对比多项式逼近**：需要乘法器，但级数少。**如果芯片里已经有乘法器，
  多项式通常赢 CORDIC**；CORDIC 的优势场景是"没有乘法器也不想要乘法器"。

## 什么时候选它 / 什么时候别用

- **需要三角函数/开方，但不想放乘法器** → CORDIC。
- **面积极度敏感、延时无所谓** → 迭代版 CORDIC。
- **需要高吞吐** → 展开 + 流水 CORDIC。
- **精度要求低（≤10 位）** → 查表更简单更快，别上 CORDIC。
- **已经有高性能乘法器** → 先算算多项式逼近，很可能更划算。
- **只要一个固定角度的旋转** → 那是常数乘法，见 `constant-multiplication.md`。

## 实现要点与坑

- **收敛范围有限。** 圆周模式只能覆盖约 ±99.7°（= Σ arctan(2⁻ⁱ)），
  超出范围必须先做象限折叠（用符号位判断，预处理一次 ±90°）。
  **这是最常见的 bug 来源**：功能仿真里角度扫得不够广就发现不了。
- **双曲模式必须重复某些迭代**（i = 4, 13, 40, …）才收敛，
  这是双曲 CORDIC 特有的，照抄圆周模式的循环会算错。
- **增益 K 的补偿别忘了**，而且**迭代次数变化时 K 也变** ——
  可配置迭代次数的设计里，K 要跟着变，不能写死。
- **定点精度**：z 的角度表、x/y 的位宽、以及移位带来的截断误差要一起算。
  一般内部位宽要比目标精度多 log₂n 位保护位。
- **结构不会被综合抹平**（不是简单的算术恒等式），所以不需要 `keep_hierarchy`
  —— CORDIC 是本知识库里少数不用担心这条的电路之一。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module CORDIC #(
    parameter DAT_W  = 16,
    parameter ITER_N = 16,
    parameter MODE   = "ROTATION",   // ROTATION | VECTORING
    parameter SYSTEM = "CIRCULAR",   // CIRCULAR | LINEAR | HYPERBOLIC
    parameter SCHEME = 2             // 0 ITERATIVE | 1 UNROLLED | 2 PIPELINED
)(input clk, rst_n, input signed [DAT_W-1:0] i_x0, i_y0, i_z0,
  output signed [DAT_W-1:0] o_xn, o_yn, o_zn);
    localparam SCHEME_ITERATIVE = 0;
    localparam SCHEME_UNROLLED  = 1;
    localparam SCHEME_PIPELINED = 2;
```

`SCHEME`（架构）这一维特别值得扫：**同一个功能、三种架构、PPA 差一个数量级**，
正好对应 `../arch-technique/` 里"折叠 vs 展开 vs 流水"的范式对比。
CORDIC 是演示这组权衡最干净的载体之一。

## 出处

- [The CORDIC Trigonometric Computing Technique](https://scispace.com/papers/the-cordic-trigonometric-computing-technique-wn9d8b23g9)
  — J. E. Volder, IRE Trans. Electronic Computers, vol. EC-8, no. 3, pp. 330–334,
  Sept. 1959。原始出处。当年是为 B-58 轰炸机的导航计算机做的。
- [A unified algorithm for elementary functions](https://dl.acm.org/doi/abs/10.1145/1478786.1478840)
  — J. S. Walther, Spring Joint Computer Conference, May 1971, pp. 379–385。
  **三种坐标系的统一框架出自这篇**，要做通用 CORDIC 必读。
- [The Story of Unified CORDIC](https://link.springer.com/article/10.1023/A:1008162721424)
  — Walther 本人回顾统一 CORDIC 的由来，J. Signal Processing Systems, 2000。
- [The Birth of CORDIC](https://www.researchgate.net/publication/220540784_The_Birth_of_Cordic)
  — Volder 本人回顾 CORDIC 的诞生。这两篇回顾比原论文好读得多，建议先看。

## 本地实测

暂无。如果要做，建议用 `ARCH` 三档（迭代 / 展开 / 流水）作为第一组实验 ——
它是"面积换吞吐"这个范式最干净的量化案例。
但注意迭代版和流水版都是**多周期**设计，和 `division.md` 一样会需要握手信号，
流程要先泛化过。
