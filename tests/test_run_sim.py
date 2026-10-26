"""`_fst_to_vcd` 报告的产物必须真的存在。

为什么值得有这个测试：`fst2vcd` 的 usage 是 `[OPTION]... [FSTFILE]`，把文件名写在
`-o` 前面时，BSD / macOS 的 getopt 在第一个非选项参数处停止解析，`-o <vcd>` 不再被
当作选项，VCD 按默认行为打到 stdout —— 而调用处的 `capture_output=True` 把它吞掉。
工具**以 0 退出**，`check=True` 放行，函数返回一个指向不存在文件的路径。

故障因此不在出错点浮现：它延后到 `flow/sim/vcd_stats.py` 才爆成 `vcdvcd` 内部的
`FileNotFoundError`，读的人会以为仿真没产出波形。这是本仓库的头号失效模式
——「报告的范围大于实际做到的范围」——长在流程的生产侧。

夹具用**桩 `fst2vcd`**：要测的输入是「工具以 0 退出但不产出文件」，真工具构造不出
这个输入；桩既能构造，又让这些用例在没装工具链的机器上照样跑。
"""
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.sim.run_sim import _fst_to_vcd

# 桩打到 stdout 的内容。真 fst2vcd 在这条路径上吐的正是 VCD 正文，
# 这里放一个可检索的标记，用来验断言失败时错误信息带上了工具的实际输出。
STDOUT_MARKER = "$date Mon Sep 13 2026 $end STUB-VCD-ON-STDOUT"

SILENT_STUB = f"""\
#!/bin/sh
# 复刻真实故障：以 0 退出，VCD 打到 stdout，不生成任何文件。
echo '{STDOUT_MARKER}'
exit 0
"""

HONEST_STUB = """\
#!/bin/sh
# 正确识别 -o 的桩：把内容写进指定文件。
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *)  shift ;;
  esac
done
[ -n "$out" ] || exit 2
echo '$date stub $end' > "$out"
exit 0
"""


def _stub_path(tmp_path, monkeypatch, body):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "fst2vcd"
    stub.write_text(body)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bindir), prepend=os.pathsep)
    return stub


def _build_dir_with_fst(tmp_path):
    build = tmp_path / "build"
    (build / "sim_build").mkdir(parents=True)
    fst = build / "sim_build" / "dump.fst"
    fst.write_bytes(b"\x00not-a-real-fst")
    return build, fst


