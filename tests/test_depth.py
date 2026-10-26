"""flow/synth/depth.py：不写记录地量被测顶层或其子模块的逻辑级数（内部#111，logic-depth）。"""
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

pytestmark = [
    pytest.mark.flow,
    pytest.mark.skipif(any(shutil.which(t) is None for t in ("yosys", "sta")),
                       reason="yosys / sta 不在 PATH"),
]

def _stat():
    """全部记录文件的 (路径, mtime)：量深度不得写任何一个（含已删设计根的与旧的单文件）。"""
    from flow import records
    files = records.record_files() + [REPO_ROOT / "results" / "experiments.jsonl"]
    return [(f, f.stat().st_mtime_ns) for f in files if f.exists()]


@pytest.mark.parametrize("module", [None, "IP_SUB"])
def test_depth_of_the_top_and_of_a_submodule(tmp_path, fixture_designs, module):
    """量 IP_TOP 本身与它例化的组合子模块 IP_SUB：级数、到达时间 > 0，起止点非空，不写记录。"""
    from flow.synth.depth import measure
    before = _stat()
    r = measure("IP_TOP", module, {"DAT_W": 16}, out_dir=tmp_path / "d")
    assert r["module"] == (module or "IP_TOP")
    assert r["stages"] > 0 and r["delay"] and r["delay"] > 0, r
    assert r["startpoint"] and r["endpoint"], r
    assert Path(r["checks"]).is_file()
    assert _stat() == before, "量级数不该写记录"


def test_unknown_module_is_named(tmp_path, fixture_designs):
    from flow.synth.depth import measure
    with pytest.raises(RuntimeError, match="NO_SUCH_MOD"):
        measure("IP_TOP", "NO_SUCH_MOD", out_dir=tmp_path / "d")


# --- sta-static-ports（内部#154）----------------------------------------------------

def test_static_ports_and_reset_do_not_start_the_worst_path(tmp_path, fixture_designs):
    """内部#154（sta-static-ports D5）：量顶层时用它的 static_ports；默认把 *rst_n* 也当不计时序的起点。"""
    from flow.synth.depth import measure
    r = measure("CFG_TOP", out_dir=tmp_path / "d")
    tcl = (tmp_path / "d" / "depth.tcl").read_text()
    assert "set_false_path -from [get_ports {cfg}]" in tcl, tcl
    assert "*rst_n*" in tcl, tcl
    assert not r["startpoint"].startswith("cfg"), r


def test_false_from_none_drops_the_reset_default(tmp_path, fixture_designs):
    from flow.synth.depth import measure
    measure("CFG_TOP", out_dir=tmp_path / "d", false_from=[])
    assert "*rst_n*" not in (tmp_path / "d" / "depth.tcl").read_text()


def test_paths_lists_the_deepest_endpoints(tmp_path, fixture_designs):
    """内部#154（sta-static-ports D5）：--paths N 按级数降序列出起点、终点、级数。"""
    from flow.synth.depth import measure
    r = measure("CFG_TOP", out_dir=tmp_path / "d", false_from=[], paths=3)
    got = r["paths"]
    assert 1 <= len(got) <= 3, got
    assert [p["stages"] for p in got] == sorted((p["stages"] for p in got), reverse=True)
    assert all(p["startpoint"] and p["endpoint"] for p in got), got


# --- 内部#167：量顶层按 sta.clocks 建钟，量子模块只看它自己的端口 --------------------------

def test_the_top_is_clocked_by_its_declared_clocks(tmp_path, fixture_designs):
    """内部#167：顶层声明了 sta.clocks（端口 core_clk），子模块的端口叫 clk——时钟必须建在 core_clk 上，
    寄存器路径受约束；不得因为网表里某个子模块有 input clk 就在顶层建一个不存在的 clk。"""
    from flow.synth.depth import measure
    measure("CFG_TOP", out_dir=tmp_path / "d", false_from=[])
    tcl = (tmp_path / "d" / "depth.tcl").read_text()
    assert "create_clock -name core_clk" in tcl, tcl
    assert "[get_ports clk]" not in tcl, tcl
    assert "core_clk" in (tmp_path / "d" / "checks.rpt").read_text()


def test_a_submodule_is_clocked_only_by_its_own_clk_port(tmp_path, fixture_designs):
    from flow.synth.depth import measure
    measure("CFG_TOP", "CFG_REG", out_dir=tmp_path / "d", false_from=[])
    assert "create_clock -name clk -period 10 [get_ports clk]" in (tmp_path / "d" / "depth.tcl").read_text()


# --- 内部#184 级数预算：一次综合列出全部超预算的终点，不受 PATHS 截断 ------------------------

