"""设计对**时钟**的声明：一个或多个，以及跨域该怎么处理。

为什么值得有这个测试：时钟声明是「一处声明、两处消费」—— 仿真侧按它在 VCD 里数
周期，STA 侧按它 `create_clock`。两处各自写死一个名字会让「设计改了时钟端口名」
只在其中一处生效，而 STA 那一侧的回退尤其危险：工具找不到端口时只报一句警告就
建一个虚拟时钟，照常出数。

多时钟把这件事又放大一层：**跨时钟域路径怎么处理**同样必须来自声明，不能来自
工具的默认行为。实测（OpenSTA 3.1.0，2026-09-15）不设分组时 `worst_slack` 取自
一条跨异步域的路径（0.9233），设了之后是域内的（4.9233）—— 两个都是 MET、
都不报警告、差 5.3 倍，而前者不说明电路的任何性质。

夹具是**临时设计根**，不是本仓的真实设计：这里要构造「声明了两个时钟」
「分组里写了不存在的时钟名」这类输入，真实设计里没有。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import (ParamError, clock_groups, clock_port,  # noqa: E402
                        clocks, static_ports)

MINIMAL_PARAMS = "params:\n  W:\n    values: [4]\n"


def _design(tmp_path, sim_block="", sta_block=""):
    """搭一个临时设计根，返回 (被测顶层名, repo_root)。

    `sim_block` / `sta_block` 由调用方按**顶层作用域**的缩进传进来（见 _indent）：
    设计根自 2026-09-20 起按 `design_root:` + `tops:` 声明被测顶层，
    `sim` / `sta` / `params` 三段都挂在顶层之下而不是根之下
    （`openspec/specs/repo-layout/spec.md` 的「设计根可以声明多个被测顶层」）。
    rtl/ 下要有同名 module —— 解析会校验它，声明了却没有是会报错的。
    """
    top = "fixture_design"
    root = tmp_path / "designs" / top
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / f"{top}.v").write_text(f"module {top}(); endmodule\n")
    body = _indent(f"{sim_block}{sta_block}{MINIMAL_PARAMS}")
    (root / "params.yaml").write_text(
        f"design_root: {top}\ntops:\n  {top}:\n{body}")
    return top, tmp_path


def _indent(block, n=4):
    """把顶层作用域下的一段 YAML 整体缩进 n 格，空行保持空。"""
    pad = " " * n
    return "".join((pad + ln if ln.strip() else ln) + "\n"
                   for ln in block.rstrip("\n").split("\n"))


# --- 单时钟：既有形式必须一字不变 ---------------------------------------------

def test_a_design_without_any_declaration_falls_back_to_one_clock(tmp_path):
    """没声明 = 回退到约定端口 `clk`，一个时钟，名字也叫 `clk`。"""
    design, root = _design(tmp_path)
    got = clocks(design, repo_root=root)
    assert len(got) == 1, got
    assert got[0]["name"] == "clk"
    assert got[0]["port"] == "clk"


def test_sim_clock_signal_still_drives_the_single_clock(tmp_path):
    """只声明 `sim.clock_signal` 时，端口名来自它，时钟仍然命名为 `clk`。

    时钟**名字**保持 `clk` 是有意的：既有 92 条记录就是在这个名字下测出来的，
    换名字会让 `sta.clocks[0].name` 与历史不可比，而那正是本变更要避免的。
    """
    design, root = _design(tmp_path, sim_block="sim:\n  clock_signal: aclk\n")
    got = clocks(design, repo_root=root)
    assert len(got) == 1
    assert got[0]["port"] == "aclk"
    assert got[0]["name"] == "clk"


def test_a_combinational_design_declares_no_clock(tmp_path):
    """`clock_signal: null` 是显式声明「没有时钟」—— 返回空列表，不是回退。"""
    design, root = _design(tmp_path, sim_block="sim:\n  clock_signal: null\n")
    assert clocks(design, repo_root=root) == []


# --- 多时钟 -------------------------------------------------------------------

TWO_CLOCKS = """\
sta:
  clocks:
    - name: clk_a
      port: clk_a
      period_ns: 5.0
    - name: clk_b
      port: clk_b
      period_ns: 3.0
