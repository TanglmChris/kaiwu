"""本机 CPU / 内存预算（内部#359，用户 2026-10-19：「mac 动不动就卡，让各 session 不要把 CPU 用太满，总要留点空闲空间」）。

    .venv/bin/python3 flow/budget.py jobs                                  # 打印默认并发（KAIWU_JOBS，默认 4）
    .venv/bin/python3 flow/budget.py run --heavy <名字> -- <命令…>          # 大活：等负载 / 内存、拿锁、跑（期间续租）、放锁
    .venv/bin/python3 flow/budget.py wait-load <名字>                      # 小活（fast_check）开跑前：只等负载，不拿锁（内部#382）

本机 10 核、16 GB。约定（docs/toolchain.md「CPU 预算」）：单个任务默认并发 4，全机重活合计 ≤ 6，大活排队。
锁 `cpu-heavy` 存在本仓 git 公共目录，排队范围是本仓所有 worktree；别的仓不经这把锁，靠 flow/cpu_watch.py 巡检点名（内部#375）。
- `jobs()`：默认 4，`KAIWU_JOBS` 覆盖，钳在 1..核数；fast_check、merge_check、review_prep 都从这里取，不再按核数满开。
- `heavy(name)`：先等 1 分钟负载 ≤ `KAIWU_MAX_LOAD`（默认核数）、内存压力不超过「正常」
  （macOS 的 `kern.memorystatus_vm_pressure_level`：1 正常、2 警告、4 严重；`KAIWU_MAX_MEM_PRESSURE` 可调，默认 1），
  再拿 keel 的共享资源租约 `cpu-heavy`（`--for 3h`，进程被杀时自动失效），持有期间每 `KAIWU_RENEW_MIN` 分钟（默认 30）
  续一次租、失败只告警（内部#375），跑完 `finally` 里释放。拿不到每 30 秒重试、
  打印持有者，等满 `KAIWU_WAIT_MIN` 分钟（默认 60）退出 3。已持有时（`KAIWU_HEAVY_HELD=1`，外层设）不再拿：
  同一角色重复 acquire 只是续期，内层一释放就把外层的锁放掉了。keel 不在 PATH 时失败，不悄悄不排队。
"""
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_JOBS = 4
LOCK = "cpu-heavy"
LEASE = "3h"
POLL_S = 30
RENEW_MIN = 30.0   # 持有期间每隔这么久续一次租（内部#375）；KAIWU_RENEW_MIN 可调


class BudgetError(RuntimeError):
    """参数写错或环境不对（退出 2）。"""


class WaitTimeout(RuntimeError):
    """等满时限仍没轮到（退出 3）。"""


def ncpu():
    return os.cpu_count() or 4


def jobs(env=None):
    env = os.environ if env is None else env
    raw = env.get("KAIWU_JOBS", "").strip()
    if not raw:
        return min(DEFAULT_JOBS, ncpu())
    if not raw.isdigit():
        raise BudgetError(f"KAIWU_JOBS={raw!r} 不是正整数")
    return max(1, min(int(raw), ncpu()))


def load1():
    return os.getloadavg()[0]


PRESSURE = {1: "正常", 2: "警告", 4: "严重"}


def mem_pressure():
    """macOS 内核自己判的内存压力级别（1 / 2 / 4）；读不到返回 None（只看负载）。

    不用 vm_stat 的空闲页数：本机平时 free + inactive 就只有 5 GB 上下（压缩内存与文件缓存不算在里面），
    按 GB 定门槛要么形同虚设、要么永远等（10-19 实测 6 GB 门槛在压力「正常」、系统空闲 64% 时一直不放行）。
    """
    try:
        out = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(out) if out.isdigit() else None


def _float_env(name, default):
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        raise BudgetError(f"{name}={raw!r} 不是数字") from None


def _keel():
    k = shutil.which("keel")
    if k is None:
        raise BudgetError("keel 不在 PATH：大活要经 keel lock 排队，不能不排队就跑（#359）")
    return k


def _holder(keel):
    r = subprocess.run([keel, "lock", "list", "--json"], capture_output=True, text=True)
    try:
        for lease in json.loads(r.stdout or "{}").get("leases", []):
            if lease.get("resource") == LOCK:
                return f"{lease.get('holder')}（{lease.get('note', '')}，到 {lease.get('expires', '?')}）"
    except ValueError:
        pass
    return "未知"


def _raise_exit(signum, frame):
    raise SystemExit(128 + signum)


@contextlib.contextmanager
def exit_on_term():
    """SIGTERM / SIGHUP 转成 SystemExit，让 finally 照常执行（放锁、删临时检出，内部#368）。

    Python 收到 SIGTERM 的默认动作是直接退出，finally 不跑。只在主线程、且信号还是默认处理时装，退出时恢复。
    """
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGHUP):
            if signal.getsignal(sig) is signal.SIG_DFL:
                old[sig] = signal.signal(sig, _raise_exit)
    try:
        yield
    finally:
        for sig, h in old.items():
            signal.signal(sig, h)


@contextlib.contextmanager
def heavy(name, say=print, sleep=time.sleep, clock=time.monotonic):
    """大活排队（D2–D5；本仓 worktree 之间）。被 SIGTERM 停掉也放锁（内部#368），持有期间续租（内部#375）。"""
    if os.environ.get("KAIWU_HEAVY_HELD") == "1":
        yield
        return
    with exit_on_term():
        with _queued(name, say, sleep, clock):
            yield


