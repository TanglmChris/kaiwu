"""CBB_FIFO 的 cocotb TB：逐拍对照一个周期级参考模型（spec.CBB_FIFO.md 的断言 A1–A9）。

下降沿驱动、ReadOnly 采样组合输出、上升沿推进模型 —— 输入不在采样沿上变，没有竞争。
激励分三段：先灌满（读慢写快）、再抽空（读快写慢）、最后随机，中间随机插 i_clr；
水线在复位前取随机静态值（A10）。参数由流程经环境变量传进来（run_sim 的 extra_env）。

这份 TB 同时是动态功耗的活动率来源：三段激励让满、空、直通、反压都出现，而不是
只在某一种状态里打转。
"""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

DAT_W = int(os.environ.get("DAT_W", "32"))
DEP = int(os.environ.get("FIFO_DEP_N", "4"))
PT_EN = int(os.environ.get("PT_EN", "0"))
CYCLES = 800


class Model:
    """寄存状态 = 存储里的项（队首在前）。o_cnt 是寄存值，不含本拍进出（spec 时序约定）。"""

    def __init__(self):
        self.q = []

    def outputs(self, src_vld, src_dat, dst_rdy, af, ae):
        cnt = len(self.q)
        src_rdy = cnt != DEP or (PT_EN and dst_rdy)    # PT_EN=1 满时下游当拍取走就仍接收（内部#256）
        if cnt:
            dst_vld, dst_dat = 1, self.q[0]
        elif PT_EN:
            dst_vld, dst_dat = src_vld, src_dat
        else:
            dst_vld, dst_dat = 0, None
        return {
            "o_cnt": cnt, "o_src_rdy": int(src_rdy), "o_dst_vld": dst_vld, "dst_dat": dst_dat,
            "o_afull": int(cnt >= af), "o_aempty": int(cnt <= ae),
            "o_overflow": int(src_vld and not src_rdy),
            "o_underflow": int(dst_rdy and not dst_vld),
        }

    def step(self, src_vld, src_dat, dst_rdy, clr, out):
        """推进一拍，返回本拍被下游收下的数据（没有则 None）。"""
        push = src_vld and out["o_src_rdy"]
        pop = out["o_dst_vld"] and dst_rdy
        got = out["dst_dat"] if pop else None
        if PT_EN and not self.q and push and pop:
            pass                                   # 直通且当拍收下：不写存储
        else:
            if pop:
                self.q.pop(0)
            if push:
                self.q.append(src_dat)
        if clr:
            self.q = []                            # i_clr 下一拍生效（A5）
        return got


def _drive(dut, src_vld, src_dat, dst_rdy, clr):
    dut.i_src_vld.value = src_vld
    dut.i_src_dat.value = src_dat
    dut.i_dst_rdy.value = dst_rdy
    dut.i_clr.value = clr


@cocotb.test()
async def test_cbb_fifo_against_a_cycle_model(dut):
    random.seed(20261001 + DAT_W * 100 + DEP * 10 + PT_EN)
    af = random.randint(1, DEP)
    ae = random.randint(0, DEP - 1)
    dut.i_af_lvl.value = af
    dut.i_ae_lvl.value = ae
    _drive(dut, 0, 0, 0, 0)
    dut.rst_n.value = 0
    cocotb.start_soon(Clock(dut.clk, 2, unit="ns").start())
    for _ in range(3):
        await RisingEdge(dut.clk)

    model, sent, received = Model(), [], []
    first = True
    for cyc in range(CYCLES):
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        phase = cyc * 3 // CYCLES
        p_vld, p_rdy = ((0.9, 0.2), (0.2, 0.9), (0.6, 0.6))[phase]
        src_vld = int(random.random() < p_vld)
        src_dat = random.getrandbits(DAT_W)
        dst_rdy = int(random.random() < p_rdy)
        clr = int(random.random() < 0.01)
        _drive(dut, src_vld, src_dat, dst_rdy, clr)

        await ReadOnly()
        exp = model.outputs(src_vld, src_dat, dst_rdy, af, ae)
        where = f"cycle {cyc} (phase {phase}, clr {clr})"
        for name in ("o_cnt", "o_src_rdy", "o_dst_vld", "o_afull", "o_aempty",
                     "o_overflow", "o_underflow"):
            got = int(getattr(dut, name).value)
            assert got == exp[name], f"{where}: {name} = {got}，期望 {exp[name]}"
        if exp["o_dst_vld"]:
            got = int(dut.o_dst_dat.value)
            assert got == exp["dst_dat"], f"{where}: o_dst_dat = {got:#x}，期望 {exp['dst_dat']:#x}"
        if first:                                  # A8：复位释放后第一拍
            assert exp["o_cnt"] == 0 and exp["o_src_rdy"] == 1, where
            first = False

        if src_vld and exp["o_src_rdy"]:
            sent.append(src_dat)
        got = model.step(src_vld, src_dat, dst_rdy, clr, exp)
        if got is not None:
            received.append(got)
        if clr:                                    # A9：两次 i_clr 之间收下的是送进的前缀
            assert received == sent[:len(received)], f"{where}: 顺序或内容不对"
            sent, received = [], []
        await RisingEdge(dut.clk)

    assert received == sent[:len(received)], "保序、不丢、不重（A9）"
    dut._log.info(f"DAT_W={DAT_W} FIFO_DEP_N={DEP} PT_EN={PT_EN}: {CYCLES} 拍逐拍对照通过")
