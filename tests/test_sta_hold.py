"""域内保持时间余量：min 侧报出来的数必须只关于电路。

为什么值得有这个测试：打开 min 分析是本仓最容易「跑通了但数字不成立」的一步。

实测（OpenSTA 3.1.0 + ASAP7，2026-09-15，当前代 `0c80b2af` 的三份真实网表）：

    设计              触发器   port 起点 min 路径   违例    reg→reg   违例
    ADDER32              8            19            8         2       0
    地址流水设计       145           216          147        72       0
    压缩流水设计      2433          3585         2945      1243       0

**全部违例的起点都是主输入端口，reg→reg 一条都没有。** 更说明问题的是
`worst_slack -min` 在这三个设计上**逐位相同**（-0.021162700663102926）——
8 个触发器和 2433 个触发器得出同一个数，因为最差 min 路径永远是
`rst_n → removal`，而 `rst_n` 按 `sta.ideal_drive_ports` 建模为理想驱动
（这个流程不综合复位树），到达时刻恒为 0，于是那个数是 DFF 单元的库 removal 时间。

所以照搬 `worst_slack -min` 进记录，放进去的是一个与设计无关的常数。这里守三件事：

1. 报出来的值等于**按定义算出来的** reg→reg 最差 —— 判据不是「等于某个常数」，
   而是「等于逐路径枚举分类的结果」，那样连「只排除了输入侧、忘了输出侧」也能抓到
   （reg→输出端口的 min 结果由 `set_output_delay 0` 决定，同样是假设不是电路）。
2. 没有时序单元时**缺席**。实测那时 OpenSTA 返回 `1.0000000433293989e+39` ——
   一个语法合法的浮点数，照直写进记录就成了「余量无穷大」。
3. 排除写在 tcl 产物里，不是藏在代码默认值中：回头看一份旧的 STA 结果，
   要能判断它排除了什么。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.sta.run_sta import run_sta  # noqa: E402
from flow.synth.synth import run_synth  # noqa: E402

LIBERTY = Path.home() / "pdk" / "asap7_merged" / "asap7sc7p5t_RVT_TT.lib"

needs_tools = pytest.mark.skipif(
    shutil.which("sta") is None or shutil.which("yosys") is None
    or not LIBERTY.exists(),
    reason="需要 sta / yosys / 合并 liberty（source ~/tools/env.sh）")

# max 侧的回归锚点：`(slack_ns, critical_path_delay_ns, register_count)`。
# 它守的是**流程改动不移动 max 侧** —— min 侧加排除、加字段，这三个数都不该动。
#
# 这些数是**测出来的**，所以按 `guardrail-scope` 的「判据确实需要一个测量出来的
# 锚点」，三样必须写在这里：
#
#   测得时间     ADDER32 两行：2026-09-15（内部#24 落地时），至今一个字未改
#                组合地址子块 一行：2026-09-17，第二次重打
#   被测对象     ADDER32 两行：合并提交 `6e1de49`
#                组合地址子块：`cd69f61`（删 `i_en`，本仓 内部#48）
#   重打条件     **只有这三个设计的 RTL 变了才重打**，重打时在这里记下新的提交。
#                RTL 没变而它红了，那就是流程侧的缺陷 —— 那时要查的是流程，
#                不是这张表。
#
# 重打过两次，两次都只动了 组合地址子块 那一行：
#
#   2026-09-16  分支改了 那个子块的 RTL。
#               `(4.933764, 0.066236, 0)` → `(4.936093, 0.063907, 0)`
#   2026-09-17  删掉 `i_en`（内部#48）。`(4.936093, 0.063907, 0)` → 下面这组。
#               这一次的幅度大得多：`i_en` 在时四个输出各要与它相与共 43 位，
#               删掉之后其中两个输出是纯连线，网表从 49 个单元
#               降到 11 个。max 侧的两个数因此都动了，而且动的**不是同一条路径**
#               —— 旧的关键路径起点就是 `i_en` 自己（`docs/data-credibility.md`
#               的 D-17）。
#
# 两次 `ADDER32` 的两行都一个字未改 —— 它们的 RTL 分支都没动。这正是这张表
# 该有的分辨力：**它分得清「RTL 变了」与「流程侧出了缺陷」**，两次都分对了。
#
# 2026-09-20（内部#45 收根 + 内部#50 改取源口径）**复测过，三行一位未动**，所以这一次
# 没有重打。这不是「没顾上」，是结论 —— 两个顶层的读入集合在这两步里恰好都没变：
#
#   ADDER32                 并集 = `rtl/` 下全部 12 份 = 改口径之前读的那 12 份。
#                           六种进位结构合起来把每一份都例化到了，一份都没多没少。
#   组合地址子块  并集 = 1 份（它一处例化都没有）。它在 2.1 之前独占一个
#                           设计根，那个根的 `rtl/` 里也只有它自己 —— 所以这一行
#                           测的编译单元与 2026-09-17 那次**是同一个**。
#
# 换句话说：`tests/test_sta_boundary.py` 的 `BROADCAST_CP_NS`（当时叫另一个名字） 动了 −4.4%，这张表
# 一位没动，两者不矛盾 —— 动的是 当时那个压缩流水设计，它的目录里确实躺进了三份解压侧
# 的文件。同一次流程改动，读入集合变了的顶层数字就变，没变的就不变。这张表这次
# 分辨的是**第三类**东西：「流程改了，但没改到我头上」。
#
# 下面这组与 `results/experiments.jsonl` 里 `git_commit = cd69f61`、`DW=64`
# 那条记录逐位相同 —— 锚点与记录是同一次测量的两种落法，不是抄来的常数。
# 2026-10-01 重打（trim-design-roots）：上面那三行的被测对象 ADDER32 / 组合地址子块
# 随设计根删除，锚点换成保留的设计与夹具，在提交 `671f745` 之后的工作区上实测。它们是回归绊线：
# 换 liberty、换 ABC 脚本或驱动单元、改这几个设计的 RTL 时重打并注明来源，不是放宽成范围。
# 2026-10-05 重打那个 FIFO 构件（flop-map-small，内部#176）：dfflibmap 排除 DFFHQx4 后触发器改为 DFFHQNx1，
# 关键路径 0.261184 → 0.262105 ns，寄存器数不变。CBB_LZD 是纯组合，不动。
# 2026-10-14 重打（kaiwu 开源拆分，内部#305）：有域内路径的被测对象从闭源的 FIFO 构件换成恢复的
# ADDER32 PIPE_STAGES=2（DAT_W=32、RIPPLE），在 94227b4d 之后的工作区上用本文件的 _build 连测两次，
# 逐位相同；hold 余量 0.046633 与 docs/data-credibility.md 里早年 adder32 那一行一致。
BEFORE = {
    "ADDER32": (4.566746, 0.433254, 32),
    "CBB_LZD": (4.752198, 0.247802, 0),
}

# 真实设计夹具（开源部分，内部#305）：有域内路径的用 ADDER32 PIPE_STAGES=2，纯组合的用 CBB_LZD，
# 「有触发器但没有域内路径」用夹具 SHAPE_REG1（`tests/fixtures/designs/shapes/`）。
# 2026-10-01 至 10-14 间有域内路径的那档用的是闭源构件，开源拆分时换回 ADDER32。
PIPE = {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 2, "CSEL_BLK_W": 4}
COMB = {"DAT_W": 32, "MSB_EN": 0, "SCHEME": 0}

# 逐路径枚举并按「起点/终点是不是主端口」分类，取 reg→reg 的最差 ——
# `-endpoint_path_count` 必须给：默认每个终点只返回最差的一条，而终点最差的 min 路径
# 常常来自输入端口，被过滤掉之后 reg→reg 一条都不剩（2026-10-01 换到一个 FIFO 构件时暴露；
# ADDER32 PIPE_STAGES=2 恰好每个终点最差的就是 reg→reg，于是没看出来 —— 所以这条参照对它仍要照算）。
# 这是 hold_slack_ns 的**定义**。测试拿它当参照，而不是拿一个抄来的常数：
# 常数只能证明"和上次一样"，定义能证明"排除的正是该排除的那两类"。
CLASSIFY = """
set worst ""
foreach pth [find_timing_paths -path_delay min -group_path_count 1000000 -endpoint_path_count 1000000] {
  set sp [get_property [get_property $pth startpoint] full_name]
  set ep [get_property [get_property $pth endpoint] full_name]
  if {[llength [get_ports -quiet $sp]] > 0} { continue }
  if {[llength [get_ports -quiet $ep]] > 0} { continue }
  set s [get_property $pth slack]
  if {$worst eq "" || $s < $worst} { set worst $s }
}
puts "REG2REG_WORST $worst"
exit
"""


def _reg2reg_worst(sta_dir):
    """把 run_sta 产出的 tcl 去掉两条排除、换成逐路径分类，重跑一次。

    复用那份 tcl 是有意的：约束环境（时钟、I/O 延时、驱动单元、负载）必须与被测
    的那一次**完全相同**，否则比的是两个不同的时序环境。这里唯一被替换掉的就是
    「怎么得到那个数」。
    """
    tcl = (sta_dir / "run_sta.tcl").read_text()
    body = tcl.split("set ws [worst_slack -max]")[0]
    body = "\n".join(ln for ln in body.splitlines()
                     if not ln.startswith("set_false_path -hold"))
    probe = sta_dir / "reg2reg.tcl"
    probe.write_text(body + CLASSIFY)
    proc = subprocess.run(["sta", "-exit", str(probe)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"^REG2REG_WORST (.*)$", proc.stdout, re.M)
    assert m, proc.stdout
    return None if not m.group(1).strip() else float(m.group(1))


def _build(design, params, tmp_path):
    synth = run_synth(design, params, LIBERTY, out_dir=tmp_path / "synth")
    result = run_sta(design, synth["netlist_path"], LIBERTY,
                     out_dir=tmp_path / "sta")
    return result, tmp_path / "sta"


@needs_tools
@pytest.mark.flow
def test_the_hold_margin_equals_the_reg_to_reg_worst(tmp_path):
    """M1：报出来的值等于按定义枚举出来的 reg→reg 最差。

    这条判据能抓到「只排除了输入侧」：那时剩下的是 min(reg→reg, reg→输出端口)，
    而后者由 `set_output_delay 0` 决定 —— 在本仓现有三个设计上它恰好都更松，
    所以只发 `-from` **当下也能得到对的数**。那是巧合，不是正确。

    取 ADDER32 PIPE_STAGES=2：段间寄存器把进位与低位和交给下一段，都是域内路径。
    """
    result, sta_dir = _build("ADDER32", PIPE, tmp_path)
    reference = _reg2reg_worst(sta_dir)
    assert reference is not None, "参照本身算不出来，夹具选错了"
    assert result["hold_slack_ns"] == pytest.approx(reference, abs=1e-9), (
        f"hold_slack_ns={result['hold_slack_ns']} 与逐路径枚举的 reg→reg 最差 "
        f"{reference} 不符 —— 排除的范围不对")


@needs_tools
@pytest.mark.parametrize("design, params", [
    ("CBB_LZD", COMB),
    ("SHAPE_COMB", {"DAT_W": 8}),
])
@pytest.mark.flow
def test_a_netlist_without_sequential_cells_reports_no_hold_margin(
        design, params, tmp_path, fixture_designs):
    """M2：一个时序单元都没有时缺席。

    实测那时 `worst_slack -min` 返回 `1.0000000433293989e+39`。它是合法 JSON 数字，
    落进记录就是「余量无穷大」，而真相是「没有可测的路径」——
    与 `experiment-trust` 的「无法测得的指标必须缺席」同一条。
    """
    result, _ = _build(design, params, tmp_path)
    assert result["register_count"] == 0, "夹具选错了，这个组合有触发器"
    assert result["hold_slack_ns"] is None, (
        f"零时序单元却报了 hold 余量 {result['hold_slack_ns']!r}"
        "（1e39 是 OpenSTA 的无路径哨兵值，不是余量）")


@needs_tools
@pytest.mark.flow
def test_registers_without_an_intra_domain_path_still_report_nothing(tmp_path, fixture_designs):
    """M3：有触发器、但一条域内路径都没有时，同样缺席。

    夹具 SHAPE_REG1 是 **8 个触发器、0 条域内路径**（早先是 `ADDER32 PIPE_STAGES=1` 的 5 个）：它们全部只被
    `输入端口→reg` 与 `reg→输出端口` 两类路径触及。`worst_slack -min` 照样返回
    `1.0000000433293989e+39`。

    这条守的是**判断缺席的依据**：按「有没有时序单元」判，当前代 92 条里会有
    **29 条**（PIPE_STAGES=1 的那一批）把哨兵值写进记录，而且不报错。
    """
    result, _ = _build("SHAPE_REG1", {"DAT_W": 8}, tmp_path)
    assert result["register_count"] == 8, "夹具变了，这一档本该有 8 个触发器"
    assert result["hold_slack_ns"] is None, (
        f"有 8 个触发器就报了 hold 余量 {result['hold_slack_ns']!r} —— "
        "缺席的依据取成了「有没有触发器」，而不是「有没有域内路径」")


@needs_tools
@pytest.mark.flow
def test_the_exclusion_is_visible_in_the_run_artifacts(tmp_path):
    """M4：排除必须写在产物里，两条都要。

    只发 `-from` 会把 reg→输出端口那一类留下，而它的结果由 `set_output_delay 0`
    决定 —— 同样是约束里的假设，不是电路。
    """
    _, sta_dir = _build("ADDER32", PIPE, tmp_path)
    tcl = (sta_dir / "run_sta.tcl").read_text()
    assert "set_false_path -hold -from" in tcl, (
        "产物里看不出输入侧的 min 路径被排除了\n" + tcl)
    assert "set_false_path -hold -to" in tcl, (
        "只排除了输入侧 —— reg→输出端口那一类还在，它的结果由 "
        "set_output_delay 0 决定\n" + tcl)


@needs_tools
@pytest.mark.parametrize("design, params", [("ADDER32", PIPE), ("CBB_LZD", COMB)])
@pytest.mark.flow
def test_the_max_side_numbers_do_not_move(design, params, tmp_path):
    """M5 回归：加了 min 侧的排除之后，max 侧一位不动。

    锚点是本变更**之前**在同一组输入上实测到的三个数。这条是整个变更的边界：
    它加的是一个新字段，不是换一次测量口径 —— 换口径就得让既有 92 条重新可比，
    而那是另一回事。
    """
    result, _ = _build(design, params, tmp_path)
    slack, cpd, regs = BEFORE[design]
    assert result["slack_ns"] == slack
    assert result["critical_path_delay_ns"] == cpd
    assert result["register_count"] == regs
