"""磁盘护栏（`flow/disk.py`，内部#173）：开跑前查剩余空间，构建产物只留最近几份。

为什么值得有这组测试：2026-10-05 Data 卷写满，全部会话的 shell 失败、正在跑的结果作废。
护栏放过一次就是又一次全员停工；反过来误删别人正用着的构建，就是毁掉别人的回归。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import flow.disk as disk  # noqa: E402
import flow.verify.regress as rg  # noqa: E402
import scripts.sweep as sweep_mod  # noqa: E402


def test_require_free_refuses_below_the_threshold(monkeypatch):
    monkeypatch.setenv("RTL_PPA_MIN_FREE_GB", "1e9")
    with pytest.raises(disk.DiskSpaceError, match="拒绝开跑"):
        disk.require_free()
    assert disk.main(["check"]) == 1


def test_require_free_passes_above_the_threshold(monkeypatch):
    monkeypatch.setenv("RTL_PPA_MIN_FREE_GB", "0")
    assert disk.require_free() > 0
    assert disk.main(["check"]) == 0


def test_the_need_estimate_is_added_to_the_threshold(monkeypatch):
    monkeypatch.setenv("RTL_PPA_MIN_FREE_GB", "0")
    with pytest.raises(disk.DiskSpaceError):
        disk.require_free(need_gb=1e9)


def test_prune_old_keeps_the_newest_and_skips_dirs_in_use(tmp_path, monkeypatch):
    for n in ("20261001-1", "20261002-1", "20261003-1", "20261004-1", "20261005-1"):
        (tmp_path / n).mkdir()
        (tmp_path / n / "Vtb").write_text("x")
    (tmp_path / "durations.verilator.json").write_text("{}")
    monkeypatch.setattr(disk, "in_use", lambda p: p.name == "20261001-1")
    removed = disk.prune_old(tmp_path, keep=2)
    assert sorted(p.name for p in removed) == ["20261002-1", "20261003-1"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "20261001-1", "20261004-1", "20261005-1", "durations.verilator.json"]


def test_in_use_sees_an_open_file(tmp_path):
    d = tmp_path / "b"
    d.mkdir()
    f = (d / "x").open("w")
    try:
        assert disk.in_use(d)
    finally:
        f.close()
    assert not disk.in_use(d)


def test_regress_refuses_to_start_on_a_full_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("RTL_PPA_MIN_FREE_GB", "1e9")
    (tmp_path / "tb_x.sv").write_text("module tb; endmodule\n")
    p = tmp_path / "regress.X.yaml"
    p.write_text("tb: tb_x.sv\ntop: tb\ndone: '^DONE'\npass: 'ok'\ngroups: []\n")
    with pytest.raises(disk.DiskSpaceError):
        rg.run(p, "inner", out_dir=tmp_path / "out", durations_path=tmp_path / "d.json")
    assert not (tmp_path / "out").exists()


def test_sweep_does_not_start_a_combo_on_a_full_disk(monkeypatch):
    """空间不够的组合不开跑，按测量失败记下（结尾列出，清理后续跑）。"""
    monkeypatch.setenv("RTL_PPA_MIN_FREE_GB", "1e9")
    called = []
    monkeypatch.setattr(sweep_mod, "run_experiment", lambda *a, **k: called.append(a))
    with pytest.raises(disk.DiskSpaceError):
        sweep_mod._run_one("X", {"A": 1}, "lib", "icarus", 5.0)
    assert called == []


def test_prune_old_by_mtime_and_match(tmp_path, monkeypatch):
    """构建缓存的名字按提交号做键、不是时间序：按修改时间留最新的，并且按 match 分类各留各的。"""
    import os
    monkeypatch.setattr(disk, "in_use", lambda p: False)
    for i, n in enumerate(("A.v.fff", "A.v.aaa", "A.v.ccc", "B.v.zzz")):
        (tmp_path / n).mkdir()
        os.utime(tmp_path / n, (1000 + i, 1000 + i))
    removed = disk.prune_old(tmp_path, keep=1, by_mtime=True, match="A.*")
    assert sorted(p.name for p in removed) == ["A.v.aaa", "A.v.fff"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["A.v.ccc", "B.v.zzz"]
