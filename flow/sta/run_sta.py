"""OpenSTA timing + power (VCD-backannotated) on a synthesized gate-level netlist.

Usable as a library (run_sta()) from scripts/run_experiment.py, or standalone:
    python flow/sta/run_sta.py --design CBB_LZD --netlist <v> --liberty <lib> --vcd <vcd>

NOTE on schema placement: critical_path_delay_ns and critical_path_stages live
under the "synth" section of an experiment record (see
openspec/specs/experiment-record/spec.md), but both
are actually computed here from OpenSTA's timing report -- yosys's own `ltp`
command turned out not to see through liberty-mapped cells (always reported
length 0), so OpenSTA's report_checks is the only place we have a real
liberty-timed path. run_experiment.py copies these values into the synth
sub-record.

NOTE on fmax: `run_sta()` 报的 `fmax_method` 是 "analytic"，也就是
1000 / critical_path_delay_ns。它的含义是「在**交给它的这一份网表**里关键路径恰好
有多长」——不是「这个实现能跑多快」。要后者得让综合被加压后再量，那是
`flow/synth/search.py` 的事：它在一组 `abc -D` 目标上各综合一次、各量一次，
取最好者，并把 `fmax_method` 换成 `"search:abc-D"`。
`scripts/run_experiment.py` 走的是搜索那条路；本文件单独调用时仍是 "analytic"，
而且那是准确的。

这里曾经有一条论据说「yosys+ABC 不是时序驱动的，所以网表与目标周期无关」，
依据是 2026-09-04 把周期扫过 5.0/2.0/1.2 ns 后关键路径与级数逐位相同。
**那个观察是真的，但它证明不了那个结论**：被扫的是本文件的 `--period-ns`，
而 `run_synth()` 的签名里没有周期参数 —— 综合从头到尾不知道目标周期。
改 STA 的周期当然不会改网表。

2026-09-13 实测：`abc -D <picoseconds>`（综合延时目标）存在，给了之后网表确实不同，
`BRENT_KUNG W=32` 在 `-D 100` 下延时 -7.40%、面积 -5.73%。所以 2026-09-13 之前的
全部记录里，fmax 都是**未加时序压力**下的值。

搜索用的是**固定阶梯**而不是二分：延时对 `-D` 非单调（`CLA W=32` 每一档都比不加压
更差），而且 ABC 有一个**设计相关**的静默死区（`BRENT_KUNG W=32` 在 `-D ≤ 70`、
`SKLANSKY W=64` 在 `-D ≤ 85` 时产出与不加压逐字节相同的网表，不报错不警告）——
二分要求单调且可达性连续，两条都不成立。见
内部#26 与
openspec/specs/experiment-record/spec.md 的「记录必须携带可比的性能标量」。

接 Design Compiler 时同样要重新验证归档 add-fmax-and-scoring/design.md 的 D1 ——
但那条**在开源流里就已经失效**，不必等 DC。

This fmax is setup-only, single-corner (TT), and carries no clock uncertainty,
no OCV derate, and no wire delay. It is valid for comparing architectures
against each other; it is not what the silicon would actually run at.

本函数一次只分析一个角（交给它的那份 liberty）。SS / FF 两角由
`scripts/run_experiment.py` 在同一份网表上各调一次，写进记录的 `sta.corners`；
上面说的 fmax 是 `sta.fmax_mhz`，它仍然是 TT 的数。

输入驱动与输出负载**不再**是理想的：它们与 `flow/synth/abc.constr` 取同一套值
（`BUFx2` 驱动、输出 0.5 fF），因为 ABC 就是照着那套边界做优化的。这让报出来的数
就是流程在优化的那个量，但它改的是**流程内部一致性**，不是"更接近硅"。
实测这项对齐把关键路径抬高 **0–15.40%**，且是**加性常数**（8–25 ps）而非比例项，
所以对路径短的实现在百分比上更不利（最大那个是 `ADDER32 W=8 CSEL PIPE_STAGES=2`，
路径只有 0.137 ns，同样的 21 ps 就是 15.4%）。

⚠️ 扇出到全部触发器的端口**不设**驱动单元，由设计在 `params.yaml` 的
`sta.ideal_drive_ports` 里声明。给它设一个 `BUFx2` 量出来的是"这个流程没有综合
复位树"，不是电路。见 `docs/data-credibility.md` 的 D-8。
"""
import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import (REPO_ROOT, adhoc_run_dir, clock_groups, clock_port,
                        clocks, ideal_drive_ports, static_ports)

