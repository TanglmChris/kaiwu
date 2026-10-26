"""CBB_BIN2ONEHOT 的 cocotb TB：对 `i_bin` 的全部 2^ADDR_W 个取值穷举，逐个对照参考模型。

纯组合、没有时钟（params.yaml 的 `sim.clock_signal: null`）：送一个输入、等组合逻辑稳定、
采样。参考模型按 spec 写：`i_bin < DAT_W` 时只有第 `i_bin` 位为 1，否则全 0 ——
用整数比较与 `1 << k` 直接算，不照抄 RTL 的「移位量越界得 0」写法。

穷举之后再把同一组输入按固定种子打乱跑一遍，让每一位都有多次翻转（VCD 活动率来源）。
`ADDR_W` 不在 params.yaml 里扫，取 DUT 端口的实际位宽（默认 `$clog2(DAT_W)`）。
"""
import os
import random

import cocotb
from cocotb.triggers import Timer

DAT_W = int(os.environ.get("DAT_W", "16"))
SETTLE_NS = 1


def model(b):
    """spec「功能」一节：编号在范围内则该位为 1，否则全 0。"""
    return (1 << b) if b < DAT_W else 0


def check_assertions(b, oh):
    # A1：全 0 或恰有一位为 1
    assert oh == 0 or bin(oh).count("1") == 1, f"A1: i_bin={b} o_oh={oh:#x} 不是 one-hot 也不是全 0"
    # A2：i_bin < DAT_W ⇔ o_oh != 0
    assert (b < DAT_W) == (oh != 0), f"A2: i_bin={b} o_oh={oh:#x}"
    # A3：i_bin < DAT_W 时 o_oh[i_bin] = 1
    if b < DAT_W:
        assert (oh >> b) & 1, f"A3: i_bin={b} o_oh={oh:#x}"


@cocotb.test()
async def test_cbb_bin2onehot_exhaustive(dut):
    addr_w = len(dut.i_bin)
    assert len(dut.o_oh) == DAT_W, f"o_oh 位宽 {len(dut.o_oh)}，期望 {DAT_W}"
    vectors = list(range(1 << addr_w))
    shuffled = vectors[:]
    random.Random(20261003 + DAT_W).shuffle(shuffled)

    for b in vectors + shuffled:
        dut.i_bin.value = b
        await Timer(SETTLE_NS, unit="ns")
        oh = int(dut.o_oh.value)
        exp = model(b)
        assert oh == exp, f"i_bin={b}: o_oh = {oh:#x}，期望 {exp:#x}"
        check_assertions(b, oh)
    n_in = min(DAT_W, 1 << addr_w)
    dut._log.info(f"DAT_W={DAT_W} ADDR_W={addr_w}: 穷举 {1 << addr_w} 个编号 × 2 遍通过"
                  f"（范围内 {n_in} 个、越界 {(1 << addr_w) - n_in} 个）")
