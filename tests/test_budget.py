"""本机 CPU / 内存预算（flow/budget.py，内部#359，cpu-budget）。

锁用桩 keel：PATH 前面放一个 `keel` 脚本，状态放在 STUB_KEEL_DIR 下 ——
`busy` 文件里的数字是「还要拒绝几次 acquire」（缺省不拒绝），`calls` 记每次调用的参数。
负载与内存门槛在子进程里用 KAIWU_MAX_LOAD / KAIWU_MAX_MEM_PRESSURE 放开（真机此刻多忙与本测无关），
等待逻辑在进程内换掉 load1 / mem_pressure / sleep / clock 来测。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGET = REPO_ROOT / "flow" / "budget.py"
sys.path.insert(0, str(REPO_ROOT))
from flow import budget  # noqa: E402

STUB_KEEL = r"""#!/bin/sh
d="$STUB_KEEL_DIR"
echo "$*" >> "$d/calls"
case "$1 $2" in
  "lock acquire")
    n=$(cat "$d/busy" 2>/dev/null || echo 0)
    if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$d/busy"; echo "held by kaiwu-other" >&2; exit 1; fi
    touch "$d/held"; exit 0 ;;
  "lock release")
    if [ -f "$d/release_fails" ]; then echo 'Group "dm-x--y" is not a valid name' >&2; exit 1; fi
    [ -f "$d/held" ] || exit 1
    rm -f "$d/held"; exit 0 ;;
  "lock list")
    echo '{"leases":[{"resource":"cpu-heavy","holder":"kaiwu-other","note":"iodeps: /x","expires":"2026-10-19T20:00:00Z"}]}' ;;