def test_tool_exit_zero_without_output_is_caught(tmp_path, monkeypatch):
    """工具以 0 退出却没产出文件时，必须在这一段失败，不能返回没核实过的路径。"""
    _stub_path(tmp_path, monkeypatch, SILENT_STUB)
    build, fst = _build_dir_with_fst(tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        _fst_to_vcd(build)

    msg = str(excinfo.value)
    assert "fst2vcd" in msg, "错误必须指明是哪一段没产出东西"
    assert str(fst.with_suffix(".vcd")) in msg, "错误必须指明缺的是哪个文件"
    assert STDOUT_MARKER in msg, (
        "错误必须带上工具的实际输出——参数被误解这个原因只存在于那里，"
        "少了它读者会被引向「仿真没产出波形」这个错误方向"
    )


def test_returns_path_when_product_exists(tmp_path, monkeypatch):
    """产物确实生成时，照常返回它的路径。"""
    _stub_path(tmp_path, monkeypatch, HONEST_STUB)
    build, fst = _build_dir_with_fst(tmp_path)

    vcd = _fst_to_vcd(build)

    assert vcd == fst.with_suffix(".vcd")
    assert vcd.exists() and vcd.stat().st_size > 0


def test_no_fst_at_all_still_returns_none(tmp_path, monkeypatch):
    """回归：一个 .fst 都没有时仍返回 None —— 这一路由 run_experiment 的守卫接手，
    它报的是「tb 是否开了波形转储」，与本文件要挡的静默失败是不同的原因。"""
    _stub_path(tmp_path, monkeypatch, SILENT_STUB)
    build = tmp_path / "empty_build"
    build.mkdir()

    assert _fst_to_vcd(build) is None


# --- 单次原始产物不得写进设计根 ---------------------------------------------

needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog 不在 PATH")

DESIGN_ROOT = REPO_ROOT / "cbb" / "cbb_lzd"    # 真实设计夹具（开源构件，内部#305）


def _design_root_files():
    """设计根下的文件集合。**不看 git**：`results.xml` 在 .gitignore 里，
    用 `git status` 检查「有没有写进设计根」会让它免检 —— 而产物本来就该被
    ignore，所以那个观察量覆盖不到几乎任何要防的情形。"""
    return {p.relative_to(DESIGN_ROOT) for p in DESIGN_ROOT.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


@needs_iverilog
def test_simulation_leaves_no_file_in_the_design_root(tmp_path):
    """真跑一次仿真，设计根必须逐项不变，`results.xml` 必须落在 runs 侧。

    用假 runner 只能证明「传进去的参数长得对」；而这里要防的恰恰是
    「参数看着对、第三方库把它解析到别处」—— 观察量必须是目录本身。
    """
    from flow.sim.run_sim import run_sim

    stale = DESIGN_ROOT / "tb" / "results.xml"
    stale.unlink(missing_ok=True)   # 修复前留下的残留，不是本次的产物
    before = _design_root_files()

    build_dir = tmp_path / "sim"
    result = run_sim("CBB_LZD",
                     {"DAT_W": 32, "MSB_EN": 0, "SCHEME": 0},
                     out_dir=build_dir)

    assert result["passed"]
    assert not stale.exists(), f"仿真把结果文件写进了设计根：{stale}"
    assert _design_root_files() == before, "设计根下多出了文件"
    assert Path(result["results_xml"]).is_relative_to(build_dir), (
        f"results.xml 不在本次运行目录下：{result['results_xml']}")


# --- 内部#53：字节码缓存不许落进设计根，而且不能靠调用方走 make ----------------
#
# 为什么值得有这一组：`PYTHONPYCACHEPREFIX` 原来只在 `flow/Makefile` 里 export，
# `run_sim.py` 自己不设。cocotb 会 import 设计根下的 `tb/test_<top>.py`，于是
# **任何绕开 Makefile 的调用**都在 `designs/<root>/tb/` 下留一个 `__pycache__`——
# 而绕开 make 正是取证、调试、写测试时最常走的那条路（2026-09-20 实撞两次）。
#
# `repo-layout` 的判据写死了是**目录内容**，不是 `git status`：被 .gitignore
# 挡住的产物同样是写进了设计根。所以这里比对的是文件清单，不是 git 的视野。

def _tree(root):
    return {str(p.relative_to(root)) for p in Path(root).rglob("*")}


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog 不在 PATH")
def test_running_run_sim_directly_leaves_the_design_root_clean(tmp_path):
    """M3: 不走 make 直接跑 `run_sim.py`，设计根下不许多出任何文件。"""
    import subprocess

    root = REPO_ROOT / "cbb" / "cbb_lzd"
    before = _tree(root)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPYCACHEPREFIX"}
    env["PYTHONDONTWRITEBYTECODE"] = ""        # 明确不靠「干脆不写」来绕过
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "flow/sim/run_sim.py"),
         "--design", "CBB_LZD", "--param", "DAT_W=32",
         "--param", "MSB_EN=0", "--param", "SCHEME=0"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    after = _tree(root)
    stray = sorted(after - before)
    for s in stray:                            # 别把仓库留脏，哪怕这条用例要红
        p = root / s
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert not stray, (
        f"直接调 run_sim.py 之后设计根下多出了 {stray} —— "
        "判据是目录内容不是 git status（被 .gitignore 挡住的产物同样是"
        "写进了设计根，repo-layout）")


def test_the_flow_does_not_override_a_cache_prefix_the_caller_already_set(tmp_path):
    """M4 (regression): 调用方已经给了 `PYTHONPYCACHEPREFIX` 就不覆盖。

    `setdefault` 而不是赋值：Makefile 已经设过时不动它，否则「谁说了算」
    会取决于 import 顺序 —— 那是最难查的一类。
    """
    import subprocess

    mine = str(tmp_path / "mycache")
    env = dict(os.environ, PYTHONPYCACHEPREFIX=mine)
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys, os; sys.path.insert(0, %r);"
         "import flow.sim.run_sim;"
         "print(os.environ['PYTHONPYCACHEPREFIX'])" % str(REPO_ROOT)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == mine, (
        f"流程把调用方给的缓存前缀覆盖成了 {r.stdout.strip()!r}")