STA_TCL_TEMPLATE = """\
read_liberty {liberty}
read_verilog {netlist}
link_design {top}

# read_liberty resets cmd units to the liberty's own (ASAP7 uses ps) --
# set ours *after* linking so period/slack/delay come out in ns as documented.
set_cmd_units -time ns -capacitance pf -resistance kohm -voltage V -current mA -power mW -distance um

{clock_cmd}
{io_delay_cmd}
# 边界条件必须与 flow/synth/abc.constr 相同：ABC 正是照着那套边界做单元选择与
# 驱动强度优化的，STA 换一套报数的话，报出来的就不是流程在优化的那个量。
# ⚠️ 单位：上面的 set_cmd_units 把电容设成了 pF，而 abc.constr 的 0.5 是 liberty
# 自己的单位（ASAP7 是 fF）。0.5 fF = 0.0005 pF。照搬 0.5 过去就是大 1000 倍，
# 而那不会报错 —— 关键路径涨十几倍，slack 仍然是 MET。tests/test_sta_boundary.py
# 两头都盯着：两处取值按 liberty 自报的单位换算后必须相等，且影响必须有上界。
# 时钟端口不给驱动单元 —— 时钟保持理想，与"无时钟不确定度"的定位一致。
# 逐端口设置，跳过被设计声明为理想驱动的那些（`params.yaml` 的
# `sta.ideal_drive_ports`）。必须是这个形式：OpenSTA 没有 `remove_from_collection`，
# 而 `set_input_transition 0` 放在 set_driving_cell 之后**盖不住它** ——
# 驱动电阻仍然生效，实测关键路径一动不动。那是最危险的写法：看起来生效但没有。
set ideal_drive {{{ideal_drive_ports}}}
foreach p [all_inputs -no_clocks] {{
  if {{[lsearch -exact $ideal_drive [get_full_name $p]] < 0}} {{
    set_driving_cell -lib_cell BUFx2_ASAP7_75t_R -pin Y $p
  }}
}}
set_load 0.0005 [all_outputs]

{vcd_cmd}
set ws [worst_slack -max]
set arrival [expr {{{period_ns} - $ws}}]

# 这次网表里有几个时序单元 —— 由**这一次**运行自己数，而不是问综合器。
# 它决定要不要对下面那份报告断言"结果来自一条真实的 I/O 到 I/O 路径"
# （见 `_assert_timing_came_from_a_real_path`）。取 `-cells` 是实例数；
# 裸的 `all_registers` 返回的是寄存器**引脚**，两者在本仓三个设计上恰好相等，
# 但相等是巧合不是定义，而这个数要落进记录、要与 design.md 里的触发器数对上。
set nregs [llength [all_registers -cells]]

# 逐时钟域的最差 slack。OpenSTA 3.1.0 **没有** `worst_slack -clock`
# （实测 `Error 562: -clock is not a known keyword or flag`），只能这么取。
# 某个域一条可分析的路径都没有时，find_timing_paths 返回空集合 —— 那时写
# null，不写 0（会被读成「刚好卡住」）也不写周期（会被读成「完全空闲」）。
set per_clock {{}}
foreach cname {clock_names} {{
  set ps [find_timing_paths -path_delay max -group_path_count 1 -to [get_clocks $cname]]
  # `-group_path_count 1` 是**每个 path group 各一条**，不是总共一条。带异步复位的
  # 设计还有一个 `asynchronous` 组（recovery），取 [lindex $ps 0] 会拿到某一组的
  # 那条而不是最差的那条 —— 实测 ADDER32 上差 0.196 ns，且两个数都像模像样。
  # 与顶层的 `worst_slack -max` 口径保持一致：全部组里取最差。
  set worst ""
  foreach pth $ps {{
    set s [get_property $pth slack]
    if {{$worst eq "" || $s < $worst}} {{ set worst $s }}
  }}
  if {{$worst ne ""}} {{
    # arrival 也在这里算，**与顶层的 `set arrival` 同一个表达式、同一份全精度
    # 值**。放到 Python 侧用 `period - 已经 %.6f 过的 slack` 去减，会与顶层差在
    # 末几位（实测 ADDER32 单时钟：5410.435648278387 vs 5410.4356482784）——
    # 那就成了「一条记录里并排放着两个本该相等的数」。
    set per [get_property [get_clocks $cname] period]
    lappend per_clock [format "\\"%s\\": {{\\"slack_ns\\": %.6f, \\"arrival_ns\\": %.6f}}" \
                      $cname $worst [expr {{$per - $worst}}]]
  }} else {{
    lappend per_clock [format "\\"%s\\": null" $cname]
  }}
}}

# --- 最小延时（hold）：只留设计内部的路径 -------------------------------------
# 放在 max 侧全部取完之后，是为了让「本变更不动 max 侧」在这份脚本上一眼可见。
# 两条都要：
#   -from [all_inputs -no_clocks]  排掉 输入端口→reg。它们的 min 结果由
#                                  `set_input_delay 0`（输入在 0 时刻到达）决定。
#   -to   [all_outputs]            排掉 reg→输出端口。同理，由 set_output_delay 0 决定。
# 实测（2026-09-15，OpenSTA 3.1.0 + ASAP7）：不排除时，三个触发器数相差 300 倍的
# 设计（8 / 145 / 2433）的 `worst_slack -min` **逐位相同**
# （-0.021162700663102926）—— 最差 min 路径永远是理想驱动的 rst_n 到 removal 检查，
# 那个数是库里 DFF 单元的 removal 时间，与电路无关。
# `-no_clocks` 是**说清意图**，不是在防一个当下存在的 bug：实测
# `[all_inputs]` 是 19 个端口、`[all_inputs -no_clocks]` 是 18 个，而两者产出的
# hold 值逐字相同（0.04663278228892245）—— 因为 reg→reg 路径的起点是寄存器的
# 时钟**引脚**，不是 `clk` 这个端口，`-from [get_ports clk]` 根本匹配不到它们。
# 写 `-no_clocks` 的理由是这一行要排的是「数据从主输入进来」那一类，时钟不属于
# 它；留着它也不会让任何现有判据变红（已实测），所以别把它当成一道防线。
set_false_path -hold -from [all_inputs -no_clocks]
set_false_path -hold -to [all_outputs]
# 判据是「排除之后还剩几条路径」，不是「有没有时序单元」。实测
# `ADDER32 PIPE_STAGES=1` 有 5 个触发器、0 条域内路径（它们全部只被
# 输入端口→reg 与 reg→输出端口两类路径触及），按后者判会把 OpenSTA 的无路径
# 哨兵值 1.0000000433293989e+39 写进记录 —— 一个合法的 JSON 数字，会被读成
# 「余量无穷大」，而真相是「没有可测的路径」。当前代 92 条里有 29 条是这个形态。
if {{[llength [find_timing_paths -path_delay min -group_path_count 1]] == 0}} {{
  set hold_json "null"
}} else {{
  set hold_json [format "%.6f" [worst_slack -min]]
}}

set fh [open {results_json} w]
puts $fh [format "{{\\"slack_ns\\": %.6f, \\"critical_path_delay_ns\\": %.6f, \\"register_count\\": %d, \\"hold_slack_ns\\": %s, \\"per_clock_slack_ns\\": {{%s}}}}" $ws $arrival $nregs $hold_json [join $per_clock ", "]]
close $fh

{power_cmd}report_checks -path_delay max -sort_by_slack > {checks_rpt}
exit
"""


