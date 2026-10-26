"""不写记录地量一个模块（被测顶层或它的任一子模块）的逻辑级数与关键路径（内部#111）。

写 RTL 时决定切不切流水要先量级数，而 `make exp` 写记录、只量被测顶层，没声明「已验证」的设计还
出不了记录。这里用与实验流程同一份 yosys 配方（`flow/synth/synth.py` 的 YOSYS_TEMPLATE、同一份
ABC 约束与合并 liberty）综合指定模块，再用 OpenSTA 报最坏路径，按 `run_sta` 同一套规则数级数。

与实验流程的差别（所以它**不是记录口径**，数字只用来指导设计）：
- 不施加 `keep_hierarchy` 声明（只量这一块，层级保不保都不影响路径上穿过几个 cell）；
- 不跑仿真、不反标活动率、不出功耗；
- STA 约束是最简的，周期 10（单位 ns，只为让路径有确定的分组）：量被测顶层时按它的 `sta.clocks` /
  `clock_groups` 建时钟，与正式 STA 同一份声明、同一个函数（内部#167）；量子模块时，只有它**自己**有
  `clk` 端口才在上面建时钟，否则建虚拟时钟。全部输入、输出的外部延时为 0。
  于是报出的是「寄存器 / 输入 → 寄存器 / 输出」里最长的一段组合逻辑。
- 不计时序的起点（内部#154）：量的就是被测顶层时用它的 `sta.static_ports`（与正式 STA 同一份声明）；
  另有 `--false-from <模式>`（可重复，默认 `*rst_n*`，`--false-from none` 关掉），量子模块时
  端口名与顶层不同，靠它把复位与静态配置排除掉。
- `--paths N`：按级数降序列出最深的 N 个终点（起点、终点、级数），做整体级数核算用。
- `--budget N`（内部#184）：列出**全部**组合单元数超过 N 的终点（内部#207：按组合单元数比，不按报告行数；两种数都列），按「起点模块 → 终点模块」分组，不受 `--paths` 截断；
  有超标时 `main` 返回 1。时序验收用它（顶层一次综合、超过预算的终点数 = 0）。

    .venv/bin/python3 flow/synth/depth.py --design <顶层> --module <子模块> \\
        --param WIDTH=256 --param DAT_W=256
    make -f flow/Makefile depth DESIGN=<顶层> MODULE=<子模块> PARAMS="…"

`--param` 原样交给 `chparam`，名字是 `--module` 那个模块的参数（子模块的参数不在 params.yaml 里，
不做声明检查）；不给的取 RTL 默认值。
"""
import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.machine_lock import machine_lock  # noqa: E402
from flow.paths import (REPO_ROOT as _PATHS_ROOT, clock_groups,  # noqa: E402
                        include_dirs, resolve_design_root, scenarios, static_ports)
from flow.sta.run_sta import (_CELL_ROW, _clock_command, _io_delay_command,  # noqa: E402
                              _case_command, _drop_tied, _module_input_widths, _resolve_clocks,
                              _static_port_command, _worst_block)
from flow.synth.synth import (ABC_CONSTR, YOSYS_TEMPLATE, _chparam_sets,  # noqa: E402
                              _inc_flags, source_files)

DEFAULT_LIBERTY = Path.home() / "pdk" / "asap7_merged" / "asap7sc7p5t_RVT_TT.lib"

STA_TCL = """\
read_liberty {liberty}
read_verilog {netlist}
link_design {module}
{clock_cmd}
{io_cmd}{false_cmd}report_checks -path_delay max -group_path_count {paths} -endpoint_path_count 1 -digits 4 > {checks}
{budget_cmd}"""

