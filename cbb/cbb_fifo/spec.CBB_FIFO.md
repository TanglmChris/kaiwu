# CBB_FIFO 规格

> 出处：用户 2026-09-29 定；`PT_EN = 1` 的 ready 改为满时下游当拍取走仍接收（内部#256，用户 2026-10-09）。

## 功能

同步 FIFO，两侧都是 valid/ready 握手，带占用计数与将满 / 将空标志。空时直通与
多一拍两种 FIFO 合为本构件，由 `PT_EN` 选择 —— 两者功能相同、
只有时序不同，符合「FIFO 用哪种只影响时序、不影响功能」。计数与水线供调用方做水线判断、
预留计数使用。

## 接口

| 信号 | 方向 | 位宽 | 含义 |
|---|---|---|---|
| `clk` | in | 1 | 时钟 |
| `rst_n` | in | 1 | 异步复位，低有效 |
| `i_clr` | in | 1 | 同步清空；不用时固接 0 |
| `i_src_vld` | in | 1 | 上游 valid（写） |
| `o_src_rdy` | out | 1 | 上游 ready：`PT_EN = 0` 时为「未满」；`PT_EN = 1` 时为「未满，或下游本拍取走」（`~full \| i_dst_rdy`） |
| `i_src_dat` | in | `DAT_W` | 上游数据 |
| `o_dst_vld` | out | 1 | 下游 valid：`PT_EN = 0` 时为「非空」；`PT_EN = 1` 时为「非空，或上游本拍有数」 |
| `i_dst_rdy` | in | 1 | 下游 ready（读） |
| `o_dst_dat` | out | `DAT_W` | 下游数据；`o_dst_vld = 0` 时为 X |
| `i_af_lvl` | in | `$clog2(FIFO_DEP_N)+1` | 将满水线；静态配置，不用时固接常数 |
| `i_ae_lvl` | in | `$clog2(FIFO_DEP_N)+1` | 将空水线；静态配置，不用时固接常数 |
| `o_cnt` | out | `$clog2(FIFO_DEP_N)+1` | 占用计数；不用时悬空 |
| `o_afull` | out | 1 | `o_cnt >= i_af_lvl` |
| `o_aempty` | out | 1 | `o_cnt <= i_ae_lvl` |
| `o_overflow` | out | 1 | 被挡住的写请求：`i_src_vld & ~o_src_rdy`；组合脉冲 |
| `o_underflow` | out | 1 | 空时有读请求：`i_dst_rdy & ~o_dst_vld`；组合脉冲 |

不单独输出 full / empty：由 `o_cnt` 看出（满 = `o_cnt == FIFO_DEP_N`，空 = `o_cnt == 0`）。`PT_EN = 0` 时它们也分别就是
`~o_src_rdy` 与 `~o_dst_vld`；`PT_EN = 1` 时不是（满且下游本拍取走时 `o_src_rdy = 1`，空且上游有数时 `o_dst_vld = 1`）。

`o_overflow` / `o_underflow` 按握手用时只表示「正在被反压 / 下游在等数据」，不代表出错；调用方
如果把 `i_src_vld` 当成不看 `o_src_rdy` 的 push（或把 `i_dst_rdy` 当成 pop）来用，它们就是真正
丢数据 / 读空的那一拍。两者都不寄存，要记住就由调用方自己锁存。`PT_EN = 1` 直通的那一拍
`o_dst_vld = 1`，下游读不算 underflow；`PT_EN = 1` 满且下游本拍取走的那一拍 `o_src_rdy = 1`，上游写不算 overflow。

## 时序约定

| `PT_EN` | 空时的行为 | `i_src_vld` → `o_dst_vld` |
|---|---|---|
| 0 | 数据先写进存储，下一拍才出现在输出 | 1 拍 |
| 1 | 为空且 `i_src_vld = 1` 时，`o_dst_vld` / `o_dst_dat` 组合直通 `i_src_vld` / `i_src_dat`；下游当拍收下则不写入存储，没收下则写入 | 0 拍 |

- **`o_src_rdy`**：
  - `PT_EN = 0`：`~full`，由寄存器状态决定，与 `i_dst_rdy` 之间没有组合路径。代价：满的那一拍即使下游
    同时在取，也不接收新数据。
  - `PT_EN = 1`：`~full | i_dst_rdy`。满的那一拍下游同时在取，就照样接收：计数不变，读写指针各进一格，
    新数据写进刚被取走的那一项。`i_dst_rdy` → `o_src_rdy`（以及 `o_overflow`）有组合路径，调用方要避免
    由此在外部成环（内部#258）。
- **输出不加寄存器**：`PT_EN = 0` 时 `o_dst_dat` 由存储阵列经一个 `FIFO_DEP_N` 选 1 给出，输出
  路径上有这级选择器。
- **`o_cnt` 是寄存值**：当前还没被下游取走的项数，不含本拍的写入与读出。`PT_EN = 1` 时，直通且
  当拍被收下的那一笔不计入；直通但没被收下的那一笔写入存储，下一拍起计入。
- **`o_afull` / `o_aempty` 是组合输出**，由寄存值 `o_cnt` 与两条水线比较得到，比较都含等于。
  因为 `o_cnt` 是寄存值、水线是静态的，这条路径上只有一个比较器，也不会与本拍的进出成环。
- **水线是静态配置**：工作期间 MUST NOT 改变；改变时 `o_afull` / `o_aempty` 的值没有定义。
  水线取任何值都允许，但 `i_af_lvl = 0` 时 `o_afull` 恒为 1、`i_af_lvl > FIFO_DEP_N` 时恒为 0，
  `i_ae_lvl >= FIFO_DEP_N` 时 `o_aempty` 恒为 1 —— 这样用没有意义。
