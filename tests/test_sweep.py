"""扫参入口：它这一轮到底覆盖了哪些组合，必须从输出看得出来。

为什么值得有这个测试：`scripts/sweep.py` 是**唯一能一次写 72 条记录的入口**，
在此之前它一个测试都没有。而它的失效方式全都是静默的 ——

1. 换代重跑时开 `--skip-existing`，它按 `(design, params)` 匹配，于是一条都不补，
   以 0 退出，看起来像「已经跑完了」。
2. 按代跳过时若拿「记录里最后一条属于哪一代」当本代，换代后第一次跑会把整代
   判成已有，同样一条不跑、同样 0 退出。
3. 两个口径不同的跳过开关同时给出时若静默择一，使用者以为跳的是本代、实际跳的是
   任何一代，新一代少几十条而没有任何迹象。
4. 过滤所依据的指纹与记录实际写入的指纹不一致时，被跳过的那些条**永远**不属于
   这一代，而新一代会一直差着它们。

四条都不报错，四条的结局都是「记录里少了几十条，而没人知道」。

这里的 `run_experiment` 全部是替身：本测试要证的是**调度与口径**，不是测量。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

# 并行路径（jobs > 1）开跑前要用真 yosys 算读入集合摘要：工具不在 PATH 时这几条不是内循环用例（内部#193）
needs_yosys = [pytest.mark.flow,
               pytest.mark.skipif(__import__("shutil").which("yosys") is None, reason="yosys 不在 PATH")]

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import param_combos  # noqa: E402
from scripts import sweep as sweep_mod  # noqa: E402

DESIGN = "CBB_LZD"   # 真实设计夹具（开源构件，内部#305）
FP_A = "sha256:" + "a" * 64      # 上一代
FP_B = "sha256:" + "b" * 64      # 本代
FP_C = "sha256:" + "c" * 64      # 又一代
SRC_A = "sha256:" + "1" * 64     # 当前 RTL 的读入集合摘要（synth.sources_sha256）
SRC_B = "sha256:" + "2" * 64     # 改过的 RTL

LIBERTY = "/nonexistent/liberty.lib"   # 替身不读它


def _combos():
    return [dict(c) for c in param_combos(DESIGN)]


def _record(params, fingerprint, design=DESIGN, passed=True, eid="x", sources=SRC_A):
    rec = {"experiment_id": eid, "design": design, "params": params,
           "flow": {"fingerprint": fingerprint}, "sim": {"passed": passed}}
    if sources is not None:      # None = 2026-09-20 之前那种没有摘要字段的记录
        rec["synth"] = {"sources_sha256": sources}
    return rec


def _write_log(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


class FakeRunner:
    """替身 run_experiment：记下被调用的组合，并按需追加一条记录。

    `write=False` 用来构造「跑了但没写进记录」——那正是结尾摘要重数一遍记录
    才能看见的那种情形。
    """

    def __init__(self, log_path, fingerprint=FP_B, write=True,
                 raise_on=None, skip_write_on=(), sources=SRC_A):
        self.log_path = Path(log_path)
        self.fingerprint = fingerprint
        self.sources = sources
        self.write = write
        self.raise_on = raise_on          # 第几次调用抛错（1 起）
        self.skip_write_on = set(skip_write_on)
        self.calls = []

    def __call__(self, design, params, liberty, sim="icarus", period_ns=5.0):
        self.calls.append(dict(params))
        n = len(self.calls)
        if self.raise_on == n:
            raise RuntimeError(f"替身在第 {n} 个组合上失败")
        fp = self.fingerprint(n) if callable(self.fingerprint) else self.fingerprint
        src = self.sources(n) if callable(self.sources) else self.sources
        rec = _record(params, fp, design=design, eid=f"e{n}", sources=src)
        if self.write and n not in self.skip_write_on:
            with self.log_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        return rec


@pytest.fixture
def runner(tmp_path, monkeypatch):
    log = tmp_path / "experiments.jsonl"
    log.touch()
    r = FakeRunner(log)
    monkeypatch.setattr(sweep_mod, "run_experiment", r)
    monkeypatch.setattr(sweep_mod, "flow_fingerprint",
                        lambda liberty, sim="icarus", *, design: {"fingerprint": FP_B},
                        raising=False)
    # 当前 RTL 的读入集合摘要：真实实现要 yosys 算读入集合，这里固定成 SRC_A
    monkeypatch.setattr(sweep_mod, "current_sources_sha256",
                        lambda design: SRC_A, raising=False)
    return r


# --- 1.1 按代跳过 -------------------------------------------------------------

def test_skip_existing_generation_also_matches_on_the_fingerprint(runner, monkeypatch):
    """M1：同一个组合在两代里各有一条，跳不跳取决于**本次**的指纹。

    `--skip-existing` 在三种情形下都跳过它 —— 那是它的口径，不是缺陷。
    """
    first = _combos()[0]
    _write_log(runner.log_path,
               [_record(first, FP_A, eid="old"), _record(first, FP_B, eid="new")])

    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    assert first not in runner.calls, "本代已有这一条，不该再跑"

    runner.calls.clear()
    _write_log(runner.log_path,
               [_record(first, FP_A, eid="old"), _record(first, FP_B, eid="new")])
    monkeypatch.setattr(sweep_mod, "flow_fingerprint",
                        lambda liberty, sim="icarus", *, design: {"fingerprint": FP_C},
                        raising=False)
    runner.fingerprint = FP_C          # 替身写出来的也得是第三代，否则撞上 1.2 的一致性校验
    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    assert first in runner.calls, (
        "本次是第三代，记录里一条都不属于它，却被跳过了 —— "
        "匹配键里没有指纹")

    runner.calls.clear()
    runner.fingerprint = FP_B
    _write_log(runner.log_path,
               [_record(first, FP_A, eid="old"), _record(first, FP_B, eid="new")])
    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing=True, log_path=runner.log_path)
    assert first not in runner.calls, "--skip-existing 的口径不含代码版本，应当跳过"


def test_two_switches_with_different_keys_refuse_to_run_together(runner):
    """M2：两个口径不同的跳过开关同时给出 —— 报错，且一个组合都不跑。"""
    with pytest.raises(sweep_mod.SweepError) as exc:
        sweep_mod.sweep(DESIGN, LIBERTY, skip_existing=True,
                        skip_existing_generation=True, log_path=runner.log_path)
    assert runner.calls == [], "报错之前已经跑了实验"
    msg = str(exc.value)
    assert "flow.fingerprint" in msg and "params" in msg, (
        f"报错没说清两者的匹配字段各是什么：{msg}")


def test_the_cli_exits_non_zero_when_both_switches_are_given():
    """M2 的另一半：命令行入口必须非 0 退出，而不是抛个 traceback 了事。"""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "sweep.py"),
         "--design", DESIGN, "--liberty", LIBERTY,
         "--skip-existing", "--skip-existing-generation"],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    out = proc.stdout + proc.stderr
    assert "flow.fingerprint" in out and "--skip-existing" in out, out


def test_a_failed_record_of_this_generation_is_still_skipped(runner):
    """M3 / D7：`sim.passed == false` 也是本代对这个组合的测量结果。

    RTL 没改，重跑它不会变成 true。跳过是对的 —— 但摘要要说明这条口径，
    以免读者以为跳过的都是成功的。
    """
    first = _combos()[0]
    _write_log(runner.log_path, [_record(first, FP_B, passed=False)])
    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    assert first not in runner.calls


def test_a_brand_new_generation_skips_nothing(runner, monkeypatch):
    """M4 回归：记录里只有上一代的全部组合，本次是新一代 —— 一条都不该跳。

    这正是拿 `latest_generation()`（记录里最后一条属于哪一代）当「本代」会判错的
    那种情形：那时最后一条属于**上一代**，整代都会被判成已有，一条不跑、0 退出。
    """
    combos = _combos()
    _write_log(runner.log_path,
               [_record(c, FP_A, eid=f"old{i}") for i, c in enumerate(combos)])
    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    assert len(runner.calls) == len(combos), (
        f"新一代一条记录都没有，却只跑了 {len(runner.calls)}/{len(combos)} 条")


def test_without_any_switch_every_combo_runs(runner):
    """M5 回归：不给跳过开关，组合总数是多少就跑多少。"""
    combos = _combos()
    _write_log(runner.log_path,
               [_record(c, FP_B, eid=f"cur{i}") for i, c in enumerate(combos)])
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    assert len(runner.calls) == len(combos)


# --- 1.2 指纹一致性 -----------------------------------------------------------

def test_a_record_written_under_a_different_fingerprint_aborts_the_sweep(runner):
    """1.2 M1：过滤按指纹 X，写出来的却是 Y —— 中止，别再往下跑。

    往下跑的后果是：新一代永远差着被跳过的那几十条，而没有任何迹象。
    """
    runner.fingerprint = FP_C          # 替身写出来的是另一代
    with pytest.raises(sweep_mod.SweepError) as exc:
        sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                        log_path=runner.log_path)
    assert len(runner.calls) == 1, (
        f"指纹已经对不上了还继续跑了 {len(runner.calls)} 条")
    msg = str(exc.value)
    assert FP_B[:16] in msg and FP_C[:16] in msg, (
        f"报错没同时给出两个指纹：{msg}")


def test_a_matching_fingerprint_runs_everything(runner):
    """1.2 M2 回归：指纹一致时照常跑完。"""
    combos = _combos()
    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    assert len(runner.calls) == len(combos)


def test_the_fingerprint_check_does_not_apply_without_the_generation_switch(runner):
    """1.2 M3 回归：没开按代跳过就没有「本代」这个前提，不做这项校验。"""
    runner.fingerprint = FP_C
    combos = _combos()
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    assert len(runner.calls) == len(combos)


# --- 2.1 覆盖摘要与逐组合进度 -------------------------------------------------

def test_the_summary_reports_total_skipped_and_actually_run(runner, capsys):
    """2.1 M1：开跑一行、结束一行，三个数与匹配口径都在。"""
    combos = _combos()
    n = len(combos)
    _write_log(runner.log_path,
               [_record(c, FP_B, eid=f"cur{i}") for i, c in enumerate(combos[:-3])])

    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    out = capsys.readouterr().out
    head = [l for l in out.splitlines() if l.startswith("# sweep") and "结束" not in l]
    tail = [l for l in out.splitlines() if "结束" in l]
    assert head and tail, out
    assert str(n) in head[0] and str(n - 3) in head[0] and "3" in head[0], head[0]
    assert "flow.fingerprint" in out, "摘要没说按什么口径判定「已有」\n" + out
    assert f"{n}/{n}" in tail[0], tail[0]


def test_the_closing_count_is_recounted_from_the_records(runner, capsys):
    """2.1 M2：结尾的「本代现有」是重数记录得来的，不是 69+3 加出来的。

    加出来的那个数在「某条实验跑了但没写进记录」时仍然是满的，而重数一遍会露出来。
    """
    combos = _combos()
    n = len(combos)
    _write_log(runner.log_path,
               [_record(c, FP_B, eid=f"cur{i}") for i, c in enumerate(combos[:-3])])
    runner.skip_write_on = {2}          # 第二条跑了，但没写进记录

    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    tail = [l for l in capsys.readouterr().out.splitlines() if "结束" in l]
    assert f"{n - 1}/{n}" in tail[0], (
        f"结尾摘要把跑过但没落盘的那条算进去了：{tail[0]}")


def test_the_summary_is_printed_even_when_a_combo_fails(runner, capsys):
    """2.1 M3：中途失败也要打摘要 —— 已经跑完的那些是真实产出。

    一个组合失败不拖住整轮（见 test_a_failing_combo_does_not_stop_the_rest），
    所以摘要应是「跑了 N-1 条」。原先断言只查 `"2" in` 摘要，在 24 个组合的夹具上靠
    「23」里碰巧有个 2 通过；换成 15 个组合的夹具后才暴露（内部#305），这里改成精确断言。
    """
    runner.raise_on = 3
    with pytest.raises(RuntimeError):
        sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    out = capsys.readouterr().out
    tail = [l for l in out.splitlines() if "结束" in l]
    assert tail, "扫参中途失败，结尾摘要一个字都没打\n" + out
    n = len(_combos())
    assert f"跑了 {n - 1} 条" in tail[0], f"摘要没反映已跑完的 {n - 1} 条：{tail[0]}"


def test_every_combo_gets_a_contiguous_progress_index(runner, capsys):
    """2.1 M4：被跳过的也打 `[i/N]`，序号连续，最后一个是 `[N/N]`。

    序号必须是**组合序号**而不是「本轮第几条」：被杀之后要能直接读出跑到哪了，
    而「本轮第 3 条」在开了跳过开关时要读者自己做减法。
    """
    combos = _combos()
    n = len(combos)
    _write_log(runner.log_path,
               [_record(c, FP_B, eid=f"cur{i}") for i, c in enumerate(combos[:-3])])

    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    out = capsys.readouterr().out
    marks = [f"[{i}/{n}]" for i in range(1, n + 1)]
    missing = [m for m in marks if m not in out]
    assert not missing, f"缺了 {len(missing)} 个进度标记，例：{missing[:3]}\n{out}"


def test_without_a_switch_the_summary_says_so_explicitly(runner, capsys):
    """2.1 M5 回归：没开跳过开关时摘要照打，且不拿「全部」去描述一个部分集合。"""
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    out = capsys.readouterr().out
    summary = [l for l in out.splitlines() if l.startswith("#")]
    assert any("全部重跑" in l for l in summary), "\n".join(summary)

    # 换成有跳过的那一轮：摘要里就不该再出现「全部」
    combos = _combos()
    _write_log(runner.log_path,
               [_record(c, FP_B, eid=f"cur{i}") for i, c in enumerate(combos[:-3])])
    capsys.readouterr()
    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing_generation=True,
                    log_path=runner.log_path)
    summary = [l for l in capsys.readouterr().out.splitlines() if l.startswith("#")]
    assert not any("全部" in l or "all" in l.lower() for l in summary), (
        "跳过了一部分，摘要却用总括词描述它\n" + "\n".join(summary))


# --- 2.4 并行扫参 -------------------------------------------------------------
#
# 为什么值得有这组：并行改的是**调度**，而这个文件守的就是调度。
# 并行能犯的错与串行不同，且同样静默：漏提交一个组合、返回顺序随完成顺序变
# （下游 print_table 的排序因此不稳定）、跳过口径在并行分支上被绕过。
# 三种都不报错，三种的结局都是「记录里少了几条或次序变了，而没人知道」。
#
# 测量本身不受并行影响，这一点不是靠这组用例保证的，是靠 design.md 的 D7：
# 测量路径上没有任何墙钟依赖，产物按 experiment_id 分目录。这里只管调度。

@needs_yosys[0]
@needs_yosys[1]
def test_parallel_runs_every_combination_and_keeps_declaration_order(runner):
    """M1: `jobs=N` 跑完全部组合，返回顺序仍是**声明顺序**、不是完成顺序。

    顺序要紧是因为下游 `print_table` 按分数排序时把返回顺序当稳定的次序基底；
    并行之后若按完成先后返回，同一批数据两次跑出来的表行序会不同 ——
    而那种不稳定看起来像数据变了。
    """
    combos = _combos()
    rows = sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, jobs=4)
    assert len(rows) == len(combos), f"并行少跑了：{len(rows)} != {len(combos)}"
    assert [r["params"] for r in rows] == combos, "返回顺序不是声明顺序"
    assert sorted(map(str, runner.calls)) == sorted(map(str, combos))


@needs_yosys[0]
@needs_yosys[1]
def test_the_summary_names_the_parallelism(runner, capsys):
    """M2: 覆盖摘要要说出本轮的并行度，以及每条的开跑/完成。

    与 `fast_check.sh`、`run_equiv.py` 同一条口径（`guardrail-scope`）：
    削弱了的覆盖与完整的覆盖必须在输出上可区分。并行还多一层 ——
    被杀之后串行日志能靠「最后一行是第几条」读出进度，而并行不能，
    所以开跑与完成都要各打一行。
    """
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, jobs=3)
    out = capsys.readouterr().out
    assert "并行度 3" in out, f"摘要没说出并行度：\n{out}"
    assert "开跑" in out and "完成" in out, (
        f"并行日志里没有开跑/完成两侧，被杀之后读不出进度：\n{out}")


@needs_yosys[0]
@needs_yosys[1]
def test_parallel_still_honours_the_skip_switch(tmp_path, runner, monkeypatch):
    """M3 (regression): `-j` 下两个跳过开关的口径不变。

    并行分支若绕开 `done` 的过滤，换代重跑的断点续跑会把已有的那些**重跑一遍**，
    产生同一代同一组合的重复记录 —— 而记录只增不改，重复的清不掉。
    """
    combos = _combos()
    _write_log(runner.log_path,
               [_record(combos[0], FP_B), _record(combos[1], FP_B)])
    rows = sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path,
                           skip_existing_generation=True, jobs=4)
    assert len(rows) == len(combos) - 2, "并行分支没有尊重按代跳过"
    ran = [str(c) for c in runner.calls]
    assert str(combos[0]) not in ran and str(combos[1]) not in ran


def test_the_two_switches_are_still_mutually_exclusive_under_j(runner):
    """M3 (regression): 互斥检查在并行分支上同样先于一切发生。"""
    with pytest.raises(sweep_mod.SweepError):
        sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path,
                        skip_existing=True, skip_existing_generation=True,
                        jobs=4)



# --- 跳过开关按 RTL 摘要匹配（guardrail-scope 的「跳过开关判定「已有」必须包含
# 被测 RTL 的内容摘要」）-----------------------------------------------------------
#
# 流程指纹不含 RTL，所以改了 RTL 不换代。两个开关以前都只按参数（与指纹）匹配，
# 改了 RTL 之后的重跑会把最该重跑的那批恰好跳过，覆盖摘要照报「已有 N 条」
# （docs/data-credibility.md 的 D-14，2026-09-16 实撞）。

SWITCHES = [pytest.param({"skip_existing": True}, id="skip_existing"),
            pytest.param({"skip_existing_generation": True}, id="skip_existing_generation")]


@pytest.mark.parametrize("switch", SWITCHES)
def test_a_combo_recorded_with_different_rtl_is_rerun(runner, switch):
    first = _combos()[0]
    _write_log(runner.log_path, [_record(first, FP_B, eid="old-rtl", sources=SRC_B)])
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, **switch)
    assert first in runner.calls, (
        f"RTL 改过却被跳过：记录的摘要是 {SRC_B[:15]}…，当前是 {SRC_A[:15]}…")


@pytest.mark.parametrize("switch", SWITCHES)
def test_a_combo_recorded_with_the_same_rtl_is_skipped(runner, switch):
    first = _combos()[0]
    _write_log(runner.log_path, [_record(first, FP_B, eid="same-rtl", sources=SRC_A)])
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, **switch)
    assert first not in runner.calls, "RTL 没改、本代已有，应当跳过"


@pytest.mark.parametrize("switch", SWITCHES)
def test_a_record_without_the_digest_is_not_existing(runner, switch):
    first = _combos()[0]
    _write_log(runner.log_path, [_record(first, FP_B, eid="pre-0920", sources=None)])
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, **switch)
    assert first in runner.calls, "没有 synth.sources_sha256 的旧记录不能当作已有"


@pytest.mark.parametrize("switch", SWITCHES)
def test_rtl_changed_during_the_sweep_aborts(runner, switch):
    runner.sources = lambda n: SRC_A if n == 1 else SRC_B
    with pytest.raises(sweep_mod.SweepError) as e:
        sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, **switch)
    assert SRC_A in str(e.value) and SRC_B in str(e.value), str(e.value)


def test_rtl_digest_check_does_not_apply_without_a_switch(runner):
    runner.sources = SRC_B
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    assert len(runner.calls) == len(_combos())


@pytest.mark.parametrize("switch", SWITCHES)
def test_the_summary_names_the_rtl_digest(runner, switch, capsys):
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, **switch)
    out = capsys.readouterr().out
    assert "synth.sources_sha256" in out, out
    assert SRC_A.split(":")[-1][:8] in out, out


# --- 内部#85：单个组合失败时其余照跑，结尾汇总 -------------------------------------

@needs_yosys[0]
@needs_yosys[1]
@pytest.mark.parametrize("jobs", [1, 3])
def test_a_failing_combo_does_not_stop_the_rest(runner, capsys, jobs):
    """一个组合测量失败是被测对象的事实，不该拖住整轮：其余组合都跑完、都写入，
    结尾摘要之后列出失败的组合，最后以 SweepFailures（RuntimeError 的子类）退出。"""
    n = len(_combos())
    runner.raise_on = 3
    with pytest.raises(RuntimeError) as exc:
        sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, jobs=jobs)
    assert isinstance(exc.value, sweep_mod.SweepFailures), type(exc.value)
    assert len(runner.calls) == n, f"失败之后停了：只调了 {len(runner.calls)}/{n} 个组合"
    written = [l for l in runner.log_path.read_text().splitlines() if l.strip()]
    assert len(written) == n - 1
    out = capsys.readouterr().out
    assert "替身在第 3 个组合上失败" in out, "结尾没有列出失败的组合与原因\n" + out
    assert f"{n - 1}/{n}" in [l for l in out.splitlines() if "结束" in l][0]


# --- param-exclude（内部#138）-------------------------------------------------------

def test_excluded_combos_are_not_run_and_the_header_says_how_many(runner, monkeypatch, capsys):
    """内部#138（param-exclude D4）：exclude 命中的组合不调用 run_experiment，开头一行写排除数。"""
    combos = _combos()
    name, value = next(iter(combos[0].items()))
    hit = [c for c in combos if c[name] == value]
    from flow.paths import load_design_config
    cfg = {**load_design_config(DESIGN), "exclude": [{name: value}]}
    monkeypatch.setattr(sweep_mod, "load_design_config", lambda design: cfg)
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    assert len(runner.calls) == len(combos) - len(hit)
    assert all(c[name] != value for c in runner.calls)
    out = capsys.readouterr().out
    assert f"共 {len(combos) - len(hit)} 个组合（params.yaml exclude 排除 {len(hit)} 个）" in out, out