def run_sta(design, netlist, liberty, vcd=None, period_ns=5.0, out_dir=None,
            repo_root=REPO_ROOT, case=None, tied=None):
    """vcd=None 表示不做活动率反标：跳过 read_vcd 与 report_power，功耗字段返回 None。

    case（`{静态输入端口: 值}`，sta-scenarios）：在约束之后把这些输入定值（set_case_analysis，多位端口逐位），
    用于按验收场景量时序。None 时脚本与改动前逐字相同。

    tied（参考口径接成常数、已不在网表里的顶层输入，reference-ppa）：`static_ports` 里只匹配这些端口的模式跳过，
    不再要求匹配得到端口；其余模式照旧，匹配不到照旧报错。None 时与改动前逐字相同。

    ⚠️ `design` 这个形参装的是**被测顶层模块名**，不是设计根的目录名。
    两者在「设计根名 MUST 等于顶层名」成立的全部历史里逐字相同，收根之后
    （本仓 内部#45）分开：一个根可以挂两个顶层（例如一个地址流水与它的组合子块）。形参名没改是因为它就是记录里 `design`
    字段的值、也是全部 CLI 的 `--design`，而那个字段一直指顶层。
    根目录由 `resolve_design_root(design)` 查 `params.yaml` 的 `tops:` 声明得到。

    不能退而求其次让 OpenSTA 用默认活动率估功耗 —— CLAUDE.md 明确要求功耗必须由
    VCD/SAIF 反标算得，不接受无活动率的静态估算。拿不到活动率就没有功耗，
    不是有一个差一点的功耗。
    """
    sta = shutil.which("sta")
    if sta is None:
        raise RuntimeError("OpenSTA 'sta' not found in PATH (need ~/tools/env.sh sourced)")

    run_dir = Path(out_dir) if out_dir else adhoc_run_dir(design, "sta")
    run_dir.mkdir(parents=True, exist_ok=True)

    results_json = run_dir / "sta_results.json"
    power_json = run_dir / "power.json"
    checks_rpt = run_dir / "checks.rpt"
    script_path = run_dir / "run_sta.tcl"
    log_path = run_dir / "sta.log"

    declared = _resolve_clocks(design, period_ns, repo_root)
    groups = clock_groups(design, repo_root)
    script = STA_TCL_TEMPLATE.format(
        clock_cmd=_clock_command(declared, groups, period_ns),
        io_delay_cmd=_io_delay_command(declared)
        + _static_port_command(_drop_tied(static_ports(design, repo_root), tied, netlist, design))
        + ("" if case is None else
           _case_command(case, _module_input_widths(Path(netlist).read_text(), design))),
        clock_names="{" + " ".join(c["name"] for c in declared) + "}",
        ideal_drive_ports=" ".join(ideal_drive_ports(design, repo_root)),
        liberty=liberty,
        netlist=netlist,
        top=design,
        period_ns=period_ns,
        vcd_cmd=f"read_vcd -scope {design} {vcd}\n" if vcd is not None else "",
        power_cmd=f"report_power -format json > {power_json}\n" if vcd is not None else "",
        results_json=results_json,
        checks_rpt=checks_rpt,
    )
    script_path.write_text(script)

    proc = subprocess.run([sta, "-exit", str(script_path)], capture_output=True, text=True)
    log_path.write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        # 流程自己拦下来的那些（端口不存在之类）要把原因带出来 —— 只给一个
        # 日志路径，等于让调用方去猜是工具崩了还是约束写错了。
        flagged = [ln for ln in (proc.stdout + proc.stderr).splitlines()
                   if ln.startswith("FLOW-ERROR:")]
        detail = ("\n" + "\n".join(flagged)) if flagged else ""
        raise RuntimeError(f"OpenSTA failed (see {log_path}){detail}")

    timing = json.loads(results_json.read_text())
    if vcd is not None:
        # 功耗字段落进记录之前先证明反标发生了 —— 顺序是有意的：证明不了就不该有数。
        _assert_activity_annotated(proc.stdout + proc.stderr)
        activity_annotation = _activity_annotation(proc.stdout + proc.stderr,
                                                   Path(netlist).read_text(), design)
        total_power = json.loads(power_json.read_text())["Total"]
        dynamic_power_w = total_power["internal"] + total_power["switching"]
        static_power_w = total_power["leakage"]
    else:
        dynamic_power_w = static_power_w = activity_annotation = None

    delay_ns = timing["critical_path_delay_ns"]
    # 级数与延时必须来自同一条路径。延时取自 worst_slack，级数取自报告里的某个块——
    # 不核对就没人保证那是同一条。
    _assert_stages_from_worst_path(checks_rpt, timing["slack_ns"])
    # 零触发器的网表还要多证一件事：那条路径真的从输入端口走到了输出端口。
    # 「设计声明无时钟」只是零触发器的一个子集，两支都要（见该函数的 docstring）。
    register_count = timing["register_count"]
    _assert_timing_came_from_a_real_path(clock_port(design, repo_root),
                                        register_count, checks_rpt)

    per_clock = timing["per_clock_slack_ns"]
    clock_entries = []
    for c in declared:
        measured = per_clock.get(c["name"])
        # 该域没有可分析的路径时 slack 缺席，fmax 跟着缺席 —— 由一个不存在的
        # 关键路径算出来的频率是编造的。
        slack = arrival = None
        if measured is not None:
            slack, arrival = measured["slack_ns"], measured["arrival_ns"]
        clock_entries.append({
            "name": c["name"],
            "port": c["port"],
            "period_ns": c["period_ns"],
            "slack_ns": slack,
            "fmax_mhz": (1000.0 / arrival) if arrival and arrival > 0 else None,
        })

    return {
        "clock_period_ns": period_ns,
        "clocks": clock_entries,
        "register_count": register_count,
        "slack_ns": timing["slack_ns"],
        # 域内（reg→reg）的最差 hold 余量。为 None 表示**没有可测的域内路径** ——
        # 不蕴含「没有触发器」：单级流水有触发器却一条域内路径都没有。
        "hold_slack_ns": timing["hold_slack_ns"],
        "critical_path_delay_ns": delay_ns,
        "critical_path_stages": _count_path_stages(checks_rpt),
        "fmax_mhz": (1000.0 / delay_ns) if delay_ns > 0 else None,
        "fmax_method": "analytic",
        "dynamic_power_w": dynamic_power_w,
        "static_power_w": static_power_w,
        "activity_annotation": activity_annotation,
        "log_path": str(log_path),
        "checks_report": str(checks_rpt),
    }


