"""`critical_path_stages` 必须只反映最坏那一条路径。

为什么值得有这个测试：`report_checks -path_delay max` **对每个 path group 各报
一条**最坏路径。本仓库三个设计的寄存器都是 `always @(posedge clk or negedge
rst_n)`，于是 OpenSTA 会额外打印一条 `asynchronous` 组的 recovery 路径。
旧的 `_count_path_stages` 逐行扫整份报告，把两块的 cell 行加在一起，级数虚高 2。

错法正是本仓库最怕的那种：`critical_path_delay_ns` 取自 `worst_slack`，是对的；
`critical_path_stages` 多算了两级，也看不出异常。一个错的数字和一个对的数字
并排放在同一条记录里。

夹具是**真实的 OpenSTA 报告文本**（OpenSTA 3.1.0 + 自带的 nangate45_typ.lib，
2026-09-13 生成），提交进仓库：本机没有 `~/pdk` 合并 liberty，跑不了真实设计；
而手写一份"我以为 OpenSTA 会这么打"的报告等于把被测对象换成了我的假设。

`checks_two_groups.rpt` 里 `asynchronous` 块排在**前面**（未加 -sort_by_slack），
这是有意的：它证明选块是按 slack 选的，不是"取第一块"。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.sta.run_sta import (
    _assert_stages_from_worst_path,
    _count_path_stages,
    _worst_path_slack,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TWO_GROUPS = FIXTURES / "checks_two_groups.rpt"   # asynchronous(2.05) 在前, clk(1.61) 在后
ONE_GROUP = FIXTURES / "checks_one_group.rpt"     # 只有 clk(1.62)

# 生成夹具那次 OpenSTA 自报的 worst_slack（6 位），报告里印的是 2 位。
WS_TWO = 1.6066299856370443
WS_ONE = 1.622322544444727


def test_extra_path_groups_do_not_inflate_the_count():
    """两个 path group 的真实报告：级数是最坏块自身的 11，不是两块之和 13。"""
    assert _count_path_stages(TWO_GROUPS) == 11


def test_single_group_report_is_unchanged():
    """只有一块时，新旧口径一致 —— 修复不该动到无异步复位的设计。"""
    assert _count_path_stages(ONE_GROUP) == 11


def test_worst_block_is_chosen_by_slack_not_by_position():
    """夹具里 asynchronous(2.05) 排在 clk(1.61) 前面；选中的必须是后者。"""
    assert _worst_path_slack(TWO_GROUPS) == pytest.approx(1.61, abs=1e-9)


def test_same_path_assertion_passes_for_the_real_pair():
    """报告里的最坏块与该次 STA 的 worst_slack 对得上时，不报错。"""
    _assert_stages_from_worst_path(TWO_GROUPS, WS_TWO)
    _assert_stages_from_worst_path(ONE_GROUP, WS_ONE)


def test_same_path_assertion_rejects_a_mismatch():
    """级数与延时不同源时必须报错，而不是记下一个看着正常的数。"""
    with pytest.raises(RuntimeError) as excinfo:
        _assert_stages_from_worst_path(TWO_GROUPS, WS_TWO + 0.5)
    msg = str(excinfo.value)
    assert "worst_slack" in msg
    assert str(TWO_GROUPS) in msg or TWO_GROUPS.name in msg


def test_report_with_no_path_block_is_an_error(tmp_path):
    """报告里一个路径块都没有时必须报错 —— 那是「没测到」，不是「零级」。

    这是本仓库「无法测得的指标必须缺席」的同一条：静默返回 0 会让一条
    看着正常的记录进到 jsonl 里。
    """
    empty = tmp_path / "checks.rpt"
    empty.write_text("No paths found.\n")

    with pytest.raises(RuntimeError):
        _count_path_stages(empty)
    with pytest.raises(RuntimeError):
        _worst_path_slack(empty)


# --- 活动率反标必须被证明真的发生了 -------------------------------------------
#
# 为什么值得有这个测试：`read_vcd` 缺 `-scope` 时 VCD 的层次名与网表引脚名对不上，
# **一个引脚都没标上，而 OpenSTA 不报错**，`report_power` 照常给出数字 ——
# 那个数字是默认活动率下的静态估算，只是网表与周期的函数。2026-09-14 实测：
# runs/ 下 633 个 sta.log 里 631 个是 `Annotated 0 pin activities`，
# 也就是说在此之前每一条记录的 dynamic_power_w 都不携带活动率信息
# （docs/data-credibility.md 的 D-1，本仓 内部#17）。
#
# 判据必须是**标注数本身**：「read_vcd 执行了」与「功耗字段非空」这两个更顺手的
# 观察量，在缺口存在时同样为真 —— 那正是它藏了八天的原因。

from flow.sta.run_sta import _assert_activity_annotated  # noqa: E402

ANNOTATED_LOG = """\
OpenSTA 3.1.0 c821ad1ad0 Copyright (c) 2026, Parallax Software, Inc.
Warning 1212: asap7.lib line 13197, timing group from output port.
Annotated 158 pin activities.
"""

UNANNOTATED_LOG = """\
OpenSTA 3.1.0 c821ad1ad0 Copyright (c) 2026, Parallax Software, Inc.
Warning 1212: asap7.lib line 13197, timing group from output port.
Annotated 0 pin activities.
"""

NO_ANNOTATION_LINE_LOG = """\
OpenSTA 3.1.0 c821ad1ad0 Copyright (c) 2026, Parallax Software, Inc.
Warning 1212: asap7.lib line 13197, timing group from output port.
"""


def test_zero_annotated_pins_is_an_error():
    """标注 0 个引脚必须报错 —— 这是「没测到」，不是「功耗小」。"""
    with pytest.raises(RuntimeError) as excinfo:
        _assert_activity_annotated(UNANNOTATED_LOG)
    msg = str(excinfo.value)
    # 错误信息必须指出标注数为 0 这一事实本身，否则排查会走向「功耗为什么偏小」
    assert "0" in msg
    assert "scope" in msg.lower()


def test_annotated_pins_pass():
    """标注数 > 0 时放行。"""
    _assert_activity_annotated(ANNOTATED_LOG)


def test_missing_annotation_line_is_an_error():
    """连那一行都没有时同样是「没测到」—— 不能当作「大概标上了」。

    read_vcd 没执行、或 OpenSTA 换了输出措辞，都会走到这里。两种情形下
    「反标真的发生了」都无法被证明，而这条要求的判据正是"能不能被证明"。
    """
    with pytest.raises(RuntimeError):
        _assert_activity_annotated(NO_ANNOTATION_LINE_LOG)


# --- 时钟端口名在流程里只有一个来源 -------------------------------------------
#
# 为什么值得有这个测试：`flow-parameterization` 写着「流程代码 MUST NOT 内嵌任何
# 具体设计的信号命名假设」，而 STA 的 tcl 模板一直写死 `[get_ports clk]` ——
# 仿真侧读的是设计声明的名字，STA 侧读的是这个字面量。设计改了时钟端口名时，
# 只有仿真侧跟着改，STA 侧静默走进「端口找不到」的回退（见下一组测试）。

from flow.sta.run_sta import _clock_command  # noqa: E402


def _one(port, period=5.0, name="clk"):
    return [{"name": name, "port": port, "period_ns": period}]


def test_clock_command_uses_the_declared_port_name():
    """声明什么名字就绑什么端口，不出现 `clk` 字面量当作端口名。"""
    cmd = _clock_command(_one("my_clock"), [["clk"]], 5.0)
    assert "[get_ports my_clock]" in cmd
    assert "-period 5.0" in cmd


def test_clock_command_for_the_conventional_name_is_unchanged():
    """四个单时钟设计都声明 `clock_signal: clk`，那条 `create_clock` 必须逐字不变。

    2026-09-15 起这个函数还会在它前面加一行端口存在性守卫（`get_ports -quiet`
    为空就 `exit 1`），所以不再能拿整个返回值做等值比较 —— 守卫不建立、也不修改
    任何约束，改变的只是「端口找不到」从静默回退变成当场报错。
    断言收窄到**约束那一行**，那才是决定测量口径的东西。
    """
    cmd = _clock_command(_one("clk"), [["clk"]], 5.0)
    lines = cmd.splitlines()
    assert lines[-1] == "create_clock -name clk -period 5.0 [get_ports clk]"
    assert "set_clock_groups" not in cmd, "单时钟不该发分组 —— 那会换掉既有记录的口径"
    assert any("get_ports -quiet clk" in ln for ln in lines[:-1]), (
        "端口存在性守卫不在 —— 端口找不到时 OpenSTA 只报一句 Warning 366 "
        "就建虚拟时钟照常出数")


# --- 无时钟设计：显式虚拟时钟 + 路径必须是真实的输入到输出 ---------------------
#
# 为什么值得有这个测试：设计没有时钟端口时，`create_clock … [get_ports clk]` 让
# OpenSTA 报一句 `Warning 366: port 'clk' not found`，然后**自己建一个虚拟时钟**，
# 组合路径照常挂在它下面出数。数字看着对（实测与显式虚拟时钟逐位相同），但它来自
# 一条没人选过的回退路径 —— 而在虚拟时钟下，「没有路径」与「路径很短」在记录里
# 长得一模一样。
#
# checks_clockless.rpt 是**真实的** OpenSTA 报告（OpenSTA 3.1.0 + ASAP7 RVT/TT，
# 2026-10-26 由开源构件 CBB_LZD〔DAT_W=16、SCHEME=0〕的网表在显式虚拟时钟下生成）。

from flow.sta.run_sta import _assert_io_to_io_path  # noqa: E402

CLOCKLESS = FIXTURES / "checks_clockless.rpt"   # i_dat[4] -> o_dec[7]


def test_virtual_clock_command_binds_no_port():
    """声明没有时钟时，那一行不带 `[get_ports …]`。

    第一个参数是**声明出来的时钟列表**（2026-09-15 起支持多时钟），空列表就是
    「这个设计声明自己没有时钟」—— 与旧的 `port=None` 同义。
    """
    cmd = _clock_command([], [], 5.0)
    assert cmd == "create_clock -name clk -period 5.0"
    assert "get_ports" not in cmd


def test_io_to_io_path_is_accepted():
    """真实的输入端口 → 输出端口路径放行。"""
    _assert_io_to_io_path(CLOCKLESS)


def test_register_path_is_rejected_for_a_clockless_design():
    """最坏路径不是 I/O 到 I/O 时必须报错。

    无时钟设计里出现寄存器起点，意味着被测的根本不是它声明的那个电路
    （网表链错、top 写错）—— 那时延时值仍然是一个看着正常的小数。
    """
    with pytest.raises(RuntimeError) as excinfo:
        _assert_io_to_io_path(ONE_GROUP)
    assert "输入端口" in str(excinfo.value)


def test_report_with_no_path_block_is_rejected_too():
    """一个路径块都没有时同样报错 —— 「没测到」不是「路径很短」。"""
    with pytest.raises(RuntimeError):
        _assert_io_to_io_path(FIXTURES / "does_not_exist.rpt")


# --- 零触发器就必须断言，不论设计声不声明时钟 --------------------------------
#
# 为什么值得有这个测试：`experiment-trust` 的「无触发器的实现必须证明其时序结果
# 来自真实路径」写的是「当某个参数组合下的网表**不含任何触发器**时」。实现一度
# 只覆盖了「设计声明自己没有时钟」那一支 —— 而**带真实 `clk` 端口、这次组合却
# 综合出零触发器**是更常见的那一半：`ADDER32 PIPE_STAGES=0` 就是，当前代 90 条
# 记录里有 31 条属于它，一条都没被断言查过（本仓 内部#32）。
#
# 那一支不触发任何工具警告：`create_clock … [get_ports clk]` 绑定成功，
# 端口确实存在。于是"路径为空"与"路径很短"照旧长得一模一样。

import os                                                  # noqa: E402
import shutil                                              # noqa: E402

from flow.sta.run_sta import (                             # noqa: E402
    _assert_timing_came_from_a_real_path,
)

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

needs_tools = pytest.mark.skipif(
    shutil.which("yosys") is None or shutil.which("sta") is None
    or not LIBERTY.is_file(),
    reason="需要 yosys / sta 在 PATH 上与合并 liberty 在本机")


def test_zero_registers_is_asserted_even_with_a_real_clock_port():
    """有真实 clk 端口、但网表零触发器 —— 路径不是 I/O 到 I/O 时必须报错。

    `ONE_GROUP` 是一条 REG→REG 路径的真实报告。零触发器的网表不可能产出这种
    路径，所以它出现就说明被测的不是这次综合出来的那份网表。
    """
    with pytest.raises(RuntimeError) as excinfo:
        _assert_timing_came_from_a_real_path("clk", 0, ONE_GROUP)
    assert "输入端口" in str(excinfo.value)


def test_registers_present_means_no_io_to_io_assertion():
    """有触发器时不断言 —— REG→REG 本来就是它的正常形态。

    扩大触发范围不能把正常形态判成错误。这一条是 M3（regression）。
    """
    _assert_timing_came_from_a_real_path("clk", 8, ONE_GROUP)


def test_clockless_branch_still_fires_regardless_of_register_count():
    """声明无时钟那一支照旧触发，与触发器数无关。

    两支各防一个失效模式：这一支防的是「`create_clock … [get_ports clk]` 在端口
    找不到之后退回隐式虚拟时钟」，那与网表里有几个触发器毫无关系。所以条件是
    `or` 而不是任何一支单独成立。这一条是 M4（regression）。
    """
    with pytest.raises(RuntimeError):
        _assert_timing_came_from_a_real_path(None, 8, ONE_GROUP)


def test_io_to_io_report_passes_both_branches():
    """真实的 I/O→I/O 报告在两支下都放行。"""
    _assert_timing_came_from_a_real_path(None, 0, CLOCKLESS)
    _assert_timing_came_from_a_real_path("clk", 0, CLOCKLESS)


@needs_tools
@pytest.mark.flow
def test_register_count_comes_from_the_sta_run(tmp_path):
    """`run_sta` 返回这次 STA 自己数出来的寄存器数。

    判据取 OpenSTA 而不取 yosys 的 `stats.json`：它与产出本次 `slack_ns` 的是
    同一次运行、同一份网表、同一份库、同一个 `link_design` 之后的视图。
    """
    from flow.sta.run_sta import run_sta
    from flow.synth.synth import run_synth

    # ADDER32 8 位、PIPE_STAGES=2：段间进位与低位和综合后剩 8 个；CBB_LZD 纯组合 = 0
    # （2026-10-14 实测，内部#305；10-01 至 10-14 间用的是一个闭源 FIFO 构件）
    cases = (("ADDER32", {"DAT_W": 8, "SCHEME": 0, "PIPE_STAGES": 2, "CSEL_BLK_W": 4}, 8),
             ("CBB_LZD", {"DAT_W": 16, "MSB_EN": 0, "SCHEME": 0}, 0))
    for design, params, expected in cases:
        synth = run_synth(design, params, LIBERTY, out_dir=tmp_path / f"synth{design}")
        sta = run_sta(design, synth["netlist_path"], LIBERTY,
                      out_dir=tmp_path / f"sta{design}")
        assert sta["register_count"] == expected, (
            f"{design} {params} 的网表报了 {sta['register_count']} 个寄存器，期望 {expected}")


# --- 活动率反标的范围进记录（flow-batch-2026-10 的 1.5，内部#65）--------------------------
#
# 只有端口被反标时，内部节点的活动率是 OpenSTA 按概率传播出来的：看不到毛刺与相关性，
# 结构之间的动态功耗排名不能当结论用。以前记录里看不出是哪种口径。

PORT_NETLIST = """\
module T(clk, i_a, i_b, o_y);
  input clk;
  input [7:0] i_a;
  input [3:0] i_b;
  output [8:0] o_y;
  wire [8:0] o_y;
