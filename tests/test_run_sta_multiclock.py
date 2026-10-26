"""多时钟 STA：跨域路径怎么处理必须来自声明，逐域 slack 必须各算各的。

为什么值得有这个测试：这条路上有**四个会静默丢数的口子**，每一个都是「工具照常
出数、不报错、数不成立」——

1. 不设时钟分组时，跨异步域的路径会被当作真实路径参与 setup 分析。实测
   （OpenSTA 3.1.0，2026-09-15）`worst_slack` 取自一条 clk_a 发、clk_b 收的路径
   （0.9233），设了分组之后是域内的（4.9233）。两个都是 `slack (MET)`、都不报
   警告、差 5.3 倍，而前者不说明电路的任何性质（异步域之间的边沿关系是任意的）。

2. 把全部输入都绑到第一个时钟再配异步分组，**另一个域的 input→reg 与
   reg→output 会被整片静默排除**（实测各 0 条、无警告）。这个坑在单时钟下不
   存在，所以重跑既有记录的对比发现不了它。

3. 某个域一条域内路径都没有时，它的 slack 必须**缺席**。填 0 会被读成「刚好
   卡住」，填周期会被读成「完全空闲」。

4. 声明的时钟端口在网表里找不到时，OpenSTA 只报一句 Warning 366 就建一个虚拟
   时钟，照常出数。

夹具在 `tests/fixtures/multiclock/`，是**流程的测试输入**不是被测设计 ——
放进 `designs/` 就会产生记录、进扫参、被设计根洁净度检查按设计对待。
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.sta.run_sta import run_sta  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "multiclock"
LIBERTY = Path.home() / "pdk" / "asap7_merged" / "asap7sc7p5t_RVT_TT.lib"

needs_tools = pytest.mark.skipif(
    shutil.which("sta") is None or shutil.which("yosys") is None
    or not LIBERTY.exists(),
    reason="需要 sta / yosys / 合并 liberty（source ~/tools/env.sh）")


def _synth(module, out_dir):
    """把夹具 RTL 映射成网表。直接调 yosys —— 夹具不是设计根，走不了 run_synth。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    netlist = out_dir / f"{module}_netlist.v"
    script = "; ".join([
        f"read_verilog {FIXTURES / (module + '.v')}",
        f"synth -top {module}",
        f"dfflibmap -liberty {LIBERTY}",
        f"abc -liberty {LIBERTY}",
        "opt_clean",
        f"write_verilog -noattr {netlist}",
    ])
    proc = subprocess.run(["yosys", "-q", "-p", script],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return netlist


def _design_root(tmp_path, module, clocks, groups=None, static=None):
    """搭一个临时设计根，它声明 `module` 这一个被测顶层。

    `sta` / `params` 挂在**顶层**之下而不是根之下（2026-09-20 起，
    `openspec/specs/repo-layout/spec.md` 的「设计根可以声明多个被测顶层」）。
    rtl/ 下要有同名 module —— 解析会校验它。
    """
    root = tmp_path / "designs" / module
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / f"{module}.v").write_text(f"module {module}(); endmodule\n")
    lines = [f"design_root: {module}", "tops:", f"  {module}:",
             "    sta:", "      clocks:"]
    for name, port, period in clocks:
        lines += [f"        - name: {name}", f"          port: {port}",
                  f"          period_ns: {period}"]
    if groups is not None:
        lines.append("      clock_groups:")
        for g in groups:
            lines.append("        - [" + ", ".join(g) + "]")
    if static is not None:
        lines.append("      static_ports:")
        lines += [f"        - {item}" for item in static]
    lines += ["    params:", "      W:", "        values: [1]"]
    (root / "params.yaml").write_text("\n".join(lines) + "\n")
    return tmp_path


TWO_CLOCKS = [("clk_a", "clk_a", 5.0), ("clk_b", "clk_b", 3.0)]


def _by_name(result):
    return {c["name"]: c for c in result["clocks"]}