# report_checks 的延时表里，一行一个 cell，例如 "28.77 28.77 v foo/Y (INVx1)"。
# 两列数字是必须的：只有一列（Time）的行属于 required 那半边，不是被穿过的 cell。
_CELL_ROW = re.compile(r"^\s*[\d.]+\s+[\d.]+\s+[v^]\s+\S+\s+\([^)]+\)\s*$")
# 每个路径块的末尾，例如 "           1.61   slack (MET)"。
_SLACK_ROW = re.compile(r"^\s*(-?[\d.]+)\s+slack\s+\(")
# 级数与延时同源的容差：报告里的 slack 印到小数点后 2 位，worst_slack 是 6 位，
# 所以容差必须大于半个最后一位（0.005）。
SAME_PATH_TOL_NS = 0.011


_POINT_ROW = re.compile(r"^(Startpoint|Endpoint):\s+(\S+)")


def worst_points(checks_rpt):
    """(起点, 终点)：slack 最小的那个路径块的起止点（与 critical_path_* 同一块，reference-ppa）。"""
    best, points, cur = None, (None, None), {}
    lines = Path(checks_rpt).read_text().splitlines()
    for line in lines:
        m = _POINT_ROW.match(line)
        if m:
            cur[m.group(1)] = m.group(2)
            continue
        m = _SLACK_ROW.match(line)
        if m:
            slack = float(m.group(1))
            if best is None or slack < best:
                best, points = slack, (cur.get("Startpoint"), cur.get("Endpoint"))
            cur = {}
    return points