- **`i_clr` 下一拍生效**：清空那一拍的全部输出照常（含 `PT_EN = 1` 的直通，下游当拍收下就算
  送达）；下一拍起 `o_cnt = 0`、存储为空。清空那一拍写进存储的数据（没有被直通送走的）丢弃；
  清空那一拍 `o_src_rdy` 照常按上面的规则输出（`i_clr` 不进 ready：`PT_EN = 1` 满且下游取走时仍为 1）。
- **保序、不丢、不重**（两次 `i_clr` 之间，A9）；`o_dst_vld = 1` 之后在握手之前 `o_dst_vld` 与 `o_dst_dat` 保持不变
  （`i_clr` 那一拍之后不保，A6）。
- 复位后 `o_cnt = 0`、`o_src_rdy = 1`；`o_dst_vld` 在 `PT_EN = 0` 时为 0，`PT_EN = 1` 时等于 `i_src_vld`（直通，A8）。

### 吞吐与深度

- 下游一直 ready 时，任何合法深度都能每拍过一笔。
- 吞吐只在 FIFO **满**时损失：`PT_EN = 0` 满的那一拍上游进不来，即使下游同拍取走一项；`PT_EN = 1`
  只有满且下游这一拍不取时才挡。
- 从稳态开始的**一次**停顿：下游停顿最长 S 拍、上游在停顿期间一直送数时，要让上游一拍都不被挡：
  `PT_EN = 0` 需要 `FIFO_DEP_N >= S + 2`，`PT_EN = 1` 需要 `FIFO_DEP_N >= S`。
  （`PT_EN = 0` 稳态时存储里始终压着 1 项，停顿结束那一拍存储里有 S + 1 项、还要未满；`PT_EN = 1`
  稳态时直通、存储为空，停顿结束那一拍存储里有 S 项，满也照收。由上面的 ready 规则推出，不是另外的出处。）
  前提是停顿前处在稳态：停顿结束后上游若仍每拍送数，存储里的积压不会消退，下一次停顿要把积压算进去。

### 断言

下面各条对任意输入序列成立（`i_clr` 那一拍的下一拍另算，见 A5）。RTL 落地时写进 TB / 形式检查。

| # | 断言 |
|---|---|
| A1 | `o_cnt <= FIFO_DEP_N` |
| A2 | `o_src_rdy == (o_cnt != FIFO_DEP_N) \| (PT_EN && i_dst_rdy)` |
| A3 | `PT_EN = 0`：`o_dst_vld == (o_cnt != 0)`；`PT_EN = 1`：`o_dst_vld == (o_cnt != 0) \| i_src_vld` |
| A4 | `o_afull == (o_cnt >= i_af_lvl)`，`o_aempty == (o_cnt <= i_ae_lvl)` |
| A5 | 下一拍的 `o_cnt`：本拍 `i_clr = 1` 时为 0；否则为本拍 `o_cnt` + 写进存储的项数 − 从存储取走的项数 |
| A6 | `o_dst_vld && !i_dst_rdy && !i_clr` 的下一拍：`o_dst_vld` 仍为 1，`o_dst_dat` 不变 |
| A7 | `o_overflow == (i_src_vld && !o_src_rdy)`，`o_underflow == (i_dst_rdy && !o_dst_vld)` |
| A8 | 复位释放后的第一拍：`o_cnt == 0`、`o_src_rdy == 1`、`o_dst_vld == i_src_vld && PT_EN` |
| A9 | 保序、不丢、不重：两次 `i_clr` 之间，下游收下的序列是上游送进的序列的前缀（由 TB 的记分板检查） |
| A10 | 环境假设：复位释放后 `i_af_lvl` / `i_ae_lvl` 保持不变 |

`sim.cycles` 的定义：带握手的构件进 PPA 流程之前，`sim.cycles` 的口径要先泛化（内部#7，
`docs/data-credibility.md` 的 C-6），届时在这里补上。

## 参数

| 参数 | 取值 | 默认 | 含义 |
|---|---|---|---|
| `DAT_W` | >= 1 | 32 | 数据位宽 |
| `FIFO_DEP_N` | 2 的幂，>= 2 | 4 | 深度（项数） |
| `PT_EN` | 0 / 1 | 0 | 1：空时直通（原 `CBB_PTFIFO`）；0：多一拍（原 `CBB_CFIFO`） |
| `RST_EN` | 0 / 1 | 0 | 1：数据存储也复位；0：只复位指针、计数等控制状态 |

地址宽度不是参数，由 `$clog2(FIFO_DEP_N)` 算出；计数与水线比它多一位，才能表示「满」。

## 实现要点

- 存储每项一个 always（`GEN_FOR`），写使能是 `wr_en` 按写指针移位得到的 one-hot `wr_sel`；`RST_EN = 1` 时按项复位。读出直接用数组下标 `mem_r[rd_ptr_r]`（深度可变，展不成固定的与或式）。
- 满 = `cnt_r == FIFO_DEP_N`，空 = `cnt_r == 0`；`PT_EN = 0` 时 `o_src_rdy = ~full` 只看寄存器，`PT_EN = 1` 时
  `o_src_rdy = ~full | i_dst_rdy`。满时同拍一进一出：`wr_en` 与 `rd_en` 同为 1，计数不变，两个指针各进一格。
- `PT_EN = 1` 时空且下游当拍收下则不写存储（直通）；否则写入。
- `i_clr` 把读写指针与计数一起清零（下一拍生效）。

## 不做

- 非 2 的幂深度。
- `PT_EN = 0` 时满时同拍一进一出（那样 `o_src_rdy` 就组合依赖 `i_dst_rdy`）。
- 跨时钟域（异步 FIFO）。
- 运行时可改的水线。
- 输出寄存器（预取）。
- 寄存或粘住的 overflow / underflow 标志。