@needs_tools
def test_io_delay_is_issued_for_every_clock(tmp_path):
    """M1 / D5 / F4：两域各自的 I/O 路径都要在，不能只有第一个时钟那一域。

    `io2` 的每个域都**只有** input→reg 与 reg→output 两类路径。输入/输出延时
    若只绑第一个时钟，clk_b 那两类会被异步分组整片排除，该域就成了空域。
    """
    netlist = _synth("io2", tmp_path / "synth")
    root = _design_root(tmp_path, "io2", TWO_CLOCKS)
    result = run_sta("io2", netlist, LIBERTY,
                     out_dir=tmp_path / "sta", repo_root=root)

    clk_b = _by_name(result)["clk_b"]
    assert clk_b["slack_ns"] is not None, (
        "clk_b 域被判成「没有域内路径」—— 它明明有 db→reg 与 reg→qb。"
        "输入/输出延时只绑了第一个时钟，异步分组把这两类整片排除了，"
        "而 OpenSTA 一句警告都不会给。")
    assert _by_name(result)["clk_a"]["slack_ns"] is not None


@needs_tools
@pytest.mark.flow
def test_cross_domain_paths_are_excluded_by_default(tmp_path):
    """M2 / D1 / F2：默认互为异步；显式并成一组时跨域路径重新参与。

    两种约束下的 `slack_ns` 必须不同 —— 相同就说明分组根本没生效，
    而那正是「看起来生效但没有」的那一类。
    """
    netlist = _synth("two", tmp_path / "synth")

    async_root = _design_root(tmp_path / "async", "two", TWO_CLOCKS)
    async_result = run_sta("two", netlist, LIBERTY,
                           out_dir=tmp_path / "sta_async", repo_root=async_root)

    sync_root = _design_root(tmp_path / "sync", "two", TWO_CLOCKS,
                             groups=[["clk_a", "clk_b"]])
    sync_result = run_sta("two", netlist, LIBERTY,
                          out_dir=tmp_path / "sta_sync", repo_root=sync_root)

    assert async_result["slack_ns"] != sync_result["slack_ns"], (
        "把两个时钟并进同一组之后 slack 没变 —— 分组没有生效。"
        f"两次都是 {async_result['slack_ns']}")
    # 同步组把跨域路径算进来，它是更紧的那条
    assert sync_result["slack_ns"] < async_result["slack_ns"]


@needs_tools
def test_a_domain_without_intra_domain_paths_reports_absent_slack(tmp_path):
    """M3 / D4 / F3：空域的 slack/fmax 缺席，但该时钟仍出现在 clocks 里。

    填 0 会被读成「刚好卡住」，填周期会被读成「完全空闲」——「这个时钟被建立过」
    与「它没有域内路径」是两件都要记下来的事。
    """
    netlist = _synth("nopath", tmp_path / "synth")
    root = _design_root(tmp_path, "nopath", TWO_CLOCKS)
    result = run_sta("nopath", netlist, LIBERTY,
                     out_dir=tmp_path / "sta", repo_root=root)

    clk_b = _by_name(result)["clk_b"]
    assert clk_b["slack_ns"] is None, (
        f"clk_b 域一条域内路径都没有，slack 却报了 {clk_b['slack_ns']}")
    assert clk_b["fmax_mhz"] is None
    # 「它被建立过」这件事本身是事实，必须留着
    assert clk_b["name"] == "clk_b"
    assert clk_b["port"] == "clk_b"
    assert clk_b["period_ns"] == 3.0


@needs_tools
def test_a_clock_port_missing_from_the_netlist_is_an_error(tmp_path):
    """M4：端口找不到必须报错，不得退回虚拟时钟后照常出数。

    OpenSTA 自己只报一句 `Warning 366: port 'xxx' not found` 就建虚拟时钟 ——
    那条路上会产出一个完整的、看不出异常的 slack。
    """
    netlist = _synth("io2", tmp_path / "synth")
    root = _design_root(tmp_path, "io2",
                        [("clk_a", "clk_a", 5.0), ("clk_b", "clk_typo", 3.0)])
    with pytest.raises(RuntimeError) as exc:
        run_sta("io2", netlist, LIBERTY,
                out_dir=tmp_path / "sta", repo_root=root)
    assert "clk_typo" in str(exc.value), (
        f"报错没点名找不到的端口：{exc.value}")


