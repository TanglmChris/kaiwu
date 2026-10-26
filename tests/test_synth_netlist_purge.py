"""网表不得留下不接任何单元的具名线（flow-batch-2026-10 的 1.3，内部#64）。

RTL 用 `integer` 做 for 循环变量时，yosys 展开循环之后留下一行
`wire signed [31:0] i;`：它不接任何逻辑，但默认的 `opt_clean` 保留具名线，而
OpenSTA 的 Verilog 读入器不认 `signed`，整个网表读不进。以前靠 RTL 迁就
（`LZD_TOOL` 改用定宽 reg 加两条 lint 豁免）；现在综合写网表之前 `opt_clean -purge`。
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
needs_flow = pytest.mark.skipif(
    any(shutil.which(t) is None for t in ("yosys", "sta")) or not LIBERTY.is_file(),
    reason="需要 yosys、sta 在 PATH 上与合并 liberty 在本机")

INTLOOP = """\
module INTLOOP (input wire [7:0] i_dat, output reg [3:0] o_cnt);
integer i;
always @* begin
    o_cnt = 4'd0;
    for (i = 0; i < 8; i = i + 1) o_cnt = o_cnt + i_dat[i];
end
endmodule
"""

YAML = """\
design_root: intloop
tops:
  INTLOOP:
    sim: {clock_signal: null}
    sta: {ideal_drive_ports: []}
    params: {}
"""


@needs_flow
def test_an_integer_loop_variable_leaves_nothing_sta_cannot_read(tmp_path, monkeypatch):
    import flow.paths as fp
    import flow.synth.synth as sy
    from flow.sta.run_sta import run_sta

    root = tmp_path / "designs" / "intloop"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "intloop.v").write_text(INTLOOP)
    (root / "params.yaml").write_text(YAML)
    monkeypatch.setattr(sy, "SOURCE_SET_CACHE", tmp_path / "runs" / ".source_sets")
    monkeypatch.setattr(sy, "resolve_design_root",
                        lambda x: fp.resolve_design_root(x, repo_root=tmp_path))
    monkeypatch.setattr(sy, "validate_params",
                        lambda x, p: fp.validate_params(x, p, repo_root=tmp_path))
    monkeypatch.setattr(sy, "keep_hierarchy_modules", lambda x: [])

    res = sy.run_synth("INTLOOP", {}, LIBERTY, out_dir=tmp_path / "synth")
    netlist = Path(res["netlist_path"])
    assert "signed" not in netlist.read_text(), (
        "网表里留着 integer 循环变量的 signed 声明，OpenSTA 读不进：\n"
        + "\n".join(l for l in netlist.read_text().splitlines() if "signed" in l))
    sta = run_sta("INTLOOP", netlist, LIBERTY, out_dir=tmp_path / "sta", repo_root=tmp_path)
    assert sta.get("critical_path_delay_ns") is not None, sta