def _path_blocks(checks_rpt):
    """把 report_checks 的输出切成路径块，返回 [(slack, cell 行数), ...]。

    report_checks 默认**对每个 path group 各报一条**最坏路径。带异步复位的设计
    因此会多出一条 `asynchronous` 组的 recovery 路径，它与关键路径无关，
    但和关键路径长在同一份文本里 —— 逐行扫整份报告就会把两者加在一起。
    """
    blocks = []
    cells = 0
    started = False
    for line in Path(checks_rpt).read_text().splitlines():
        if line.startswith("Startpoint:"):
            started, cells = True, 0
            continue
        if not started:
            continue
        if _CELL_ROW.match(line):
            cells += 1
            continue
        m = _SLACK_ROW.match(line)
        if m:
            blocks.append((float(m.group(1)), cells))
            started = False
    return blocks


def _worst_block(checks_rpt):
    """slack 最小的那一块。

    按 slack 选而不是「取第一块」：tcl 里的 -sort_by_slack 只保证顺序，
    依赖顺序是隐式契约，报告格式一变就静默错位。
    """
    blocks = _path_blocks(checks_rpt)
    if not blocks:
        raise RuntimeError(
            f"{checks_rpt} 里没有任何完整的路径块（找不到 Startpoint: … slack (…) 这样一对）。"
            "这是「没测到」，不是「零级」—— 不返回 0，见 experiment-trust 的"
            "「无法测得的指标必须缺席」。")
    return min(blocks, key=lambda b: b[0])


def _worst_path_slack(checks_rpt):
    """报告里最坏那一块自己印的 slack（2 位小数）。"""
    return _worst_block(checks_rpt)[0]


ANNOTATED_RE = re.compile(r"Annotated\s+(\d+)\s+pin activities")


def _resolve_clocks(design, period_ns, repo_root):
    """设计声明的时钟，周期补齐。

    `flow/paths.py::clocks` 在单时钟回退路径上把 `period_ns` 留成 `None`
    （那时周期由命令行的 `--period-ns` 决定）；多时钟时每个时钟自带周期 ——
    不同域周期不同才是多时钟的意义。这里把两支合到一处。
    """
    out = []
    for c in clocks(design, repo_root):
        c = dict(c)
        if c["period_ns"] is None:
            c["period_ns"] = period_ns
        out.append(c)
    return out


def _clock_command(declared, groups, period_ns):
    """建立时序环境的那几行：每个时钟一条 `create_clock`，外加分组。

    `declared` 为空表示设计声明自己没有时钟，那时建一个**显式的虚拟时钟**。
    不能靠写 `[get_ports clk]` 然后指望"端口找不到"达到同一效果：OpenSTA 那时
    只报一句 `Warning 366: port 'clk' not found` 就自己建一个虚拟时钟，组合路径
    照常挂在它下面出数 —— 结果来自一条没人选过的回退路径。两种写法实测数值逐位
    相同（一个组合设计上 worst_slack 都是 4.873560），差别全在可读性
    与可断言性上：显式之后，"端口找不到"重新变回一个真正的错误。

    **分组只在多于一组时才发。** 单时钟设计发出的 tcl 因此与本变更之前逐字相同
    —— 那是「本变更对既有记录的测量口径零影响」的第一道判据
    （`tests/test_run_sta_multiclock.py::test_a_single_clock_design_emits_the_same_tcl_as_before`）。

    未声明分组时 `clock_groups` 返回「每个时钟自成一组」，也就是互为异步。
    实测（OpenSTA 3.1.0，2026-09-15）不设分组时 `worst_slack` 取自一条跨异步域的
    路径（0.9233），设了之后是域内的（4.9233）—— 两个都是 `slack (MET)`、
    都不报警告、差 5.3 倍，而前者不说明电路的任何性质。
    """
    if not declared:
        return f"create_clock -name clk -period {period_ns}"
    lines = []
    for c in declared:
        # 端口找不到时 OpenSTA 只报一句 `Warning 366: port 'x' not found` 就自己
        # 建一个虚拟时钟，照常出数 —— 一条没人选过的回退路径。显式拦掉它。
        lines.append(
            f"if {{[llength [get_ports -quiet {c['port']}]] == 0}} {{"
            f" puts \"FLOW-ERROR: 声明的时钟 {c['name']} 的端口 {c['port']}"
            f" 在网表里不存在\"; exit 1 }}")
        lines.append(
            f"create_clock -name {c['name']} -period {c['period_ns']}"
            f" [get_ports {c['port']}]")
    if len(groups) > 1:
        args = " ".join(f"-group [get_clocks {_clock_selector(g)}]"
                        for g in groups)
        lines.append(f"set_clock_groups -asynchronous {args}")
    return "\n".join(lines)


def _clock_selector(group):
    """`get_clocks` 的参数：一个时钟直接给名字，多个要用花括号括成一个列表。"""
    if len(group) == 1:
        return group[0]
    return "{" + " ".join(group) + "}"


