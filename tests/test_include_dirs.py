"""参数片段：设计根的 rtl/inc/ 自动成为 include 目录（flow-batch-2026-10 的 1.2，内部#76）。

书写风格允许用 `include 把参数片段插进参数列表（add-rtl-coding-style D14），而流程
以前一个工具都不传 include 目录：第一个用片段的模块在综合、仿真、lint 里都会找不到
文件。片段改了参数就改了电路，所以它也要进读入集合摘要，否则跳过开关会把最该重跑
的组合跳过（D-14 同形）。
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))
needs_yosys = pytest.mark.skipif(
    shutil.which("yosys") is None or not LIBERTY.is_file(),
    reason="需要 yosys 在 PATH 上与合并 liberty 在本机")
needs_icarus = pytest.mark.skipif(shutil.which("iverilog") is None,
                                  reason="需要 iverilog 在 PATH 上")

P_RTL = """\
module P #(
     parameter DAT_W = 4
`include "foo_param.vh"
)(
     input  wire [DAT_W-1:0] i_a
    ,output wire [DAT_W-1:0] o_y
);
assign o_y = i_a + SHIFT;
endmodule
"""

P_YAML = """\
design_root: p
tops:
  P:
    sim: {clock_signal: null}
    sta: {ideal_drive_ports: []}
    params:
      DAT_W: {type: enum, role: scale, values: [4]}
"""

P_TB = """\
import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def adds_the_shift_from_the_fragment(dut):
    dut.i_a.value = 3
    await Timer(1, unit="ns")
    assert int(dut.o_y.value) == 3 + 2
"""


def _repo(tmp_path, shift=2, dep=False):
    root = tmp_path / "designs" / "p"
    (root / "rtl" / "inc").mkdir(parents=True)
    (root / "tb").mkdir()
    (root / "rtl" / "p.v").write_text(P_RTL)
    (root / "params.yaml").write_text(P_YAML)
    (root / "tb" / "test_P.py").write_text(P_TB)
    inc = root / "rtl" / "inc"
    if dep:
        # 片段放在 deps 的 cbb 根里：P 例化 CBB_Q，片段在 cbb/cbb_q/rtl/inc/
        inc = tmp_path / "cbb" / "cbb_q" / "rtl" / "inc"
        inc.mkdir(parents=True)
        q = tmp_path / "cbb" / "cbb_q"
        (q / "rtl" / "cbb_q.v").write_text(
            "module CBB_Q (input wire i_a, output wire o_y);\nassign o_y = i_a;\nendmodule\n")
        (q / "params.yaml").write_text(
            "design_root: cbb_q\ntops:\n  CBB_Q:\n    sim: {clock_signal: null}\n"
            "    sta: {ideal_drive_ports: []}\n    params: {}\n")
        (root / "params.yaml").write_text(P_YAML + "    deps: [CBB_Q]\n")
        (root / "rtl" / "p.v").write_text(P_RTL.replace(
            "assign o_y", "CBB_Q U_P_LSB_CBB_Q (.i_a(i_a[0]), .o_y());\nassign o_y"))
    (inc / "foo_param.vh").write_text(f"    ,parameter SHIFT = {shift}\n")
    return tmp_path


def _patch(monkeypatch, repo, module):
    import flow.paths as fp
    monkeypatch.setattr(module, "resolve_design_root",
                        lambda x: fp.resolve_design_root(x, repo_root=repo))
    monkeypatch.setattr(module, "validate_params",
                        lambda x, p: fp.validate_params(x, p, repo_root=repo))
    if hasattr(module, "SOURCE_SET_CACHE"):
        monkeypatch.setattr(module, "SOURCE_SET_CACHE", Path(repo) / "runs" / ".source_sets")
    if hasattr(module, "keep_hierarchy_modules"):
        monkeypatch.setattr(module, "keep_hierarchy_modules", lambda x: [])


def test_include_dirs_lists_the_root_and_its_deps(tmp_path):
    from flow.paths import include_dirs

    repo = _repo(tmp_path)
    assert include_dirs("P", repo_root=repo) == [repo / "designs/p/rtl/inc"]
    repo2 = _repo(tmp_path / "d", dep=True)
    assert include_dirs("P", repo_root=repo2) == [repo2 / "cbb/cbb_q/rtl/inc",
                                                    repo2 / "designs/p/rtl/inc"]


def test_a_top_without_inc_has_no_include_dirs():
    from flow.paths import include_dirs

    assert include_dirs("CBB_LZD") == []


@needs_yosys
@pytest.mark.parametrize("dep", [False, True])
def test_synthesis_finds_the_fragment(tmp_path, monkeypatch, dep):
    import flow.synth.synth as sy

    repo = _repo(tmp_path, dep=dep)
    _patch(monkeypatch, repo, sy)
    res = sy.run_synth("P", {"DAT_W": 4}, LIBERTY, out_dir=tmp_path / "out")
    assert res["cell_count"] > 0
    assert "-I" in (tmp_path / "out" / "synth.ys").read_text()


@needs_yosys
def test_editing_only_the_fragment_changes_the_read_set_digest(tmp_path, monkeypatch):
    import flow.synth.synth as sy

    repo = _repo(tmp_path)
    _patch(monkeypatch, repo, sy)
    before = sy.run_synth("P", {"DAT_W": 4}, LIBERTY, out_dir=tmp_path / "a")["sources_sha256"]
    (repo / "designs/p/rtl/inc/foo_param.vh").write_text("    ,parameter SHIFT = 3\n")
    after = sy.run_synth("P", {"DAT_W": 4}, LIBERTY, out_dir=tmp_path / "b")["sources_sha256"]
    assert before != after, "只改了片段，sources_sha256 却没变"


@needs_yosys
def test_tops_without_fragments_keep_their_digest():
    import flow.synth.synth as sy

    src = sy.source_files("CBB_LZD")
    assert sy.read_set_digest("CBB_LZD", src) == sy.sources_digest(src)


@needs_icarus
def test_rtl_simulation_finds_the_fragment(tmp_path, monkeypatch):
    import flow.sim.run_sim as rs
    import flow.synth.synth as sy

    repo = _repo(tmp_path)
    _patch(monkeypatch, repo, rs)
    _patch(monkeypatch, repo, sy)
    monkeypatch.setattr(rs, "source_files", sy.source_files)
    res = rs.run_sim("P", {"DAT_W": 4}, sim="icarus", out_dir=tmp_path / "sim")
    assert res["passed"], res
