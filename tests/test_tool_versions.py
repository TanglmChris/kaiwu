"""工具最低版本门禁（内部#260）：fast_check 与验证侧回归脚本开跑前共用 flow/check/tool_versions.py。"""
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stub_verilator(tmp_path, version):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    f = d / "verilator"
    f.write_text(f"#!/bin/sh\necho 'Verilator {version} 2025-01-01 rev v{version}'\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def _run(tmp_path, version, *args):
    env = dict(os.environ, PATH=f"{_stub_verilator(tmp_path, version)}{os.pathsep}{os.environ['PATH']}")
    return subprocess.run([sys.executable, "flow/check/tool_versions.py", *args], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("version,ok", [("5.020", False), ("5.036", True), ("5.053", True)])
def test_verilator_minimum(tmp_path, version, ok):
    r = _run(tmp_path, version, "--sim", "verilator")
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
    if not ok:
        assert f"FAIL  环境：verilator {version} < 5.036" in r.stdout, r.stdout


def test_icarus_run_does_not_need_verilator(tmp_path):
    r = _run(tmp_path, "5.020", "--sim", "icarus")
    assert r.returncode == 0, r.stdout + r.stderr


def test_cocotb_must_match_requirements_pin(monkeypatch):
    sys.path.insert(0, str(REPO_ROOT))
    from flow.check import tool_versions as tv
    pin = tv.requirements_pin("cocotb")
    assert pin == "2.1.0"
    monkeypatch.setattr(tv, "installed_version", lambda name: "1.9.2")
    probs = tv.problems("icarus")
    assert any("cocotb 1.9.2 != 2.1.0" in p for p in probs), probs
    monkeypatch.setattr(tv, "installed_version", lambda name: pin)
    assert tv.problems("icarus") == []


def test_fast_check_reads_the_same_minimum():
    """最低版本只有一份：fast_check 从 tool_versions 取，不在 shell 里另写一个数。"""
    text = (REPO_ROOT / "scripts" / "fast_check.sh").read_text()
    assert "VERILATOR_MIN=5." not in text
    assert "tool_versions" in text
