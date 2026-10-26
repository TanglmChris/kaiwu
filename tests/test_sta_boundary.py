"""STA 的边界条件必须与综合给 ABC 的那套相同。

为什么值得有这个测试：ABC 正是照着 `flow/synth/abc.constr` 那套边界做单元选择与
驱动强度优化的。STA 若换一套边界报数，**报出来的就不是流程在优化的那个量**。

这里有一种**不会响**的错法：tcl 在 `set_cmd_units` 之后用 pF，而 `abc.constr` 用
liberty 自己的单位（ASAP7 是 fF）。把 `0.5` 照搬过去就是 500 fF，大 1000 倍 ——
实测关键路径涨 +194% 到 +2000%，而 STA 照常给出一个正数 slack：
`ADDER32 KOGGE_STONE W=32` 会从 0.19 ns 变成 4.04 ns，在 5 ns 周期下仍是 MET，
照常出报告、照常写记录。所以只断言"边界条件被设上了"是不够的，必须断言**量级**。
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.sta.run_sta import (STA_TCL_TEMPLATE, _clock_command,
                              _io_delay_command)
from flow.synth.synth import ABC_CONSTR, run_synth

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

needs_tools = pytest.mark.skipif(
    shutil.which("yosys") is None or shutil.which("sta") is None
    or not LIBERTY.is_file(),
    reason="需要 yosys / sta 在 PATH 上与合并 liberty 在本机")

# 上界的意义是分辨"配置对了"与"配置错了一个量级"，不是给延时定精度。
# 实测（2026-09-14，一次全量重跑的 84 个组合）：对齐边界后的真实范围是
# **0–15.40%**，最大那个是 `ADDER32 W=8 CSEL PIPE_STAGES=2`（路径 0.137 ns，
# 加性增量 21 ps）。单位错 1000 倍时最小 +194%。
#
# 上界仍取 10%，因为这道检查跑的是下面那个固定组合（`KOGGE_STONE W=32`，实测
# 4.26%），不是全量 —— 10% 对它有两倍多的余量，离 +194% 又差一个量级。
# 2026-09-13 最初写的依据是"实测最大 4.26%"，那是取样不足：诊断只覆盖了
# `W=32/64 PIPE_STAGES=0`，没测路径最短的 `W=8` 流水档。
MAX_BOUNDARY_EFFECT = 0.10

# 影响最大的组合 —— 边界条件是加性常数（8–25 ps），所以路径最短的百分比最大。
# 拿慢电路测这道检查会把上界测得毫无压力（RIPPLE W=64 只有 0.44%）。
# 真实设计夹具：ADDER32 KOGGE_STONE 32 位（最快的那一档，边界条件的相对影响最大）。2026-10-01 随设计根
# 删除后一度换成闭源的 FIFO 构件，2026-10-14 设计根恢复后换回（内部#305）。
FASTEST_DESIGN = "ADDER32"      # 手搭的 tcl 建了 clk 时钟，被测设计要有 clk 端口
FASTEST = {"DAT_W": 32, "SCHEME": 4, "PIPE_STAGES": 0, "CSEL_BLK_W": 4}

_FARAD_PER = {"ff": 1e-15, "pf": 1e-12, "nf": 1e-9, "uf": 1e-6, "f": 1.0}


def _liberty_cap_unit_farads(path):
    """liberty 自报的电容单位，例如 `capacitive_load_unit (1,ff);` → 1e-15 F。

    刻意从库里读而不是把 "fF" 写死：换 PDK 时单位可能不同，写死会让这道检查
    在换库之后静默失效 —— 那正是它要防的那类错误。
    """
    m = re.search(r"capacitive_load_unit\s*\(\s*([\d.]+)\s*,\s*([a-zA-Z]+)\s*\)",
                  Path(path).read_text()[:200000])
    assert m, f"{path} 里没有 capacitive_load_unit，无法核对两处负载是否一致"
    scale, unit = float(m.group(1)), m.group(2).lower()
    assert unit in _FARAD_PER, f"不认识的电容单位 {unit!r}"
    return scale * _FARAD_PER[unit]


def _tcl_cap_unit_farads(tcl):
    m = re.search(r"set_cmd_units\b.*?-capacitance\s+([a-zA-Z]+)", tcl)
    assert m, "STA 脚本没有声明电容单位，无法核对两处负载是否一致"
    unit = m.group(1).lower()
    assert unit in _FARAD_PER, f"不认识的电容单位 {unit!r}"
    return _FARAD_PER[unit]


def _driving_cell(text):
    m = re.search(r"^\s*set_driving_cell\b[^\n]*", text, re.M)
    return m.group(0) if m else None


def _load_value(text):
    m = re.search(r"^\s*set_load\s+(-?[\d.eE+-]+)", text, re.M)
    return float(m.group(1)) if m else None


# --- M1 ---------------------------------------------------------------------
@pytest.mark.skipif(not LIBERTY.is_file(), reason="合并 liberty 不在本机")
def test_both_sides_declare_the_same_output_load():
    constr = Path(ABC_CONSTR).read_text()
    synth_load = _load_value(constr)
    assert synth_load is not None, f"{ABC_CONSTR} 里没有 set_load"
    sta_load = _load_value(STA_TCL_TEMPLATE)
    assert sta_load is not None, "STA 侧没有声明输出负载"

    # 换算到法拉再比 —— 两处的单位不同，比字面值等于没比。
    #
    # 比的是**比值**不是差值：这两个数在法拉量级（1e-16 左右），而
    # `pytest.approx` 默认带 1e-12 的绝对容差，它会把 5e-16 和 5e-13 判成相等 ——
    # 也就是对这道检查唯一要抓的那个错（差 1000 倍）完全免疫。
    synth_f = synth_load * _liberty_cap_unit_farads(LIBERTY)
    sta_f = sta_load * _tcl_cap_unit_farads(STA_TCL_TEMPLATE)
    assert synth_f > 0 and sta_f > 0, "两处的负载都必须是正数"
    assert abs(sta_f / synth_f - 1.0) < 1e-9, (
        f"综合侧 {synth_load} × liberty 单位 = {synth_f:.3e} F，"
        f"STA 侧 {sta_load} × 脚本单位 = {sta_f:.3e} F —— 相差 {sta_f / synth_f:.0f} 倍。"
        "把一处的数字照搬到另一处不等于一致。")


def test_both_sides_drive_inputs_with_the_same_cell():
    constr = Path(ABC_CONSTR).read_text()
    synth_cell = _driving_cell(constr)
    assert synth_cell is not None, f"{ABC_CONSTR} 里没有 set_driving_cell"
    sta_cell = _driving_cell(STA_TCL_TEMPLATE)
    assert sta_cell is not None, "STA 侧没有声明输入驱动单元"

    cell_name = synth_cell.split()[-1]
    assert cell_name in sta_cell, (
        f"综合侧用 {cell_name} 驱动输入，STA 侧却是 {sta_cell.strip()!r}")


def _run_tcl(tcl_text, tmp_path, tag):
    script = tmp_path / f"{tag}.tcl"
    script.write_text(tcl_text)
    p = subprocess.run(["sta", "-exit", str(script)], capture_output=True, text=True)
    m = re.search(r"^WS (-?[\d.]+)", p.stdout, re.M)
    assert m, f"{tag}: 没拿到 worst_slack\n{p.stdout}\n{p.stderr}"
    return 5.0 - float(m.group(1))


@needs_tools
@pytest.mark.flow
def test_boundary_conditions_move_the_path_but_not_by_an_order_of_magnitude(tmp_path):
    """既要证明边界条件真的生效（>0），又要证明它没错一个量级（<上界）。

    只断言上界对"边界条件根本没设上"是瞎的 —— 0% 也满足上界。
    只断言下界对"单位错了 1000 倍"是瞎的 —— 那同样是 >0。
    """
    synth_result = run_synth(FASTEST_DESIGN, dict(FASTEST), LIBERTY,
                             out_dir=tmp_path / "synth")
    one_clock = [{"name": "clk", "port": "clk", "period_ns": 5.0}]
    base_tcl = STA_TCL_TEMPLATE.format(
        clock_cmd=_clock_command(one_clock, [["clk"]], 5.0),
        io_delay_cmd=_io_delay_command(one_clock),
        clock_names="{clk}",
        ideal_drive_ports="", liberty=LIBERTY,
        netlist=synth_result["netlist_path"], top=FASTEST_DESIGN,
        period_ns=5.0, vcd_cmd="", power_cmd="",
        results_json=tmp_path / "r.json", checks_rpt=tmp_path / "c.rpt")
    # 把边界条件摘掉，得到"加边界条件之前"的那份脚本：整个 foreach 块 + set_load
    stripped = re.sub(r"^set ideal_drive .*?^\}\n", "", base_tcl, flags=re.M | re.S)
    stripped = re.sub(r"^set_load .*\n", "", stripped, flags=re.M)
    # 用与上面两条检查同一组解析器判断"摘干净了"—— 模板的注释里也提到这两个命令名，
    # 拿子串判断会把注释也算进去。
    assert _driving_cell(stripped) is None and _load_value(stripped) is None, (
        "没能把边界条件从模板里摘干净，这个对照组无效")

    def probed(text):
        """去掉结尾的 exit，换成打印 worst_slack 再退出。"""
        body = [l for l in text.splitlines() if l.strip() != "exit"]
        return "\n".join(body + ['puts "WS [worst_slack -max]"', "exit", ""])

    with_bc = _run_tcl(probed(base_tcl), tmp_path, "with")
    without_bc = _run_tcl(probed(stripped), tmp_path, "without")

    delta = (with_bc - without_bc) / without_bc
    assert delta > 0, (
        f"加了边界条件但关键路径没变（{without_bc:.6f} → {with_bc:.6f}）——"
        "set_load / set_driving_cell 没有生效，检查引脚名与端口集合")
    assert delta < MAX_BOUNDARY_EFFECT, (
        f"边界条件把关键路径抬高了 {100 * delta:.1f}%（{without_bc:.6f} → {with_bc:.6f}），"
        f"超过上界 {100 * MAX_BOUNDARY_EFFECT:.0f}%。实测正确配置下最大 4.26%，"
        "而把电容值按错误的单位照搬过去（差 1000 倍）会涨 +194% 以上 —— 先核对单位。")


# --- M1（任务 1.1）------------------------------------------------------------
# rst_n 扇出到全部触发器。给它设一个 BUFx2 的话，那一跳就要上纳秒 —— 关键路径从 REG→REG
# 变成 recovery 路径，度量的是"这个流程没有综合复位树"，不是电路。
#
# 被测对象是夹具 RST_FANOUT（`tests/fixtures/designs/rst_fanout/`，1024 个带异步复位的触发器）。
# 开源部分里扇出最大的 ADDER32 只有 65 个触发器：2026-10-14 实测去掉 rst_n 的理想驱动声明，
# 它的关键路径一位不动，这道检查在它上面没有会失败的那一臂，所以专门造了这个夹具（内部#305）。
# 历史上用过一个 2433 个触发器的压缩流水设计（2026-09-15 起）与一个 525 个触发器的 FIFO 构件
# （2026-10-01 起），两者都已不在开源部分里，它们的数与下面的值不可比。
BROADCAST_DESIGN = "RST_FANOUT"
BROADCAST = {"DAT_W": 1024}

# 这个数是**回归绊线**，不是契约。契约是下面那句「最坏路径落在 clk 组」——
# 它才是「复位广播没有劫持关键路径」这件事本身。绊线的作用只是让「悄悄变成
# 劫持后的数」这种事有个量上的对照；它会因为任何无害的改动而失效，那时应当
# **重打并注明来源**，不是放宽成一个永远通过的范围。
#
# 测得时间：2026-10-14（内部#305）
# 被测对象：夹具 `RST_FANOUT DAT_W=1024`，提交 94227b4d 之后的工作区，连测两次逐位相同
# 两臂实测：rst_n 按理想驱动 → 0.119431 ns、clk 组；去掉理想驱动声明 → 1.434771 ns、
#           asynchronous 组（被复位网络劫持）
# 重打条件：改了夹具的 RTL、换 liberty、换 ABC 脚本或驱动单元、改了「综合读哪些源文件」的口径。
BROADCAST_CP_NS = 0.119431
BROADCAST_HIJACKED_CP_NS = 1.434771


@needs_tools
@pytest.mark.flow
def test_broadcast_port_does_not_hijack_the_critical_path(tmp_path, fixture_designs):
    from flow.sta.run_sta import run_sta

    synth_result = run_synth(BROADCAST_DESIGN, dict(BROADCAST), LIBERTY,
                             out_dir=tmp_path / "synth")
    sta_result = run_sta(BROADCAST_DESIGN, synth_result["netlist_path"], LIBERTY,
                         out_dir=tmp_path / "sta")

    rpt = Path(sta_result["checks_report"]).read_text()
    first = rpt.split("Startpoint:")[1]
    group = re.search(r"^Path Group: (\S+)", first, re.M)
    assert group and group.group(1) == "clk", (
        f"最坏路径落在 {group.group(1) if group else '?'} 组，"
        f"关键路径 {sta_result['critical_path_delay_ns']}（期望 {BROADCAST_CP_NS}）"
        " —— 被一个流程从未综合过的驱动网络劫持了，量出来的不是电路")
    assert sta_result["critical_path_delay_ns"] == pytest.approx(
        BROADCAST_CP_NS, abs=1e-6), (
        f"关键路径 {sta_result['critical_path_delay_ns']}，"
        f"期望 {BROADCAST_CP_NS}（被 rst_n 劫持时是 {BROADCAST_HIJACKED_CP_NS}）")


def test_ideal_drive_ports_is_declared_by_the_design(tmp_path, fixture_designs):
    from flow.paths import ideal_drive_ports

    for design in ("ADDER32", "IP_TOP"):
        assert ideal_drive_ports(design) == ["rst_n"], (
            f"{design} 应当把 rst_n 声明为理想驱动端口")

    # 没声明的设计回退到空列表 —— 全部输入都设驱动单元，流程不按名字猜复位
    (tmp_path / "designs" / "nodecl" / "rtl").mkdir(parents=True)
    (tmp_path / "designs" / "nodecl" / "rtl" / "nodecl.v").write_text(
        "module nodecl(); endmodule\n")
    (tmp_path / "designs" / "nodecl" / "params.yaml").write_text(
        "design_root: nodecl\n"
        "tops:\n"
        "  nodecl:\n"
        "    sim:\n      clock_signal: clk\n"
        "    params: {}\n")
    assert ideal_drive_ports("nodecl", repo_root=tmp_path) == []


# --- M1（任务 2.1）------------------------------------------------------------
# 综合侧的驱动单元（flow/synth/abc.constr），STA 侧用的是同一个。
DRIVING_CELL = "BUFx2_ASAP7_75t_R"

# 端口扇出要大到超过驱动单元的 max_capacitance，这道检查才有会失败的那一臂。
# 2026-10-14 起用夹具 RST_FANOUT（内部#305）：rst_n 负载 757.5，是 BUFx2 上限 92.16 的 8 倍多；
# 开源的 ADDER32 最大一档的复位负载远不到上限（而且保了层级，port_loads 只读网表里第一个模块，
# 读到的是子模块），在它上面这条永远通过。10-01 至 10-14 间用的是两个闭源构件。
BROADCAST_CASES = [
    ("RST_FANOUT", {"DAT_W": 1024}),
]


def port_loads(netlist_path, liberty_path=LIBERTY):
    """{顶层输入端口名: 它驱动的全部输入引脚电容之和}，单位是 liberty 自己的。

    复用 `test_synth_electrical` 的 liberty 解析与实例正则 —— 那一套是**独立于**
    `synth.py` 写的（用被测流程自己的代码去验证它，测不出流程本身的偏差），
    这里扩的只是"把顶层端口也算进来"这一步：`electrical_violations()` 只看网表里
    的单元实例，它的 docstring 明写端口不在覆盖范围（「端口没有驱动单元，
    也就没有『哪个 cell 扛不住』这回事」）。加了 `set_driving_cell` 之后，
    端口就有驱动单元了。
    """
    from test_synth_electrical import _liberty_cells

    lib = _liberty_cells(str(liberty_path))
    text = Path(netlist_path).read_text()

    m = re.search(r"module\s+\S+\s*\((.*?)\);", text, re.S)
    assert m, f"{netlist_path} 里找不到顶层模块的端口表"
    ports = set()
    for decl in re.finditer(r"\binput\s+(?:wire\s+)?(?:\[[^\]]*\]\s*)?(\\?\S+)\s*;",
                            text[:m.end() + 20000]):
        ports.add(decl.group(1).strip().lstrip("\\"))
    assert ports, f"{netlist_path} 里一个 input 声明都没解析到"

    inst_re = re.compile(
        r"\n\s*\\?([A-Za-z0-9_$\\.]+)\s+(\\?[A-Za-z0-9_$\\.\[\]]+)\s*\(([^;]*?)\);",
        re.S)
    conn_re = re.compile(r"\.([A-Za-z0-9_]+)\(([^)]*)\)")
    loads = {p: 0.0 for p in ports}
    for im in inst_re.finditer(text):
        cell, body = im.group(1), im.group(3)
        if cell not in lib:
            continue
        in_pins = lib[cell][1]
        for pin, net in conn_re.findall(body):
            net = net.strip().lstrip("\\")
            if pin in in_pins and net in loads:
                loads[net] += in_pins[pin]
    return loads


@needs_tools
@pytest.mark.parametrize("design,params", BROADCAST_CASES,
                         ids=[f"{c[0]}-SCHEME{c[1].get('SCHEME', '')}" for c in BROADCAST_CASES])
@pytest.mark.flow
def test_broadcast_ports_are_declared_ideal(design, params, tmp_path, fixture_designs):
    """未被声明为理想驱动的输入端口，扇出负载不得超过驱动单元的 max_capacitance。

    没有这道检查，下一个广播端口会重演 2026-09-13 那次：84 个组合里只有 2 个
    显形（一个压缩流水设计的 P1/P2），其余 81 个照常绿，而那 2 个的
    `critical_path_delay_ns` 度量的是"这个流程没有综合复位树"。
    """
    from test_synth_electrical import _liberty_cells
    from flow.paths import clock_signal, ideal_drive_ports

    max_cap = _liberty_cells(str(LIBERTY))[DRIVING_CELL][0]
    assert max_cap, f"{DRIVING_CELL} 在 liberty 里没有 max_capacitance"

    synth_result = run_synth(design, dict(params), LIBERTY, out_dir=tmp_path)
    ideal = set(ideal_drive_ports(design))
    # 时钟端口按构造就是理想的（tcl 用 `[all_inputs -no_clocks]`，它从来不被设驱动
    # 单元），所以不在本检查的范围里 —— 它的扇出同样很大（那个压缩流水设计上是
    # 1126 fF），但那从来不影响任何数。
    clk = clock_signal(design)
    if clk:
        ideal.add(clk.split(".", 1)[1])
    over = [(p, load) for p, load in port_loads(synth_result["netlist_path"]).items()
            if load > max_cap and p not in ideal]
    assert not over, "；".join(
        f"{design} 的端口 {p} 未被声明为理想驱动，但扇出负载 {load:.1f} 是 "
        f"{DRIVING_CELL} 的 max_capacitance（{max_cap}）的 {load / max_cap:.1f} 倍"
        for p, load in sorted(over, key=lambda x: -x[1]))
