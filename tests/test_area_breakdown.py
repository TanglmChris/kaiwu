"""按层次拆开的面积（area-breakdown，内部#174；experiment-record「记录必须携带按层次拆开的面积」）。

为什么值得有这组测试：面积表是给用户拍板用的，拆错了不会有任何东西失败 —— 实例数没乘、胶合逻辑
算漏、存储模型只数到第 2 级，表照样能生成，只是数字是错的。这里用一个层次已知的夹具把几条
算术关系钉死：每层子行加胶合行等于父行、顶层等于 `synth.area_um2`、实例数乘进面积、存储模型按
实例数累计到第 3 级。
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

needs_tools = pytest.mark.skipif(shutil.which("yosys") is None or not LIBERTY.is_file(),
                                 reason="需要 yosys 与合并 liberty")


@pytest.fixture
def synthesized(tmp_path, fixture_designs):
    from flow.synth.synth import run_synth
    return run_synth("AREA_TOP", {"DAT_W": 8}, str(LIBERTY), out_dir=tmp_path)


@needs_tools
@pytest.mark.flow
def test_hierarchy_adds_up_and_instances_are_multiplied(synthesized, fixture_designs):
    from flow.synth import area
    bd = area.breakdown("AREA_TOP", synthesized["stats_path"], str(LIBERTY))
    rows = {r["path"]: r for r in bd["hierarchy"]}
    top = rows["AREA_TOP"]
    assert top["level"] == 0 and abs(top["area_um2"] - synthesized["area_um2"]) < 1e-6
    # 两个 AREA_LEAF 同参数，合成一行、实例数 2，面积已乘
    leaf = [r for r in bd["hierarchy"] if r["module"] == "AREA_LEAF"]
    assert len(leaf) == 1 and leaf[0]["instances"] == 2 and leaf[0]["level"] == 1
    # 每一层：子行 + 胶合行 = 父行
    for parent in bd["hierarchy"]:
        kids = [r for r in bd["hierarchy"] if r["path"].rsplit("/", 1)[0] == parent["path"] and r["level"] == parent["level"] + 1]
        if not kids:
            continue
        assert abs(sum(k["area_um2"] for k in kids) - parent["area_um2"]) < 1e-6, parent["path"]
        assert abs(sum(k["sequential_area_um2"] for k in kids) - parent["sequential_area_um2"]) < 1e-6
    # 只展开到第 2 级：AREA_SUB 下的 AREA_MEM（第 3 级）不单列
    assert max(r["level"] for r in bd["hierarchy"]) == 2
    assert "AREA_TOP/AREA_MID/AREA_SUB" in rows
    # 存储模型：两个实例（AREA_MID 下一个、AREA_SUB 下一个，后者在第 3 级）
    mem_row = rows["AREA_TOP/AREA_MID/AREA_MEM"]
    assert bd["memory_models"]["modules"] == ["AREA_MEM"]
    assert abs(bd["memory_models"]["area_um2"] - 2 * mem_row["area_um2"]) < 1e-6
    assert bd["memory_models"]["sequential_area_um2"] > 0
    assert abs(bd["sequential_area_um2"] - top["sequential_area_um2"]) < 1e-6


@needs_tools
def test_gate_unit_is_read_from_the_liberty():
    from flow.synth import area
    assert area.gate_unit(str(LIBERTY)) == {"cell": "NAND2x1_ASAP7_75t_R", "area_um2": 0.08748}


@needs_tools
@pytest.mark.flow
def test_a_misspelled_memory_model_is_refused(synthesized):
    from flow.synth import area
    with pytest.raises(RuntimeError, match="AREA_MEMX"):
        area.breakdown("AREA_TOP", synthesized["stats_path"], str(LIBERTY), memory_models=["AREA_MEMX"])


def test_memory_models_are_in_the_design_recipe(fixture_designs):
    from flow.flow_fingerprint import METRIC_MODULES, design_recipe
    assert design_recipe("AREA_TOP")["memory_models"] == ["AREA_MEM"]
    assert "flow/synth/area.py" in METRIC_MODULES
