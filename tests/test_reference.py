"""reference-ppa：参考口径（内部#202）—— 按场景 case 接常数、跨层次优化（synth -hieropt）、保层级、绕开 内部#205。"""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path.home() / "pdk" / "asap7_merged" / "asap7sc7p5t_RVT_TT.lib"
needs_tools = [pytest.mark.flow,
               pytest.mark.skipif(any(shutil.which(t) is None for t in ("yosys", "sta", "yosys-abc"))
                                  or not LIBERTY.exists(), reason="yosys / sta / ASAP7 合并库不在")]
P = {"W": 8}


def test_the_reference_ports_enter_the_recipe(fixture_designs):
    from flow.flow_fingerprint import METRIC_MODULES, design_recipe
    from flow.paths import reference_ports
    assert reference_ports("REF_TOP") == ["mode"]
    assert design_recipe("REF_TOP")["reference_ports"] == ["mode"]
    assert design_recipe("CBB_LZD")["reference_ports"] == []
    assert "flow/synth/reference.py" in METRIC_MODULES


def test_the_tie_is_the_one_applicable_scenario_and_must_cover_the_reference_ports(fixture_designs, monkeypatch):
    from flow.paths import ParamError
    from flow.synth import reference
    assert reference.tie("REF_TOP", P) == ("lean", {"mode": 1})
    monkeypatch.setattr(reference, "scenarios", lambda d, params=None: [])
    with pytest.raises(ParamError, match="恰好一个"):
        reference.tie("REF_TOP", P)
    monkeypatch.setattr(reference, "scenarios", lambda d, params=None: [
        {"name": "x", "case": {"other": 0}, "by": "R.001", "when": None}])
    with pytest.raises(ParamError, match="mode"):
        reference.tie("REF_TOP", P)


def test_empty_cell_connections_are_dropped_from_rtlil():
    from flow.synth.reference import drop_empty_connections
    il = ("module \\top\n  wire \\x\n  connect \\x 1'0\n  cell \\sub \\u1\n    connect \\a \\x\n"
          "    connect \\y { }\n  end\nend\n")
    out, n = drop_empty_connections(il)
    assert n == 1 and "connect \\y { }" not in out and "connect \\a \\x" in out and "connect \\x 1'0" in out


def _both(tmp_path):
    from flow.synth.reference import synthesize
    from flow.synth.synth import run_synth
    formal = run_synth("REF_TOP", P, str(LIBERTY), out_dir=tmp_path / "formal")
    ref = synthesize("REF_TOP", P, str(LIBERTY), {"mode": 1}, out_dir=tmp_path / "ref")
    return formal, ref


@needs_tools[0]
@needs_tools[1]
def test_the_reference_is_smaller_keeps_the_operator_and_is_equivalent(tmp_path, fixture_designs):
    from flow.equiv.netlist_equiv import prove_netlist
    formal, ref = _both(tmp_path)
    assert ref["area_um2"] < formal["area_um2"], (ref["area_um2"], formal["area_um2"])
    text = Path(ref["netlist_path"]).read_text()
    assert re.search(r"^module \\?\S*REF_ADD\b", text, re.M), "保层级的 REF_ADD 要还是独立模块"
    assert not re.search(r"\binput\b[^;]*\bmode\b", text.split("module REF_TOP", 1)[1].split("endmodule")[0]), \
        "mode 接成常数后不再是顶层输入"
    status, _, log = prove_netlist("REF_TOP", P, ref["netlist_path"], str(LIBERTY), tie={"mode": 1})
    assert status == "PROVED", log[-2000:]


@needs_tools[0]
@needs_tools[1]
def test_a_mutated_reference_netlist_is_caught(tmp_path, fixture_designs):
    from flow.equiv.netlist_equiv import prove_netlist
    from tests.test_netlist_equiv import _mutate
    _, ref = _both(tmp_path)
    status, _, log = prove_netlist("REF_TOP", P, _mutate(Path(ref["netlist_path"]), tmp_path), str(LIBERTY),
                                   tie={"mode": 1})
    assert status == "FAILED", log[-2000:]


@needs_tools[0]
@needs_tools[1]
def test_sta_and_depth_run_on_the_reference_netlist(tmp_path, fixture_designs):
    from flow.sta.run_sta import run_sta
    from flow.synth.depth import measure
    _, ref = _both(tmp_path)
    r = run_sta("REF_TOP", ref["netlist_path"], str(LIBERTY), out_dir=tmp_path / "sta", tied={"mode"})
    assert r["critical_path_delay_ns"] > 0 and r["critical_path_stages"] > 0
    from flow.sta.run_sta import worst_points
    start, end = worst_points(r["checks_report"])
    assert start and end, (start, end)
    d = measure("REF_TOP", params=P, out_dir=tmp_path / "depth", netlist=ref["netlist_path"], budget=30,
                tied={"mode"})
    assert d["stages"] > 0 and not (tmp_path / "depth" / "synth.ys").exists(), "给了网表就不重新综合"


# --- 1.2 记录的 reference 字段 --------------------------------------------------------

