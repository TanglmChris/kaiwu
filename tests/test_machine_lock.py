"""全机互斥（内部#223）：锁文件在 git 公共目录下，所有 worktree 共用；第二个进程等第一个放锁，等的时候说明在等谁。"""
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow import machine_lock as ml  # noqa: E402

HOLD = """
import sys, time
sys.path.insert(0, {root!r})
from flow import machine_lock as ml
ml.LOCK_DIR = __import__('pathlib').Path({d!r})
with ml.machine_lock("t", "持有者"):
    print("got", flush=True)
    time.sleep(1.5)
"""


def test_second_holder_waits_and_names_the_first(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ml, "LOCK_DIR", tmp_path)
    p = subprocess.Popen([sys.executable, "-c", HOLD.format(root=str(REPO_ROOT), d=str(tmp_path))],
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "got"
    t0 = time.monotonic()
    with ml.machine_lock("t", "第二个"):
        waited = time.monotonic() - t0
    p.wait()
    assert waited > 0.8, waited
    out = capsys.readouterr().out
    assert "持有者" in out and "等" in out, out


def test_free_lock_does_not_wait(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ml, "LOCK_DIR", tmp_path)
    t0 = time.monotonic()
    with ml.machine_lock("t", "x"):
        pass
    assert time.monotonic() - t0 < 0.5
    assert capsys.readouterr().out == ""


def test_default_dir_is_git_common_dir():
    common = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert ml.default_lock_dir() == Path(common) / "locks"


def test_netlist_equiv_and_depth_take_the_locks():
    assert 'machine_lock("equiv"' in (REPO_ROOT / "flow" / "equiv" / "netlist_equiv.py").read_text()
    assert 'machine_lock("source_set"' in (REPO_ROOT / "flow" / "synth" / "depth.py").read_text()