# 级数预算（内部#184）：逐个终点取最坏的 PER_ENDPOINT 条路径，按与 run_sta 报告同一套规则数级数
# （报告里带单元或端口名的每一行：起点寄存器的 CLK 与 Q、每个组合单元的输出、终点的 D 或输出端口），
# 预算比的是组合单元数（内部#207，用户定「30 级」= 30 个组合单元）：路径上非端口的输出引脚数，减去起点寄存器的 Q；
# ABC 插的缓冲与反相器照算。寄存器起点时行数 = 组合单元数 + 3，输入端口起点时 + 2。两种数都写进 tsv。
# 只把超过预算的写出来。不经 report_checks 打全量报告：几万个终点的完整路径文本会上 GB。
# OpenSTA 按延时（slack）挑每个终点的路径，级数最深的那条未必是延时最长的那条，所以每个终点看前
# PER_ENDPOINT 条、取级数最大的；这是近似，不是穷举（见 docs/toolchain.md「不写记录地量逻辑级数」）。
BUDGET_TCL = """\
proc _depth_rows {{pe}} {{
  set pts [get_property $pe points]
  set n 0
  set last [expr {{[llength $pts] - 1}}]
  for {{set i 0}} {{$i <= $last}} {{incr i}} {{
    set pin [get_property [lindex $pts $i] pin]
    if {{[get_property $pin is_port] || [get_property $pin direction] == "output" || $i == $last}} {{ incr n }}
  }}
  if {{![get_property [get_property [lindex $pts 0] pin] is_port]}} {{ incr n }}
  return $n
}}
proc _comb_cells {{pe}} {{
  set pts [get_property $pe points]
  set n 0
  foreach _pt $pts {{
    set pin [get_property $_pt pin]
    if {{![get_property $pin is_port] && [get_property $pin direction] == "output"}} {{ incr n }}
  }}
  if {{![get_property [get_property [lindex $pts 0] pin] is_port]}} {{ incr n -1 }}
  return $n
}}
set _fh [open {over} w]
foreach _pe [find_timing_paths -path_delay max -group_path_count 100000000 -endpoint_path_count {per_endpoint} -unique_paths_to_endpoint] {{
  set _n [_depth_rows $_pe]
  set _c [_comb_cells $_pe]
  if {{$_c > {budget}}} {{
    set _pins {{}}
    foreach _p [get_property $_pe points] {{ lappend _pins [get_full_name [get_property $_p pin]] }}
    puts $_fh "$_c\t$_n\t[get_full_name [get_property $_pe startpoint]]\t[get_full_name [get_property $_pe endpoint]]\t[join $_pins {{ }}]"
  }}
}}
close $_fh
"""
PER_ENDPOINT = 3
GROUP_PATHS = 3

_ARRIVAL = re.compile(r"^\s*(-?[\d.]+)\s+data arrival time", re.M)
_POINT = re.compile(r"^(Startpoint|Endpoint):\s+(\S+)", re.M)


def _parse_params(items):
    out = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--param 要写成 NAME=VALUE：{item}")
        k, v = item.split("=", 1)
        out[k] = int(v) if re.fullmatch(r"-?\d+", v) else v
    return out


DEFAULT_FALSE_FROM = ("*rst_n*",)
DEPTH_PERIOD_NS = 10


def _module_inputs(netlist_text, module):
    """网表里 `module` 这一个模块自己的输入端口名（yosys write_verilog 的形状）。"""
    m = re.search(r"^module\s+" + re.escape(module) + r"\b.*?^endmodule", netlist_text, re.M | re.S)
    if not m:
        return set()
    return set(re.findall(r"^\s*input\s+(?:\[[^\]]*\]\s*)?(\w+)\s*;", m.group(0), re.M))


def _false_from_command(patterns):
    """不计时序的起点：匹配不到就跳过（子模块未必有复位），不报错。"""
    return "".join(f"set _ff [get_ports -quiet {{{p}}}]\nif {{[llength $_ff]}} {{ set_false_path -from $_ff }}\n"
                   for p in patterns)


def _paths(checks):
    """[(级数, 起点, 终点)]，每个路径块一条，按级数降序。"""
    out = []
    for blk in ("Startpoint:" + b for b in checks.read_text().split("Startpoint:")[1:]):
        points = dict(_POINT.findall(blk))
        cells = sum(1 for ln in blk.splitlines() if _CELL_ROW.match(ln))
        out.append({"stages": cells, "startpoint": points.get("Startpoint"),
                    "endpoint": points.get("Endpoint")})
    return sorted(out, key=lambda p: -p["stages"])


def _hier_module(pin, levels=2):
    """引脚 / 端口名 → 它所在的实例层次（前 levels 级）。顶层的端口与顶层自己的单元归「（顶层）」。"""
    parts = pin.split("/")[:-2]      # 去掉单元名与引脚名
    return "/".join(parts[:levels]) or "（顶层）"


def _over_budget(path, budget):
    """读预算模式写出的 over_budget.tsv（组合单元数、报告行数、起点、终点、引脚），按终点去重（取组合单元数最大的那条），按「起点模块 → 终点模块」分组。"""
    best = {}
    for ln in Path(path).read_text().splitlines():
        c, n, start, end, pins = ln.split("\t")
        c, n = int(c), int(n)
        if end not in best or (c, n) > (best[end]["comb_cells"], best[end]["stages"]):
            best[end] = {"comb_cells": c, "stages": n, "startpoint": start, "endpoint": end,
                         "pins": pins.split(" ")}
    groups = {}
    for p in best.values():
        groups.setdefault((_hier_module(p["pins"][0]), _hier_module(p["pins"][-1])), []).append(p)
    out = []
    for (frm, to), ps in groups.items():
        ps.sort(key=lambda p: (-p["comb_cells"], -p["stages"]))
        out.append({"from": frm, "to": to, "count": len(ps), "max_comb_cells": ps[0]["comb_cells"],
                    "max_stages": ps[0]["stages"],
                    "paths": ps[:GROUP_PATHS]})
    out.sort(key=lambda g: (-g["max_comb_cells"], -g["count"]))
    return {"budget": budget, "count": len(best), "groups": out}


