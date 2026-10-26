# ADDER32 参数化实现

## 1. 参数与结构

| 参数 | 影响的结构（generate 分支、位宽推导） | 派生量 |
|---|---|---|
| `DAT_W` | 各段位宽、前缀网络级数 | `SEG_W = DAT_W / (PIPE_STAGES + 1)`；`LVL_N = $clog2(DAT_W)` |
| `SCHEME` | `ADDER_CORE` 的分支 `GEN_RIPPLE` / `GEN_CLA` / `GEN_CSEL` / `GEN_PREFIX`，`PREFIX_ADDER` 的网络分支 | |
| `PIPE_STAGES` | 段数与段间寄存器 `GEN_REG` | `SEG_N = PIPE_STAGES + 1` |
| `CSEL_BLK_W` | `CARRY_SELECT_ADDER` 的块宽 | `BLK_N = ceil(DAT_W / CSEL_BLK_W)` |

## 2. 参数裁剪

`PIPE_STAGES = 0` 时不生成任何寄存器，`clk`、`rst_n` 不接（lint 豁免见 `waivers.vlt`）。`SCHEME != 2` 时 `CSEL_BLK_W` 不影响网表。

## 3. 参数合法性检查

`CBB_PARAM_CHK_ON` 下：`DAT_W >= PIPE_STAGES + 1`、`SCHEME` 属于 0–5、`PIPE_STAGES` 属于 0–2、`CSEL_BLK_W >= 1`；`ADDER_CORE` 与 `PREFIX_ADDER` 各自再查一次 `SCHEME`。
