"""门级仿真：综合产出的网表 + ASAP7 单元的 Verilog 模型，跑该顶层现有的 cocotb TB（本仓 内部#22）。

为什么在网表等价（`flow/equiv/netlist_equiv.py`）之外还值得有这一层：等价证明里单元的
功能来自 **liberty 的 `function` 描述**（yosys `read_liberty`），门级仿真里来自 PDK 附带的
**Verilog 单元模型** —— 两份独立的描述。liberty 与 Verilog 模型对同一个单元说的不是
同一个函数、触发器的复位/初态在 Verilog 模型里行为不同（X 传播）、TB 依赖了网表里不存在
的东西 —— 这几类问题等价证明看不见，门级仿真看得见。反过来，门级仿真只覆盖 TB 给的
激励，不是证明；两层互补，不互相替代。

两个用处，都是零延时（单元模型的 specify 不启用，不带 SDF）：

1. **功耗的活动率来源**（gate-level-activity，内部#65）：`run_experiment` 对胜出网表调
   `gate_activity()`，开波形，落在 `runs/<id>/sim_gate/`，TT 与两角的功耗都用这份 VCD 反标，
   活动率标到网表内部引脚（`sta.activity_annotation.scope == internal`）。RTL 仿真的 VCD
   只对得上端口（`docs/data-credibility.md` 的 D-27、D-30）。所以本文件在 `METRIC_MODULES`
   里，改它换代；读的单元模型按内容进指纹（`flow.cell_models_sha256`）。看得到相关性，
   看不到毛刺（要 SDF 时序仿真，没做）。
2. **事后功能检查**（下面的 CLI，本仓 内部#22）：本代每份网表跑一遍 TB，不开波形，构建目录
   `runs/<id>/gls/`，与 `sim_gate/` 分开 —— 每次开跑先清空自己的目录，共用会删掉记录依据的 VCD。
   网表来自 `runs/<id>/synth/`（search 胜出、记录里测的那一份）。`runs/` 清过就没有网表
   可仿 —— 那一条报 MISSING，不算通过。

单元模型：`~/pdk/asap7/asap7sc7p5t_28/Verilog/`（稀疏检出，`git sparse-checkout add Verilog`，
见 `docs/toolchain.md`）。Vt 与综合用的 liberty 一致（RVT）；模型文件名里的 corner 只是
出处，零延时下各 corner 的功能相同。
"""
import argparse
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# 字节码缓存重定向与 run_sim 同一处（导入它就生效，内部#53）；必须在 import cocotb 之前
import flow.sim.run_sim  # noqa: E402,F401
from flow.equiv.netlist_equiv import netlist_path, select_records  # noqa: E402
from flow.paths import resolve_design_root, run_dir  # noqa: E402

CELL_MODEL_DIR = Path.home() / "pdk" / "asap7" / "asap7sc7p5t_28" / "Verilog"
CELL_MODEL_GLOB = "asap7sc7p5t_*_RVT_TT_*.v"


def cell_models(model_dir=CELL_MODEL_DIR):
    """五类单元（AO/INVBUF/OA/SEQ/SIMPLE）的模型文件。缺一类就报错，不猜。"""
    files = sorted(Path(model_dir).glob(CELL_MODEL_GLOB))
    kinds = {f.name.split("_")[1] for f in files}
    missing = {"AO", "INVBUF", "OA", "SEQ", "SIMPLE"} - kinds
    if missing:
        raise FileNotFoundError(
            f"{model_dir} 下缺 ASAP7 单元模型 {sorted(missing)}（匹配 {CELL_MODEL_GLOB}）。"
            "PDK 是稀疏检出的：cd ~/pdk/asap7/asap7sc7p5t_28 && git sparse-checkout add Verilog")
    return files


def gate_sim(design, params, netlist, out_dir, model_dir=CELL_MODEL_DIR, waves=False):
    """用网表替换 RTL 跑一次该顶层的 TB。返回 (PASSED|FAILED, 日志尾)。

    `waves=True` 时转储波形（icarus 写 FST），供 `gate_activity` 转成 VCD 做功耗反标。
    """
    from cocotb_tools.runner import get_runner

    from flow.sim.run_sim import _results_xml_passed

    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tb_dir = resolve_design_root(design) / "tb"
    runner = get_runner("icarus")
    try:
        # 不传 parameters：网表已经是这组参数下的电路。TB 仍经环境变量拿到参数取值
        # （它按 PIPE_STAGES 等决定等几拍），与 RTL 仿真同一个口径。
        runner.build(sources=[str(netlist)] + [str(f) for f in cell_models(model_dir)],
                     hdl_toplevel=design, build_dir=out_dir, waves=waves,
                     timescale=("1ns", "1ps"))
    except (RuntimeError, SystemExit) as e:
        return "FAILED", f"构建没起来（不是 TB 的结论）：{e}"
    xml = out_dir / "results.xml"
    try:
        runner.test(test_module=f"test_{design}", hdl_toplevel=design,
                    build_dir=out_dir, test_dir=tb_dir, waves=waves,
                    extra_env={k: str(v) for k, v in params.items()},
                    results_xml=str(xml))
    except (RuntimeError, SystemExit) as e:
        # cocotb 的 runner 在 TB 断言失败时也以 SystemExit 退出 —— 这时 results.xml 在，
        # 结论照它读；不在才是仿真本身没跑起来
        if not xml.is_file():
            return "FAILED", f"仿真没跑起来（不是 TB 的结论）：{e}"
    if not xml.is_file():
        return "FAILED", f"仿真没有产出 {xml}"
    return ("PASSED" if _results_xml_passed(xml) else "FAILED"), f"TB 结论见 {xml}"