def shrink_over_budget(path):
    """over_budget.tsv 每个终点只留组合单元数最大的一条，写成同名 .gz、删掉原文件（内部#225：大设计一份约 50 MB）。返回 .gz 路径。"""
    path = Path(path)
    best = {}
    for ln in path.read_text().splitlines():
        cols = ln.split("\t")
        key = (int(cols[0]), int(cols[1]))
        if cols[3] not in best or key > best[cols[3]][0]:
            best[cols[3]] = (key, ln)
    gz = path.with_name(path.name + ".gz")
    with gzip.open(gz, "wt") as f:
        f.writelines(ln + "\n" for _, ln in best.values())
    path.unlink()
    return gz


def measure(design, module=None, params=None, liberty=DEFAULT_LIBERTY, out_dir=None,
            false_from=DEFAULT_FALSE_FROM, paths=1, budget=None, netlist=None, tied=None):
    """返回 {module, params, stages, delay, startpoint, endpoint, cell_count, netlist, checks, paths}；
    给了 budget（级数预算，内部#184）时另有 over_budget：全部超过预算的终点，不受 paths 截断。"""
    module = module or design
    params = params or {}
    yosys, sta = shutil.which("yosys"), shutil.which("sta")
    if yosys is None or sta is None:
        raise RuntimeError("yosys / sta 不在 PATH（source ~/tools/env.sh）")
    # 全机互斥（内部#223）：读入集合探测（yosys 枚举全部声明组合）缓存未命中时负载高要几分钟，两个 depth 同时开会各算一遍；
    # 排队后第二个多半直接命中第一个写下的缓存（缓存键含内容哈希，同一 worktree 内共享）
    with machine_lock("source_set", f"depth {design} {module}"):
        sources = source_files(design, yosys=yosys)
    texts = "".join(Path(s).read_text(errors="replace") for s in sources)
    if not re.search(r"\bmodule\s+" + re.escape(module) + r"\b", texts):
        raise RuntimeError(f"{design} 的源文件集合里没有模块 {module}")

    tag = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:8]
    run_dir = Path(out_dir) if out_dir else REPO_ROOT / "runs" / "depth" / f"{module}-{tag}"
    run_dir.mkdir(parents=True, exist_ok=True)
    given = netlist is not None
    netlist = Path(netlist) if given else run_dir / f"{module}_netlist.v"
    stats_json = run_dir / "stats.json"

    if not given:
        _synthesize(design, module, params, liberty, sources, run_dir, netlist, stats_json, yosys)
    return _measure_netlist(design, module, params, liberty, run_dir, netlist, stats_json if not given else None,
                            false_from, paths, budget, tied, sta)


def _synthesize(design, module, params, liberty, sources, run_dir, netlist, stats_json, yosys):
    incs = include_dirs(design, resolve_design_root(design).parent.parent)
    script = YOSYS_TEMPLATE.format(
        read_verilog_cmds="\n".join(f"read_verilog {_inc_flags(incs)}{s}" for s in sources),
        chparam_sets=_chparam_sets(params),
        top=module,
        keep_hierarchy_cmds=f"hierarchy -top {module}\n",
        liberty=liberty, abc_constr=ABC_CONSTR, delay_opt="",
        stats_json=stats_json, netlist=netlist)
    (run_dir / "synth.ys").write_text(script)
    p = subprocess.run([yosys, "-s", "synth.ys"], cwd=run_dir, capture_output=True, text=True)
    (run_dir / "yosys.log").write_text(p.stdout + p.stderr)
    if p.returncode != 0:
        tail = (p.stdout + p.stderr).strip().splitlines()[-12:]
        raise RuntimeError(f"yosys failed (see {run_dir / 'yosys.log'})\n  " + "\n  ".join(tail))


