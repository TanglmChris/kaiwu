# 仿真子进程用跑流程的这个解释器（flow-parameterization「仿真子进程必须用跑流程的那个解释器」，内部#442）。
# Verilator 生成的 Vtop.mk 调 verilator_includer（#!/usr/bin/env python3），cocotb runner 却按当前解释器设好了 Python
# 环境；不激活 venv 时 PATH 里的 python3 是系统那个（macOS 3.9），拿到 3.11 的标准库就崩。
# 不写进 run_sim.py：它在 METRIC_MODULES 里，改它换代，而这里只改子进程找 python3 的路径、不改任何测量值。
# 入口在开头调一次：scripts/sweep.py（scripts/exp.py 导入它）、tests/conftest.py。
import os
import sys
from pathlib import Path


def prefer_this_python():
    """把当前解释器所在目录放到 PATH 最前面；已经在最前面就不动。不解析符号链接：.venv/bin/python3 → .venv/bin。"""
    here = str(Path(sys.executable).parent)
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if parts[:1] == [here]:
        return
    os.environ["PATH"] = os.pathsep.join([here] + [p for p in parts if p != here])
