# CBB_FIFO 验证

验证状态：已验证（`tb/test_CBB_FIFO.py`：`params.yaml` 全部 24 组参数各 800 拍，逐拍对照周期级参考模型；`tb/tb_cbb_fifo_directed.sv`：深度 2 / 8 × `PT_EN` 0 / 1 定向用例，内部#256）

## 现状（2026-10-01）

`tb/test_CBB_FIFO.py`（cocotb）逐拍对照周期级参考模型：`params.yaml` 声明的全部 24 组参数（`DAT_W` 1/32 × `FIFO_DEP_N` 2/4/16 × `PT_EN` × `RST_EN`）各跑 800 拍，全部通过。它同时是流程的 RTL 仿真 TB：动态功耗的活动率来自它的 VCD。

## 激励

- 复位前取随机的静态水线 `i_af_lvl` ∈ [1, `FIFO_DEP_N`]、`i_ae_lvl` ∈ [0, `FIFO_DEP_N`-1]（A10）。
- 三段：先灌满（写 0.9、读 0.2）、再抽空（写 0.2、读 0.9）、最后随机（0.6 / 0.6），每拍 1% 的概率插 `i_clr`；满、空、直通、反压、清空都出现。
- 固定种子（由参数推出），同一组参数每次跑的激励相同。

## 检查（逐拍）

| 断言 | 怎么查 |
|---|---|
| A1–A4、A7 | 每拍 ReadOnly 阶段，`o_cnt` / `o_src_rdy` / `o_dst_vld` / `o_afull` / `o_aempty` / `o_overflow` / `o_underflow` 与模型逐位相同 |
| A5 | 模型按「写进存储的项 − 取走的项」推进，`i_clr` 下一拍清空；下一拍的 `o_cnt` 对得上即成立 |
| A6 | `o_dst_vld = 1` 时 `o_dst_dat` 必须等于模型的队首（未握手则下一拍队首不变） |
| A8 | 复位释放后第一拍 `o_cnt == 0`、`o_src_rdy == 1` |
| A9 | 记分板：两次 `i_clr` 之间下游收下的序列是上游送进序列的前缀 |

TB 的检出能力验过：把模型里 `o_afull` 的 `>=` 改成 `>`，第一组参数当场报 `o_afull = 1，期望 0`。

2026-10-14（内部#256）模型的 `o_src_rdy` 改成「未满，或 `PT_EN = 1` 且下游本拍取走」，激励不变（这份 TB 的 VCD 是动态功耗的
活动率来源，激励不动）。新 RTL 上 24 组全过；旧 RTL（`o_src_rdy = ~full`）配新模型，`PT_EN = 1` 的 12 组全部失败。

## 定向用例（`tb/tb_cbb_fifo_directed.sv`，内部#256）

不进流程（流程只跑 `test_CBB_FIFO.py`）。跑法：

```bash
iverilog -g2012 -s tb -o tb.vvp cbb/cbb_fifo/tb/tb_cbb_fifo_directed.sv cbb/cbb_fifo/rtl/cbb_fifo.v && vvp -n tb.vvp
```

四个实例：`FIFO_DEP_N` 2 / 8 × `PT_EN` 0 / 1（`RST_EN` 两种各占一半），`DAT_W = 8`、`i_af_lvl = FIFO_DEP_N`、`i_ae_lvl = 0`。
每拍把全部输出与一个环形缓冲模型比，`o_dst_vld = 1` 时比 `o_dst_dat`。激励按段：

| 段 | 激励 | 覆盖 |
|---|---|---|
| 复位 | 复位 3 拍后释放 | A8 |
| 空时直通 | 空、上游有数、下游收 | `PT_EN = 1` 直通不写存储 |
| 空时存储 | 上游有数、下游不收 | 写进存储 |
| 保持 | 都不动 | A6 |
| 灌满 | 上游一直送、下游不收，满后再送 2 拍 | 满、overflow |
| 满时同拍出入 | 满后上游一直送、下游一直收，`3 × FIFO_DEP_N + 2` 拍 | `PT_EN = 1` 照收、计数不变；`PT_EN = 0` 被挡；指针绕回 |
| 抽空 | 上游不送、下游一直收 | 空、underflow |
| clear | 送 2 笔后 `i_clr` 与上游有数、下游收同拍 | A5 的清空 |
| 随机 | 300 拍，含 `i_clr` | 混合 |
| 中途复位 | 运行中复位 2 拍，再随机 60 拍 | 第二次 A8 |

每个实例结束时打印各类事件的命中数：`FULL_INOUT`（满时同拍出入，`PT_EN = 1` 要 > 0）、`FULL_RDY_REJ`（满、下游取、上游
被挡，`PT_EN = 0` 要 > 0）、`PT_DIRECT`（`PT_EN = 1` 要 > 0）、`EMPTY_STORE`、`HOLD`、`WRAP`（写入次数 / 深度，要 ≥ 2）、
`CLR`、`RESET`（要 ≥ 2）、`UNDERFLOW`，有 0 的就判 FAIL。

比较用 `!==`，输出为 X / Z 也算不符；有失败或超时由 `$fatal(1, …)` 结束，`vvp` 退出码非 0。

失败臂：旧 RTL（`o_src_rdy = ~full`）上 `PT_EN = 1` 的两个实例在「满时同拍出入」第一拍报 `o_src_rdy = 0, expected 1`，
汇总 `FAIL tb_cbb_fifo_directed: 2 of 4 instances failed`、`vvp` 退出 1；把 `o_afull` 改成 `1'bx` 的变异体第一拍报
`o_afull = X, expected 0`、退出 1；新 RTL 上 `PASS tb_cbb_fifo_directed: 4 instances`、退出 0。

## 全仓通用规范的验证项

`docs/spec-writing.md` 第 3 节的通用规则（模板 `flow/templates/design-root/verify.md`，内部#286）。

| 通用规范 | 覆盖 |
|---|---|
| 握手保持 | 覆盖（A6：`o_dst_vld=1` 未握手时下一拍队首不变） |
| valid 不依赖 ready | 部分（逐拍对照模型；没有做端口组合依赖实测） |
| 汇聚口屏蔽 | 不适用（单通道，没有汇聚口） |
| 活性 | 部分（A9 记分板：下游收下的是上游送进的前缀；没有看门狗） |
| 写数据不等命令 | 不适用（没有命令 / 写数据两条通道） |
| 功能不依赖打拍配置 | 部分（`PT_EN` 取 0 / 1 对同一个模型逐拍比对；`PT_EN = 1` 的 `o_src_rdy` 组合依赖 `i_dst_rdy`，调用方外部成环要自己查） |

## 没做的

- RTL 里 `` `ifdef CBB_ASSERT_ON `` 段的 SVA 还没有在仿真里执行（icarus 不支持并发断言，verilator 仿真待接）。
- 等价检查：两种 `PT_EN` 时序不同，不是组合等价关系。

规格里的断言（`spec.CBB_FIFO.md`）写进了 RTL 末尾的 `` `ifdef CBB_ASSERT_ON `` 段的那些条目，在有 TB 之前没有被执行过。
