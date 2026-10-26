"""内部#232：网表等价的每一步 dprove / PDR 都要有墙钟上限，函数入口与命令行同一个默认值。

参考口径（run_experiment._reference）调 prove_netlist 时不传 timeout；默认是 None 的话 dprove 没有上限，
一个大设计的一个点跑了 6.3 小时（内部#232）。这里只锁默认值与传递，不跑真工具。"""
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.equiv import netlist_equiv as ne  # noqa: E402


def test_prove_entry_points_default_to_a_finite_timeout():
    for fn in (ne.prove_netlist, ne.prove_one):
        default = inspect.signature(fn).parameters["timeout"].default
        assert default == ne.DEFAULT_TIMEOUT_S, (fn.__name__, default)
    assert 0 < ne.DEFAULT_TIMEOUT_S <= 3600


def test_abc_passes_the_limit_to_the_subprocess(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        raise ne.subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(ne.subprocess, "run", fake_run)
    v, out = ne._abc("yosys-abc", "read_aiger x.aig; dprove", tmp_path, ne.DEFAULT_TIMEOUT_S)
    assert seen["timeout"] == ne.DEFAULT_TIMEOUT_S
    assert v == "UNDECIDED" and "没有结论" in out


def test_designs_declared_without_equivalence_are_skipped(monkeypatch):
    """equiv-optional D4：事后等价工具跳过声明了 equiv: false 的设计，并说出跳过了谁。"""
    recs = [{"design": "BIG"}, {"design": "SMALL"}]
    monkeypatch.setattr(ne, "equiv_enabled", lambda d: d != "BIG")
    kept, skipped = ne.drop_undeclared(recs)
    assert kept == [{"design": "SMALL"}] and skipped == ["BIG"]
