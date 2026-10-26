"""Build + run the cocotb testbench for a design with verilator or icarus.

Usable as a library (run_sim()) from scripts/run_experiment.py, or standalone:
    python flow/sim/run_sim.py --design CBB_LZD --param DAT_W=32 --param MSB_EN=0 --param SCHEME=0

`params` is a plain {RTL 参数名: 取值} mapping read from the design's
params.yaml -- no design name appears in this file's logic.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# 字节码缓存必须落在设计根之外，而这件事**不能靠调用方走 make**（本仓 内部#53）。
# cocotb 走 pytest 的 import hook 加载设计根下的 `tb/test_<top>.py`，于是任何
# 绕开 Makefile 的调用都会在 `designs/<root>/tb/` 下留一个 `__pycache__` ——
# 而绕开 make 正是取证、调试、写测试时最常走的那条路（2026-09-20 实撞两次）。
# `repo-layout` 的判据是**目录内容**，不是 `git status`：被 .gitignore 挡住的
# 产物同样是写进了设计根。
#
# `setdefault` 而不是赋值：`flow/Makefile` 已经 export 过时不动它，
# 否则「谁说了算」取决于 import 顺序，那是最难查的一类。
# 必须排在 import cocotb 之前 —— 解释器读这个变量的时机是写 .pyc 的时候，
# 而那发生在第一次 import 设计根下的模块时。
os.environ.setdefault("PYTHONPYCACHEPREFIX", str(REPO_ROOT / ".pycache"))

from flow.paths import (adhoc_run_dir, cli_params, dependency_roots, include_dirs, resolve_design_root,
                        validate_params)
from flow.synth.synth import source_files

# verilator 仿真构建读的配置（告警豁免）。lint 与仿真两类，不合成一份：
# - lint 的：宽度类告警 verilator 仿真时默认也开着、也致命，而它们已在 lint 那边
#   逐条核过 —— 同一批告警、同一批理由，抄一份副本就会漂移（内部#312 实撞：flow 里抄的两条
#   WIDTHTRUNC 还指着搬走前的旧文件，早已失效）；
# - 仿真独有的：UNOPTFLAT 是调度期告警，lint 走不到，理由写在 flow/sim/verilator.vlt 文件头。
# 全仓通用的两份在 flow/ 下（VERILATOR_CONFIGS）；设计专属的写在设计根（内部#312）：被测顶层所在设计根
# 与各依赖根的 waivers.vlt（lint）与 sim_waivers.vlt（仿真），由 verilator_configs(design) 按根依次列出。
# 都是逐条（-file + -match）的；**不**用 -Wno-UNOPTFLAT / -Wno-fatal 之类的全局开关，
# 新告警照样让构建失败（flow-parameterization「流程列出的每个仿真器都必须对全部参数组合可用」）。
VERILATOR_CONFIGS = (
    REPO_ROOT / "flow" / "lint" / "waivers.vlt",
    REPO_ROOT / "flow" / "sim" / "verilator.vlt",
)
ROOT_WAIVER_NAMES = ("waivers.vlt", "sim_waivers.vlt")


def verilator_configs(design):
    """该顶层的 verilator 仿真构建要读的豁免文件：flow/ 下两份，再按 [设计根] + 依赖根读各根存在的
    waivers.vlt 与 sim_waivers.vlt（内部#312）。没有的跳过。"""
    roots = [resolve_design_root(design)] + [root for _, root in dependency_roots(design)]
    out = list(VERILATOR_CONFIGS)
    for root in dict.fromkeys(roots):
        out += [root / n for n in ROOT_WAIVER_NAMES if (root / n).is_file()]
    return out