endmodule
"""


@pytest.mark.parametrize("pins, scope", [(22, "ports"), (5, "ports"), (23, "internal")])
def test_annotation_scope_compares_pins_with_port_bits(pins, scope):
    from flow.sta.run_sta import _activity_annotation

    got = _activity_annotation(f"Annotated {pins} pin activities.\n", PORT_NETLIST, "T")
    assert got == {"pins": pins, "port_bits": 1 + 8 + 4 + 9, "scope": scope}


@pytest.mark.flow
def test_a_real_sta_run_reports_its_annotation_scope(tmp_path):
    from flow.sim.run_sim import run_sim
    from flow.sta.run_sta import run_sta
    from flow.synth.synth import run_synth

    params = {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 1, "CSEL_BLK_W": 4}
    synth = run_synth("ADDER32", params, LIBERTY, out_dir=tmp_path / "synth")
    sim = run_sim("ADDER32", params, out_dir=tmp_path / "sim")
    sta = run_sta("ADDER32", synth["netlist_path"], LIBERTY, vcd=sim["vcd_path"],
                  out_dir=tmp_path / "sta")
    log = Path(sta["log_path"]).read_text()
    ann = sta["activity_annotation"]
    assert f"Annotated {ann['pins']} pin activities" in log, (ann, log[-400:])
    # clk rst_n i_cin o_cout + i_a[32] + i_b[32] + o_sum[32]
    assert ann["port_bits"] == 4 + 32 + 32 + 32, ann
    assert ann["scope"] == "ports", ann
