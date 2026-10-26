# 除法器（Restoring / Non-restoring / SRT / 乘法迭代）

- **类别**：算术单元
- **一句话**：除法是四则运算里唯一没有便宜并行解的，所以第一反应应该是
  "能不能不做除法"，实在要做再在减法迭代和乘法迭代之间选。
- **典型用途**：定点/浮点除法、求余、归一化、倒数。

## 结构

两大流派。

### 一、减法迭代（digit recurrence）

每次迭代产出固定几位商，靠"试减"决定商位：

```
R[j+1] = r·R[j] − q[j+1]·D        // r 是基，D 是除数
```

- **Restoring（恢复余数）**：减了发现负，就加回去。每位要两次操作，慢。
- **Non-restoring（不恢复余数）**：负了就下一步改成加，商位取 −1。
  商用 {−1, +1} 表示，最后转换成常规二进制。每位一次操作。
- **SRT（Sweeney–Robertson–Tocher）**：非恢复法的推广，也是**实用的那个**。
  两个关键改进：
  1. **冗余商数字集**（比如 radix-4 用 {−2,−1,0,1,2}），使得商位选错一点
     后面还能补救；
  2. 因此**只需要看部分余数的高几位**就能定商位 —— 于是部分余数可以保持
     **carry-save 形式**，迭代里不需要全宽进位传播。
  商位由一张查找表（P-D 图）给出，输入是部分余数和除数的高几位。
  radix-r 每次出 log₂r 位商。

### 二、乘法迭代（functional iteration）

- **Newton-Raphson**：先算 `1/D` 的近似，迭代 `x_{k+1} = x_k(2 − D·x_k)`，
  **二次收敛**（每次迭代精度翻倍），然后乘以被除数。
- **Goldschmidt**：同时缩放分子分母，迭代更适合流水。

这类方法**用乘法器换延时**：如果芯片里已经有一个高性能乘法器（比如为了 MAC），
除法几乎白送；如果没有，为了除法专门放一个乘法器就很贵。

## 关键路径

- Restoring / Non-restoring radix-2：**n 次迭代**，每次一个全宽加减法 O(log n)
  → 总延时 O(n log n)，很慢。
- SRT radix-r：**n / log₂r 次迭代**，每次只有 CSA + 一次小查表 → 每次 O(1)。
  radix-4 就是 n/2 次。这是定点除法器的主流。
- Newton-Raphson：**O(log n) 次迭代**，每次一到两个全宽乘法。
  迭代次数少但每次很贵。

**没有 O(log n) 总延时的除法器。** 这是除法和加法/乘法的根本区别，
选型时要接受这个前提。

## PPA 权衡

- **SRT 提高基（radix）能减少迭代次数，但查找表会指数级变大**，
  而且商位选择逻辑进了迭代环路，基太高会让每次迭代变慢。
  radix-4 / radix-8 是常见落点，再往上通常靠"两级 radix-4 叠加"实现。
- **面积**：SRT 小（一个 CSA + 查表 + 寄存器），Newton-Raphson 大（要乘法器）
  但可以复用已有乘法器。
- **功耗**：迭代型除法器周期多，总能量往往不低，尽管峰值功率小。
- **流水化**：Newton-Raphson / Goldschmidt 容易流水；SRT 是紧耦合反馈环，
  难流水（可以做多路交织提吞吐，但单次延时降不下来）。

## 什么时候选它 / 什么时候别用

**优先级从高到低：**

1. **除数是 2 的幂** → 移位。别做除法。
2. **除数是编译期常数** → 乘以倒数再移位（魔数除法）。别做除法。
3. **只需要低精度** → 查表 + 少量修正。
4. **已经有高性能乘法器** → Newton-Raphson / Goldschmidt。
5. **面积敏感、没有现成乘法器** → SRT radix-4。
6. **位宽很小（≤8）或者延时完全不敏感** → non-restoring，简单不出错。

实际优化时，**第 1、2 条能砍掉的除法器远比优化除法器值钱**。
看到关键路径上有 `/`，先花五分钟确认它是不是真的需要。

## 实现要点与坑

- **SRT 的查找表是历史上出过大事故的地方。** 1994 年 Intel Pentium 的 FDIV bug
  就是 SRT 商位选择表里少了几个表项，导致特定输入下除法结果错误，最终召回。
  教训很直接：**这张表必须穷举验证，不能靠随机测试**。表项数量有限，
  形式化或穷举都做得到，不做就是在赌。
- **验证要专门覆盖**：除数为 0、被除数为 0、最负值 / −1（补码溢出）、
  商刚好在边界、余数为 0。这些点比随机向量重要得多。
- **符号与余数约定要先定死**：截断除法还是向下取整？余数符号跟被除数还是除数？
  不同语言/规范不一样，写之前定，写完在文档里写清楚。
- **carry-save 部分余数** 是 SRT 快的关键，别为了图省事改成全宽相加，那会
  把每次迭代变成 O(log n)，退化成非恢复法。
- **除法器很难被综合工具"优化掉"**，所以 `keep_hierarchy` 在这里不是必需的
  —— 但如果你写的是 `a / b` 让工具自己实现，那结构就完全不是你的了。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module DIVIDER #(
    parameter DAT_W     = 32,
    parameter SCHEME    = 3,        // 0 RESTORING | 1 NONRESTORING | 2 SRT2 | 3 SRT4 | 4 NEWTON
    parameter SIGNED_EN = 1
)(input clk, rst_n, input i_start, input [DAT_W-1:0] i_a, i_b,
  output [DAT_W-1:0] o_q, o_r, output o_done);
    localparam SCHEME_RESTORING    = 0;
    localparam SCHEME_NONRESTORING = 1;
    localparam SCHEME_SRT2         = 2;
    localparam SCHEME_SRT4         = 3;
    localparam SCHEME_NEWTON       = 4;
```

注意除法器是**多周期**的，接进本仓库现有流程时要留意：
`run_experiment.py` 目前的 testbench 假设是组合/短流水的加法器，
除法器需要握手信号和 `done`，`sim` 那一环的 cycles 统计含义也会变。
**这是第一个会逼着流程泛化的设计**，值得留意。

## 出处

- [SRT Division: Architectures, Models, and Implementations](https://pages.hmc.edu/harris/research/srtlong.pdf)
  — D. Harris, S. Oberman, M. Horowitz。**想真正搞懂 SRT 就读这篇**，
  把商位选择、P-D 图、基的选择讲得很实在，作者主页公开 PDF。
- [SRT division architectures and implementations](https://ieeexplore.ieee.org/abstract/document/614875/)
  — Harris & Oberman, ARITH-13, 1997。上一篇的会议版。
- J. E. Robertson, "A new class of digital division methods",
  IRE Trans. Electronic Computers, vol. EC-7, pp. 218–222, Sept. 1958.
  —— SRT 里的 R。S 是 IBM 的 D. W. Sweeney（1957），T 是帝国理工的
  K. D. Tocher（1958），三人各自独立提出，故合称 SRT。
- [Division algorithm（Wikipedia）](https://en.wikipedia.org/wiki/Division_algorithm)
  —— 各类方法的速查和 Pentium FDIV 事故的来龙去脉，适合先扫一遍建立地图。

## 本地实测

暂无。**优先级建议排在加法器/乘法器之后** —— 除法器是多周期设计，
会逼着 `flow/sim` 和记录 schema 做泛化（握手、`done`、cycles 语义），
在流程还没为多周期设计准备好之前先做它，会同时调试两件事。