# --- 内部#172 功耗算完就删 VCD ------------------------------------------------------

def _plant_vcds(root, eids):
    """每个实验在 sim/ 与 sim_gate/ 下各放一份 VCD，外加一份不该被删的网表。"""
    for eid in eids:
        for stage in ("sim", "sim_gate", "synth"):
            d = root / eid / stage
            d.mkdir(parents=True, exist_ok=True)
            (d / ("TOP_netlist.v" if stage == "synth" else "TOP.vcd")).write_text("x" * 10)


@pytest.fixture
def runs_root(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    monkeypatch.setattr(sweep_mod, "run_dir",
                        lambda eid, stage=None: root / eid / stage if stage else root / eid)
    _plant_vcds(root, [f"e{i}" for i in range(1, len(_combos()) + 1)])
    return root


@needs_yosys[0]
@needs_yosys[1]
@pytest.mark.parametrize("jobs", [1, 2])
def test_vcds_are_deleted_after_each_successful_combo(runner, runs_root, jobs):
    """默认每个组合成功后删掉 sim/ 与 sim_gate/ 下的 VCD，网表留着（内部#172）。"""
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, jobs=jobs)
    assert len(runner.calls) == len(_combos())
    assert list(runs_root.rglob("*.vcd")) == []
    assert len(list(runs_root.rglob("*_netlist.v"))) == len(_combos())


