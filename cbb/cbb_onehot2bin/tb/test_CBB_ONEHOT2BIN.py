"""CBB_ONEHOT2BIN 的 cocotb TB：对照 spec「时序约定」里的公式逐个比对。

纯组合、没有时钟（params.yaml 的 `sim.clock_signal: null`）：送一个输入、等组合逻辑稳定、采样。

参考模型按 spec 的两种说法各写一份、互相印证：
- one-hot 与全 0：`o_bin` = 那一位的下标 / 0（A1、A2），用 `bit_length() - 1` 求；
- 任意输入（含多热）：`o_bin` = 所有为 1 的位的下标按位或（spec 的公式），逐位累或。
多热时 spec 说调用方不得依赖输出，但输出仍由公式定义，所以也按公式查。

激励：
- `DAT_W` <= 16：全部 2^DAT_W 个输入穷举；
- 更宽：全 0、每个 one-hot、全 1、相邻两位、首尾两位，再加固定种子的 2000 个随机多热输入。
`ADDR_W` 不在 params.yaml 里扫，取 DUT 端口的实际位宽（默认 `$clog2(DAT_W)`）。
"""
import os
import random

import cocotb
from cocotb.triggers import Timer

DAT_W = int(os.environ.get("DAT_W", "16"))
CNT_W = (DAT_W - 1).bit_length()          # $clog2(DAT_W)
EXHAUSTIVE_MAX_W = 16
RANDOM_N = 2000
SETTLE_NS = 1


def model_formula(oh):
    """spec：o_bin 的第 i 位 = 下标第 i 位为 1 的那些 i_oh 位之或。"""
    out = 0
    for k in range(DAT_W):
        if (oh >> k) & 1:
            out |= k
    return out


def model_onehot(oh):
    """spec：one-hot 时等于那一位的下标，全 0 时为 0。"""
    return 0 if oh == 0 else oh.bit_length() - 1


def build_vectors():
    if DAT_W <= EXHAUSTIVE_MAX_W:
        return list(range(1 << DAT_W)), "穷举"
    full = (1 << DAT_W) - 1
    vecs = [0, full, 1 | (1 << (DAT_W - 1))]
    vecs += [1 << k for k in range(DAT_W)]
    vecs += [3 << k for k in range(DAT_W - 1)]
    rnd = random.Random(20261003 + DAT_W)
    vecs += [rnd.getrandbits(DAT_W) for _ in range(RANDOM_N)]
    return vecs, "定向 + 随机"


@cocotb.test()
async def test_cbb_onehot2bin(dut):
    addr_w = len(dut.o_bin)
    assert len(dut.i_oh) == DAT_W, f"i_oh 位宽 {len(dut.i_oh)}，期望 {DAT_W}"
    vecs, kind = build_vectors()
    n_onehot = 0
    for oh in vecs:
        dut.i_oh.value = oh
        await Timer(SETTLE_NS, unit="ns")
        got = int(dut.o_bin.value)
        exp = model_formula(oh)
        assert got == exp, f"i_oh={oh:#x}: o_bin = {got}，期望 {exp}（按位或公式）"
        # A3：第 $clog2(DAT_W) 位及以上恒为 0
        assert got >> CNT_W == 0, f"A3: i_oh={oh:#x} o_bin={got:#x} 高位不为 0"
        if oh == 0:                                # A2
            assert got == 0, f"A2: i_oh=0 时 o_bin = {got}"
        if oh != 0 and oh & (oh - 1) == 0:         # A1：one-hot
            n_onehot += 1
            assert got == model_onehot(oh), f"A1: i_oh={oh:#x} o_bin={got}"
            assert (oh >> got) & 1, f"A1: i_oh[o_bin] 不为 1（i_oh={oh:#x} o_bin={got}）"
    assert n_onehot == DAT_W, f"激励里的 one-hot 输入只有 {n_onehot} 个，期望 {DAT_W}"
    dut._log.info(f"DAT_W={DAT_W} ADDR_W={addr_w}: {kind} {len(vecs)} 个输入通过"
                  f"（其中 one-hot {n_onehot} 个）")
