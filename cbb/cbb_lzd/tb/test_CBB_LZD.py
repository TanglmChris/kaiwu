"""CBB_LZD 的 cocotb TB：逐个输入对照参考模型，并查 spec「时序约定」里三个输出之间的关系。

纯组合、没有时钟（params.yaml 的 `sim.clock_signal: null`）：送一个输入、等组合逻辑稳定、采样。

参考模型按 spec 用整数运算直接求，不照抄 RTL 的「补齐到 2 的幂、反转位序、数前导零」：
- `MSB_EN = 0`：最低位的 1 的下标 = `(x & -x).bit_length() - 1`；
- `MSB_EN = 1`：最高位的 1 的下标 = `x.bit_length() - 1`。
`o_zero = 1` 时 spec 说 `o_enc` 无意义（各 `SCHEME` 可以不同），不查它的值，只查高位为 0。

激励：
- `DAT_W` <= 16：全部 2^DAT_W 个输入穷举；
- 更宽：全 0、全 1、每个单热位、每个单热位加上它「下方 / 上方」的全 1 与随机噪声
  （分别卡住 MSB / LSB 方向的边界），再加固定种子、三种密度的 3000 个随机输入。
三种 `SCHEME` 用同一组激励、同一个模型，所以「`o_zero = 0` 时各结构逐位相同」由
三个组合都对上同一模型间接保证。`ADDR_W` 不在 params.yaml 里扫，取 DUT 端口的实际位宽。
"""
import os
import random

import cocotb
from cocotb.triggers import Timer

DAT_W = int(os.environ.get("DAT_W", "16"))
MSB_EN = int(os.environ.get("MSB_EN", "0"))
SCHEME = int(os.environ.get("SCHEME", "0"))
CNT_W = (DAT_W - 1).bit_length()          # $clog2(DAT_W)
FULL = (1 << DAT_W) - 1
EXHAUSTIVE_MAX_W = 16
RANDOM_N = 1000                           # 每种密度
SETTLE_NS = 1


def model(x):
    """返回 (zero, enc, dec)。zero 时 enc 为 None（spec：无意义）。"""
    if x == 0:
        return 1, None, 0
    pos = x.bit_length() - 1 if MSB_EN else (x & -x).bit_length() - 1
    return 0, pos, 1 << pos


def build_vectors():
    if DAT_W <= EXHAUSTIVE_MAX_W:
        return list(range(1 << DAT_W)), "穷举"
    rnd = random.Random(20261003 + DAT_W * 10 + MSB_EN)
    vecs = [0, FULL]
    for k in range(DAT_W):
        one = 1 << k
        below = one - 1                    # k 以下全 1
        above = FULL & ~((one << 1) - 1)   # k 以上全 1
        vecs += [one, one | below, one | above,
                 one | (rnd.getrandbits(DAT_W) & below),
                 one | (rnd.getrandbits(DAT_W) & above)]
    for density in (0.05, 0.5, 0.95):      # 稀疏 / 均匀 / 稠密
        for _ in range(RANDOM_N):
            x = 0
            for k in range(DAT_W):
                if rnd.random() < density:
                    x |= 1 << k
            vecs.append(x)
    return vecs, "定向 + 随机"


@cocotb.test()
async def test_cbb_lzd(dut):
    addr_w = len(dut.o_enc)
    assert len(dut.i_dat) == DAT_W and len(dut.o_dec) == DAT_W
    vecs, kind = build_vectors()
    for x in vecs:
        dut.i_dat.value = x
        await Timer(SETTLE_NS, unit="ns")
        zero = int(dut.o_zero.value)
        enc = int(dut.o_enc.value)
        dec = int(dut.o_dec.value)
        e_zero, e_enc, e_dec = model(x)
        where = f"i_dat={x:#x}"
        assert zero == e_zero, f"{where}: o_zero = {zero}，期望 {e_zero}"
        assert dec == e_dec, f"{where}: o_dec = {dec:#x}，期望 {e_dec:#x}"
        # o_enc 高位恒为 0（任何输入，包括 o_zero = 1）
        assert enc >> CNT_W == 0, f"{where}: o_enc = {enc:#x} 的第 {CNT_W} 位及以上不为 0"
        if zero:
            # o_zero = 1 ⇔ i_dat == 0，此时 o_dec == 0；o_enc 不查
            assert x == 0 and dec == 0, where
            continue
        assert enc == e_enc, f"{where}: o_enc = {enc}，期望 {e_enc}"
        # 关系式逐条再查一遍（与模型独立的写法）
        assert dec == 1 << enc, f"{where}: o_dec 不是 o_enc 处的单热"
        assert (x >> enc) & 1, f"{where}: i_dat[o_enc] 不为 1"
        if MSB_EN:
            assert x >> (enc + 1) == 0, f"{where}: o_enc 之上还有 1"
        else:
            assert x & ((1 << enc) - 1) == 0, f"{where}: o_enc 之下还有 1"
    dut._log.info(f"DAT_W={DAT_W} ADDR_W={addr_w} MSB_EN={MSB_EN} SCHEME={SCHEME}: "
                  f"{kind} {len(vecs)} 个输入通过")
