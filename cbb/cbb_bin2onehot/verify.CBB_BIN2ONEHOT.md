# CBB_BIN2ONEHOT 验证

验证状态：已验证（`tb/test_CBB_BIN2ONEHOT.py`：`params.yaml` 全部 5 组参数，`i_bin` 的全部取值穷举，逐个对照参考模型并查 A1–A3）

## 现状（2026-10-03）

`tb/test_CBB_BIN2ONEHOT.py`（cocotb）对 `params.yaml` 声明的全部 5 组参数（`DAT_W` 2/5/16/32/33）各穷举 `i_bin` 的全部 2^`ADDR_W` 个取值，全部通过。跑法（参数给全）：

```bash
make -f flow/Makefile sim DESIGN=CBB_BIN2ONEHOT PARAMS="DAT_W=33"
```

它同时是流程的 RTL 仿真 TB：动态功耗的活动率来自它的 VCD。

## 激励

- 纯组合、没有时钟（`sim.clock_signal: null`）：送一个输入、等 1 ns、采样。
- `i_bin` 的全部 2^`ADDR_W` 个取值顺序走一遍，再按固定种子打乱走一遍（让输出位有多次翻转）。
- `ADDR_W` 不在 `params.yaml` 里扫，取 DUT 端口的实际位宽（默认 `$clog2(DAT_W)`）。`DAT_W` = 5 / 33 不是 2 的幂，越界编号（5–7、33–63）因此也被穷举到。

## 判对错

参考模型按 spec「功能」一节用整数直接算：`i_bin < DAT_W` 时 `1 << i_bin`，否则 0（不照抄 RTL「移位量越界得 0」的写法）。每个输入 `o_oh` 与模型逐位相同。

| 断言 | 怎么查 |
|---|---|
| A1 | 每个输入：`o_oh` 为 0 或恰有一位为 1 |
| A2 | 每个输入：`(i_bin < DAT_W) == (o_oh != 0)` |
| A3 | `i_bin < DAT_W` 时 `o_oh` 的第 `i_bin` 位为 1 |

## 全仓通用规范的验证项

`docs/spec-writing.md` 第 3 节的通用规则（模板 `flow/templates/design-root/verify.md`，内部#286）。

| 通用规范 | 覆盖 |
|---|---|
| 握手保持 | 不适用（纯组合构件，没有握手接口） |
| valid 不依赖 ready | 不适用（纯组合构件，没有握手接口） |
| 汇聚口屏蔽 | 不适用（纯组合构件，没有握手接口） |
| 活性 | 不适用（纯组合构件，没有握手接口） |
| 写数据不等命令 | 不适用（纯组合构件，没有握手接口） |
| 功能不依赖打拍配置 | 不适用（纯组合构件，没有握手接口） |

## 没做的

- RTL 末尾 `` `ifdef CBB_ASSERT_ON `` 段的断言没有在仿真里打开执行（TB 在 Python 侧独立查同样的三条）。
- `ADDR_W > $clog2(DAT_W)` 的配置不在 `params.yaml` 里，TB 支持（按端口位宽穷举），但没有组合跑到它。