def run_sim(design, params, sim="icarus", out_dir=None):
    """跑一次仿真：建 RTL、挂 cocotb TB、产出 VCD。

    ⚠️ `design` 这个形参装的是**被测顶层模块名**，不是设计根的目录名。
    两者在「设计根名 MUST 等于顶层名」成立的全部历史里逐字相同，收根之后
    （本仓 内部#45）分开：一个根可以挂两个顶层（例如一个地址流水与它的组合子块）。形参名没改是因为它就是记录里 `design`
    字段的值、也是全部 CLI 的 `--design`，而那个字段一直指顶层。
    根目录由 `resolve_design_root(design)` 查 `params.yaml` 的 `tops:` 声明得到。
    TB 按 `test_<顶层>.py` 找，所以同一个根下两个顶层各有一份，同目录不冲突。
    """
    from cocotb_tools.runner import get_runner

    params = validate_params(design, params)
    design_dir = resolve_design_root(design)
    tb_dir = design_dir / "tb"

    # 与综合读同一组源文件（该顶层的依赖闭包），不是整个目录 —— 见
    # flow/synth/synth.py::source_files 的注释与本仓 内部#50。两边必须同口径：
    # 仿真验的是一个编译单元，综合测的是另一个，那测出来的 PPA 不属于被验过的电路。
    sources = source_files(design)

    build_dir = Path(out_dir) if out_dir else adhoc_run_dir(design, "sim")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    test_module = f"test_{design}"
    if not (tb_dir / f"{test_module}.py").is_file():
        raise FileNotFoundError(f"找不到 testbench {tb_dir / (test_module + '.py')}")

    # verilator 的波形文件名写死在 cocotb 的 main 里（`dump.vcd`，相对**测试的工作目录**
    # = 设计根的 `tb/`），不给路径就落进设计根（repo-layout）。它认 `--trace-file`。
    # 波形用它原生的 VCD：FST 要 lz4.h，本机没有（make-verilator-sim-usable 的 F4）。
    build_args, test_args = [], []
    if sim == "verilator":
        build_args = [str(p) for p in verilator_configs(design)]
        test_args = ["--trace-file", str(build_dir / "dump.vcd")]

    # 参数片段的 include 目录（内部#76）；没有片段时不传，与以前的调用逐字相同
    incs = include_dirs(design, design_dir.parent.parent)
    build_kw = {"includes": [str(d) for d in incs]} if incs else {}

    runner = get_runner(sim)
    runner.build(
        **build_kw,
        verilog_sources=sources,
        hdl_toplevel=design,
        # Verilog 字符串参数要带引号送进仿真器，数值参数原样传
        parameters={k: (f'"{v}"' if isinstance(v, str) else v) for k, v in params.items()},
        build_dir=build_dir,
        build_args=build_args,
        waves=True,
        timescale=("1ns", "1ps"),
    )

    results_xml = runner.test(
        test_module=test_module,
        hdl_toplevel=design,
        build_dir=build_dir,
        test_dir=tb_dir,
        waves=True,
        # tb 通过环境变量拿到本次的参数取值（ADDER32 的 tb 读 PIPE_STAGES）
        extra_env={k: str(v) for k, v in params.items()},
        # 绝对路径：cocotb 的解析顺序里它优先级最高且原样使用，相对路径会落在
        # test_dir（= 设计根的 tb/），违反 repo-layout「单次原始产物 MUST NOT
        # 写入设计根目录内部」；而且在 pytest 进程里给相对路径会直接抛
        # NotImplementedError。
        results_xml=str(build_dir / "results.xml"),
        test_args=test_args,
    )

    passed = _results_xml_passed(results_xml)
    vcd_path = _fst_to_vcd(build_dir) or _native_vcd(build_dir)

    return {
        "passed": passed,
        "build_dir": str(build_dir),
        "vcd_path": str(vcd_path) if vcd_path else None,
        "results_xml": str(results_xml),
    }


def _results_xml_passed(results_xml):
    import xml.etree.ElementTree as ET

    tree = ET.parse(results_xml)
    for testcase in tree.iter("testcase"):
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            return False
    return True


def _fst_to_vcd(build_dir):
    """Icarus (via cocotb's runner) dumps FST; STA power/VCD tooling wants VCD.
    oss-cad-suite ships fst2vcd (from gtkwave), so just convert.

    fst2vcd 的 usage 是 `[OPTION]... [FSTFILE]`：**选项必须在文件名之前**。
    把 FST 写在 `-o` 前面时，BSD / macOS 的 getopt 在第一个非选项参数处停止解析，
    `-o` 不再被当成选项，VCD 按默认行为打到 stdout —— 工具仍以 0 退出。
    所以这里用全选项形式 `-f <fst> -o <vcd>`，并且**不把退出码当作产出的证据**。
    """
    import subprocess

    fst_candidates = list(Path(build_dir).rglob("*.fst"))
    if not fst_candidates:
        return None
    fst_path = fst_candidates[0]
    vcd_path = fst_path.with_suffix(".vcd")
    fst2vcd = shutil.which("fst2vcd")
    if fst2vcd is None:
        raise RuntimeError("fst2vcd not found in PATH (need oss-cad-suite env sourced)")

    proc = subprocess.run(
        [fst2vcd, "-f", str(fst_path), "-o", str(vcd_path)],
        capture_output=True, text=True, errors="replace",
    )
    produced = vcd_path.is_file() and vcd_path.stat().st_size > 0
    if proc.returncode != 0 or not produced:
        raise RuntimeError(
            f"fst2vcd 这一段没有产出它本该产出的 {vcd_path}"
            f"（{'不存在' if not vcd_path.is_file() else '为空'}）。\n"
            f"输入 {fst_path}，fst2vcd 退出码 {proc.returncode}。\n"
            "退出码为 0 不等于产物存在：fst2vcd 的 usage 是 `[OPTION]... [FSTFILE]`，"
            "选项写在文件名之后时不被识别，VCD 会按默认行为打到 stdout。\n"
            f"fst2vcd stdout: {_head(proc.stdout)}\n"
            f"fst2vcd stderr: {_head(proc.stderr)}"
        )
    return vcd_path


def _native_vcd(build_dir):
    """仿真器直接写了 VCD（verilator）：原样用，不转换。没有就返回 None，
    由 run_experiment 的守卫报「仿真通过但未产出 VCD」。"""
    vcds = [p for p in Path(build_dir).rglob("*.vcd") if p.stat().st_size > 0]
    return vcds[0] if vcds else None


def _head(text, limit=400):
    """把外部工具的输出原样带进错误信息。参数被误解这个原因只存在于那里 ——
    少了它，读者会被引向「仿真没产出波形」这个错误方向。"""
    if not text:
        return "(空)"
    return repr(text[:limit] + ("…" if len(text) > limit else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="RTL 参数取值，可重复；名字必须在设计的 params.yaml 里声明过")
    ap.add_argument("--sim", default="icarus", choices=["icarus", "verilator"])
    args = ap.parse_args()

    result = run_sim(args.design, cli_params(args.param), sim=args.sim)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
