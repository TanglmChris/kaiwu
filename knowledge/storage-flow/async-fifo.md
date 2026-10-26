# 异步 FIFO（Asynchronous FIFO）

- **类别**：存储与流控
- **一句话**：跨时钟域高吞吐传数据的标准答案 —— 靠**格雷码指针**让多位指针
  能安全跨域，靠"保守的空/满"保证宁可少报也绝不多报。
- **典型用途**：跨时钟域数据通路、异步接口桥、多时钟 SoC 的模块边界。

## 结构

存储体是双口 RAM：写口在写时钟域，读口在读时钟域，**存储体本身不跨域**
（两个口各自同步）。真正跨域的只有两个指针。

```
写域                              读域
wptr(bin) ──► wptr(gray) ──同步──► wptr_gray_s
                                      │
                                   empty 判断
rptr_gray_s ◄──同步── rptr(gray) ◄── rptr(bin)
   │
 full 判断
```

### 为什么必须是格雷码

二进制指针从 `0111` 变到 `1000` 时四位同时翻转。跨域采样如果落在变化点上，
每一位独立地取到旧值或新值 —— 可能采到 `1111`、`0000` 等**从未存在过的值**。
指针错了，空/满判断就错了，数据就丢了或重复了。

格雷码保证相邻值只差一位，采样时只有那一位可能不确定，
所以结果**要么是旧值要么是新值**，二者都是真实出现过的指针，都安全。

### 空/满判断

指针宽度同样是 `$clog2(DEPTH) + 1`（多一位表示圈数），
但判断要在**格雷码域**上做：

```
empty = (rptr_gray == wptr_gray_s)                       // 完全相等

full  = (wptr_gray[MSB]   != rptr_gray_s[MSB])   &&      // 最高两位都翻转
        (wptr_gray[MSB-1] != rptr_gray_s[MSB-1]) &&
        (wptr_gray[MSB-2:0] == rptr_gray_s[MSB-2:0])
```

满的判断要比较**最高两位**，因为格雷码的高位翻转规律和二进制不同。
这是异步 FIFO 最容易写错的一行。

### 保守性 —— 这是它能工作的关键

同步器有 2~3 拍延迟，所以：

- 写域看到的读指针是**过时的**（读侧可能已经又读走了几个），
  所以 `full` 可能**误报满**，但绝不会漏报满 → 不会写溢出。
- 读域看到的写指针也是过时的，所以 `empty` 可能**误报空**，
  但绝不会漏报空 → 不会读到无效数据。

**两个方向的误差都指向安全的一侧。** 这不是巧合，是设计出来的：
指针单调递增，过时的值总是"更小"，而更小的写指针意味着更空、
更小的读指针意味着更满。

## 关键路径

- 存储体读写：各自域内，正常时序。
- 指针增量 + 二进制转格雷码：`gray = bin ^ (bin >> 1)`，一层 XOR，很浅。
- 空/满比较：O(log DEPTH)。
- **跨域路径必须在 SDC 里约束**（`set_false_path` 或
  `set_max_delay -datapath_only`），否则工具按同步路径算，
  时序永远收不了 —— 或者更糟，工具忽略它而实际延迟失控。

## PPA 权衡

- 存储体主导面积，同 [`sync-fifo.md`](sync-fifo.md)。
- **额外开销**：两组格雷码转换 + 两组同步器，面积可以忽略。
- **延迟明显高于同步 FIFO**：数据本身只过一次存储，
  但空/满标志有 2~3 拍滞后，等效于 FIFO 的可用深度被"吃掉"几个。
  **深度必须留出这个余量**，DEPTH=2 的异步 FIFO 几乎没有吞吐。
- 深度太浅时吞吐会被同步延迟卡住，经验上至少 DEPTH ≥ 8 才谈得上流畅。

## 什么时候选它 / 什么时候别用

- **跨时钟域 + 需要吞吐** → 异步 FIFO，没有更好的选择。
- **跨时钟域 + 偶尔传几个字** → 握手同步器更省，
  见 [`cdc-synchronizers.md`](cdc-synchronizers.md)。
- **同时钟域** → 同步 FIFO，别用异步版（白付同步延迟）。
- **两个域是同源分频（比如 100MHz 和 50MHz 来自同一 PLL）** →
  严格说不需要异步 FIFO，可以用使能信号做单域设计，但**前提是相位关系
  真的确定且被约束住**。判断错的代价很大，不确定就用异步 FIFO。

## 实现要点与坑

- **满判断比较最高两位**，不是一位。写成一位是最常见的实现错误。
- **格雷码指针不能直接用来寻址存储体**，要用二进制指针的低位。
  两份指针（bin 和 gray）都要维护。
- **复位**：两个域各自的复位必须都做，且要考虑一个域先复位、
  另一个域还在跑的情况。见 [`reset-strategy.md`](reset-strategy.md)。
- **DEPTH 必须是 2 的幂**，理由同同步 FIFO 的指针法，
  格雷码更是强依赖这一点。
- **不要在跨域路径上加任何组合逻辑**。指针同步器的输入必须直接来自
  格雷码寄存器输出。
- **仿真测不出 CDC 错误**：一个满判断写错一位的异步 FIFO，
  在 RTL 仿真里可能跑几百万拍都不出错，硅上偶发丢数据。
  必须靠 CDC 静态检查。**本仓库没有这个能力**（见
  [`cdc-synchronizers.md`](cdc-synchronizers.md)）。
- **不需要 `keep_hierarchy`**，但跨域路径的约束是必需的。

## 参数化接口建议

> 接口按本仓 RTL 命名约定写（`rtl-structure-authority`，2026-09-28）：参数 `DAT_W` / `*_W` / `*_N` / `*_EN` / `SCHEME`，端口 `i_` / `o_` 前缀，握手 `i_vld/o_rdy/o_vld/i_rdy`。

```verilog
module ASYNC_FIFO #(
    parameter DAT_W       = 32,
    parameter DEPTH       = 16,        // 必须是 2 的幂，且建议 >= 8
    parameter SYNC_STAGES = 2
)(
    input  wr_clk, wr_rst_n,           // 多时钟口按 <域>_clk / <域>_rst_n 命名
    input  i_wr_vld, output o_wr_rdy, input [DAT_W-1:0] i_wr_dat,
    input  rd_clk, rd_rst_n,
    output o_rd_vld, input  i_rd_rdy, output [DAT_W-1:0] o_rd_dat
);
```

## 出处

- Clifford E. Cummings, "Simulation and Synthesis Techniques for Asynchronous
  FIFO Design", SNUG San Jose 2002 —— 格雷码指针法、多一位判满、
  保守性论证的原始出处，附完整可综合 Verilog。
- Clifford E. Cummings & Peter Alfke, "Simulation and Synthesis Techniques for
  Asynchronous FIFO Design with Asynchronous Pointer Comparisons",
  SNUG San Jose 2002 —— 另一种判满方案（异步比较），
  权衡与上一篇不同。

这两篇是异步 FIFO 事实上的标准参考，公开可得。

## 本地实测

暂无，**且当前流程做不了**：`flow/sim` 与 `flow/sta` 都是单时钟假设
（`create_clock` 只建一个时钟，`run_sta.py` 里写死 `clk` 端口）。
要测异步 FIFO 必须先支持多时钟约束，这是一件独立的流程工作，
不该和某个具体设计的调试混在一起（`arith/` 结尾也提过同样的判断）。

即使流程支持了，**PPA 数字对异步 FIFO 的意义也有限** ——
它的价值在正确性和吞吐，不在面积延时。优先级应低于组合逻辑类的实验。