@contextlib.contextmanager
def _queued(name, say, sleep, clock):
    keel = _keel()
    wait_s = _float_env("KAIWU_WAIT_MIN", 60.0) * 60
    max_pressure = _float_env("KAIWU_MAX_MEM_PRESSURE", 1.0)
    max_load = _float_env("KAIWU_MAX_LOAD", float(ncpu()))
    start = clock()
    while True:
        why = []
        load = load1()
        if load > max_load:
            why.append(f"1 分钟负载 {load:.1f} > {max_load:g}")
        level = mem_pressure()
        if level is not None and level > max_pressure:
            why.append(f"内存压力{PRESSURE.get(level, level)}（级别 {level}）")
        if not why:
            note = f"{name}: {Path.cwd()}"
            r = subprocess.run([keel, "lock", "acquire", LOCK, "--for", LEASE, "--note", note],
                               capture_output=True, text=True)
            if r.returncode == 0:
                break
            why.append(f"{LOCK} 被 {_holder(keel)} 占着")
        waited = clock() - start
        if waited >= wait_s:
            raise WaitTimeout(f"{name}：等了 {waited / 60:.0f} 分钟仍没轮到 —— " + "；".join(why))
        say(f"budget：{name} 等待中（{'；'.join(why)}），{POLL_S} 秒后再看")
        sleep(POLL_S)
    old = os.environ.get("KAIWU_HEAVY_HELD")
    os.environ["KAIWU_HEAVY_HELD"] = "1"
    stop = threading.Event()
    renewer = threading.Thread(target=_renew, args=(keel, note, stop, say,
                                                    _float_env("KAIWU_RENEW_MIN", RENEW_MIN) * 60), daemon=True)
    renewer.start()
    try:
        yield
    finally:
        stop.set()
        renewer.join()
        if old is None:
            os.environ.pop("KAIWU_HEAVY_HELD", None)
        else:
            os.environ["KAIWU_HEAVY_HELD"] = old
        r = subprocess.run([keel, "lock", "release", LOCK], capture_output=True, text=True)
        if r.returncode != 0:   # 释放失败不改命令的退出码，但要说出来：锁会挂到租约过期（10-20 实撞，keel 建通知组失败）
            say(f"budget：释放 {LOCK} 失败（keel 退出码 {r.returncode}）：{(r.stderr or r.stdout).strip()}；"
                f"请手工 keel lock release {LOCK}，不行就等租约（{LEASE}）过期，并在群里说一声")


def wait_load(name, say=print, sleep=time.sleep, clock=time.monotonic):
    """小活开跑前等 1 分钟负载降到 KAIWU_MAX_LOAD（默认核数）以下；不拿锁、不看内存（内部#382，D3）。

    最多等 KAIWU_FASTCHECK_WAIT_MIN 分钟（默认 10），等满照跑：推送不该一直卡住。已在大活里（KAIWU_HEAVY_HELD=1）
    或设了 FAST_CHECK_NO_LOAD_WAIT=1 时不等。
    """
    if os.environ.get("KAIWU_HEAVY_HELD") == "1" or os.environ.get("FAST_CHECK_NO_LOAD_WAIT") == "1":
        return
    max_load = _float_env("KAIWU_MAX_LOAD", float(ncpu()))
    wait_s = _float_env("KAIWU_FASTCHECK_WAIT_MIN", 10.0) * 60
    start = clock()
    while (load := load1()) > max_load:
        waited = clock() - start
        if waited >= wait_s:
            say(f"budget：{name} 等满 {wait_s / 60:g} 分钟负载仍高（{load:.1f} > {max_load:g}），照跑")
            return
        say(f"budget：{name} 等负载（1 分钟负载 {load:.1f} > {max_load:g}），{POLL_S} 秒后再看")
        sleep(min(POLL_S, wait_s - waited))


def _renew(keel, note, stop, say, every_s):
    """持有期间定期再 acquire 一次（同一持有者就是续租），长于租期的大活也不丢锁（内部#375）。失败只告警。"""
    while not stop.wait(every_s):
        r = subprocess.run([keel, "lock", "acquire", LOCK, "--for", LEASE, "--note", note],
                           capture_output=True, text=True)
        if r.returncode != 0:
            say(f"budget：续租失败（{LOCK}，keel 退出码 {r.returncode}）：{(r.stderr or r.stdout).strip()}；"
                f"命令照常跑完，{LEASE} 后租约可能被别人拿走，请在群里说一声")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("jobs", help="打印默认并发")
    w = sub.add_parser("wait-load", help="小活开跑前等负载（不拿锁）")
    w.add_argument("name", help="写进提示里的名字，如 fast_check")
    r = sub.add_parser("run", help="大活：排队后跑命令")
    r.add_argument("--heavy", required=True, metavar="名字", help="写进锁的说明，如 iodeps、regress")
    r.add_argument("command", nargs=argparse.REMAINDER, help="-- 之后是要跑的命令")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "jobs":
            print(jobs())
            return 0
        if a.cmd == "wait-load":
            wait_load(a.name, say=lambda m: print(m, file=sys.stderr, flush=True))
            return 0
        cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
        if not cmd:
            raise BudgetError("run --heavy 后面要跟 -- <命令…>")
        with heavy(a.heavy, say=lambda m: print(m, file=sys.stderr, flush=True)):
            p = subprocess.Popen(cmd)
            try:
                return p.wait()
            except BaseException:  # 被停掉：先让命令自己收尾（它若也是本仓的 Python 工具，会放锁、删检出），再放锁
                p.terminate()
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    p.kill()
                raise
    except BudgetError as e:
        print(f"budget：{e}", file=sys.stderr)
        return 2
    except WaitTimeout as e:
        print(f"budget：{e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
