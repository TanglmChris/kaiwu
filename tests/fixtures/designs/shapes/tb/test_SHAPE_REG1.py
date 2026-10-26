import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

DAT_W = int(os.environ.get("DAT_W", "8"))


@cocotb.test()
async def registers_the_inverse(dut):
    random.seed(1)
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())
    for _ in range(64):
        await FallingEdge(dut.clk)
        a = random.getrandbits(DAT_W)
        dut.i_a.value = a
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        assert int(dut.o_y.value) == (~a) & ((1 << DAT_W) - 1)
