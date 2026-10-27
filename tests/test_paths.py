"""设计根怎么声明它的**被测顶层**，以及流程怎么按顶层名找到它。

为什么值得有这个测试：在本变更之前，「设计根名 == 顶层模块名」是一条**只存在于
代码里**的约束 —— `hdl_toplevel=design`、综合脚本的 `-top {design}`、`link_design {design}`
三处各自拿设计名当顶层名。那条约束把「一个 IP 的两个方向」逼成两个设计根，
两个根之间只能靠逐字节相同的文件拷贝保持一致，而拷贝的失效方式是**漂移**。

改成显式声明之后，新的失效方式变了，而且都很安静：
  - 两个根声明同一个顶层名 -> 解析静默择一，跑的是哪一份取决于目录遍历顺序；
  - 声明了一个 `rtl/` 下不存在的顶层 -> 要么综合当场失败，要么（更糟）
    yosys 挑了个别的模块当顶层照常出数；
  - `params.yaml` 没写 `tops:` 而代码回退到目录名 -> 那条回退路径**平时不被使用**，
    它的失效只会在有人真的漏写时暴露，而那正是最需要报错的时刻。
本文件把这三条各钉一个用例。

夹具用**临时设计根**构造前两条（真实仓库里造不出重名与缺失顶层），
第三条与「既有五个顶层的解析结果不变」用真实仓库。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import (DesignRootError, ParamError,  # noqa: E402
                        clock_port, clock_signal, ideal_drive_ports,
                        param_combos, resolve_design_root)


# --- 既有顶层：按名字解析出的配置必须一项不差 ----------------------------------
#
# 黄金值取自真实仓库的 params.yaml（开源部分：演示设计 ADDER32 与开源 cbb 构件；2026-10-14 起
# 不再用闭源构件，内部#305）。正在开发的 IP 会改名、改参数，不拿来当黄金值：「顶层名与根名不同」
# 由夹具根 tests/fixtures/designs/ip_root（顶层 IP_TOP）代替（内部#110）。clock_signal 是 `<顶层>.clk` —— 它是 VCD
# 里的作用域前缀，VCD 的顶层作用域就是 hdl_toplevel，所以它必须跟**顶层**走，不能跟根走。
BEFORE = {
    # CSEL_BLK_W 标了 sweep: false，扫参组合 4 × 6 × 3 = 72。
    "ADDER32": dict(n_combos=72, clock_signal="ADDER32.clk",
                    ideal=["rst_n"], clock_port="clk"),
    "CBB_BIN2ONEHOT": dict(n_combos=5, clock_signal=None, ideal=[], clock_port=None),
    # CBB_LZD 的 MSB_EN 标了 sweep: false（2026-10-03），扫参组合 5 × 3 = 15。
    "CBB_LZD": dict(n_combos=15, clock_signal=None, ideal=[], clock_port=None),
    "IP_TOP": dict(n_combos=4, clock_signal="IP_TOP.clk",
                   ideal=["rst_n"], clock_port="clk"),
}


@pytest.mark.parametrize("top", sorted(BEFORE))
def test_the_existing_tops_resolve_exactly_as_before(top, fixture_designs):
    want = BEFORE[top]
    assert len(list(param_combos(top))) == want["n_combos"]
    assert clock_signal(top) == want["clock_signal"]
    assert ideal_drive_ports(top) == want["ideal"]
    assert clock_port(top) == want["clock_port"]
    assert resolve_design_root(top).is_dir()


def test_a_tops_clock_signal_is_scoped_by_the_top_not_the_root(fixture_designs):
    """VCD 的顶层作用域是 hdl_toplevel，所以前缀必须是顶层名。

    `IP_TOP` 住在夹具根 `ip_root` 里：前缀必须是 `IP_TOP.`，不是 `ip_root.`。
    找不到时 vcd_stats 会报错 —— 那是好的；真正的风险是找到了**别人的**时钟。
    """
    assert clock_signal("IP_TOP").startswith("IP_TOP.")


# --- 临时设计根：造真实仓库里造不出的输入 --------------------------------------

MINIMAL = "params:\n      W:\n        values: [4]\n"


def _root(tmp_path, root_name, tops, make_rtl=True):
    """搭一个声明了 `tops` 的临时设计根。tops 是顶层名的列表。"""
    root = tmp_path / "designs" / root_name
    (root / "rtl").mkdir(parents=True)
    body = [f"design_root: {root_name}", "tops:"]
    for t in tops:
        body += [f"  {t}:", "    sim:", "      clock_signal: clk",
                 "    sta:", "      ideal_drive_ports: [rst_n]",
                 f"    {MINIMAL}"]
        if make_rtl:
            (root / "rtl" / f"{t}.v").write_text(
                f"module {t} #(parameter W = 4) (input wire [W-1:0] a,\n"
                f"                               output wire [W-1:0] y);\n"
                f"  assign y = a;\nendmodule\n")
    (root / "params.yaml").write_text("\n".join(body) + "\n")
    return root


def test_a_top_name_declared_in_two_roots_is_an_error_naming_both(tmp_path):
    """静默择一意味着「跑的是哪一份」取决于目录遍历顺序 —— 而记录里看不出来。

    这与既有的「设计根必须按名字唯一解析」同口径：那条管的是根目录重名，
    这条管的是顶层重名，而多顶层之后后者才是真正会发生的那个。
    """
    _root(tmp_path, "root_a", ["shared_top"])
    _root(tmp_path, "root_b", ["shared_top"])
    with pytest.raises(DesignRootError) as e:
        resolve_design_root("shared_top", repo_root=tmp_path)
    msg = str(e.value)
    assert "root_a" in msg and "root_b" in msg, (
        f"报错必须同时指出两处声明，实际是：{msg}")


def test_a_declared_top_missing_from_rtl_is_an_error(tmp_path):
    """声明了但 rtl/ 下没有，最坏的结局不是报错而是 yosys 挑了别的模块照常出数。

    ⚠️ 只断言「抛了异常」是**假绿**：改动前它也抛，但抛的是「找不到设计根
    designs/ghost_top」—— 那是按目录名解析失败，与本条要防的是两回事。
    所以断言必须点到 `rtl`：报错得说清楚是**声明的顶层在 RTL 目录下缺失**，
    而不是「没有这么个设计」。
    """
    _root(tmp_path, "root_c", ["ghost_top"], make_rtl=False)
    with pytest.raises((ParamError, DesignRootError)) as e:
        resolve_design_root("ghost_top", repo_root=tmp_path)
    msg = str(e.value)
    assert "ghost_top" in msg
    assert "rtl" in msg, (
        f"报错该点明顶层在 RTL 目录下缺失，而不是「找不到设计根」，实际是：{msg}")
    assert "root_c" in msg, (
        f"报错该指出是哪个设计根声明了它，实际是：{msg}")


def test_a_params_yaml_without_tops_is_an_error_not_a_fallback(tmp_path):
    """不给「省略 tops: 时以根目录名为顶层」留回退。

    留了回退的话，两种形态就有两条解析路径，而只有一条会被日常使用 ——
    另一条的失效是静默的。本仓已经有过同形的教训（两个 SKIP 开关口径不同、
    输出长得一模一样）。
    """
    root = tmp_path / "designs" / "root_d"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "root_d.v").write_text("module root_d(); endmodule\n")
    (root / "params.yaml").write_text("design: root_d\nparams:\n  W:\n    values: [4]\n")
    with pytest.raises(ParamError) as e:
        resolve_design_root("root_d", repo_root=tmp_path)
    assert "tops" in str(e.value), (
        f"报错该说清楚缺的是 tops:，实际是：{e.value}")


def test_two_tops_in_one_root_keep_their_own_sim_and_sta(tmp_path):
    """同一个根下两个顶层的 sim/sta 不得串味。

    这是**静默失效**的一类：串了味之后 STA 照常出数，只是那个数在测别的东西
    （本仓真实情形里一个组合子块是 ideal=[]/clock=null，
    而它要并入的那个流水设计是 [rst_n]/clk —— 完全相反）。
    """
    root = tmp_path / "designs" / "root_e"
    (root / "rtl").mkdir(parents=True)
    for t in ("seq_top", "comb_top"):
        (root / "rtl" / f"{t}.v").write_text(f"module {t}(); endmodule\n")
    (root / "params.yaml").write_text(
        "design_root: root_e\n"
        "tops:\n"
        "  seq_top:\n"
        "    sim:\n      clock_signal: clk\n"
        "    sta:\n      ideal_drive_ports: [rst_n]\n"
        "    params:\n      W:\n        values: [4]\n"
        "  comb_top:\n"
        "    sim:\n      clock_signal: null\n"
        "    sta:\n      ideal_drive_ports: []\n"
        "    params:\n      W:\n        values: [8, 16]\n")
    assert clock_signal("seq_top", repo_root=tmp_path) == "seq_top.clk"
    assert clock_signal("comb_top", repo_root=tmp_path) is None
    assert ideal_drive_ports("seq_top", repo_root=tmp_path) == ["rst_n"]
    assert ideal_drive_ports("comb_top", repo_root=tmp_path) == []
    assert len(list(param_combos("seq_top", repo_root=tmp_path))) == 1
    assert len(list(param_combos("comb_top", repo_root=tmp_path))) == 2
    assert resolve_design_root("seq_top", repo_root=tmp_path) == \
           resolve_design_root("comb_top", repo_root=tmp_path)


# --- 被测顶层声明对 cbb 构件的依赖（add-design-cbb-deps）---------------------------
#
# `designs/` 只放由构件组装出来的 IP，而流程以前只读设计根自己的 rtl/。依赖写在
# `tops:<顶层>:deps:`，按**顶层名**解析、只许指向 cbb/、可传递。这一组用例钉住
# 解析规则本身；读入集合（yosys 求闭包）在 tests/test_synth_sources.py。

def _dep_root(repo, tree, root_name, top, deps=None, extra_files=()):
    """在 `repo/<tree>/<root_name>` 搭一个只有一个顶层的设计根，可带 `deps`。"""
    root = repo / tree / root_name
    (root / "rtl").mkdir(parents=True)
    body = [f"design_root: {root_name}", "tops:", f"  {top}:",
            "    sim:", "      clock_signal: clk", f"    {MINIMAL}"]
    if deps is not None:
        body.append(f"    deps: [{', '.join(deps)}]")
    (root / "params.yaml").write_text("\n".join(body) + "\n")
    (root / "rtl" / f"{top.lower()}.v").write_text(f"module {top}; endmodule\n")
    for f in extra_files:
        (root / "rtl" / f).write_text("module X_" + f.split(".")[0].upper()
                                      + "; endmodule\n")
    return root


def test_deps_are_resolved_transitively_into_candidate_files(tmp_path):
    from flow.paths import rtl_candidates

    ip = _dep_root(tmp_path, "designs", "ip", "IP", deps=["CBB_A"])
    a = _dep_root(tmp_path, "cbb", "cbb_a", "CBB_A", deps=["CBB_B"],
                  extra_files=["cbb_a_helper.v"])
    b = _dep_root(tmp_path, "cbb", "cbb_b", "CBB_B")
    got = rtl_candidates("IP", repo_root=tmp_path)
    want = sorted([ip / "rtl/ip.v", a / "rtl/cbb_a.v", a / "rtl/cbb_a_helper.v",
                   b / "rtl/cbb_b.v"])
    assert got == want


def test_a_top_without_deps_reads_only_its_own_root(tmp_path):
    from flow.paths import rtl_candidates

    ip = _dep_root(tmp_path, "designs", "ip", "IP", extra_files=["other.v"])
    _dep_root(tmp_path, "cbb", "cbb_a", "CBB_A")
    assert rtl_candidates("IP", repo_root=tmp_path) == sorted(
        [ip / "rtl/ip.v", ip / "rtl/other.v"])


def test_deps_naming_no_declared_top_is_an_error(tmp_path):
    from flow.paths import rtl_candidates

    _dep_root(tmp_path, "designs", "ip", "IP", deps=["CBB_TYPO"])
    _dep_root(tmp_path, "cbb", "cbb_a", "CBB_A")
    with pytest.raises(DesignRootError, match="CBB_TYPO"):
        rtl_candidates("IP", repo_root=tmp_path)


def test_deps_may_not_point_into_designs(tmp_path):
    from flow.paths import rtl_candidates

    _dep_root(tmp_path, "designs", "ip", "IP", deps=["OTHER_IP"])
    _dep_root(tmp_path, "designs", "other", "OTHER_IP")
    with pytest.raises(DesignRootError, match="OTHER_IP.*cbb/"):
        rtl_candidates("IP", repo_root=tmp_path)


def test_deps_cycle_is_an_error(tmp_path):
    from flow.paths import rtl_candidates

    _dep_root(tmp_path, "designs", "ip", "IP", deps=["CBB_A"])
    _dep_root(tmp_path, "cbb", "cbb_a", "CBB_A", deps=["CBB_B"])
    _dep_root(tmp_path, "cbb", "cbb_b", "CBB_B", deps=["CBB_A"])
    with pytest.raises(DesignRootError, match="成环.*CBB_A.*CBB_B.*CBB_A"):
        rtl_candidates("IP", repo_root=tmp_path)


# --- 规格先行的设计根（flow-batch-2026-10 的 1.1，内部#74）-------------------------------
#
# 「先有规格、后有电路」：既没有 params.yaml 也没有 rtl/ 的根只放规格，解析跳过它。
# 有 rtl/ 却没有 params.yaml 是漏写了声明，照旧报错；空目录也报错。

def test_a_spec_only_root_is_skipped_by_resolution(tmp_path):
    from flow.paths import rtl_candidates

    ip = _dep_root(tmp_path, "designs", "ip", "IP")
    spec_only = tmp_path / "designs" / "later"
    spec_only.mkdir()
    (spec_only / "spec.LATER.md").write_text("# LATER\n")
    assert resolve_design_root("IP", repo_root=tmp_path) == ip
    assert rtl_candidates("IP", repo_root=tmp_path) == [ip / "rtl/ip.v"]


def test_rtl_without_params_yaml_is_still_an_error(tmp_path):
    _dep_root(tmp_path, "designs", "ip", "IP")
    bad = tmp_path / "designs" / "forgot" / "rtl"
    bad.mkdir(parents=True)
    (bad / "forgot.v").write_text("module FORGOT; endmodule\n")
    with pytest.raises(ParamError, match="缺少 params.yaml"):
        resolve_design_root("IP", repo_root=tmp_path)


def test_an_empty_root_is_an_error(tmp_path):
    _dep_root(tmp_path, "designs", "ip", "IP")
    (tmp_path / "designs" / "empty").mkdir()
    with pytest.raises(DesignRootError, match="既没有.*也没有规格"):
        resolve_design_root("IP", repo_root=tmp_path)


def test_a_root_with_only_an_lrs_is_spec_only(tmp_path):
    """lrs-lld-docs：designs/ 的规格先行根可以只有 LRS。"""
    from flow.paths import _spec_only
    root = tmp_path / "designs" / "later"
    root.mkdir(parents=True)
    (root / "lrs.LATER.md").write_text("# LATER\n")
    assert _spec_only(root) is True


# --- 设计树只有 designs/ 与 cbb/（2026-10-15 搬回 3.1，内部#305）--------------------------
#
# 开源与闭源的设计根同放这两棵树，开源与否只看开源白名单（用户 2026-10-15）。2026-10 曾短暂
# 另设 ip_designs/、ip_cbb/，已收回：那两个目录不是设计树，里面声明的顶层解析不到。

def test_a_top_only_in_ip_designs_does_not_resolve(tmp_path):
    _dep_root(tmp_path, "ip_designs", "secret", "SECRET_TOP")
    with pytest.raises(DesignRootError):
        resolve_design_root("SECRET_TOP", repo_root=tmp_path)