def gate_activity(design, params, netlist, out_dir, model_dir=CELL_MODEL_DIR):
    """功耗反标用的门级 VCD：零延时门级仿真，开波形。返回 {passed, vcd_path, note}。

    `run_experiment` 对胜出网表调它（gate-level-activity，内部#65）。没通过时 VCD 即使在也
    不交给 STA —— 它描述的是一次错误的行为。
    """
    from flow.sim.run_sim import _fst_to_vcd

    status, note = gate_sim(design, params, netlist, out_dir, model_dir, waves=True)
    vcd = _fst_to_vcd(out_dir) if status == "PASSED" else None
    return {"passed": status == "PASSED", "vcd_path": str(vcd) if vcd else None, "note": note}


def gate_sim_record(rec, model_dir=CELL_MODEL_DIR):
    """一条记录的网表跑门级仿真。返回 (PASSED|FAILED|MISSING, 耗时秒, 说明)。"""
    nl = netlist_path(rec)
    if not nl.is_file():
        return "MISSING", 0.0, f"网表不在：{nl}（runs/ 被清过？）"
    t0 = time.monotonic()
    status, note = gate_sim(rec["design"], rec["params"], nl,
                            run_dir(rec["experiment_id"], "gls"), model_dir)
    return status, time.monotonic() - t0, note


def _run_isolated(rec, model_dir):
    """一条记录一个子进程：cocotb 的 runner 在同一进程里并行跑不安全。"""
    import json
    import subprocess

    code = ("import sys, json; sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from flow.sim.gate_sim import gate_sim_record\n"
            "s, dt, note = gate_sim_record(json.loads(sys.argv[1]), Path(sys.argv[2]))\n"
            "print('GATE-SIM-RESULT', json.dumps([s, dt, note]))\n") % str(REPO_ROOT)
    r = subprocess.run([sys.executable, "-c", code, json.dumps(rec), str(model_dir)],
                       capture_output=True, text=True, cwd=REPO_ROOT)
    for line in (r.stdout or "").splitlines():
        if line.startswith("GATE-SIM-RESULT "):
            return tuple(json.loads(line[len("GATE-SIM-RESULT "):]))
    return "FAILED", 0.0, (r.stdout + r.stderr)[-2000:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", help="只跑这个被测顶层")
    ap.add_argument("--generation", default="latest", help="latest 或指纹前缀")
    ap.add_argument("--id", action="append", dest="ids", help="只跑这条记录，可重复")
    ap.add_argument("--models", default=str(CELL_MODEL_DIR), help="ASAP7 单元 Verilog 模型目录")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="同时跑几条（默认 1）。与 sweep / netlist_equiv 同一条理由：不按 CPU 数推")
    a = ap.parse_args(argv)

    cell_models(a.models)          # 模型不齐就当场报，别等 120 条各失败一次
    recs, scope = select_records(a.design, a.generation, a.ids)
    n = len(recs)
    print(f"# gate-sim: {scope}，{n} 条记录" + (f"，只看 {a.design}" if a.design else "")
          + f"，并行度 {a.jobs}", flush=True)
    if n == 0:
        print("# 一条都没选中 —— 不能当作通过", flush=True)
        return 1
    counts = {"PASSED": 0, "FAILED": 0, "MISSING": 0}
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futs = {pool.submit(_run_isolated, r, a.models): (i, r) for i, r in enumerate(recs, 1)}
        for fut in as_completed(futs):
            i, r = futs[fut]
            status, dt, note = fut.result()
            counts[status] += 1
            print(f"[{i}/{n}] {status:8s} {r['experiment_id']}  ({dt:.1f} s)", flush=True)
            if status != "PASSED":
                print("    " + "\n    ".join(str(note).strip().splitlines()[-6:]), flush=True)
    print(f"# gate-sim 结束: 通过 {counts['PASSED']}/{n}，失败 {counts['FAILED']}，"
          f"缺网表 {counts['MISSING']}，用时 {time.monotonic() - t0:.1f} s", flush=True)
    return 0 if counts["PASSED"] == n else 1


if __name__ == "__main__":
    sys.exit(main())
