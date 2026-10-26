"""sta-scenarios：验收场景的声明（flow/paths.py）、正式 STA 按场景定值、记录的 sta.scenarios（内部#189 后续，选项 A）。"""
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path.home() / "pdk" / "asap7_merged" / "asap7sc7p5t_RVT_TT.lib"
needs_tools = pytest.mark.skipif(any(shutil.which(t) is None for t in ("yosys", "sta")) or not LIBERTY.exists(),
                                 reason="yosys / sta / ASAP7 合并库不在")


# --- 声明 ----------------------------------------------------------------------

def test_scenarios_are_parsed_from_params_yaml(fixture_designs):
    from flow.paths import scenarios
    assert scenarios("SCEN_TOP") == [
        {"name": "deep", "case": {"mode": 0}, "by": "R.001", "when": None},
        {"name": "shallow", "case": {"mode": 1}, "by": "R.001", "when": None},
    ]
    assert scenarios("CBB_LZD") == []


@pytest.mark.parametrize("bad", [
    [{"name": "a", "case": {}, "by": "R.001"}],
    [{"name": "a", "case": {"mode": 0}, "by": "R1"}],
    [{"name": "a", "case": {"mode": 0}, "by": "R.001"}, {"name": "a", "case": {"mode": 1}, "by": "R.001"}],
    [{"name": "a", "case": {"mode": 0}}],
])
def test_malformed_scenarios_are_refused(monkeypatch, bad):
    import flow.paths as paths
    monkeypatch.setattr(paths, "load_design_config", lambda d, *a, **k: {"sta": {"scenarios": bad}})
    with pytest.raises(paths.ParamError):
        paths.scenarios("X")


def test_the_design_recipe_carries_scenarios(fixture_designs):
    from flow.flow_fingerprint import design_recipe
    assert [s["name"] for s in design_recipe("SCEN_TOP")["scenarios"]] == ["deep", "shallow"]
    assert design_recipe("CBB_LZD")["scenarios"] == []


def test_depth_reads_the_same_declaration():
    from flow import paths
    from flow.synth import depth
    assert depth.scenarios is paths.scenarios


# --- run_sta(case=) --------------------------------------------------------------

@pytest.mark.flow
@needs_tools
def test_fixing_a_static_input_prunes_the_mutually_exclusive_path(tmp_path, fixture_designs):
    """SCEN_TOP：mode=1 剪掉 64 级深链，延时与级数都小于不定值；mode=0 不大于不定值；不定值的 tcl 不含定值。"""
    from flow.sta.run_sta import run_sta
    from flow.synth.synth import run_synth
    s = run_synth("SCEN_TOP", {"DAT_W": 8}, str(LIBERTY), out_dir=tmp_path / "syn")
    net = s["netlist_path"]
    base = run_sta("SCEN_TOP", net, str(LIBERTY), out_dir=tmp_path / "base")
    assert "set_case_analysis" not in (tmp_path / "base" / "run_sta.tcl").read_text()
    shallow = run_sta("SCEN_TOP", net, str(LIBERTY), out_dir=tmp_path / "sh", case={"mode": 1})
    deep = run_sta("SCEN_TOP", net, str(LIBERTY), out_dir=tmp_path / "dp", case={"mode": 0})
    assert "set_case_analysis 1 [get_ports {mode}]" in (tmp_path / "sh" / "run_sta.tcl").read_text()
    assert shallow["critical_path_delay_ns"] < base["critical_path_delay_ns"]
    assert shallow["critical_path_stages"] < base["critical_path_stages"]
    assert deep["critical_path_delay_ns"] <= base["critical_path_delay_ns"] + 1e-6


@pytest.mark.flow
@needs_tools
def test_a_case_on_a_missing_port_fails(tmp_path, fixture_designs):
    from flow.sta.run_sta import run_sta
    from flow.synth.synth import run_synth
    s = run_synth("SCEN_TOP", {"DAT_W": 8}, str(LIBERTY), out_dir=tmp_path / "syn")
    with pytest.raises(RuntimeError, match="no_such"):
        run_sta("SCEN_TOP", s["netlist_path"], str(LIBERTY), out_dir=tmp_path / "x", case={"no_such": 1})


# --- 记录 ------------------------------------------------------------------------

def _with_scenarios(tmp_path, monkeypatch, declared, scen_delay=0.5):
    from tests.test_run_experiment import _stub_flow
    rx, log, calls = _stub_flow(tmp_path, monkeypatch)
    monkeypatch.setattr(rx, "scenarios", lambda d, params=None: declared)
    inner = rx.run_sta

    def sta(design, netlist, liberty, vcd=None, period_ns=5.0, out_dir=None, case=None):
        r = inner(design, netlist, liberty, vcd=vcd, period_ns=period_ns, out_dir=out_dir)
        calls["sta"][-1]["case"] = case
        if case is not None:
            r = {**r, "critical_path_delay_ns": scen_delay, "fmax_mhz": 1000.0 / scen_delay}
        return r
    monkeypatch.setattr(rx, "run_sta", sta)
    return rx, log, calls


DECL = [{"name": "case_a", "case": {"m": 1}, "by": "R.021", "when": None},
        {"name": "case_b", "case": {"m": 0}, "by": "R.021", "when": None}]


