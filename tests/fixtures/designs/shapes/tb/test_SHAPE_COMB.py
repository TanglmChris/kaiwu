import os
import random

import cocotb
from cocotb.triggers import Timer

DAT_W = int(os.environ.get("DAT_W", "8"))


@cocotb.test()
async def inverts(dut):
    random.seed(1)
    for _ in range(64):
        a = random.getrandbits(DAT_W)
        dut.i_a.value = a
        await Timer(1, unit="ns")
        assert int(dut.o_y.value) == (~a) & ((1 << DAT_W) - 1)