def _ref_flow(tmp_path, monkeypatch, equiv="PROVED"):
    from tests.test_run_experiment import _stub_flow
    rx, log, calls = _stub_flow(tmp_path, monkeypatch)
    inner = rx.run_sta
    seen = {"ref": [], "sta_tied": [], "depth": []}

    def sta(design, netlist, liberty, vcd=None, period_ns=5.0, out_dir=None, case=None, tied=None):
        r = inner(design, netlist, liberty, vcd=vcd, period_ns=period_ns, out_dir=out_dir)
        if tied is not None:
            seen["sta_tied"].append((netlist, liberty, tied))
            r = {**r, "critical_path_delay_ns": 0.5, "fmax_mhz": 2000.0, "critical_path_stages": 3}
        return {**r, "checks_report": "x"}
    monkeypatch.setattr(rx, "run_sta", sta)
    monkeypatch.setattr(rx, "worst_points", lambda rpt: ("a_reg/CLK", "q_reg/D"))

    def synth_ref(design, params, liberty, case=None, out_dir=None, delay_target_ps=None):
        seen["ref"].append(delay_target_ps)
        return {"cell_count": 4, "area_um2": 1.0, "netlist_path": "ref.v", "stats_path": "ref.json",
                "scenario": "lean", "case": {"mode": 1}, "delay_target_ps": delay_target_ps}
    monkeypatch.setattr(rx, "reference_synthesize", synth_ref)
    monkeypatch.setattr(rx, "prove_netlist", lambda *a, **k: (equiv, 1.0, "log"))
    monkeypatch.setattr(rx, "equiv_enabled", lambda design: True)     # 替身顶层 TOP 不在任何设计根里；缺省做等价

    def depth(design, params=None, out_dir=None, netlist=None, budget=None, tied=None, **k):
        seen["depth"].append((netlist, budget, tied))
        return {"stages": 7, "over_budget": {"budget": budget, "count": 0, "groups": []}}
    monkeypatch.setattr(rx, "depth_measure", depth)
    return rx, log, seen


def test_the_record_carries_the_reference_block_only_when_asked(tmp_path, monkeypatch):
    rx, log, seen = _ref_flow(tmp_path, monkeypatch)
    plain = rx.run_experiment("TOP", {}, "tt.lib")
    assert plain["reference"] is None and seen["ref"] == []
    rec = rx.run_experiment("TOP", {}, "tt.lib", reference=True)
    ref = rec["reference"]
    assert ref["scenario"] == "lean" and ref["case"] == {"mode": 1}
    assert ref["delay_target_ps"] == rec["synth"]["delay_target_ps"], "延时目标沿用正式口径胜出的那一档"
    assert ref["synth"]["area_um2"] == 1.0 and ref["synth"]["cell_count"] == 4 and "area_breakdown" in ref["synth"]
    assert ref["sta"]["fmax_mhz"] == 2000.0 and ref["sta"]["critical_path_stages"] == 3
    assert ref["sta"]["startpoint"] == "a_reg/CLK" and ref["sta"]["endpoint"] == "q_reg/D"
    assert set(ref["sta"]["corners"]) == {"SS", "FF"}
    assert [t for _, _, t in seen["sta_tied"]] == [{"mode"}] * 3
    assert ref["depth"] == {"stages": 7, "budget": 30, "over_budget_count": 0}
    assert seen["depth"] == [("ref.v", 30, {"mode"})]
    assert ref["equiv"] == "PROVED"
    for k in ("sta", "synth", "sim"):
        a, b = dict(plain[k]), dict(rec[k])
        assert a == b, f"正式口径的 {k} 不因 reference 改变"


@pytest.mark.parametrize("equiv", ["UNDECIDED", "FAILED"])
def test_an_unproved_reference_keeps_only_the_verdict(tmp_path, monkeypatch, equiv):
    """内部#202 D10：参考网表等价不是 PROVED 时不丢正式记录；reference 只留结论与日志，不量参考 STA / depth。"""
    rx, log, seen = _ref_flow(tmp_path, monkeypatch, equiv=equiv)
    plain = rx.run_experiment("TOP", {}, "tt.lib")
    rec = rx.run_experiment("TOP", {}, "tt.lib", reference=True)
    ref = rec["reference"]
    assert set(ref) == {"scenario", "case", "delay_target_ps", "equiv", "equiv_log_path"}, ref
    assert ref["equiv"] == equiv and Path(ref["equiv_log_path"]).read_text() == "log"
    assert seen["sta_tied"] == [] and seen["depth"] == []
    for k in ("sta", "synth", "sim"):
        assert dict(plain[k]) == dict(rec[k]), f"正式口径的 {k} 不因 reference 改变"
    assert len(log.read_text().splitlines()) == 2, "两条记录都写了"


# --- equiv-optional（内部#232）：设计声明 equiv: false 时不做参考网表等价，照常报数 -----------------

def test_equiv_enabled_reads_the_declaration(monkeypatch):
    from flow import paths
    cfgs = {"A": {}, "B": {"equiv": False}, "C": {"equiv": "no"}}
    monkeypatch.setattr(paths, "load_design_config", lambda d, repo_root=None: cfgs[d])
    assert paths.equiv_enabled("A") is True
    assert paths.equiv_enabled("B") is False
    with pytest.raises(paths.ParamError, match="C"):
        paths.equiv_enabled("C")


def test_design_recipe_carries_equiv():
    from flow.flow_fingerprint import design_recipe
    assert design_recipe("CBB_LZD")["equiv"] is True


def test_a_skipped_equivalence_still_measures_the_reference(tmp_path, monkeypatch):
    rx, log, seen = _ref_flow(tmp_path, monkeypatch, equiv="UNDECIDED")
    called = []
    monkeypatch.setattr(rx, "prove_netlist", lambda *a, **k: called.append(1) or ("PROVED", 0, ""))
    monkeypatch.setattr(rx, "equiv_enabled", lambda design: False)
    ref = rx.run_experiment("TOP", {}, "tt.lib", reference=True)["reference"]
    assert called == [], "声明了不做等价，不该调 prove_netlist"
    assert ref["equiv"] == "SKIPPED"
    assert ref["synth"]["area_um2"] == 1.0 and ref["sta"]["fmax_mhz"] == 2000.0 and ref["depth"]["stages"] == 7