def _io_delay_command(declared):
    """输入/输出延时。**每个时钟各发一次**，第二个起带 `-add_delay`。

    ⚠️ 这是本变更里唯一一处「不这么写就静默丢数」的地方。把全部输入都绑到第一个
    时钟（也就是单时钟写法的自然延伸）再配上异步分组，**另一个域的 input→reg 与
    reg→output 会被整片排除**。实测（OpenSTA 3.1.0，2026-09-15，`io2` 夹具）：

        全部输入绑 clk_a      db→reg 0 条，reg→qb 0 条，无任何警告
        逐时钟各发一次        db→reg 1 条，reg→qb 1 条

    这个坑在单时钟下不存在，所以重跑既有记录的对比**发现不了它** ——
    判据只能是 `tests/test_run_sta_multiclock.py::test_io_delay_is_issued_for_every_clock`。

    第一条不带 `-add_delay`，其余带：不带的那条会**替换**已有设置，全带上则第一条
    没有可加的对象。顺序因此是有意义的。
    """
    if not declared:
        names = ["clk"]
    else:
        names = [c["name"] for c in declared]
    lines = []
    for i, name in enumerate(names):
        add = "" if i == 0 else " -add_delay"
        lines.append(f"set_input_delay 0 -clock {name}{add} [all_inputs -no_clocks]")
        lines.append(f"set_output_delay 0 -clock {name}{add} [all_outputs]")
    return "\n".join(lines) + "\n"


def _static_port_command(specs):
    """设计声明的静态端口：false path 或 multicycle（sta-static-ports D2，内部#154）。

    没有声明时返回空串，tcl 与以前逐字相同。每一项先查 `get_ports -quiet` 非空：
    模式打错时 OpenSTA 对空集合的 set_false_path 只是什么都不做，排除静默失效。
    """
    lines = []
    for spec in specs:
        pats = " ".join(spec["ports"])
        sel = f"[get_ports {{{pats}}}]"
        lines.append(
            f"if {{[llength [get_ports -quiet {{{pats}}}]] == 0}} {{"
            f" puts \"FLOW-ERROR: static_ports 的 {pats}（{spec['by']}）在网表里匹配不到端口\"; exit 1 }}")
        if spec["kind"] == "false_path":
            lines.append(f"set_false_path -from {sel}")
        else:
            n = spec["cycles"]
            lines.append(f"set_multicycle_path -setup {n} -from {sel}")
            lines.append(f"set_multicycle_path -hold {n - 1} -from {sel}")
    return "".join(ln + "\n" for ln in lines)


_PORT_DECL_RE = re.compile(r"^\s*(input|output|inout)\s*(?:\[(\d+):(\d+)\])?\s*([^;]+);", re.M)


def _drop_tied(specs, tied, netlist, design):
    """去掉只匹配被接成常数端口的模式（它们已不在网表里）；整项都空了就去掉这一项。"""
    if not tied:
        return specs
    inputs = _module_input_widths(Path(netlist).read_text(), design)
    out = []
    for spec in specs:
        keep = [p for p in spec["ports"]
                if not (any(fnmatch.fnmatchcase(t, p) for t in tied)
                        and not any(fnmatch.fnmatchcase(i, p) for i in inputs))]
        if keep:
            out.append({**spec, "ports": keep})
    return out


def _module_input_widths(netlist_text, module):
    """{输入端口: 位宽}，取自网表里该模块的端口声明。"""
    m = re.search(r"^module\s+\\?" + re.escape(module) + r"\b.*?^endmodule", netlist_text, re.M | re.S)
    out = {}
    for hi, lo, name in re.findall(r"^\s*input\s+(?:\[(\d+):(\d+)\]\s*)?(\w+)\s*;", m.group(0) if m else "", re.M):
        out[name] = abs(int(hi) - int(lo)) + 1 if hi else 1
    return out


def _case_command(case, width):
    """把静态输入定值：一位端口直接定，多位端口逐位定。端口不在网表里就报错，不静默放过。"""
    cmds = []
    for port, val in case.items():
        if port not in width:
            raise RuntimeError(f"验收场景定值的端口 {port} 不是网表的输入端口")
        w = width[port]
        if val >= (1 << w):
            raise RuntimeError(f"验收场景给 {port}（{w} 位）的值 {val} 超出位宽")
        if w == 1:
            cmds.append(f"set_case_analysis {val} [get_ports {{{port}}}]")
        else:
            cmds += [f"set_case_analysis {(val >> b) & 1} [get_ports {{{port}[{b}]}}]" for b in range(w)]
    return "".join(c + "\n" for c in cmds)


def _port_bits(netlist_text, design):
    """网表里被测顶层全部端口的位数之和（yosys `write_verilog` 的端口声明）。"""
    m = re.search(rf"^module\s+\\?{re.escape(design)}\s*\(.*?^endmodule", netlist_text,
                  re.S | re.M)
    if m is None:
        raise RuntimeError(f"网表里找不到顶层模块 {design}，数不出端口位数")
    total = 0
    for d in _PORT_DECL_RE.finditer(m.group(0)):
        width = abs(int(d.group(2)) - int(d.group(3))) + 1 if d.group(2) else 1
        total += width * len([n for n in d.group(4).split(",") if n.strip()])
    return total


