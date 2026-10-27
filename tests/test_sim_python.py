"""仿真子进程必须用跑流程的那个解释器（flow-parameterization，内部#442）。

Verilator 生成的 makefile 调 `#!/usr/bin/env python3` 的脚本，cocotb runner 却按当前解释器设好了 Python 环境。
不激活 venv 时 PATH 里的 python3 是系统那个（macOS 3.9），拿到 venv 3.11 的标准库就崩。入口在开头把当前解释器的
目录放到 PATH 最前面；这里用一个假的 `python3` 占住 PATH 前面来模拟「没激活」。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

HERE = str(Path(sys.executable).parent)


def _decoy(tmp_path):
    """PATH 前面放一个别的 python3，像没激活 venv 时的系统解释器。"""
    d = tmp_path / "other"
    d.mkdir()
    (d / "python3").write_text("#!/bin/sh\nexit 1\n")
    (d / "python3").chmod(0o755)
    return str(d)


def test_the_flow_interpreter_comes_first_on_path(tmp_path, monkeypatch):
    import flow.sim.python_path as pp
    decoy = _decoy(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([decoy, "/usr/bin", "/bin"]))
    assert Path(shutil.which("python3")).parent == Path(decoy)   # 臂：调用前找到的是假的那个
    pp.prefer_this_python()
    assert Path(shutil.which("python3")).parent == Path(HERE)
    assert os.environ["PATH"].split(os.pathsep)[1:] == [decoy, "/usr/bin", "/bin"]


def test_calling_it_again_does_not_stack(tmp_path, monkeypatch):
    import flow.sim.python_path as pp
    monkeypatch.setenv("PATH", os.pathsep.join([_decoy(tmp_path), HERE, "/bin"]))
    pp.prefer_this_python()
    once = os.environ["PATH"]
    pp.prefer_this_python()
    assert os.environ["PATH"] == once
    assert once.split(os.pathsep).count(HERE) == 1


def test_the_entry_points_put_the_flow_interpreter_first(tmp_path):
    """用不含 venv 的 PATH 起子进程，只导入入口模块，看它找到的 python3。"""
    decoy = _decoy(tmp_path)
    for mod in ("scripts.sweep", "scripts.exp"):
        r = subprocess.run([sys.executable, "-c", f"import {mod}, shutil; print(shutil.which('python3'))"],
                           cwd=REPO_ROOT, capture_output=True, text=True,
                           env=dict(os.environ, PATH=os.pathsep.join([decoy, "/usr/bin", "/bin"])))
        assert r.returncode == 0, r.stderr
        assert Path(r.stdout.strip()).parent == Path(HERE), (mod, r.stdout)