@needs_tools
def test_clocks_with_a_command_line_period_get_the_cli_period_and_stay_synchronous(tmp_path):
    """内部#138（clock-period-cli D2）：两个时钟都写 `cli` 且同组时，都按 --period-ns 建钟，不发异步分组。"""
    netlist = _synth("two", tmp_path / "synth")
    root = _design_root(tmp_path, "two", [("clk_a", "clk_a", "cli"), ("clk_b", "clk_b", "cli")],
                        groups=[["clk_a", "clk_b"]])
    out_dir = tmp_path / "sta"
    run_sta("two", netlist, LIBERTY, period_ns=4.0, out_dir=out_dir, repo_root=root)
    tcl = (out_dir / "run_sta.tcl").read_text()
    assert "create_clock -name clk_a -period 4.0" in tcl, tcl
    assert "create_clock -name clk_b -period 4.0" in tcl, tcl
    assert "set_clock_groups" not in tcl, tcl


CFG_CLK = [("clk", "clk", 5.0)]


def _startpoints(out_dir):
    import re as _re
    return _re.findall(r"^Startpoint:\s+(\S+)", (out_dir / "checks.rpt").read_text(), _re.M)


@needs_tools
def test_a_static_port_declared_false_path_no_longer_starts_the_worst_path(tmp_path):
    """内部#154（sta-static-ports D2）：cfg -> o 原本是最坏路径；声明 false_path 后不再从 cfg 起。"""
    netlist = _synth("cfgpath", tmp_path / "synth")
    base = _design_root(tmp_path / "a", "cfgpath", CFG_CLK)
    run_sta("cfgpath", netlist, LIBERTY, out_dir=tmp_path / "a" / "sta", repo_root=base)
    assert any(sp.startswith("cfg") for sp in _startpoints(tmp_path / "a" / "sta")), "夹具失效：cfg 本该是最坏路径的起点"
    root = _design_root(tmp_path / "b", "cfgpath", CFG_CLK,
                        static=["{ports: [cfg*], kind: false_path, by: R.011}"])
    run_sta("cfgpath", netlist, LIBERTY, out_dir=tmp_path / "b" / "sta", repo_root=root)
    tcl = (tmp_path / "b" / "sta" / "run_sta.tcl").read_text()
    assert "set_false_path -from [get_ports {cfg*}]" in tcl, tcl
    assert not any(sp.startswith("cfg") for sp in _startpoints(tmp_path / "b" / "sta"))


@needs_tools
def test_a_multicycle_static_port_emits_setup_and_hold(tmp_path):
    netlist = _synth("cfgpath", tmp_path / "synth")
    root = _design_root(tmp_path, "cfgpath", CFG_CLK,
                        static=["{ports: [cfg*], kind: multicycle, cycles: 3, by: R.011}"])
    run_sta("cfgpath", netlist, LIBERTY, out_dir=tmp_path / "sta", repo_root=root)
    tcl = (tmp_path / "sta" / "run_sta.tcl").read_text()
    assert "set_multicycle_path -setup 3 -from [get_ports {cfg*}]" in tcl, tcl
    assert "set_multicycle_path -hold 2 -from [get_ports {cfg*}]" in tcl, tcl


@needs_tools
def test_a_static_port_pattern_matching_nothing_is_an_sta_error(tmp_path):
    netlist = _synth("cfgpath", tmp_path / "synth")
    root = _design_root(tmp_path, "cfgpath", CFG_CLK,
                        static=["{ports: [cgf*], kind: false_path, by: R.011}"])
    with pytest.raises(RuntimeError) as exc:
        run_sta("cfgpath", netlist, LIBERTY, out_dir=tmp_path / "sta", repo_root=root)
    assert "cgf*" in str(exc.value)