def _activity_annotation(log_text, netlist_text, design):
    """活动率反标到了哪一层（experiment-record「记录必须说明活动率反标到了哪一层」，内部#65）。

    标注引脚数不超过端口位数时判为 `ports`：内部节点的活动率是 OpenSTA 按概率传播出来的，
    看不到毛刺与相关性，结构之间的动态功耗排名不能当结论用。今天 RTL 仿真的 VCD 只对得上
    端口名，所以全部记录都是这个口径；门级 VCD 反标做起来之后（内部#65 的修法 1）才会出现
    `internal`。判据是「≤ 端口位数」，偏保守：误判只会把真反标了内部节点的记录说成只标了端口。
    """
    pins = int(ANNOTATED_RE.search(log_text).group(1))
    port_bits = _port_bits(netlist_text, design)
    return {"pins": pins, "port_bits": port_bits,
            "scope": "ports" if pins <= port_bits else "internal"}


def _assert_activity_annotated(log_text):
    """确认这次 `read_vcd` 真的把活动率标到引脚上了。

    `read_vcd` 的层次作用域与网表引脚名对不上时，**一个引脚都没标上，而 OpenSTA
    不报错**，`report_power` 照常给出数字 —— 那个数字是工具默认活动率下的静态
    估算，与设计实际怎么翻转没有任何关系，只是网表与周期的函数。2026-09-14 实测：
    `runs/` 下 633 个 `sta.log` 里 631 个是 `Annotated 0 pin activities`
    （`docs/data-credibility.md` 的 D-1，本仓 内部#17）。

    判据必须是**标注数本身**。「`read_vcd` 这一步执行了」与「功耗字段非空」
    这两个更顺手的观察量，在缺口存在时同样为真 —— 那正是它藏了八天的原因。

    那一行整个不存在时同样报错：read_vcd 没跑、或 OpenSTA 换了输出措辞，
    两种情形下"反标真的发生了"都无法被证明，而这条要求的判据正是能不能被证明。
    """
    m = ANNOTATED_RE.search(log_text)
    if m is None:
        raise RuntimeError(
            "OpenSTA 日志里找不到 `Annotated N pin activities` 一行，"
            "无法证明活动率反标真的发生了。反标不能被证明就没有功耗，"
            "不是有一个差一点的功耗（experiment-trust 的"
            "「活动率反标必须被证明真的发生了」）。")
    annotated = int(m.group(1))
    if annotated == 0:
        raise RuntimeError(
            "活动率反标标上了 0 个引脚：`read_vcd` 读进去了，但 VCD 的层次名与"
            "网表的引脚名对不上，一个都没标上。OpenSTA 不会因此报错，"
            "`report_power` 会照常给出一个量级正常、却只是网表与周期的函数的数字。"
            "检查 `read_vcd -scope <top>` 的 scope 取值与 VCD 顶层作用域名是否一致。")


def _count_path_stages(checks_rpt):
    """最坏那一条路径上穿过的 cell 行数。

    只数最坏那一块 —— 跨 path group 求和会让带异步复位的设计虚高 2
    （recovery 路径贡献 `rst_n (in)` 与 `<ff>/RN` 两行）。
    """
    return _worst_block(checks_rpt)[1]


_START_ROW = re.compile(r"^Startpoint:\s+(\S+)\s+\((.*)\)\s*$", re.M)
_END_ROW = re.compile(r"^Endpoint:\s+(\S+)\s+\((.*)\)\s*$", re.M)


def _assert_io_to_io_path(checks_rpt):
    """报告里每一条路径都必须真的从输入端口走到输出端口。

    **何时**跑这道断言不在这里，在 `_assert_timing_came_from_a_real_path`。
    两件事分开：那边按「设计声明无时钟 **或** 这次网表零触发器」决定要不要查，
    这里只管查起来看什么。分开写是因为它们的判据来源不同 —— 触发条件要数
    网表里的时序单元，而下面的判据**有意不数**（见末段）。

    跑到这里时，时序环境整个由 `set_input_delay 0` / `set_output_delay 0`
    撑起来，路径两端都是 I/O 约束而不是寄存器 —— 于是"没有路径"与"路径很短"
    在记录里长得一模一样，都是一个小的 delay 值加一个小的级数，不会报错
    （`openspec/specs/experiment-trust/spec.md` 的「无触发器的实现必须证明其
    时序结果来自真实路径」）。

    检查**全部**路径块而不是最坏那一块：无时钟设计里本来就不该有别的形态，
    而"取第一块"是隐式契约（报告顺序一变就静默错位，`_worst_block` 的 docstring
    专门写过这一条）。全查就与顺序无关。

    判据取 Startpoint / Endpoint 那两行自己印的括注（`input port` / `output port`），
    **不**去数网表里有没有触发器：报告说的是这次 STA 实际选中的那些路径，
    而触发器数说的是网表 —— 两者不同步时（比如 top 写错、网表链错），
    可信的是前者。

    ⚠️ 与触发条件那边**不矛盾**，尽管那边正是数触发器：两边要的东西相反。
    触发条件要的是"宁可多查"——不同步时应当**仍然**跑这道断言，所以它数网表；
    判据要的是"看这次实际发生了什么"——不同步时应当相信报告，所以它不数网表。
    正因为触发条件的计数也来自同一次 STA 运行（`all_registers -cells`），
    两边读的根本是同一个视图，不同步这件事在这条链上不会发生。
    """
    path = Path(checks_rpt)
    text = path.read_text() if path.exists() else ""
    starts = _START_ROW.findall(text)
    ends = _END_ROW.findall(text)
    if not starts or len(starts) != len(ends):
        raise RuntimeError(
            f"{checks_rpt} 里没有成对的 Startpoint / Endpoint 行"
            f"（Startpoint {len(starts)} 条、Endpoint {len(ends)} 条），"
            "无时钟设计的时序结果无法被证明来自一条真实路径。"
            "这是「没测到」，不是「路径很短」——不记录时序字段。")
    for (sname, skind), (ename, ekind) in zip(starts, ends):
        if "input port" not in skind or "output port" not in ekind:
            raise RuntimeError(
                f"{checks_rpt} 里有一条路径是 {sname} ({skind}) → {ename} ({ekind})，"
                "不是**输入端口**到**输出端口**。该设计声明自己没有时钟，"
                "它的每条路径都应当是 I/O 到 I/O；出现别的形态说明被测的不是它"
                "声明的那个电路（top 写错、网表链错），而那时延时值仍然是一个"
                "看着正常的小数。")