def _measure_netlist(design, module, params, liberty, run_dir, netlist, stats_json, false_from, paths, budget,
                     tied, sta):
    """量一份网表。`stats_json` 为 None 表示网表是调用方给的（参考口径，reference-ppa）：不重新综合，单元数不报；
    `tied` 是已接成常数、不在网表里的输入，`static_ports` 里只匹配它们的模式跳过，验收场景也不再定值（常数已在网表里）。"""
    if module == design:
        # 被测顶层：用它声明的时钟与分组（内部#167）。端口不存在时 _clock_command 发的 FLOW-ERROR 让 STA 失败
        declared = _resolve_clocks(design, DEPTH_PERIOD_NS, _PATHS_ROOT)
        groups = clock_groups(design)
    else:
        # 子模块：只看它自己的端口。网表保留层级，别的子模块有 input clk 不算（内部#167 的根因）
        declared = ([{"name": "clk", "port": "clk", "period_ns": DEPTH_PERIOD_NS}]
                    if "clk" in _module_inputs(netlist.read_text(), module) else [])
        groups = [["clk"]] if declared else []
    false_cmd = ((_static_port_command(_drop_tied(static_ports(design), tied, netlist, design))
                  if module == design else "")
                 + _false_from_command(false_from))
    stats = json.loads(stats_json.read_text())["design"] if stats_json is not None else {}

    def sta_once(sfx, case_cmd):
        """跑一遍 STA；sfx 区分场景的产物文件名（不分场景时为空）。"""
        checks = run_dir / f"checks{sfx}.rpt"
        over = run_dir / f"over_budget{sfx}.tsv"
        tcl = STA_TCL.format(
            liberty=liberty, netlist=netlist, module=module, checks=checks,
            clock_cmd=_clock_command(declared, groups, DEPTH_PERIOD_NS),
            io_cmd=_io_delay_command(declared),
            false_cmd=false_cmd + case_cmd,
            paths=max(1, int(paths)),
            budget_cmd=("" if budget is None else
                        BUDGET_TCL.format(over=over, budget=int(budget), per_endpoint=PER_ENDPOINT)))
        (run_dir / f"depth{sfx}.tcl").write_text(tcl)
        p = subprocess.run([sta, "-no_init", "-exit", f"depth{sfx}.tcl"], cwd=run_dir,
                           capture_output=True, text=True)
        (run_dir / f"sta{sfx}.log").write_text(p.stdout + p.stderr)
        if p.returncode != 0 or not checks.exists():
            flagged = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.startswith("FLOW-ERROR:")]
            raise RuntimeError(f"OpenSTA failed (see {run_dir / f'sta{sfx}.log'})" + "".join("\n" + f for f in flagged))

        slack, stages = _worst_block(checks)      # 没有完整路径块时它会报错，不返回 0
        # 起止点与到达时间取同一块（slack 最小的那条路径；异步复位的 recovery 组另成一块，不混进来）
        worst = None
        for blk in ("Startpoint:" + b for b in checks.read_text().split("Startpoint:")[1:]):
            m = re.search(r"^\s*(-?[\d.]+)\s+slack\s+\(", blk, re.M)
            if m and abs(float(m.group(1)) - slack) < 1e-9 and worst is None:
                worst = blk
        arrival = _ARRIVAL.search(worst or "")
        points = dict(_POINT.findall(worst or ""))
        return {
            "module": module,
            "params": params,
            "stages": stages,
            "delay": float(arrival.group(1)) if arrival else None,   # liberty 的时间单位（ASAP7 是 ps）
            "startpoint": points.get("Startpoint"),
            "endpoint": points.get("Endpoint"),
            "cell_count": stats.get("num_cells"),
            "netlist": str(netlist),
            "checks": str(checks),
            "paths": _paths(checks)[:max(1, int(paths))],
            **({} if budget is None else {"over_budget": _over_budget(over, int(budget)),
                                          "over_budget_tsv": str(shrink_over_budget(over))}),
        }

    scen = scenarios(design, params) if module == design and not tied else []   # 只量本组合适用的场景（内部#198）
    if not scen:
        return sta_once("", "")
    # 验收场景（内部#189）：同一份网表，每个场景把静态输入定值（set_case_analysis）各跑一遍 STA。
    # 顶层字段取级数最深的那个场景，另附每个场景的结果。
    width = _module_input_widths(netlist.read_text(), module)
    runs = []
    for sc in scen:
        r = sta_once(f".{sc['name']}", _case_command(sc["case"], width))
        runs.append({"name": sc["name"], "case": sc["case"], "by": sc["by"], "when": sc["when"], **r})
    top = max(runs, key=lambda r: r["stages"])
    out = {k: v for k, v in top.items() if k not in ("name", "case", "by", "when")}
    out["scenario"] = top["name"]
    out["scenarios"] = runs
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--design", required=True, help="被测顶层（确定源文件集合）")
    ap.add_argument("--module", help="要量的模块，默认就是 --design")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="该模块的参数，可重复；不给取 RTL 默认值")
    ap.add_argument("--point", help="按被测顶层 params.yaml 的 sweep_points 点名取全部参数（#332），与 --param 二选一")
    ap.add_argument("--liberty", default=str(DEFAULT_LIBERTY))
    ap.add_argument("--false-from", action="append", metavar="模式",
                    help="不计时序的输入端口（通配，可重复）；默认 *rst_n*，写 none 关掉默认")
    ap.add_argument("--paths", type=int, default=1, help="按级数降序列出最深的 N 个终点")
    ap.add_argument("--budget", type=int, default=None,
                    help="级数预算（组合单元数，#207）：列出全部超过它的终点（按起止模块分组），有超标时退出码 1（#184）")
    args = ap.parse_args(argv)
    if args.point and args.param:
        ap.error("--point 与 --param 不能同时给：--point 已经给全了全部参数")
    if args.point and args.module and args.module != args.design:
        ap.error(f"--point 取的是被测顶层的参数，不能用于子模块 {args.module}；子模块的参数用 --param 给")
    if args.point:
        from flow.param_exclude import point_params
        params = dict(point_params(args.design, args.point))
    else:
        params = _parse_params(args.param)
    ff = DEFAULT_FALSE_FROM if args.false_from is None else [x for x in args.false_from if x != "none"]
    r = measure(args.design, args.module, params, args.liberty,
                false_from=ff, paths=args.paths, budget=args.budget)
    if r["module"] != args.design:
        # 子模块单独综合时它的上下文（常量输入、跨边界优化）不在，网表与顶层里的同一模块不同：
        # 2026-10-05 同一 RDAT 单独 72299 个单元、0 个超标，顶层里 71720 个、33 个超标（design_sub 实撞）
        print(f"# 注意：单独量 {r['module']}，网表与它在顶层 {args.design} 里的不同，级数与超标数可能不一样；"
              "时序验收以顶层为准（docs/toolchain.md「时序验收」）")
    if r["module"] == args.design and not r.get("scenarios") and scenarios(args.design):
        print(f"# 注意：{args.design} 声明了验收场景，但没有一个适用这组参数（when，#198），按不定值量了一遍")
    runs = r.get("scenarios") or [r]
    if r.get("scenarios"):
        print(f"# depth {r['module']}：按声明的验收场景各量一遍（#189），最深的是 {r['scenario']}")
    for x in runs:
        tag = f"[{x['name']} {x['case']} by {x['by']}] " if "name" in x else ""
        print(f"# depth {tag}{x['module']} {x['params'] or '(默认参数)'}：{x['stages']} 级，"
              f"{x['delay']}（liberty 时间单位，ASAP7 为 ps），{x['startpoint']} → {x['endpoint']}，{x['cell_count']} 个 cell")
        print(f"#   报告 {x['checks']}（不写记录；口径见本文件头）")
        if args.paths > 1:
            for i, p in enumerate(x["paths"], 1):
                print(f"#   {i:3d}. {p['stages']:3d} 级  {p['startpoint']} → {p['endpoint']}")
        ob = x.get("over_budget")
        if ob is not None:
            print(f"# {tag}超过预算 {ob['budget']} 个组合单元的终点：{ob['count']} 个，{len(ob['groups'])} 组"
                  "（起点模块 → 终点模块；「单元」是组合单元数，与预算比；「行」是报告行数，即旧口径的级数，#207）")
            for g in ob["groups"]:
                print(f"#   {g['count']:6d} 个  最深 {g['max_comb_cells']:3d} 单元 / {g['max_stages']:3d} 行  {g['from']} → {g['to']}")
                for p in g["paths"]:
                    print(f"#            {p['comb_cells']:3d} 单元 / {p['stages']:3d} 行  {p['startpoint']} → {p['endpoint']}")
            print(f"#   每个终点最深一条的引脚在 {x['over_budget_tsv']}（gzip；两次结果按终点比：flow/synth/depth_compare.py A B，#225）")
    print(json.dumps({k: v for k, v in r.items() if k not in ("over_budget", "scenarios")}
                     | ({"scenarios": [{k: v for k, v in x.items() if k != "over_budget"} for x in r["scenarios"]]}
                        if r.get("scenarios") else {}), ensure_ascii=False))
    return 1 if any((x.get("over_budget") or {}).get("count") for x in runs) else 0

if __name__ == "__main__":
    sys.exit(main())
