"""门级仿真：真网表要过 TB，改坏一个单元的网表必须过不了。

与 `tests/test_netlist_equiv.py` 同一个道理：只测正例的话，「TB 其实没连到网表上」
（比如构建时悄悄读进了 RTL）与「网表真的对」输出一模一样。所以每条正例配一条反例。
网表由用例自己现综合（`runs/` 是 gitignored 的，不能当夹具）。
"""
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.sim.gate_sim import CELL_MODEL_DIR, cell_models, gate_sim  # noqa: E402

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

needs_tools = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("yosys", "iverilog")) or not LIBERTY.is_file()
    or not any(CELL_MODEL_DIR.glob("*.v")),
    reason="yosys / iverilog / 合并 liberty / ASAP7 单元模型 不齐")

# 真实设计夹具：ADDER32 一级流水（带时钟与寄存器；10-01 至 10-14 间用的是一个闭源 FIFO 构件，内部#305）
ADDER = ("ADDER32", {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 1, "CSEL_BLK_W": 4})


def _synth(tmp_path, design, params):
    from flow.synth.synth import run_synth
    return Path(run_synth(design, params, str(LIBERTY), out_dir=tmp_path / "synth")["netlist_path"])


def _mutants(netlist, tmp_path, limit=8):
    """依次给出把第 k 个二输入门换成另一种的网表 —— 函数一定变，端口不变。

    换中的门可能落在可达状态上冗余的逻辑里（内部#301：一个 FIFO 构件的第一个门 NAND 换成 NOR，
    只在深度到不了的 cnt = 5 / 6 时不同），单个反例过了 TB 不说明 TB 没连上。所以给前 limit 个，
    任一个被 TB 抓到就算连上；全过才说明 TB 没连到网表上。
    """
    text = netlist.read_text()
    swaps = {"XOR2xp5_ASAP7_75t_R": "XNOR2xp5_ASAP7_75t_R",
             "XNOR2xp5_ASAP7_75t_R": "XOR2xp5_ASAP7_75t_R",
             "NAND2xp5_ASAP7_75t_R": "NOR2xp33_ASAP7_75t_R",
             "NOR2xp33_ASAP7_75t_R": "NAND2xp5_ASAP7_75t_R"}
    found = list(re.finditer("|".join(swaps), text))[:limit]
    assert found, "网表里没有可替换的单元 —— 反例构造不出来，这条用例就证明不了什么"
    for k, m in enumerate(found):
        bad = tmp_path / f"bad_netlist_{k}.v"
        bad.write_text(text[:m.start()] + swaps[m.group(0)] + text[m.end():])
        yield k, bad


def _root_files(root):
    return {p.relative_to(root) for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


@pytest.mark.flow
@needs_tools
def test_the_netlist_passes_the_tb_and_a_mutated_one_does_not(tmp_path):
    from flow.paths import resolve_design_root

    design, params = ADDER
    nl = _synth(tmp_path, design, params)
    root = resolve_design_root(design)
    before = _root_files(root)

    status, note = gate_sim(design, params, nl, tmp_path / "gls")
    assert status == "PASSED", note
    assert _root_files(root) == before, "门级仿真在设计根下留了文件"

    passed = []
    for k, bad in _mutants(nl, tmp_path):
        status, note = gate_sim(design, params, bad, tmp_path / f"gls_bad_{k}")
        if status == "FAILED":
            # 失败必须来自 TB 的断言，不是构建没起来 —— 后者什么也证明不了
            assert note.startswith("TB 结论见"), note
            break
        passed.append(f"第 {k} 个：{status}")
    else:
        pytest.fail("改掉一个单元的网表全都过了 TB —— TB 没连到网表上？\n" + "\n".join(passed))


def test_missing_cell_models_are_named_not_guessed(tmp_path):
    (tmp_path / "asap7sc7p5t_AO_RVT_TT_201020.v").write_text("")
    with pytest.raises(FileNotFoundError, match="INVBUF"):
        cell_models(tmp_path)
