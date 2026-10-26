"""综合能被加压，以及在一组延时目标上搜 fmax。

为什么值得有这个测试：`abc -D` 有一个**静默死区** —— 目标给得太紧时 ABC 会产出与
不给 `-D` 逐字节相同的网表，不报错也不警告（2026-09-13 实测，`SKLANSKY W=64` 在
`-D ≤ 85` 全部如此）。而「整组目标都失效」与「搜过了，base 恰好最好」在结果上
完全一样。所以这里断言的是**网表真的变了**，而不是"函数返回了一个值"。
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.synth.search import DELAY_TARGET_RATIOS, pick_best, search_fmax
from flow.synth.synth import run_synth

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

needs_yosys = pytest.mark.skipif(
    shutil.which("yosys") is None or not LIBERTY.is_file(),
    reason="需要 yosys 在 PATH 上与合并 liberty 在本机")

needs_flow = pytest.mark.skipif(
    any(shutil.which(t) is None for t in ("yosys", "sta", "iverilog"))
    or not LIBERTY.is_file(),
    reason="需要 yosys / sta / iverilog 在 PATH 上与合并 liberty 在本机")

# 真实设计夹具：CBB_LZD 32 位 TOOL 结构（trim-design-roots 的 D1）。早先用 ADDER32 BRENT_KUNG
# 32 位（2026-09-13 细扫里加压收益最大的组合），随设计根于 2026-10-01 删除。2026-10-01 实测
# 这一组 d0 ≈ 297 ps，1.5 × d0 那一档改变了网表，其余档落在死区 —— 加压没有赢过不加压。
FMAX_DESIGN = "CBB_LZD"
BK32 = {"DAT_W": 32, "MSB_EN": 0, "SCHEME": 2}


def _abc_line(script_text):
    for line in script_text.splitlines():
        if line.startswith("abc "):
            return line
    raise AssertionError(f"生成的 synth.ys 里没有 abc 行：\n{script_text}")


# --- M1 ---------------------------------------------------------------------
@needs_yosys
@pytest.mark.flow
def test_no_delay_target_keeps_the_abc_line_unchanged(tmp_path):
    """不给目标时，abc 行必须与本变更之前逐字相同 —— 否则既有记录的口径被动了。"""
    out = tmp_path / "base"
    run_synth(FMAX_DESIGN, dict(BK32), LIBERTY, out_dir=out)
    # 字面冻结，不从模板反推：从模板反推等于拿被测代码验证它自己。
    assert _abc_line((out / "synth.ys").read_text()) == (
        f"abc -liberty {LIBERTY} -constr {REPO_ROOT / 'flow/synth/abc.constr'}")


@needs_yosys
def test_delay_target_reaches_abc(tmp_path):
    out = tmp_path / "d90"
    run_synth(FMAX_DESIGN, dict(BK32), LIBERTY, out_dir=out, delay_target_ps=90)
    assert _abc_line((out / "synth.ys").read_text()) == (
        f"abc -liberty {LIBERTY} -constr {REPO_ROOT / 'flow/synth/abc.constr'} -D 90")


@needs_yosys
@pytest.mark.flow
def test_delay_target_actually_changes_the_netlist(tmp_path):
    """加压必须改变网表本身。

    只断言"命令行里有 -D"是不够的：死区里 ABC 收下这个选项、照常退出 0、
    产出的却是同一份网表。这一条断言的是产物。
    """
    # 450 ps ≈ 1.5 × d0：这个设计上死区之外的那一档（2026-10-01 实测）
    base = run_synth(FMAX_DESIGN, dict(BK32), LIBERTY, out_dir=tmp_path / "base")
    tight = run_synth(FMAX_DESIGN, dict(BK32), LIBERTY, out_dir=tmp_path / "d450",
                      delay_target_ps=450)
    base_bytes = Path(base["netlist_path"]).read_bytes()
    tight_bytes = Path(tight["netlist_path"]).read_bytes()
    assert tight_bytes != base_bytes, (
        "给了 -D 450 但网表与不给 -D 时逐字节相同 —— ABC 的延时目标在这个设计上"
        "落进了静默死区，或者 -D 根本没传进去")


# --- M1（任务 2.1）-----------------------------------------------------------
def _candidate(target, delay, area):
    return {"delay_target_ps": target,
            "synth": {"area_um2": area},
            "sta": {"critical_path_delay_ns": delay}}


def test_best_is_the_smallest_delay():
    best = pick_best([_candidate(None, 0.30, 25.0),
                      _candidate(300, 0.29, 24.0),
                      _candidate(90, 0.28, 23.0)])
    assert best["delay_target_ps"] == 90


def test_delay_ties_are_broken_by_area():
    """平手真的会发生：BK32 在 D=300 与 D=80 延时同为 0.284901，面积差 0.4%。"""
    best = pick_best([_candidate(300, 0.284901, 23.69250),
                      _candidate(80, 0.284901, 23.77998)])
    assert best["delay_target_ps"] == 300


def test_full_ties_are_broken_towards_no_target():
    """延时与面积都相同时取不加压 —— 结果不能依赖遍历顺序。"""
    tied = [_candidate(90, 0.28, 23.0), _candidate(None, 0.28, 23.0)]
    assert pick_best(tied)["delay_target_ps"] is None
    assert pick_best(list(reversed(tied)))["delay_target_ps"] is None


@needs_flow
@pytest.mark.flow
def test_search_runs_every_rung_and_keeps_the_fastest(tmp_path):
    """真跑一次：每一档都跑过，胜出的是候选里最快的那一档，记录的延时来自它。

    早先这一条还断言「胜出的是某个加压档，且比不加压快」—— 那是 ADDER32 BRENT_KUNG 32 位
    恰好成立的事实，不是契约（guardrail-scope「护栏的断言必须是契约」）：换到 CBB_LZD 上
    加压赢不了不加压，而缺陷一个也没有。
    """
    result = search_fmax(FMAX_DESIGN, dict(BK32), LIBERTY, out_dir=tmp_path)
    assert result["sta"]["fmax_method"] == "search:abc-D"

    by_target = {c["delay_target_ps"]: c for c in result["candidates"]}
    assert len(by_target) == 1 + len(DELAY_TARGET_RATIOS), "每一档都要真的跑过"
    fastest = min(c["critical_path_delay_ns"] for c in by_target.values())
    won = by_target[result["delay_target_ps"]]["critical_path_delay_ns"]
    assert won == fastest, "胜出的不是候选里最快的那一档"
    assert result["sta"]["critical_path_delay_ns"] == won, (
        "记录里的延时必须来自胜出的那一档，不是来自不加压的那一次")

    # 目标是从这个设计自己的 d0 推出来的，不是一组写死的绝对值
    d0_ps = round(by_target[None]["critical_path_delay_ns"] * 1000)
    assert set(by_target) - {None} == {round(r * d0_ps) for r in DELAY_TARGET_RATIOS}


@needs_flow
@pytest.mark.flow
def test_a_design_an_order_of_magnitude_slower_still_searches(tmp_path, fixture_designs):
    """慢一个量级的设计上搜索照样跑得完。

    早先用一个地址流水设计（绝对阶梯整组失效的那个，2026-10-01 删除）；现在用夹具
    `SLOW_CHAIN`（256 级串行链，`tests/fixtures/designs/slow_chain/`）。

    这个用例存在的理由：慢一个量级的设计上，搜索必须**跑得完并给出结论**，
    而不是因为目标够不着而整组空转 —— 那正是老的绝对阶梯在这个设计上的失效方式。

    ⚠️ 这里**不断言哪一档胜出**。原先有一句 `assert delay_target_ps is None`
    （「这个设计的 base 最快」），2026-09-16 合并那个设计的功能分支
    之后它红了：div15 重构把 d0 从约 1381 ps 降到 1169.9 ps，`target=351` 以
    1162.8 ps 险胜 base。那句断言编码的是**当时恰好为真的事实**，不是本用例要守的
    契约 —— RTL 在允许的范围内变了它就会红，而缺陷一个也没有。同一个反模式
    在 `test_run_experiment.py::test_the_schema_only_grows` 上发作过一次，
    契约写在 `openspec/specs/guardrail-scope/spec.md` 的「护栏的断言必须是契约，
    不得是当下恰好为真的事实」。
    """
    result = search_fmax("SLOW_CHAIN", {"DAT_W": 256}, LIBERTY, out_dir=tmp_path)

    # 搜索**跑完了并给出了结论** —— 这才是本用例要守的
    assert result["sta"]["fmax_method"] == "search:abc-D"
    by_target = {c["delay_target_ps"]: c for c in result["candidates"]}
    assert None in by_target, "base 那一次综合必须在候选里"
    assert len(by_target) == len(DELAY_TARGET_RATIOS) + 1, (
        f"阶梯有 {len(DELAY_TARGET_RATIOS)} 档加 base，候选却只有 "
        f"{len(by_target)} 个 —— 有档整个空转了")
    for target, cand in by_target.items():
        assert cand["critical_path_delay_ns"] > 0, (
            f"target={target} 这一档没量出关键路径")

    # 选这个夹具的理由：它慢一个量级
    d0_ps = round(by_target[None]["critical_path_delay_ns"] * 1000)
    assert d0_ps > 1000, "取这个组合就是为了它慢一个量级"
    # 老的绝对阶梯最松的一档是 300 ps，对这个设计仍然紧了 3 倍以上
    assert min(t for t in by_target if t is not None) > 300


@needs_flow
@pytest.mark.flow
def test_a_ladder_that_changes_nothing_is_recorded_as_ineffective(tmp_path):
    """搜索必须能证明自己搜索过 —— 证明不了时由结果自己说明，不冒充搜过。

    死区是静默的，而"整组目标都失效"与"搜过了，base 恰好最好"在结果上完全一样。
    `ratios=()` 是这件事的退化形态：一档加压都没有，等于什么都没搜。2026-10-03 之前
    这里报错、不写记录；浅组合（d0 只有几十皮秒）因此一条记录都写不出（内部#85），
    改为取不加压那一档，`search_effective = False`、`fmax_method = "analytic"`。
    """
    r = search_fmax(FMAX_DESIGN, dict(BK32), LIBERTY, out_dir=tmp_path, ratios=())
    assert r["search_effective"] is False
    assert r["delay_target_ps"] is None
    assert r["sta"]["fmax_method"] == "analytic", "没搜成就不能记成 search:abc-D"
    assert len(r["candidates"]) == 1


@needs_flow
@pytest.mark.flow
def test_an_effective_ladder_says_so(tmp_path):
    r = search_fmax(FMAX_DESIGN, dict(BK32), LIBERTY, out_dir=tmp_path)
    assert r["search_effective"] is True
    assert r["sta"]["fmax_method"] == "search:abc-D"


@needs_flow
@pytest.mark.flow
def test_record_says_which_rung_won(tmp_path, monkeypatch):
    """端到端一条记录：两个新字段都在，且不碰真的 experiments.jsonl。"""
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    # **显式绕过 provenance 守卫。** 本用例写的是 tmp 目录下的日志，不是数据集，
    # 而它必然在开发中的脏工作区里跑 —— 守卫拦住它是对的（红线 3 管的是数据集
    # 里的记录）。绕过写在这里而不是让守卫自己放水：守卫一旦有"日志不是数据集
    # 就不查"这类隐式例外，就多了一条没人看得见的逃生口，而这个仓库防的正是
    # 静默的例外。see tests/test_run_experiment.py
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")
    record = rx.run_experiment(
        "ADDER32", {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 1, "CSEL_BLK_W": 4},
        LIBERTY)

    assert record["sta"]["fmax_method"] == "search:abc-D"
    won = record["synth"]["delay_target_ps"]
    # 记的是绝对皮秒（要复现这次综合就得把它原样交给 abc -D），不是比例
    assert won is None or won == round(won), f"{won} 不是整数皮秒"
    assert log.read_text().count("\n") == 1


@needs_flow
@pytest.mark.flow
def test_plain_sta_still_reports_analytic(tmp_path):
    """不经搜索地单独跑一次 STA，`fmax_method` 仍是 `"analytic"`。

    既有的 470 条记录都带这个取值，按 `experiment-record` 的定义它们是**准确**的 ——
    加了搜索不是去回填它们，是给新的取得方式一个新取值。
    """
    from flow.sta.run_sta import run_sta

    synth_result = run_synth(FMAX_DESIGN, dict(BK32), LIBERTY,
                             out_dir=tmp_path / "synth")
    sta_result = run_sta(FMAX_DESIGN, synth_result["netlist_path"], LIBERTY,
                         out_dir=tmp_path / "sta")
    assert sta_result["fmax_method"] == "analytic"


# --- 比例集必须在被测设计的 d0 量级上真的"活"着 -------------------------------
#
# 为什么值得有这个测试：不加压等于「延时目标 0，能多快多快」，所以任何**紧于**
# d0 的目标都够不着，ABC 产出同一份网表。`docs/data-credibility.md` 的 D-7 与
# search.py 的 docstring 曾把死区推广成「一个固定比例，0.2–0.25 × d0」——
# 那是在 6 个 d0 ∈ [180, 1400] ps 的组合上标定的。2026-09-14 在
# 一个组合地址子块（d0 = 126 ps）上实测：死区一直延伸到 1.0 × d0，
# 有响应的区间在 d0 **上方**（1.5 × d0 产出另一份网表：面积 −3.3%、延时 +31%）。
#
# 所以比例集里必须有一个**宽松于 d0** 的档，否则浅设计会整组落进死区，
# 护栏（正确地）拦住它，而那个设计一条记录也写不成。

def test_ratio_set_contains_a_target_looser_than_d0():
    """比例集里必须至少有一个 > 1 的档。

    这不是风格：所有 ≤ 1 的档在"不加压已经跑到最快"的设计上都够不着，
    整组失效后护栏会把一次诚实的"搜索无效"报成失败而无路可走。
    """
    assert any(r > 1.0 for r in DELAY_TARGET_RATIOS), (
        "比例集里没有宽松于 d0 的档：d0 很小的设计会整组落进 ABC 的死区，"
        "护栏拦住之后那个设计一条记录都写不成（见 D-7 的范围收窄）")


def test_ratio_set_still_probes_below_d0():
    """也必须保留紧于 d0 的档 —— 那才是"加压"的本意。"""
    assert any(r < 1.0 for r in DELAY_TARGET_RATIOS)
