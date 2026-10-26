"""触发器映射到同功能里面积最小的单元（内部#176，experiment-trust）。

为什么值得有这个测试：`dfflibmap` 默认只用输出极性相符的单元，ASAP7 里 Q 输出的上升沿触发器只有
`DFFHQx4`（0.3645 µm²），于是不复位的触发器全部落在 x4 上，比 `DFFHQNx1`（0.2916 µm²）大 25%。
一个大设计的触发器占面积 41–44%，所有设计的面积都系统性偏大，而流程不报任何错。
"""
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

pytestmark = [
    pytest.mark.flow,
    pytest.mark.skipif(shutil.which("yosys") is None or not LIBERTY.is_file(), reason="需要 yosys 与合并 liberty"),
]


def test_unreset_flops_map_to_the_smallest_cell(tmp_path, fixture_designs):
    """夹具 SHAPE_REG1：8 个不带复位的触发器（`always @(posedge clk) y_r <= ~i_a;`）。
    开源的 ADDER32 的寄存器全带异步复位，测不到这一类；10-01 至 10-14 间用的是一个闭源 FIFO 构件（内部#305）。"""
    from flow.synth.synth import run_synth
    r = run_synth("SHAPE_REG1", {"DAT_W": 8}, str(LIBERTY), out_dir=tmp_path)
    netlist = Path(r["netlist_path"]).read_text()
    cells = re.findall(r"^\s*(DFF\w+)\s", netlist, re.M)
    assert cells, "夹具里应当有触发器"
    assert "DFFHQx4_ASAP7_75t_R" not in cells, sorted(set(cells))
    assert "DFFHQNx1_ASAP7_75t_R" in cells, sorted(set(cells))
    assert "-dont_use DFFHQx4_ASAP7_75t_R" in (tmp_path / "synth.ys").read_text()
