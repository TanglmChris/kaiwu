import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

# 位宽由流程通过环境变量传进来（run_sim 把 params 原样放进 extra_env）。
DAT_W = int(os.environ.get("DAT_W", "32"))
MASK = (1 << DAT_W) - 1


async def apply_and_check(dut, pipe_stages, a, b, cin):
    dut.i_a.value = a
    dut.i_b.value = b
    dut.i_cin.value = cin

    for _ in range(pipe_stages + 1):
        await RisingEdge(dut.clk)

    expected = a + b + cin
    exp_sum = expected & MASK
    exp_cout = (expected >> DAT_W) & 1

    got_sum = int(dut.o_sum.value)
    got_cout = int(dut.o_cout.value)
    assert got_sum == exp_sum, (
        f"sum mismatch a={a:#x} b={b:#x} cin={cin} got={got_sum:#x} exp={exp_sum:#x}"
    )
    assert got_cout == exp_cout, (
        f"cout mismatch a={a:#x} b={b:#x} cin={cin} got={got_cout} exp={exp_cout}"
    )


@cocotb.test()
async def test_adder32_directed_and_random(dut):
    pipe_stages = int(os.environ.get("PIPE_STAGES", "0"))

    cocotb.start_soon(Clock(dut.clk, 2, units="ns").start())

    dut.rst_n.value = 0
    dut.i_a.value = 0
    dut.i_b.value = 0
    dut.i_cin.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # 按位宽生成，不写死 32 位字面量。覆盖的边界与原来一致：全零、最大值加一
    # （进位溢出）、全一相加、最高位相加、交替位模式。
    msb = 1 << (DAT_W - 1)
    pat_5 = sum(1 << i for i in range(0, DAT_W, 2))   # 0b0101... = 0x5555...
    pat_a = sum(1 << i for i in range(1, DAT_W, 2))   # 0b1010... = 0xAAAA...
    directed = [
        (0, 0, 0),
        (MASK, 1, 0),
        (MASK, 0, 1),
        (MASK, MASK, 1),
        (msb, msb, 0),
        (pat_5, pat_a, 1),
    ]
    for a, b, cin in directed:
        await apply_and_check(dut, pipe_stages, a, b, cin)

    random.seed(1234)
    for _ in range(50):
        a = random.getrandbits(DAT_W)
        b = random.getrandbits(DAT_W)
        cin = random.getrandbits(1)
        await apply_and_check(dut, pipe_stages, a, b, cin)
