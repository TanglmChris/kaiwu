# CBB_LZD 验证

验证状态：已验证（`tb/test_CBB_LZD.py`：`params.yaml` 全部 30 组参数，`DAT_W` <= 16 穷举、更宽定向加固定种子随机，逐个对照参考模型并查三个输出之间的关系）

## 现状（2026-10-03）

`tb/test_CBB_LZD.py`（cocotb）覆盖 `params.yaml` 声明的全部 30 组参数（`DAT_W` 2/5/16/32/33 × `MSB_EN` 0/1 × `SCHEME` 0/1/2），全部通过。跑法（参数给全，`SCHEME` 取编号）：

```bash
make -f flow/Makefile sim DESIGN=CBB_LZD PARAMS="DAT_W=33 MSB_EN=1 SCHEME=2"
```

它同时是流程的 RTL 仿真 TB：动态功耗的活动率来自它的 VCD。

## 激励

- 纯组合、没有时钟（`sim.clock_signal: null`）：送一个输入、等 1 ns、采样。
- `DAT_W` <= 16（2、5、16）：全部 2^`DAT_W` 个输入穷举。
- `DAT_W` = 32 / 33：全 0、全 1；每个单热位 k 再配四种「噪声」—— k 以下全 1、k 以上全 1、k 以下随机、k 以上随机（分别卡住 `MSB_EN` = 0 / 1 两个方向的边界）；再加固定种子、密度 5% / 50% / 95% 各 1000 个随机输入。共约 3160 个。
- 种子只由 `DAT_W`、`MSB_EN` 推出，不含 `SCHEME`：三种结构吃同一组激励、对同一个模型。
- `ADDR_W` 不在 `params.yaml` 里扫，取 DUT 端口的实际位宽。

## 判对错

参考模型按 spec 用整数直接求位置，不照抄 RTL 的「补齐到 2 的幂、反转位序、数前导零」：`MSB_EN = 0` 取 `(x & -x).bit_length() - 1`，`MSB_EN = 1` 取 `x.bit_length() - 1`。每个输入 `o_zero`、`o_dec` 与模型逐位相同；`o_zero = 0` 时 `o_enc` 也要相同（`o_zero = 1` 时 spec 说 `o_enc` 无意义，不查其值）。

spec 没有编号的断言表，「时序约定」列的关系逐条查（下表的 R 编号是本文件为引用方便加的）：

| 关系 | 怎么查 |
|---|---|
| R1 `o_zero = 1` ⇔ `i_dat == 0`，此时 `o_dec == 0` | 每个输入，对模型；`o_zero = 1` 时另查 `i_dat == 0`、`o_dec == 0` |
| R2 `o_zero = 0` 时 `o_dec` 单热、位置等于 `o_enc`、`i_dat[o_enc] = 1`，`o_enc` 之下（`MSB_EN = 0`）/ 之上（`MSB_EN = 1`）全为 0 | 每个非零输入，与模型无关的写法再查一遍：`o_dec == 1 << o_enc`、`i_dat` 在 `o_enc` 的位为 1、对应一侧的位全 0 |
| R3 `o_enc` 的第 `$clog2(DAT_W)` 位及以上恒为 0 | 每个输入（包括 `o_zero = 1`） |
| R4 不同 `SCHEME` 在 `o_zero = 0` 时输出逐位相同 | 三种 `SCHEME` 用同一组激励、各自对同一个模型逐位相同，间接成立 |

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

- RTL 没有 `` `ifdef CBB_ASSERT_ON `` 断言段；关系只由本 TB 查。
- `ADDR_W > $clog2(DAT_W)` 的配置不在 `params.yaml` 里，TB 支持（R3 按 `$clog2(DAT_W)` 查高位），但没有组合跑到它。
- 32 / 33 位不是穷举。