@needs_tools
def test_the_constraints_are_left_in_the_run_artifacts(tmp_path):
    """M5：本次所用的时钟与分组约束原文要留在 runs/<id>/sta/ 下。

    `experiment-trust` 要求跨域路径的处理方式**出现在产物里**，而不是只存在于
    代码的默认值中 —— 否则回头看一份旧的 STA 结果时无从判断它是怎么约束的。
    """
    netlist = _synth("two", tmp_path / "synth")
    root = _design_root(tmp_path, "two", TWO_CLOCKS)
    out_dir = tmp_path / "sta"
    run_sta("two", netlist, LIBERTY, out_dir=out_dir, repo_root=root)

    tcl = (out_dir / "run_sta.tcl").read_text()
    assert "create_clock -name clk_a" in tcl
    assert "create_clock -name clk_b" in tcl
    assert "set_clock_groups -asynchronous" in tcl, (
        "产物里看不出跨域路径是怎么处理的\n" + tcl)


@needs_tools
@pytest.mark.flow
def test_a_single_clock_design_emits_the_same_tcl_as_before(tmp_path):
    """M6 回归 / A1 的第一道判据：单时钟路径上发出的 tcl 与本变更前逐字相同。

    一条 `create_clock -name clk`、一次 `set_input_delay`、一次
    `set_output_delay`、**不发** `set_clock_groups`。这条守的是「本变更对既有
    92 条记录的测量口径零影响」——它的另一半判据是重跑后的逐字段配对。
    """
    from flow.synth.synth import run_synth
    params = {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 1, "CSEL_BLK_W": 4}   # 开源的单时钟设计（内部#305）
    synth = run_synth("ADDER32", params, LIBERTY, out_dir=tmp_path / "synth")
    out_dir = tmp_path / "sta"
    run_sta("ADDER32", synth["netlist_path"], LIBERTY, out_dir=out_dir)

    tcl = (out_dir / "run_sta.tcl").read_text()
    # 数的是**发出去的命令**，不是整份文件里的字符串出现次数。模板里的注释大量
    # 引用这些命令名（解释为什么这么约束），拿整份文件去 count 会把注释算进来 ——
    # 2026-09-15 实测栽过一次：给 min 侧加排除时在注释里写了
    # 「由 `set_input_delay 0` 决定」，`tcl.count(...)` 就从 1 变成 2，
    # 用例变红而被测行为一个字没变。
    cmds = "\n".join(ln for ln in tcl.splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#"))
    assert cmds.count("create_clock") == 1
    assert "create_clock -name clk -period 5.0 [get_ports clk]" in cmds
    assert "set_clock_groups" not in cmds, (
        "单时钟设计发出了 set_clock_groups —— 那会换掉既有 92 条的口径\n" + cmds)
    assert cmds.count("set_input_delay") == 1
    assert cmds.count("set_output_delay") == 1
    assert "set_input_delay 0 -clock clk [all_inputs -no_clocks]" in cmds
    assert "set_output_delay 0 -clock clk [all_outputs]" in cmds
    assert "-add_delay" not in cmds


@needs_tools
@pytest.mark.flow
def test_single_clock_result_still_carries_one_clock_entry(tmp_path):
    """单时钟设计的 `clocks` 有且只有一项，其 slack 等于顶层的 slack_ns。"""
    from flow.synth.synth import run_synth
    params = {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 1, "CSEL_BLK_W": 4}   # 开源的单时钟设计（内部#305）
    synth = run_synth("ADDER32", params, LIBERTY, out_dir=tmp_path / "synth")
    result = run_sta("ADDER32", synth["netlist_path"], LIBERTY,
                     out_dir=tmp_path / "sta")
    assert len(result["clocks"]) == 1
    entry = result["clocks"][0]
    assert entry["name"] == "clk"
    assert entry["port"] == "clk"
    assert entry["period_ns"] == result["clock_period_ns"]
    assert entry["slack_ns"] == result["slack_ns"]