def test_the_record_carries_each_scenario_on_every_corner(tmp_path, monkeypatch):
    rx, log, calls = _with_scenarios(tmp_path, monkeypatch, DECL)
    rec = rx.run_experiment("TOP", {}, "tt.lib")
    sc = rec["sta"]["scenarios"]
    assert [s["name"] for s in sc] == ["case_a", "case_b"]
    assert sc[0]["case"] == {"m": 1} and sc[0]["by"] == "R.021"
    assert sc[0]["critical_path_delay_ns"] == 0.5 and sc[0]["fmax_mhz"] == 2000.0
    assert sc[0]["fmax_method"] == "analytic"
    assert set(sc[0]["corners"]) == {"SS", "FF"}
    assert sc[0]["corners"]["SS"]["critical_path_delay_ns"] == 0.5
    scen_calls = [c for c in calls["sta"] if c.get("case") is not None]
    assert len(scen_calls) == 6 and all(c["vcd"] is None for c in scen_calls), "场景 STA 不读 VCD"
    assert rec["sta"]["fmax_mhz"] != 2000.0, "主字段仍是不定值的那次"
    assert json.loads(log.read_text())["sta"]["scenarios"] == sc


def test_an_undeclared_design_records_an_empty_list(tmp_path, monkeypatch):
    rx, log, _ = _with_scenarios(tmp_path, monkeypatch, [])
    assert rx.run_experiment("TOP", {}, "tt.lib")["sta"]["scenarios"] == []


def test_a_scenario_slower_than_the_main_sta_is_refused(tmp_path, monkeypatch):
    rx, log, _ = _with_scenarios(tmp_path, monkeypatch, DECL, scen_delay=99.0)
    with pytest.raises(RuntimeError, match="case_a"):
        rx.run_experiment("TOP", {}, "tt.lib")
    assert not log.exists()


# --- 内部#198：场景按参数组合适用（when）------------------------------------------------

def test_when_selects_the_scenarios_of_a_param_combo(fixture_designs):
    from flow.paths import scenarios
    assert [s["name"] for s in scenarios("SCEN_WHEN_TOP", {"DAT_W": 8, "PICK": 0})] == ["deep"]
    assert [s["name"] for s in scenarios("SCEN_WHEN_TOP", {"DAT_W": 8, "PICK": 1})] == ["shallow"]
    full = scenarios("SCEN_WHEN_TOP")
    assert [(s["name"], s["when"]) for s in full] == [("deep", {"PICK": [0]}), ("shallow", {"PICK": [1]})]
    assert scenarios("SCEN_TOP", {"DAT_W": 8})[0]["when"] is None, "没写 when 的场景对所有组合适用"


@pytest.mark.parametrize("when, msg", [
    ({"NO_SUCH": 0}, "未声明的参数 'NO_SUCH'"),
    ({"PICK": 7}, "值 7 不在"),
    ({}, "when 要是非空"),
])
def test_a_bad_when_is_refused(monkeypatch, fixture_designs, when, msg):
    import flow.paths as paths
    real = paths.load_design_config
    def cfg(d, *a, **k):
        c = real(d, *a, **k)
        if d == "SCEN_WHEN_TOP":
            c = {**c, "sta": {**c["sta"], "scenarios": [{"name": "x", "case": {"mode": 0}, "by": "R.001", "when": when}]}}
        return c
    monkeypatch.setattr(paths, "load_design_config", cfg)
    with pytest.raises(paths.ParamError, match=msg):
        paths.scenarios("SCEN_WHEN_TOP")


def test_a_combo_missing_a_when_key_is_refused(fixture_designs):
    from flow.paths import ParamError, scenarios
    with pytest.raises(ParamError, match="PICK"):
        scenarios("SCEN_WHEN_TOP", {"DAT_W": 8})


@pytest.mark.flow
@needs_tools
def test_depth_measures_only_the_scenario_of_the_combo(tmp_path, fixture_designs):
    """PICK=1 只适用 shallow：预算 20 不超标；以前全局场景会把 deep 也量进来、超标。"""
    from flow.synth.depth import measure
    r = measure("SCEN_WHEN_TOP", params={"DAT_W": 8, "PICK": 1}, out_dir=tmp_path, budget=20)
    assert [s["name"] for s in r["scenarios"]] == ["shallow"]
    assert r["over_budget"]["count"] == 0


def test_the_record_lists_only_the_applicable_scenarios_with_their_when(tmp_path, monkeypatch):
    rx, log, calls = _with_scenarios(tmp_path, monkeypatch, [])
    seen = {}
    def scen(design, params=None):
        seen["params"] = params
        return [{"name": "case_a", "case": {"m": 1}, "by": "R.021", "when": {"P": [1]}}]
    monkeypatch.setattr(rx, "scenarios", scen)
    rec = rx.run_experiment("TOP", {"P": 1}, "tt.lib")
    assert seen["params"] == {"P": 1}, "要按本组合的参数取适用场景"
    assert [(s["name"], s["when"]) for s in rec["sta"]["scenarios"]] == [("case_a", {"P": [1]})]