def test_a_budget_lists_every_endpoint_over_it_not_just_the_deepest(tmp_path, fixture_designs):
    """BUDGET_TOP：DEEP 链 46 级、MID 链 30 级、SHORT 链 7 级（报告行数）。预算 20 时 DEEP 与 MID 两批都要列出来，
    即使 paths=1（以前只看最深的那条，MID 那批要等 DEEP 修完才冒出来）；SHORT 不列；分组按起止模块。"""
    from flow.synth.depth import measure
    r = measure("BUDGET_TOP", out_dir=tmp_path, paths=1, budget=20)
    ob = r["over_budget"]
    assert ob["budget"] == 20
    groups = {(g["from"], g["to"]): g for g in ob["groups"]}
    assert set(groups) == {("U_BUDGET_TOP_DEEP", "U_BUDGET_TOP_DEEP"), ("U_BUDGET_TOP_MID", "U_BUDGET_TOP_MID")}
    assert groups[("U_BUDGET_TOP_DEEP", "U_BUDGET_TOP_DEEP")]["max_stages"] == r["stages"]
    assert 20 < groups[("U_BUDGET_TOP_MID", "U_BUDGET_TOP_MID")]["max_stages"] < r["stages"]
    assert ob["count"] == sum(g["count"] for g in ob["groups"]) >= 2
    deepest = groups[("U_BUDGET_TOP_DEEP", "U_BUDGET_TOP_DEEP")]["paths"][0]
    assert deepest["stages"] > 20 and deepest["startpoint"] and deepest["endpoint"] and deepest["pins"]


def test_the_cli_exits_non_zero_when_anything_is_over_budget(tmp_path, fixture_designs, capsys):
    from flow.synth import depth
    assert depth.main(["--design", "BUDGET_TOP", "--budget", "20"]) == 1
    assert "超过预算 20 个组合单元的终点" in capsys.readouterr().out
    assert depth.main(["--design", "BUDGET_TOP", "--budget", "60"]) == 0


# --- 内部#207 预算按组合单元数比：报告行数里起点寄存器的 CLK / Q、终点的 D / 端口不算 ------------

def _over_paths(ob):
    return [p for g in ob["groups"] for p in g["paths"]]


@pytest.mark.parametrize("module, extra", [(None, 3), ("BUDGET_PORT_CHAIN", 2)])
def test_the_budget_counts_combinational_cells_not_report_rows(tmp_path, fixture_designs, module, extra):
    """寄存器起点：行数 = 组合单元数 + 3；输入端口起点：+ 2。超标列表两种数都给；
    预算取「最深那条的行数 − 1」时按行数会超、按组合单元数不超，列表必须是空的。"""
    from flow.synth.depth import measure
    r = measure("BUDGET_TOP", module, out_dir=tmp_path / "a", budget=5)
    paths = _over_paths(r["over_budget"])
    assert paths
    for p in paths:
        assert p["comb_cells"] == p["stages"] - extra, p
    for g in r["over_budget"]["groups"]:
        assert g["max_comb_cells"] == g["paths"][0]["comb_cells"]
    rows = max(p["stages"] for p in paths)
    tight = measure("BUDGET_TOP", module, out_dir=tmp_path / "b", budget=rows - 1)
    assert tight["over_budget"]["count"] == 0, tight["over_budget"]


# --- 内部#189 验收场景：一次综合，按场景把静态输入定值各跑一遍 STA ----------------------------

def test_each_declared_scenario_is_measured_with_its_static_inputs_fixed(tmp_path, fixture_designs):
    """SCEN_TOP：静态输入 mode 选深链（mode=0）或浅链（mode=1）。不分场景时两条链都算；
    按场景量，deep 超预算 20、shallow 不超——超标归到声明它的场景，不再因互斥排布的组合路径误报。"""
    from flow.synth.depth import measure
    r = measure("SCEN_TOP", out_dir=tmp_path, budget=20)
    by = {s["name"]: s for s in r["scenarios"]}
    assert set(by) == {"deep", "shallow"}
    assert by["deep"]["over_budget"]["count"] >= 1
    assert by["shallow"]["over_budget"]["count"] == 0, by["shallow"]["over_budget"]
    assert by["shallow"]["stages"] <= 20 < by["deep"]["stages"]
    assert r["scenario"] == "deep" and r["stages"] == by["deep"]["stages"]
    assert "set_case_analysis 1 [get_ports {mode}]" in (tmp_path / "depth.shallow.tcl").read_text()
    assert len(list(tmp_path.glob("*_netlist.v"))) == 1   # 只综合一次


def test_the_cli_fails_if_any_scenario_is_over_budget(tmp_path, fixture_designs, capsys):
    from flow.synth import depth
    assert depth.main(["--design", "SCEN_TOP", "--budget", "20"]) == 1
    out = capsys.readouterr().out
    assert "[deep" in out and "[shallow" in out



def test_a_submodule_run_says_the_top_is_what_counts(tmp_path, fixture_designs, capsys):
    """design_sub 反馈（2026-10-05）：子模块单独量与顶层里的同一模块网表不同，输出要提示验收以顶层为准。"""
    from flow.synth import depth
    depth.main(["--design", "IP_TOP", "--module", "IP_SUB", "--param", "DAT_W=16"])
    assert "时序验收以顶层为准" in capsys.readouterr().out
    depth.main(["--design", "IP_TOP", "--param", "DAT_W=16"])
    assert "时序验收以顶层为准" not in capsys.readouterr().out
