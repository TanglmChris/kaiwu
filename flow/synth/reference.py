"""参考口径综合（reference-ppa，内部#202；用户 2026-10-05 定「两种口径都报」）。

正式口径（`synth.py`）：配置输入是输入，`synth` 不打平、不跨模块边界传常数，两种排布的逻辑都在。
参考口径：同一份 RTL、同一组参数，把本组合**唯一**适用的验收场景的 `case`（目标配置的定值）在顶层接成常数，
`synth -hieropt` 跨层次传常数、删掉用不到的逻辑；声明了 `keep_hierarchy` 的照保；之后的映射与正式口径共用
`MAP_TEMPLATE`，ABC 延时目标由调用方给（取正式口径胜出的那一档），两种口径只差「接常数 + 跨层次优化」。

`opt_hier`（`-hieropt` 里的那一步）碰上例化里的空输出连接 `.y( )` 会报错退出（内部#205，pitfalls P-20）：
在它之前从 RTLIL 删掉 cell 块里的 `connect \\<端口> { }`。删的是「什么都没接」的连接，语义不变。

在 METRIC_MODULES 里：它决定记录 `reference` 的值，改它换代。
"""
import fnmatch
import json
import re
import shutil
import subprocess
from pathlib import Path

from flow.paths import (ParamError, adhoc_run_dir, include_dirs, keep_hierarchy_modules, reference_ports,
                        resolve_design_root, scenarios, validate_params)
from flow.synth.synth import (ABC_CONSTR, MAP_TEMPLATE, _chparam_sets, _inc_flags, _keep_hierarchy_cmds,
                              source_files)

STAGE1 = """\
{read_verilog_cmds}
chparam {chparam_sets} {top}
{keep_hierarchy_cmds}proc
rename -top {top}
write_rtlil {pre}
"""

STAGE2 = """\
read_rtlil {post}
hierarchy -top {top}
cd {top}
{tie_cmds}cd ..
synth -top {top} -hieropt
""" + MAP_TEMPLATE

_EMPTY_CONN = re.compile(r"connect \S+ \{ \}")


def tie(design, params, inputs=None):
    """(场景名, case)：本组合唯一适用的场景与它的定值。`inputs`（顶层输入端口名集合）给了就按它展开
    `reference_ports` 的模式；没给时只核不带通配的模式。"""
    scen = scenarios(design, params)
    if len(scen) != 1:
        raise ParamError(f"{design} 的参考口径要求本组合恰好一个适用的验收场景（sta.scenarios 的 when），"
                         f"实得 {[s['name'] for s in scen]}")
    sc = scen[0]
    case = sc["case"]
    for pat in reference_ports(design):
        wanted = ([p for p in inputs if fnmatch.fnmatchcase(p, pat)] if inputs is not None
                  else ([] if any(c in pat for c in "*?[") else [pat]))
        missing = sorted(p for p in wanted if p not in case)
        if missing:
            raise ParamError(f"{design} 的参考口径：synth.reference_ports 的 {pat} 匹配到的 {missing} "
                             f"在场景 {sc['name']} 的 case 里没有定值（会留成输入，参考值偏大）")
    return sc["name"], dict(case)


def drop_empty_connections(rtlil):
    """删掉 cell 块里的空连接（内部#205 / P-20）。返回 (新文本, 删了几条)。"""
    out, in_cell, n = [], False, 0
    for line in rtlil.splitlines():
        s = line.strip()
        if s.startswith("cell "):
            in_cell = True
        elif s == "end" and in_cell:
            in_cell = False
        if in_cell and _EMPTY_CONN.fullmatch(s):
            n += 1
            continue
        out.append(line)
    return "\n".join(out) + "\n", n


def top_inputs(rtlil, top):
    """{输入端口: 位宽}，取自 RTLIL 里顶层模块的 wire 声明。"""
    m = re.search(r"^module \\" + re.escape(top) + r"\n(.*?)^end\n", rtlil, re.M | re.S)
    out = {}
    for w, name in re.findall(r"^\s*wire (?:width (\d+) )?(?:upto )?(?:offset -?\d+ )?input \d+ \\(\S+)$",
                              m.group(1) if m else "", re.M):
        out[name] = int(w) if w else 1
    return out


def synthesize(design, params, liberty, case=None, out_dir=None, delay_target_ps=None):
    """参考口径综合。`case` 不给就按 `tie(design, params)` 取。返回与 `run_synth` 同形的结果，另带
    `scenario`、`case`、`empty_connections_dropped`。"""
    yosys = shutil.which("yosys")
    if yosys is None:
        raise RuntimeError("yosys not found in PATH (need oss-cad-suite env sourced)")
    params = validate_params(design, params)
    sources = source_files(design, yosys=yosys)
    run_dir = Path(out_dir) if out_dir else adhoc_run_dir(design, "synth_reference")
    run_dir.mkdir(parents=True, exist_ok=True)
    pre, post = run_dir / "pre.il", run_dir / "post.il"
    stats_json, netlist = run_dir / "stats.json", run_dir / f"{design}_netlist.v"
    incs = include_dirs(design, resolve_design_root(design).parent.parent)

    s1 = STAGE1.format(read_verilog_cmds="\n".join(f"read_verilog {_inc_flags(incs)}{src}" for src in sources),
                       chparam_sets=_chparam_sets(params), top=design,
                       keep_hierarchy_cmds=_keep_hierarchy_cmds(keep_hierarchy_modules(design), design), pre=pre)
    _run(yosys, run_dir, "stage1", s1)
    rtlil, dropped = drop_empty_connections(pre.read_text())
    inputs = top_inputs(rtlil, design)
    if case is None:
        name, tie_case = tie(design, params, set(inputs))
    else:
        name, tie_case = None, dict(case)
    for port, val in tie_case.items():
        if port not in inputs:
            raise ParamError(f"{design} 的参考口径要接常数的 {port} 不是顶层输入")
        if not isinstance(val, int) or val < 0 or val >= (1 << inputs[port]):
            raise ParamError(f"{design} 的参考口径给 {port}（{inputs[port]} 位）的值 {val!r} 超出位宽")
    post.write_text(rtlil)
    tie_cmds = "".join(f"delete -input w:{p}\nconnect -set {p} {inputs[p]}'d{v}\n" for p, v in tie_case.items())
    s2 = STAGE2.format(post=post, top=design, tie_cmds=tie_cmds, liberty=liberty, abc_constr=ABC_CONSTR,
                       delay_opt="" if delay_target_ps is None else f" -D {delay_target_ps}",
                       stats_json=stats_json, netlist=netlist)
    _run(yosys, run_dir, "stage2", s2)
    d = json.loads(stats_json.read_text())["design"]
    return {"cell_count": d.get("num_cells", 0), "area_um2": d.get("area"), "delay_target_ps": delay_target_ps,
            "netlist_path": str(netlist), "stats_path": str(stats_json), "scenario": name, "case": tie_case,
            "empty_connections_dropped": dropped}


def _run(yosys, run_dir, tag, script):
    (run_dir / f"{tag}.ys").write_text(script)
    p = subprocess.run([yosys, "-s", f"{tag}.ys"], cwd=run_dir, capture_output=True, text=True)
    (run_dir / f"{tag}.log").write_text(p.stdout + p.stderr)
    if p.returncode != 0:
        tail = (p.stdout + p.stderr).strip().splitlines()[-12:]
        raise RuntimeError(f"参考口径综合 {tag} 失败（见 {run_dir / (tag + '.log')}）\n  " + "\n  ".join(tail))