esac
"""


@pytest.fixture
def keel(tmp_path, monkeypatch):
    bindir, state = tmp_path / "bin", tmp_path / "state"
    bindir.mkdir()
    state.mkdir()
    k = bindir / "keel"
    k.write_text(STUB_KEEL)
    k.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_KEEL_DIR", str(state))
    monkeypatch.delenv("KAIWU_HEAVY_HELD", raising=False)  # conftest 默认当已持有
    monkeypatch.setenv("KAIWU_MAX_LOAD", "1e9")
    monkeypatch.setenv("KAIWU_MAX_MEM_PRESSURE", "4")
    return state


def _calls(state):
    p = state / "calls"
    return p.read_text().splitlines() if p.exists() else []


def _run(*args, **env):
    return subprocess.run([sys.executable, str(BUDGET), *args], capture_output=True, text=True,
                          env=dict(os.environ, **env))


# ---- jobs ----

def test_jobs_defaults_to_four_not_core_count():
    assert budget.jobs({}) == min(4, os.cpu_count())
    assert budget.jobs({}) < os.cpu_count()


def test_jobs_override_and_clamp():
    assert budget.jobs({"KAIWU_JOBS": "2"}) == 2
    assert budget.jobs({"KAIWU_JOBS": "0"}) == 1
    assert budget.jobs({"KAIWU_JOBS": "999"}) == os.cpu_count()


@pytest.mark.parametrize("bad", ["auto", "-1", "2.5"])
def test_jobs_rejects_non_integer(bad):
    with pytest.raises(budget.BudgetError):
        budget.jobs({"KAIWU_JOBS": bad})
    r = _run("jobs", KAIWU_JOBS=bad)
    assert r.returncode == 2 and "KAIWU_JOBS" in r.stderr


def test_jobs_cli_prints_default():
    env = {k: v for k, v in os.environ.items() if k != "KAIWU_JOBS"}
    r = subprocess.run([sys.executable, str(BUDGET), "jobs"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.strip() == "4"


# ---- run --heavy ----

def test_heavy_acquires_runs_and_releases(keel):
    r = _run("run", "--heavy", "unit", "--", "sh", "-c", "echo held=$KAIWU_HEAVY_HELD")
    assert r.returncode == 0, r.stderr
    assert "held=1" in r.stdout  # 子命令看得到已持有，不会再拿一次
    calls = _calls(keel)
    assert calls[0].startswith("lock acquire cpu-heavy --for 3h --note unit:"), calls
    assert calls[-1] == "lock release cpu-heavy", calls
    assert not (keel / "held").exists()


def test_heavy_releases_when_command_fails(keel):
    r = _run("run", "--heavy", "unit", "--", "sh", "-c", "exit 7")
    assert r.returncode == 7
    assert _calls(keel)[-1] == "lock release cpu-heavy"
    assert not (keel / "held").exists()


def test_heavy_times_out_with_holder_named(keel):
    (keel / "busy").write_text("99\n")
    r = _run("run", "--heavy", "unit", "--", "true", KAIWU_WAIT_MIN="0")
    assert r.returncode == 3, r.stderr
    assert "kaiwu-other" in r.stderr and "iodeps" in r.stderr
    assert not any(c.startswith("lock release") for c in _calls(keel))  # 没拿到就不放


def test_heavy_retries_until_lock_is_free(keel):
    (keel / "busy").write_text("2\n")
    said, slept = [], []
    with budget.heavy("unit", say=said.append, sleep=slept.append, clock=lambda: 0.0):
        assert os.environ["KAIWU_HEAVY_HELD"] == "1"
    assert len(slept) == 2 and all(s == budget.POLL_S for s in slept)
    assert all("kaiwu-other" in m for m in said)
    assert [c.split()[1] for c in _calls(keel) if c.startswith("lock acquire") or c.startswith("lock release")] \
        == ["acquire", "acquire", "acquire", "release"]
    assert "KAIWU_HEAVY_HELD" not in os.environ


def test_heavy_waits_for_load_and_memory(keel, monkeypatch):
    monkeypatch.delenv("KAIWU_MAX_LOAD")
    monkeypatch.delenv("KAIWU_MAX_MEM_PRESSURE")
    state = {"load": budget.ncpu() * 3.0, "mem": 2}
    monkeypatch.setattr(budget, "load1", lambda: state["load"])
    monkeypatch.setattr(budget, "mem_pressure", lambda: state["mem"])
    said = []

    def sleep(_):
        if state["load"] > budget.ncpu():
            state["load"] = 1.0  # 第一次等完负载降下来，内存压力仍是警告
        else:
            state["mem"] = 1

    with budget.heavy("unit", say=said.append, sleep=sleep, clock=lambda: 0.0):
        pass
    assert "负载" in said[0] and "内存压力警告" in said[0]
    assert "负载" not in said[1] and "内存" in said[1]
    assert sum(c.startswith("lock acquire") for c in _calls(keel)) == 1  # 门槛没过不去碰锁


def test_mem_pressure_reads_the_kernel_level():
    level = budget.mem_pressure()
    assert level in (None, 1, 2, 4)


def test_heavy_held_skips_the_lock(keel):
    r = _run("run", "--heavy", "unit", "--", "true", KAIWU_HEAVY_HELD="1")
    assert r.returncode == 0
    assert _calls(keel) == []


def test_heavy_without_keel_fails_instead_of_running_unqueued(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "KAIWU_HEAVY_HELD"}
    env["PATH"] = "/usr/bin:/bin"
    marker = tmp_path / "ran"
    r = subprocess.run([sys.executable, str(BUDGET), "run", "--heavy", "unit", "--", "touch", str(marker)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "keel" in r.stderr
    assert not marker.exists()


# ---- 接入 ----

def test_fast_check_takes_jobs_from_budget():
    text = (REPO_ROOT / "scripts" / "fast_check.sh").read_text()
    assert 'NJOBS="$("$PY" flow/budget.py jobs)"' in text
    # 一个组合同时起 iverilog 与 verilator：两个都在时组合数减半，进程总数不超过 KAIWU_JOBS
    assert '[ "$HAVE_IV" = 1 ] && [ "$HAVE_VL" = 1 ] && NJOBS=$(( NJOBS > 1 ? NJOBS / 2 : 1 ))' in text
    assert "hw.ncpu" not in text and "nproc" not in text


def test_make_heavy_targets_go_through_budget():
    for target in ("iodeps", "sweep"):
        r = subprocess.run(["make", "-n", "-f", "flow/Makefile", target, "DESIGN=CBB_LZD"], cwd=REPO_ROOT,
                           capture_output=True, text=True)
        cmds = [l for l in r.stdout.splitlines() if "budget.py" in l]
        assert any(f"run --heavy {target} --" in l for l in cmds), (target, r.stdout, r.stderr)


def _wait_for(cond, timeout=20.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_sigterm_releases_lock_and_stops_command(keel, tmp_path):
    """被 SIGTERM 停掉时照样放锁，命令也停下（内部#368：PM 10-19 停 merge_check 后锁没放）。"""
    import signal
    pidfile = tmp_path / "child.pid"
    p = subprocess.Popen([sys.executable, str(BUDGET), "run", "--heavy", "unit", "--",
                          "sh", "-c", f"echo $$ > {pidfile}; exec sleep 60"])
    assert _wait_for(lambda: (keel / "held").exists() and pidfile.exists() and pidfile.read_text().strip())
    child = int(pidfile.read_text())
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=60) == 128 + signal.SIGTERM
    assert not (keel / "held").exists() and _calls(keel)[-1] == "lock release cpu-heavy"
    assert _wait_for(lambda: subprocess.run(["kill", "-0", str(child)], capture_output=True).returncode != 0)