def test_keep_vcd_keeps_them(runner, runs_root):
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path, keep_vcd=True)
    assert len(list(runs_root.rglob("*.vcd"))) == 2 * len(_combos())


def test_a_failed_combo_keeps_its_vcd(runner, runs_root):
    """失败的组合不删，留着排查：替身第 1 次调用抛错，它的 e1 目录原样保留。"""
    runner.raise_on = 1
    with pytest.raises(sweep_mod.SweepFailures):
        sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    left = sorted(p.parent.parent.name for p in runs_root.rglob("*.vcd"))
    # 替身的实验号按调用次序编：第 1 次失败，第 2 次起记录为 e2…，所以只有 e1 的 VCD 还在
    assert left == ["e1", "e1"]


# --- 内部#214 sweep_points：声明了点表就只跑点表 ------------------------------------------------

def test_sweep_points_run_only_the_listed_points(runner, monkeypatch, capsys):
    from flow.paths import load_design_config
    cfg = dict(load_design_config(DESIGN))
    picked = _combos()[:2]
    cfg["sweep_points"] = [{"name": f"p{i}", **c} for i, c in enumerate(picked)]
    monkeypatch.setattr(sweep_mod, "load_design_config", lambda design: cfg, raising=False)
    sweep_mod.sweep(DESIGN, LIBERTY, log_path=runner.log_path)
    assert runner.calls == picked
    assert "按 sweep_points 跑 2 个点" in capsys.readouterr().out


# --- 内部#422：不给 log_path 时读写都落在本设计根的记录文件 ---

def test_default_log_path_is_design_root_file_and_run_experiment_is_redirected(runner, monkeypatch, tmp_path):
    from flow import records
    from scripts import run_experiment as rx
    target = tmp_path / "results" / "cbb_lzd" / "experiments.jsonl"
    target.parent.mkdir(parents=True)
    monkeypatch.setattr(records, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(records, "log_path", lambda design, repo_root=None: target)
    runner.log_path = target
    first = _combos()[0]
    _write_log(target, [_record(first, FP_B)])          # 已有一条：skip_existing 要从这个文件读到它
    seen = []

    def spy(*a, **k):
        seen.append(rx.EXPERIMENTS_LOG)
        return runner(*a, **k)
    monkeypatch.setattr(sweep_mod, "run_experiment", spy)
    saved = rx.EXPERIMENTS_LOG
    sweep_mod.sweep(DESIGN, LIBERTY, skip_existing=True)
    assert first not in runner.calls and len(runner.calls) == len(_combos()) - 1
    assert seen and all(p == target for p in seen)
    assert rx.EXPERIMENTS_LOG == saved