"""


def test_multiple_clocks_are_all_returned(tmp_path):
    """声明了几个就返回几个，名字/端口/周期都原样带出来。"""
    design, root = _design(tmp_path, sta_block=TWO_CLOCKS)
    got = clocks(design, repo_root=root)
    assert [c["name"] for c in got] == ["clk_a", "clk_b"]
    assert [c["port"] for c in got] == ["clk_a", "clk_b"]
    assert [c["period_ns"] for c in got] == [5.0, 3.0]


def test_an_incomplete_clock_declaration_is_refused(tmp_path):
    """缺 name/port/period_ns 任何一项都要当场报错。

    补一个默认值等于让「声明写漏了」这件事静默通过，而漏掉的那一项决定了
    STA 建出什么约束 —— 这正是本仓最怕的那类失效。
    """
    for missing, block in (
        ("period_ns", "sta:\n  clocks:\n    - name: c\n      port: c\n"),
        ("port", "sta:\n  clocks:\n    - name: c\n      period_ns: 2.0\n"),
        ("name", "sta:\n  clocks:\n    - port: c\n      period_ns: 2.0\n"),
    ):
        design, root = _design(tmp_path / missing, sta_block=block)
        with pytest.raises(ParamError) as exc:
            clocks(design, repo_root=root)
        assert missing in str(exc.value), f"报错没说清缺的是 {missing}：{exc.value}"


def test_a_clock_period_can_come_from_the_command_line(tmp_path):
    """内部#138（clock-period-cli D1）：`period_ns: cli` 显式声明周期取 `--period-ns`，解析成 None。"""
    block = ("sta:\n  clocks:\n    - name: core_clk\n      port: core_clk\n      period_ns: cli\n"
             "    - name: cg_clk\n      port: cg_clk\n      period_ns: cli\n"
             "  clock_groups:\n    - [core_clk, cg_clk]\n")
    design, root = _design(tmp_path, sta_block=block)
    assert [c["period_ns"] for c in clocks(design, repo_root=root)] == [None, None]
    assert clock_groups(design, repo_root=root) == [["core_clk", "cg_clk"]]


def test_an_unknown_period_word_is_refused(tmp_path):
    """内部#138（clock-period-cli D1）：只认数字或 `cli`，别的字符串报错并说明可写什么。"""
    block = "sta:\n  clocks:\n    - name: c\n      port: c\n      period_ns: same\n"
    design, root = _design(tmp_path, sta_block=block)
    with pytest.raises(ParamError) as exc:
        clocks(design, repo_root=root)
    assert "cli" in str(exc.value) and "same" in str(exc.value)


def test_static_ports_are_parsed(tmp_path):
    """内部#154（sta-static-ports D1）：ports 可以是一个或多个，kind 与 cycles、by 原样带出。"""
    block = ("sta:\n  static_ports:\n    - {ports: cfg_*, kind: false_path, by: R.901}\n"
             "    - {ports: [mode_sel, mode_en], kind: multicycle, cycles: 2, by: R.902}\n")
    design, root = _design(tmp_path, sta_block=block)
    assert static_ports(design, repo_root=root) == [
        {"ports": ["cfg_*"], "kind": "false_path", "cycles": None, "by": "R.901"},
        {"ports": ["mode_sel", "mode_en"], "kind": "multicycle", "cycles": 2, "by": "R.902"}]


@pytest.mark.parametrize("item, named", [
    ("{ports: x, kind: false_path}", "by"),
    ("{ports: x, kind: ignore, by: R.901}", "kind"),
    ("{ports: x, kind: multicycle, by: R.901}", "cycles"),
    ("{ports: x, kind: multicycle, cycles: 1, by: R.901}", "cycles"),
    ("{ports: x, kind: false_path, cycles: 2, by: R.901}", "cycles"),
    ("{ports: x, kind: false_path, by: 801}", "by"),
])
def test_a_wrong_static_port_entry_is_refused(tmp_path, item, named):
    """内部#154（sta-static-ports D1）：缺键、kind 不认识、cycles 不对、by 格式不对都当场报错。"""
    design, root = _design(tmp_path, sta_block=f"sta:\n  static_ports:\n    - {item}\n")
    with pytest.raises(ParamError) as exc:
        static_ports(design, repo_root=root)
    assert named in str(exc.value)


