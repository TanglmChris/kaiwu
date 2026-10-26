"""`--sim verilator` 必须真能用：每个被测顶层都跑得通，波形落在 runs 侧。

为什么值得有这个文件：`verilator` 在 `--sim` 的取值里列了很久，却一个组合都跑不通
（内部#22 第 1 条；2026-09-27 全组合实测 117/117 构建失败）。三处各自独立地断：
`UNOPTFLAT` 把按位赋值的向量当组合环、宽度类告警默认致命、`dump.vcd` 落在设计根的
`tb/`（测试的工作目录）。一个列在取值里却跑不通的仿真器，看起来是个可用的旋钮。

2026-10-14 起用开源的 ADDER32（内部#305）：前缀网络的组合档与带寄存器的流水档各一档，两档都要靠
设计根 designs/adder32/sim_waivers.vlt 里的 UNOPTFLAT 豁免才能构建（内部#312 起 run_sim 读设计根的豁免；
之前在 flow/sim/verilator.vlt）。10-01 至 10-14 间 ADDER32 随设计根删除，
用的是一个闭源 FIFO 构件。
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

pytestmark = [
    pytest.mark.flow,
    pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator 不在 PATH"),
]

# 真实设计夹具：ADDER32 的两档（内部#305）。2026-10-14 实测 2 种位宽 × 6 种进位结构 × 3 种流水级数共
# 36 档在补回的豁免下全部构建并通过；这里挑 Kogge-Stone 组合档与 Brent-Kung 两级流水档。
CASES = [
    ("ADDER32", {"DAT_W": 32, "SCHEME": 4, "PIPE_STAGES": 0, "CSEL_BLK_W": 4}),
    ("ADDER32", {"DAT_W": 8, "SCHEME": 5, "PIPE_STAGES": 2, "CSEL_BLK_W": 4}),
]


def _params(design, params):
    if params is not None:
        return params
    from flow.paths import param_combos
    return next(iter(param_combos(design)))


def _root_files(root):
    """设计根下的文件集合。判据是目录内容，不是 git（repo-layout）。"""
    return {p.relative_to(root) for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


@pytest.mark.parametrize("design,params", CASES, ids=["pt0", "pt1"])
def test_verilator_runs_and_keeps_the_wave_on_the_runs_side(tmp_path, design, params):
    from flow.paths import resolve_design_root
    from flow.sim.run_sim import run_sim

    root = resolve_design_root(design)
    before = _root_files(root)
    build = tmp_path / "sim"
    result = run_sim(design, _params(design, params), sim="verilator", out_dir=build)
    stray = sorted(_root_files(root) - before)
    for s in stray:                    # 别把仓库留脏，哪怕这条用例要红
        (root / s).unlink(missing_ok=True)

    assert result["passed"], result
    assert not stray, f"verilator 仿真在设计根下留了 {stray}"
    vcd = result["vcd_path"]
    assert vcd is not None, "仿真通过却没有收到 VCD —— run_experiment 会当场拒记"
    assert Path(vcd).is_relative_to(build), f"VCD 不在本次构建目录下：{vcd}"
    assert Path(vcd).stat().st_size > 0


def _all_sim_waiver_files():
    """每个顶层的 verilator 构建实际读的全部豁免文件（flow/ 两份 + 各设计根的 waivers.vlt / sim_waivers.vlt）。"""
    from flow.paths import _top_index
    from flow.sim.run_sim import verilator_configs
    files = {p for top in _top_index(REPO_ROOT) for p in verilator_configs(top)}
    return sorted(files)


def test_every_simulator_waiver_names_a_file_and_a_signal():
    """与 lint 同一纪律：每条豁免带 `-file` 与 `-match`，不许整规则、整文件地关。
    内部#312 起设计专属条目在设计根的 sim_waivers.vlt，纪律覆盖 run_sim 会读的每一份。"""
    files = _all_sim_waiver_files()
    assert any(p.name == "sim_waivers.vlt" for p in files), files   # 设计根的那几份确实被读到
    lines = [l for p in files for l in p.read_text().splitlines()
             if l.strip() and not l.lstrip().startswith("//") and not l.startswith("`")]
    # 豁免文件可以是空的；有的话每条都要点名
    for l in lines:
        assert re.match(r'lint_off -rule \w+ +-file "[^"]+" +-match "[^"*][^"]*"|'
                        r'lint_off -rule \w+ +-file "[^"]+" +-match "\*[^"]+"', l), (
            f"豁免没有同时点名文件与信号：{l}")
        assert "-match \"*\"" not in l


def test_flow_sim_waivers_hold_no_design_specific_entries():
    """内部#312：flow/sim/verilator.vlt 只放通用条目；设计专属的在各设计根的 sim_waivers.vlt。"""
    from flow.sim.run_sim import VERILATOR_CONFIGS
    sim_vlt = next(p for p in VERILATOR_CONFIGS if p.name == "verilator.vlt")
    entries = [l for l in sim_vlt.read_text().splitlines() if l.startswith("lint_off")]
    assert entries == [], entries