def test_failed_release_is_reported_not_swallowed(keel):
    """keel 释放失败时要报出来，命令自己的退出码不变（10-20 keel 建通知私聊组时组名超长，释放失败却没人知道）。"""
    (keel / "release_fails").write_text("")
    r = _run("run", "--heavy", "unit", "--", "sh", "-c", "exit 0")
    assert r.returncode == 0, r.stderr
    assert "释放 cpu-heavy 失败" in r.stderr and "not a valid name" in r.stderr, r.stderr
    assert "keel lock release cpu-heavy" in r.stderr   # 告诉人怎么手工处理



# ---- 续租（内部#375，budget-renew-fast-check-load 1.1）----

def test_heavy_renews_the_lease_while_the_command_runs(keel):
    r = _run("run", "--heavy", "unit", "--", "sleep", "1.5", KAIWU_RENEW_MIN=str(0.3 / 60))
    assert r.returncode == 0, r.stderr
    calls = _calls(keel)
    acquires = [c for c in calls if c.startswith("lock acquire cpu-heavy --for 3h")]
    assert len(acquires) >= 3, f"跑了 1.5 秒、每 0.3 秒续租一次，应有多次 acquire：{calls}"
    assert calls[-1] == "lock release cpu-heavy", "命令结束后不该再续租"


def test_a_failed_renewal_warns_and_the_command_finishes(keel):
    # 第一次 acquire 放行（拿锁），之后桩 keel 全部拒绝（续租失败）
    (keel / "busy").write_text("0\n")
    stub = keel.parent / "bin" / "keel"
    stub.write_text(STUB_KEEL.replace('touch "$d/held"; exit 0 ;;',
                                      'if [ -f "$d/held" ]; then echo "renew refused" >&2; exit 1; fi; touch "$d/held"; exit 0 ;;'))
    r = _run("run", "--heavy", "unit", "--", "sh", "-c", "sleep 1; echo done", KAIWU_RENEW_MIN=str(0.3 / 60))
    assert r.returncode == 0 and "done" in r.stdout, r.stderr
    assert "续租失败" in r.stderr and "照常" in r.stderr, r.stderr
    assert _calls(keel)[-1] == "lock release cpu-heavy"


# ---- fast_check 开跑前等负载（内部#382，budget-renew-fast-check-load 1.2）----

@pytest.fixture
def free(monkeypatch):
    """conftest 默认当已持有（KAIWU_HEAVY_HELD=1）、并关掉等负载；这里要测等待本身。"""
    monkeypatch.delenv("KAIWU_HEAVY_HELD", raising=False)
    monkeypatch.delenv("FAST_CHECK_NO_LOAD_WAIT", raising=False)


def _wait_load():
    w = getattr(budget, "wait_load", None)
    assert w is not None, "flow/budget.py 没有 wait_load：fast_check 开跑前不等负载（#382）"
    return w

def test_wait_load_waits_while_load_is_high_then_goes(monkeypatch, free):
    loads = iter([25.0, 18.0, 3.0])
    monkeypatch.setattr(budget, "load1", lambda: next(loads))
    monkeypatch.setenv("KAIWU_MAX_LOAD", "10")
    said, slept = [], []
    _wait_load()("fast_check", say=said.append, sleep=slept.append, clock=lambda: 0.0)
    assert len(slept) == 2 and len(said) == 2 and all("等负载" in m for m in said), said


def test_wait_load_gives_up_after_the_limit_and_runs_anyway(monkeypatch, free):
    monkeypatch.setattr(budget, "load1", lambda: 50.0)
    monkeypatch.setenv("KAIWU_MAX_LOAD", "10")
    monkeypatch.setenv("KAIWU_FASTCHECK_WAIT_MIN", "1")
    t = iter(range(0, 10_000, 30))
    said = []
    _wait_load()("fast_check", say=said.append, sleep=lambda s: None, clock=lambda: float(next(t)))
    assert "照跑" in said[-1] and "等负载" in said[0], said


@pytest.mark.parametrize("env", [{"KAIWU_HEAVY_HELD": "1"}, {"FAST_CHECK_NO_LOAD_WAIT": "1"}])
def test_wait_load_is_skipped_inside_a_heavy_job_or_when_switched_off(env):
    r = _run("wait-load", "fast_check", KAIWU_MAX_LOAD="0", KAIWU_FASTCHECK_WAIT_MIN="5", **env)
    assert r.returncode == 0 and r.stderr == "" and r.stdout == "", "wait-load 不认或没跳过（应不等负载、不打印）：" + r.stderr
