"""形式化等价层的回归测试。

**关键在 test_injected_bug_is_caught。** 只验证「能通过」不构成对这层能力的验证——
一个永远返回成功的脚本与一个正确的证明脚本，在全绿的日志上完全一样。必须同时
验证「该失败时会失败」。契约在 openspec/specs/formal-equivalence/spec.md 的
「等价证明的能力必须由一个会失败的例子证实」。

反例用运行时注入：把 RTL 复制到临时目录再改一位。仓库里躺一份故意坏掉的 .v 会
被 fast_check.sh 的 elaborate 扫到，也可能被误当成参考实现。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

needs_yosys = pytest.mark.skipif(
    shutil.which("yosys") is None, reason="yosys 不在 PATH（source ~/tools/env.sh）")


def _prove(design, **kw):
    from flow.equiv.run_equiv import prove
    return prove(design, **kw)


def _declared(design):
    """该设计当下声明的全部组，解析成 {pair 名: [config, ...]}。

    从声明读而不是从一次运行的结果读：覆盖面是**声明**决定的，
    而「这一轮跑了哪些」会被账、被 --pair 改变。两者混用会让
    「少声明了一对」藏在「这轮跳过了」后面。
    """
    import flow.equiv.run_equiv as m
    out = {}
    for pair in m.PAIRS[design](m.design_rtl_dir(design)):
        out[pair.name] = list(pair.configs)
    return out


def _assert_proved(design):
    """账齐全 → 秒级通过；账对不上 → **当场失败**，报出哪几组、为什么、怎么更新。

    仍然「不靠 marker」：内部#42 提过把慢证明标成 opt-in，但「opt-in 的护栏等于没有护栏」。
    账就是那个强制者 —— 账对不上测试就红，不需要人记得去加开关。

    但测试 MUST NOT 写仓库里的账（formal-equivalence「证明器必须可观测，且跑测试不得写
    仓库里的账」）。以前这里就地重证并写回，2026-09-27 一次内循环只改了三条 `proved_at`
    就把工作区弄脏了（内部#70）。更新账是一次有意的、在 diff 里看得见的提交：
    照报错里的命令跑 `run_equiv.py`，提交 `proved.json`（用户 2026-10-01 选定）。
    """
    import flow.equiv.run_equiv as m

    stale = m.stale_entries(design)
    if stale:
        why = "\n".join(f"    {k} —— {reason}" for k, reason in stale)
        raise AssertionError(
            f"{design}: {len(stale)} 组等价账目对不上：\n{why}\n"
            f"更新账：.venv/bin/python3 flow/equiv/run_equiv.py --design {design} "
            f"--skip-proved -j <N>，然后提交 flow/equiv/proved.json。"
            f"测试不就地重证、不写仓库的账（#70）。")

    orphans = m.orphan_entries()
    assert not orphans, (
        "账里有声明中不存在的陈旧账目 —— 它们不是任何一组的证据，"
        "对照被删掉之后账上那条 PROVED 会让人以为它还被证着：\n  "
        + "\n  ".join(orphans))


def test_a_stale_ledger_fails_the_test_and_writes_nothing(tmp_path, monkeypatch):
    """账对不上时测试直接失败、给出更新命令，**不写任何账**（内部#70）。

    formal-equivalence「跑测试 MUST NOT 修改仓库里的账本」。以前这里就地重证并写回
    仓库的账：2026-09-27 一次内循环只改了三条 `proved_at`，工作区被弄脏，接着记实验
    会撞脏树守卫。更新账是一次有意的、在 diff 里看得见的提交，不是跑测试的副作用
    （用户 2026-10-01 选「测试直接失败并给出更新命令」）。
    """
    import json

    import flow.equiv.run_equiv as m

    led = m.load_ledger()
    key = next(k for k in led if k.startswith("CBB_LZD::"))
    led[key] = dict(led[key], sources_sha256={"stale": "sha256:0"})
    path = tmp_path / "proved.json"
    path.write_text(json.dumps(led))
    before = path.read_bytes()
    monkeypatch.setattr(m, "LEDGER_PATH", path)
    calls = []
    monkeypatch.setattr(m, "prove", lambda *a, **k: calls.append(a) or (True, []))

    with pytest.raises(AssertionError) as e:
        _assert_proved("CBB_LZD")
    assert "run_equiv.py --design CBB_LZD" in str(e.value), str(e.value)
    assert calls == [], "账过期时不该就地重证"
    assert path.read_bytes() == before, "账被写了"


def _run_cli(*args, ledger=None):
    """按命令行跑一次 run_equiv，返回 (退出码, 合并后的输出)。

    走 CLI 而不是 `prove()`，是因为覆盖摘要是**给人看的输出**，
    它只在命令行这一层存在；从函数返回值断言不了「有没有打印」。

    `ledger` 必须给 —— 真跑一轮的用例要把账写到自己的 tmp 目录。不给的话
    它会写仓库里的 `flow/equiv/proved.json`，于是跑一次 `pytest tests/`
    工作区就脏了（本仓 内部#49）。只读的用例（不触发任何一组重证）可以不给。
    """
    extra = ["--ledger", str(ledger)] if ledger else []
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "flow" / "equiv" / "run_equiv.py"),
         *args, *extra],
        capture_output=True, text=True, cwd=REPO_ROOT)
    return r.returncode, r.stdout + r.stderr


def test_proving_nothing_is_not_a_pass():
    """M1: 一组都没证，不得与全证过了同形。

    走 `--pair` 给一个不存在的名字：现在的行为是屏幕上一片安静、
    末行 `0/0 组证明通过`、退出码 0。这正是本仓头号失效模式在形式验证
    一侧的形态 —— 跑通了、有输出、没人问输出是不是在回答一个有意义的问题。
    """
    rc, out = _run_cli("--design", "CBB_LZD", "--pair", "没有这一对")
    assert rc != 0, (
        f"一组都没证，退出码却是 0 —— 「一条都没证」与「全证过了」"
        f"在退出码上必须可区分\n{out}")
    assert "0" in out and "组" in out, f"摘要没写证了几组:\n{out}"


@needs_yosys
@pytest.mark.flow
def test_the_run_reports_what_it_actually_covered(tmp_path):
    """M2: 覆盖摘要必须说清声明了多少、证了多少、跳过哪些及原因。

    与 `sweep.py` 的扫参摘要、`fast_check.sh` 的覆盖摘要同一条原则
    （`guardrail-scope`）：削弱了的证明与完整的证明，在输出上必须可区分。
    """
    rc, out = _run_cli("--design", "CBB_LZD", "--pair", "cbb_lzd_lsb_vs_ref",
                       ledger=tmp_path / "proved.json")
    assert rc == 0, out

    assert "# equiv CBB_LZD" in out, f"没有覆盖摘要:\n{out}"
    assert "声明" in out and "跳过" in out, f"摘要没写声明/跳过:\n{out}"

    # --pair 过滤掉的那些必须逐条列出，并注明为什么跳过
    skipped = [ln for ln in out.splitlines() if "跳过" in ln and "--pair" in ln]
    assert skipped, f"覆盖摘要里没有跳过原因\n{out}"
    for name in ("cbb_lzd_msb_vs_ref",):
        assert any(name in ln for ln in skipped), (
            f"被 --pair 排除的 {name} 没有出现在跳过列表里\n{out}")

    # 每组各用了多久 —— 这是 内部#42 的诊断依据，不是装饰
    assert " s)" in out or " s " in out, f"摘要没有逐组耗时:\n{out}"


@needs_yosys
@pytest.mark.flow
def test_a_test_run_does_not_touch_the_repo_ledger(tmp_path):
    """真跑一轮的用例把账写到自己的 tmp 目录，仓库里那一份逐字节不变。

    这条守的不是「功能对不对」，是**跑测试的副作用**。账的全部价值是
    「改动在 diff 里看得见」；每跑一次 `pytest tests/` 就产生几行
    `proved_at` 的 diff，久了没人细看账的 diff —— 那正好废掉它唯一的用途。
    更直接的后果是跑完测试工作区就是脏的，接着记实验会撞红线 3 的脏树守卫
    （本仓 内部#49，2026-09-18 实撞过一次）。
    """
    import hashlib
    from flow.equiv.run_equiv import LEDGER_PATH

    before = hashlib.sha256(LEDGER_PATH.read_bytes()).hexdigest()
    out = tmp_path / "proved.json"
    rc, log = _run_cli("--design", "CBB_LZD", "--pair", "cbb_lzd_lsb_vs_ref",
                       ledger=out)
    assert rc == 0, log
    assert out.exists(), f"账没写到 tmp 目录：{log}"
    after = hashlib.sha256(LEDGER_PATH.read_bytes()).hexdigest()
    assert after == before, (
        "跑一轮测试把仓库里的 proved.json 改脏了 —— "
        "它应当只写 --ledger 指定的那一份")


@needs_yosys
def test_the_output_is_flushed_line_by_line(tmp_path):
    """输出边跑边出，不是攒到进程退出才一次性吐。

    一个带除法器的地址流水设计一轮约 100 分钟。全缓冲时日志**全程 0 字节**，
    「还在跑」与「卡死了」在外部看来完全一样，只能靠数 yosys 子进程分辨
    （2026-09-17 实撞过）。逐组耗时本来就是这一层的诊断依据，
    攒到退出才吐出来等于没有。

    判据取**第一行在进程结束之前到达**：那一行是覆盖摘要的头，在任何一组
    开证之前就该打出来。读到它就 `kill`，所以这条用例是秒级的，
    不需要等完整一轮。
    """
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "flow" / "equiv" / "run_equiv.py"),
         "--design", "CBB_LZD",
         # 账也要给 tmp：读到第一行就 kill 并不保证一组都没证完 —— 机器一忙，
         # 快的几组会赶在 kill 之前证完并写进仓库里那份账，
         # 只改 proved_at（2026-09-24 在 pytest -n 下实撞，内部#49 的同一种泄漏）。
         "--ledger", str(tmp_path / "proved.json")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=REPO_ROOT)
    try:
        first = proc.stdout.readline()
        assert proc.poll() is None, (
            "第一行到达时进程已经结束了 —— 这条用例没能证明是行刷新，"
            "换一个更早的观察点")
        assert first.startswith("# equiv CBB_LZD:"), (
            f"第一行不是覆盖摘要的头：{first!r}")
    finally:
        proc.kill()
        proc.wait()


# --- 任务 2.1：账 ---------------------------------------------------------
#
# 账要回答的是「这一组是对**哪些字节**证的」。它不是防篡改机制 —— 谁都能手改
# proved.json。它的价值是**可见性**：现在削弱证明器根本不出现在任何地方，
# 有了账，改证明器必然表现为一次全量重证，而且出现在 diff 里。


def _ledger_mod():
    import flow.equiv.run_equiv as m
    return m


def test_ledger_hit_does_not_call_the_solver(capsys):
    """M1: 源文件与证明器都没变时，账命中的组不得调用求解器。

    判据不是「函数里没写 subprocess」——那要靠读代码。判据是**注入一个不存在的
    求解器名**跑整条 prove()：账若没真的拦住，yosys 这一步会立刻炸。
    """
    m = _ledger_mod()
    assert m.stale_entries("CBB_LZD") == [], "前提不成立：CBB_LZD 的账不齐"

    ok, res = m.prove("CBB_LZD", yosys="这个求解器不存在",
                      skip_proved=True)
    assert ok, "账齐全，prove() 却没通过"
    assert res == [], f"账命中的组不该被证：{[r['label'] for r in res]}"
    out = capsys.readouterr().out
    assert "账目命中" in out, f"摘要没说清为什么跳过：\n{out}"


def test_changing_the_proved_rtl_invalidates_only_that_design(tmp_path):
    """M2: 被证的 RTL 改了，该设计的账目失效；原样的 RTL 照旧命中。

    **改的是临时副本，不碰仓库里的文件**（2026-10-01 起）。早先这条就地改写
    某个设计根的 RTL 再还原：并行跑测试时，别的 worker 恰好在那个
    窗口里读账就会看到「过期」，而当时的 `_assert_proved` 会就地重证、只改 `proved_at`
    地写回仓库的账 —— 这正是 内部#70 观察到的现象。
    """
    m = _ledger_mod()
    shutil.copytree(m.design_rtl_dir("CBB_LZD"), tmp_path / "rtl")
    victim = tmp_path / "rtl" / "cbb_lzd.v"
    victim.write_bytes(victim.read_bytes() + "\n// 注入\n".encode())
    stale = m.stale_entries("CBB_LZD", rtl_dir=tmp_path / "rtl")
    assert stale, "改了 RTL，账目却仍然命中"
    assert all("被证的源文件变了" in why for _, why in stale), (
        f"失效原因应当是源文件变了：{stale}")
    assert m.stale_entries("CBB_LZD") == [], "仓库里原样的 RTL 应当照旧命中"


def test_changing_the_prover_invalidates_every_design(tmp_path, monkeypatch):
    """M3: 改证明器的任意一个字节（含注释），全部设计的账目一次性失效。

    为什么连注释都算：`run_equiv.py` 的注释里写着覆盖边界（「证的是组合等价」
    「带寄存器的顶层不在射程内」）。改了注释而不改行为，恰恰是最该有人重看
    一遍的情形。宁可多证一次 —— 这与 `metrics_code_sha256()` 哈希 AST 的取舍
    相反，理由写在 design.md 的 D3。
    """
    m = _ledger_mod()
    monkeypatch.setattr(m, "recipe_sha256", lambda: "sha256:" + "0" * 64)
    for design in sorted(m.PAIRS):
        assert m.stale_entries(design), (
            f"改了证明器，{design} 的账目却仍然命中")


def test_a_ledger_entry_outside_the_declared_set_is_reported():
    """M4: 账里有声明中不存在的陈旧账目，必须被报告且不被当作证据。"""
    m = _ledger_mod()
    ledger = dict(m.load_ledger())
    ledger["CBB_LZD::没有这一对::{}"] = {
        "sources_sha256": {}, "recipe_sha256": m.recipe_sha256(),
        "proved_at": "2000-01-01T00:00:00Z"}
    orphans = m.orphan_entries(ledger)
    assert any("没有这一对" in o for o in orphans), (
        f"陈旧账目没有被报告：{orphans}")


def test_the_ledger_writes_deterministically(tmp_path):
    """M5: 同一份账连写两次逐字节相同 —— 否则 diff 全是噪声，没人会读。"""
    m = _ledger_mod()
    led = m.load_ledger()
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    m.save_ledger(led, a)
    m.save_ledger(led, b)
    assert a.read_bytes() == b.read_bytes(), "账目写入不稳定"
    assert a.read_bytes() == (REPO_ROOT / "flow" / "equiv" / "proved.json").read_bytes(), (
        "重写仓库里那份账会产生 diff —— 说明写入不是规范形式")


def test_the_prover_finds_the_rtl_by_the_top_name_not_the_directory_name(fixture_designs):
    """账目的 `design` 是**被测顶层名**，源文件要按顶层名去找它所在的设计根。

    为什么值得有这条：`run_equiv.py` 原来两处写死
    `REPO_ROOT / "designs" / design / "rtl"`，即把顶层名当目录名。内部#45 收根之后
    这个等式就不成立了（那个设计根已经不存在），但当时**没有红** ——
    账本里 20 条的 design 只有两个小写的旧根名，它们碰巧既是
    顶层名也是根名（本仓 内部#51，当时按「代价是 100 分钟重证、等下一次动证明器时搭车」
    退回过一次）。

    2026-09-21 把顶层名改成大写之后它**当场炸了**：`PAIRS` 的键变成
    大写顶层名，而 `designs/<大写顶层名>/` 不存在。这正是那条 issue 说的
    「第一个动这个文件的人会撞上」。
    """
    from flow.equiv.run_equiv import design_rtl_dir

    # 夹具 IP_TOP 住在 ip_root/：顶层名与根名不同，正是这条要守的情形（开发中的 IP 会改名，内部#110）
    for top, root in [("IP_TOP", fixture_designs / "ip_root"), ("CBB_LZD", REPO_ROOT / "cbb/cbb_lzd")]:
        got = design_rtl_dir(top)
        assert got == root / "rtl", (
            f"{top} 的源文件目录解析成了 {got}")
        assert got.is_dir(), f"{top} 解析出来的目录不存在：{got}"


# --- 并行（本仓 内部#54） ---------------------------------------------------
#
# 为什么值得有这一组：等价证明的墙钟是本仓最贵的单项 —— 那个地址流水设计
# 的 9 组一轮 5976 秒（2026-09-21 实测），而账目键的是**被证 RTL 的字节**，
# 所以任何动到 addr 侧 RTL 的改动都要付一次，哪怕只改了注释。
#
# 并行在这里的风险不是「跑不快」，是**跑快了但证得少了**：并行度如果能改变
# 账目内容，它就不再是性能开关，而是一个会悄悄改变证据强度的旋钮 ——
# 而账目正是用来回答「这一组是对哪些字节证的」。所以下面钉的是
# 「结论/账目/退出码/声明顺序与 -j 无关」，而不是「-j 跑得快」。

# 一对 15 组（CBB_LZD 的 MSB_EN = 0 那一对：5 档位宽 × 3 种结构），`-j 15` 时全部同时起跑。
# 2026-10-01 起（trim-design-roots）：早先是一个已删设计的解压子块（3 组、每组秒级），
# 现在每组只要零点几秒，M1 的「墙钟 < 逐组之和」因此很宽松，并行的实据是 M2 的
# 「全部开跑之后才有第一个完成」。
_ZC_FAST = ("--design", "CBB_LZD", "--pair", "cbb_lzd_lsb_vs_ref")
_FAST_N = 15


@needs_yosys
def test_jobs_actually_runs_the_groups_concurrently(tmp_path):
    """M1: `-j` 真的并行 —— 墙钟明显小于逐组耗时之和。

    判据取**逐组耗时之和 vs 墙钟**而不是「比串行快」：后者会把机器当时的负载
    也量进去，在一台正在干别的活的机器上会假红。逐组耗时是证明器自己报的，
    墙钟是外面量的，两者的差只能来自并行。
    """
    import re
    import time

    t0 = time.monotonic()
    rc, out = _run_cli(*_ZC_FAST, "-j", str(_FAST_N), ledger=tmp_path / "p.json")
    wall = time.monotonic() - t0
    assert rc == 0, out
    per = [float(x) for x in re.findall(r"\((\d+\.\d+) s\)", out)]
    assert len(per) == _FAST_N, f"没有 {_FAST_N} 组的逐组耗时：\n{out}"
    assert sum(per) > 0, out
    # 各组 >0 —— 墙钟必须小于逐组之和（留出解释器启动的余量）
    assert wall < sum(per) + 5.0, (
        f"墙钟 {wall:.1f}s 不小于逐组耗时之和 {sum(per):.1f}s —— `-j {_FAST_N}` 没并行\n{out}")


@needs_yosys
def test_a_group_that_has_started_is_visible_before_any_group_finishes(tmp_path):
    """M2: 并行下**已开跑的组**当场可见，不是只报完成。

    串行时「上一组完成」每十分钟就发生一次，所以报完成足够；`-j 9` 时九组
    同时起跑、十分钟内一组都不会完成 —— 只报完成的话，最该看见进度的那十分钟
    里一个字都没有，而「还在跑」与「卡死了」又变得无法分辨。
    判据取输出文本里两类行的**先后位置**，不取「跑通了」。
    """
    # CBB_LZD 每组只要 0.1 s 左右，机器一忙，15 个线程还没全部起跑就有组跑完了
    # （2026-10-03 在 load 22 下连红两次）。每组先睡 1 s 再交给真的 yosys：
    # 线程起跑的间隔远小于 1 s，判据因此只取决于「开跑」打在哪，不取决于机器多忙。
    slow = tmp_path / "yosys_slow"
    slow.write_text(f'#!/bin/sh\nsleep 1\nexec "{shutil.which("yosys")}" "$@"\n')
    slow.chmod(0o755)
    rc, out = _run_cli(*_ZC_FAST, "-j", str(_FAST_N), "--yosys", str(slow),
                       ledger=tmp_path / "p.json")
    assert rc == 0, out
    lines = out.splitlines()
    started = [i for i, ln in enumerate(lines) if "开跑" in ln]
    done = [i for i, ln in enumerate(lines) if "PROVED" in ln or "FAILED" in ln]
    assert len(started) == _FAST_N, f"{_FAST_N} 组里没有 {_FAST_N} 行「开跑」：\n{out}"
    assert done, f"没有任何一行报完成：\n{out}"
    assert max(started) < min(done), (
        "有组在别的组「开跑」之前就报了完成 —— 说明开跑那一行是完成之后才打的，"
        f"并行进度不可见\n{out}")


@needs_yosys
@pytest.mark.flow
def test_the_ledger_is_the_same_whether_serial_or_parallel(tmp_path):
    """M3: 串行与并行写出的账**除 `proved_at` 外逐字段相同**，退出码相同。

    这是本组用例的核心。并行如果能改变账目内容，`-j` 就不是性能开关了。
    """
    import json

    a, b = tmp_path / "serial.json", tmp_path / "par.json"
    rc_a, out_a = _run_cli(*_ZC_FAST, "-j", "1", ledger=a)
    rc_b, out_b = _run_cli(*_ZC_FAST, "-j", str(_FAST_N), ledger=b)
    assert rc_a == rc_b == 0, out_a + out_b

    def strip(path):
        d = json.loads(path.read_text())
        return {k: {kk: vv for kk, vv in v.items() if kk != "proved_at"}
                for k, v in d.items()}

    assert strip(a) == strip(b), (
        "串行与并行写出的账不一样 —— `-j` 改变了证据本身，"
        f"而它只该改墙钟\n串行 {strip(a)}\n并行 {strip(b)}")
    # `[i/N]` 的编号按**声明顺序**，与完成先后无关
    import re
    nums = lambda out: [int(m) for m in re.findall(rf"^\[(\d+)/{_FAST_N}\].*(?:PROVED|FAILED)",
                                                   out, re.M)]
    assert sorted(nums(out_b)) == list(range(1, _FAST_N + 1)), (
        f"并行下的组编号不是声明顺序的那 {_FAST_N} 个：{nums(out_b)}\n{out_b}")


@needs_yosys
@pytest.mark.flow
def test_the_coverage_summary_states_the_parallelism_even_when_it_is_one(tmp_path):
    """M4: 覆盖摘要写明本轮并行度，`-j 1` 时也写。

    为什么 `-j 1` 时也要写：逐组耗时之和与墙钟不再相等之后，读的人必须能看出
    差的那一截是并行省下来的，而不是**有几组根本没跑**。缺了它，
    「9 组 × 11 分钟跑了 12 分钟」读起来像一次可疑的提速。
    """
    rc, out = _run_cli(*_ZC_FAST, "-j", "1", ledger=tmp_path / "p.json")
    assert rc == 0, out
    assert "并行度" in out, f"`-j 1` 的覆盖摘要里没写并行度：\n{out}"
    rc, out3 = _run_cli(*_ZC_FAST, "-j", "3", ledger=tmp_path / "p3.json")
    assert rc == 0, out3
    assert "并行度 3" in out3, f"`-j 3` 的覆盖摘要里没写并行度 3：\n{out3}"


@needs_yosys
@pytest.mark.flow
def test_the_default_parallelism_is_one_not_the_cpu_count(tmp_path):
    """M5: 不给 `-j` 时并行度是 1，**不按 CPU 数推**。

    与 `flow/Makefile` 的 `JOBS ?= 1` 同一条理由：并行只压墙钟，
    但默认开会让一台正在干别的活的机器被塞满，而这个代价的承担者是调用方。
    """
    rc, out = _run_cli(*_ZC_FAST, ledger=tmp_path / "p.json")
    assert rc == 0, out
    assert "并行度 1" in out, (
        f"不给 -j 时的并行度不是 1 —— 默认值不许按 CPU 数推：\n{out}")


@needs_yosys
@pytest.mark.flow
def test_started_means_started_not_queued(tmp_path):
    """`开跑` 这一行必须意味着「真的在跑」，不是「排在队里」。

    2026-09-21 实撞：第一版把这一行打在**提交到线程池**的地方，于是
    `-j 3` 提交 9 组时九行「开跑」一次性全出来 —— 读的人会以为九个 yosys
    在跑，而实际只有三个。谎报进度比不报更糟：它让「卡在第 4 组」看起来像
    「九组都在跑，只是都还没完」。

    判据取「第一行结果之前有几行开跑」：真正要挡住的是「全部 N 组一次性全报」，
    所以要求它**少于总组数**。早先要求 ≤ `jobs + 1`，在全量 `pytest -n auto` 负载下
    偶发误报（内部#123）：CBB_LZD 每组约 0.1 s，主线程打印结果滞后时，工作线程已经
    真的接手了后面几组，那些「开跑」不是谎报。
    """
    jobs = 2
    rc, out = _run_cli("--design", "CBB_LZD", "-j", str(jobs),
                       ledger=tmp_path / "p.json")
    assert rc == 0, out
    lines = out.splitlines()
    first_done = next(i for i, ln in enumerate(lines) if "PROVED" in ln)
    started_before = sum(1 for ln in lines[:first_done] if "开跑" in ln)
    total = sum(1 for ln in lines if "开跑" in ln)
    assert total > jobs + 1, (
        f"这一轮只有 {total} 组，测不出「排队」与「开跑」的区别\n{out}")
    assert started_before < total, (
        f"第一组完成之前 {total} 组的「开跑」已经全部打出，而并行度只有 {jobs} "
        f"—— 这一行打在了提交处，报的是排队不是开跑\n{out}")


# --- 多结构构件的结构间等价进账（equiv-cbb-structures，内部#66）--------------------------
#
# 结构间逐位等价是 PPA 对比的前提。每种结构对一份独立写的行为级参考证等价（不复用
# TOOL 结构，免得同源）；全零输入时计数 / 位置输出无意义，两侧经同一个掩码包装件比较。

@needs_yosys
@pytest.mark.parametrize("design, n", [("CBB_LZD", 30)])
def test_every_structure_of_a_cbb_is_proved_against_a_reference(design, n):
    declared = _declared(design)
    assert sum(len(c) for c in declared.values()) == n, declared
    _assert_proved(design)


@needs_yosys
@pytest.mark.parametrize("design, src, rtl, anchor, bug", [
    ("CBB_LZD", "cbb/cbb_lzd/rtl", "cbb_lzd.v", "assign pos    = ~lzd_cnt;", "assign pos    = lzd_cnt;"),
])
def test_a_wrong_structure_is_caught(tmp_path, design, src, rtl, anchor, bug):
    shutil.copytree(REPO_ROOT / src, tmp_path / "rtl")
    victim = tmp_path / "rtl" / rtl
    text = victim.read_text()
    assert text.count(anchor) == 1, f"注入锚点在 {rtl} 里不是恰好一处，夹具要更新"
    victim.write_text(text.replace(anchor, bug))
    ok, res = _prove(design, rtl_dir=tmp_path / "rtl", jobs=4)
    assert not ok, f"{design} 改坏了一种结构，等价证明却仍然通过"