def _assert_timing_came_from_a_real_path(clock_port_name, register_count,
                                        checks_rpt):
    """**什么时候**要求时序结果来自一条真实的输入到输出路径。

    与 `_assert_io_to_io_path`（**判什么**）分开的两件事，别混起来读：
    这里决定要不要跑那道断言，那边决定跑起来看什么。

    两支，各防一个失效模式，所以是 `or` 而不是任何一支单独成立：

    - `clock_port_name is None` —— 设计声明自己没有时钟。防的是
      `create_clock … [get_ports clk]` 在端口找不到之后**退回隐式虚拟时钟**：
      OpenSTA 只报一句 `Warning 366`，路径照常挂在回退的时钟下面出数。
      这与网表里有几个触发器毫无关系，所以它不能被下面那支取代。

    - `register_count == 0` —— 这次综合出来的网表一个时序单元都没有。防的是
      `experiment-trust` 那条要求本来就写明的情形：路径两端都是 `set_input_delay 0`
      / `set_output_delay 0` 的 I/O 约束而不是寄存器，于是"没有路径"与
      "路径很短"在记录里长得一模一样，都是一个小的 delay 值加一个小的级数。

    第二支是**更常见**的那一半，而且不触发任何工具警告：一个带真实 `clk` 端口的
    参数化设计，流水深度取 0 时照样综合出零触发器，`create_clock` 绑定成功。
    实测 `flow = sha256:c4dacda99…` 那 90 条里有 31 条属于它
    （`ADDER32 PIPE_STAGES=0` 27 + 另外两个已删设计 `PIPE_STAGES=0` 的 3
    与 1），在补上这一支之前一条都没被查过
    （本仓 内部#32）。

    `register_count` MUST 来自产出本次 `slack_ns` 的那一次 STA 运行，
    MUST NOT 来自综合器的统计输出：两者不同步时（top 写错、网表链错、读进去的
    不是刚综合出来的那一份）不同步的方向恰好是**该断言的却没断言**。
    """
    if clock_port_name is None or register_count == 0:
        _assert_io_to_io_path(checks_rpt)


def _assert_stages_from_worst_path(checks_rpt, worst_slack):
    """确认报告里选中的那一块就是 worst_slack 所描述的那条路径。

    没有这条断言，选错块仍然是静默的：级数会是另一条路径的级数，
    而它旁边的 critical_path_delay_ns 是对的，两个数并排放着看不出异常。
    """
    reported = _worst_path_slack(checks_rpt)
    if abs(reported - worst_slack) > SAME_PATH_TOL_NS:
        raise RuntimeError(
            f"级数与延时不同源：{checks_rpt} 里最坏路径块的 slack 是 {reported}，"
            f"而本次 STA 的 worst_slack 是 {worst_slack}（差 "
            f"{abs(reported - worst_slack):.6f} ns > 容差 {SAME_PATH_TOL_NS} ns）。"
            "critical_path_stages 与 critical_path_delay_ns 必须来自同一条路径，"
            "对不上就是没测到，不记录。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--vcd", default=None,
                    help="活动率来源；不给则跳过功耗，只出时序")
    ap.add_argument("--period-ns", type=float, default=5.0)
    ap.add_argument("--out-dir", default=None,
                    help="产物目录；不给则落进一个 runs/adhoc-* 目录")
    args = ap.parse_args()

    result = run_sta(args.design, args.netlist, args.liberty, args.vcd, args.period_ns,
                     out_dir=args.out_dir)
    print(json.dumps(result, indent=2))
