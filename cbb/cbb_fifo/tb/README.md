# CBB_FIFO 的验证环境

`test_CBB_FIFO.py`（cocotb）：逐拍对照一个周期级参考模型，覆盖 `spec.CBB_FIFO.md` 断言 A1–A9。参数由流程经环境变量传入，跑法：

```bash
.venv/bin/python3 flow/sim/run_sim.py --design CBB_FIFO --param DAT_W=32 --param FIFO_DEP_N=4 --param PT_EN=0 --param RST_EN=0
```

`tb_cbb_fifo_directed.sv`（iverilog）：定向用例，深度 2 / 8 × `PT_EN` 0 / 1，不进流程（内部#256）：

```bash
iverilog -g2012 -s tb -o tb.vvp cbb/cbb_fifo/tb/tb_cbb_fifo_directed.sv cbb/cbb_fifo/rtl/cbb_fifo.v && vvp -n tb.vvp
```

验证方案与覆盖见 `../verify.CBB_FIFO.md`。