def test_no_static_ports_is_an_empty_list(tmp_path):
    design, root = _design(tmp_path)
    assert static_ports(design, repo_root=root) == []


def test_sta_clocks_wins_over_sim_clock_signal(tmp_path):
    """两种声明同时存在时，以 `sta.clocks` 为准 —— 但仿真侧仍要拿得到端口名。"""
    design, root = _design(tmp_path,
                           sim_block="sim:\n  clock_signal: clk_a\n",
                           sta_block=TWO_CLOCKS)
    got = clocks(design, repo_root=root)
    assert len(got) == 2
    # clock_port 是仿真侧与「第一个时钟」的兼容入口
    assert clock_port(design, repo_root=root) == "clk_a"


# --- 分组 ---------------------------------------------------------------------

def test_undeclared_groups_default_to_each_clock_asynchronous(tmp_path):
    """没声明分组 = 每个时钟自成一组、互为异步。

    默认取保守的那一侧：多时钟设计里跨域路径需要同步器是常态，当同步路径分析
    会产出一批假违例，而假违例会逼人加豁免。
    """
    design, root = _design(tmp_path, sta_block=TWO_CLOCKS)
    assert clock_groups(design, repo_root=root) == [["clk_a"], ["clk_b"]]


def test_declared_groups_are_returned_as_declared(tmp_path):
    """声明了就原样返回 —— 同组内按同步处理。"""
    design, root = _design(
        tmp_path,
        sta_block=TWO_CLOCKS + "  clock_groups:\n    - [clk_a, clk_b]\n")
    assert clock_groups(design, repo_root=root) == [["clk_a", "clk_b"]]


def test_a_group_naming_an_undeclared_clock_is_refused(tmp_path):
    """分组里写了一个没声明过的时钟名，必须报错。

    静默忽略它的后果是：使用者以为自己把两个域并成了同步组，实际那一组只有一个
    时钟，跨域路径照样被排除 —— 一个**看起来生效但没有**的约束。
    """
    design, root = _design(
        tmp_path,
        sta_block=TWO_CLOCKS + "  clock_groups:\n    - [clk_a, clk_typo]\n")
    with pytest.raises(ParamError) as exc:
        clock_groups(design, repo_root=root)
    assert "clk_typo" in str(exc.value)


def test_a_clock_left_out_of_every_group_is_refused(tmp_path):
    """声明了分组就要分全 —— 漏掉一个时钟必须报错，不得默默给它补一组。

    补一组是「合理的默认」，但它让「漏写」与「有意把它单独分出来」不可区分，
    而两者对跨域路径的处理完全相同、对读记录的人含义完全不同。
    """
    design, root = _design(
        tmp_path,
        sta_block=TWO_CLOCKS + "  clock_groups:\n    - [clk_a]\n")
    with pytest.raises(ParamError) as exc:
        clock_groups(design, repo_root=root)
    assert "clk_b" in str(exc.value)


def test_a_combinational_design_has_no_groups(tmp_path):
    """没有时钟就没有分组。"""
    design, root = _design(tmp_path, sim_block="sim:\n  clock_signal: null\n")
    assert clock_groups(design, repo_root=root) == []


# --- 既有设计不得被动到（M3 回归；开源的 ADDER32 与 cbb 构件，内部#305；开发中的 IP 用夹具 IP_TOP 代替，内部#110）----

@pytest.mark.parametrize("design, expected_port", [
    ("ADDER32", "clk"),
    ("IP_TOP", "clk"),
    ("CBB_LZD", None),
])
def test_existing_designs_keep_their_clock_port(design, expected_port, fixture_designs):
    """`clock_port` 由各自 params.yaml 的 `sim.clock_signal` 决定，单时钟路径不变。"""
    assert clock_port(design) == expected_port


@pytest.mark.parametrize("design", ["ADDER32", "IP_TOP"])
def test_existing_single_clock_designs_yield_exactly_one_clock(design, fixture_designs):
    """现有的单时钟设计走的仍是单时钟那条路：一个时钟、名字是 `clk`。"""
    got = clocks(design)
    assert len(got) == 1, got
    assert got[0]["name"] == "clk"
    assert got[0]["port"] == "clk"


def test_the_combinational_design_still_yields_no_clock():
    """`CBB_LZD` 声明了 `clock_signal: null`。"""
    assert clocks("CBB_LZD") == []
