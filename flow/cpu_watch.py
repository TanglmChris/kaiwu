"""全机 CPU 巡检（内部#359，cpu-watch；用户 2026-10-19：全机 CPU 由 kaiwu-flow 兼管，只点名、不动别人的进程）。

    .venv/bin/python3 flow/cpu_watch.py                # 打印此刻谁在占 CPU（按仓 / worktree / 角色归）
    .venv/bin/python3 flow/cpu_watch.py --post <群>    # 连续两次采样超载时在这个 keel chat 群里点名（主机定时任务用）

归因：沿父进程链找第一个工作目录在 `$KAIWU_WATCH_ROOT`（默认是工作区根：本仓 git 公共目录的上两级，不写死目录名，
见 `default_root`）下的进程，归到它所在的仓或
worktree（`<仓>/.claude/worktrees/<名>`）；merge_check 建在系统临时目录里的检出，归到启动它的会话。
kaiwu 这类用 keel chat 的仓，worktree 再按 `.git/keel-chat/roles.json` 换成角色名（keel 内部文件，读不到用路径）。

点名：1 分钟负载超过 `KAIWU_WATCH_LOAD`（默认核数）且上次采样也超，才点合计 ≥ 1 个核的前 5 家；同一家 30 分钟内
不重复；「其他」（系统进程、桌面应用）不点。状态存 `~/.cache/kaiwu/cpu_watch.json`。本脚本只读，不碰任何进程。
主机定时任务见 flow/cpu_watch_agent.sh。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OTHER = "其他"
MIN_CPU = 100.0       # 合计至少一个核才点名
HOLDER_CPU = 600.0    # 持有 cpu-heavy 的是排过队的大活，超过全机重活上限（6 核，内部#359）才点
TOP = 5
QUIET_S = 30 * 60     # 同一家 30 分钟内不重复点名
STATE = Path.home() / ".cache" / "kaiwu" / "cpu_watch.json"


def parse_ps(text):
    out = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        out.append({"pid": int(parts[0]), "ppid": int(parts[1]), "cpu": float(parts[2].replace(",", ".")),
                    "rss": int(parts[3]), "cmd": parts[4].strip()})
    return out


def parse_lsof(text):
    out, pid = {}, None
    for line in text.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            out[pid] = line[1:]
    return out


def owner_of(path, root):
    """工作目录 → 归属键（仓或 worktree 的绝对路径）；不在 root 下返回 None。"""
    try:
        rel = Path(path).relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    if len(parts) >= 4 and parts[1:3] == (".claude", "worktrees"):
        return str(Path(root, *parts[:4]))
    return str(Path(root, parts[0]))


def _roles(keys, root):
    names = {}
    for key in keys:
        repo = Path(key).relative_to(root).parts[0]
        f = Path(root, repo, ".git", "keel-chat", "roles.json")
        try:
            role = json.loads(f.read_text()).get(key)
        except (OSError, ValueError, AttributeError):
            role = None
        names[key] = role if isinstance(role, str) and role else str(Path(key).relative_to(root))
    return names


def attribute(procs, cwds, root):
    """{归属名: {cpu, n, top}}：沿 ppid 找第一个有归属的工作目录。"""
    root = Path(root)
    by_pid = {p["pid"]: p for p in procs}
    cache = {}

    def key(pid):
        seen = []
        while pid in by_pid and pid not in cache and pid not in seen:
            seen.append(pid)
            k = owner_of(cwds[pid], root) if pid in cwds else None
            if k:
                cache[pid] = k
                break
            pid = by_pid[pid]["ppid"]
        k = cache.get(pid)
        for p in seen:
            cache[p] = k
        return k

    groups = {}
    for p in procs:
        k = key(p["pid"])
        g = groups.setdefault(k, {"cpu": 0.0, "n": 0, "top": "", "_max": -1.0})
        g["cpu"] += p["cpu"]
        g["n"] += 1
        if p["cpu"] > g["_max"]:
            g["_max"], g["top"] = p["cpu"], p["cmd"]
    names = _roles([k for k in groups if k], root)
    out = {}
    for k, g in groups.items():
        g.pop("_max")
        name = names[k] if k else OTHER
        if name in out:  # 两个路径映射到同一角色时合并
            out[name]["cpu"] += g["cpu"]
            out[name]["n"] += g["n"]
        else:
            out[name] = g
    return out


def sample(root):
    env = dict(os.environ, LC_ALL="C")
    procs = parse_ps(subprocess.run(["ps", "-Ao", "pid=,ppid=,pcpu=,rss=,command="],
                                    capture_output=True, text=True, env=env).stdout)
    by_pid = {p["pid"]: p for p in procs}
    want = set()
    for p in procs:
        if p["cpu"] >= 1.0:
            pid = p["pid"]
            while pid in by_pid and pid not in want and pid > 1:
                want.add(pid)
                pid = by_pid[pid]["ppid"]
    cwds = {}
    if want:
        r = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(map(str, sorted(want)))],
                           capture_output=True, text=True)
        cwds = parse_lsof(r.stdout)
    return os.getloadavg()[0], os.cpu_count() or 1, attribute(procs, cwds, root)


def decide(load, ncpu, owners, state, now, limit=None, holders=()):
    """(点名消息或 None, 新状态)。连续两次超载才点名，同一家 QUIET_S 内不重复；holders 是持有 cpu-heavy 的归属名。"""
    limit = float(ncpu) if limit is None else limit
    over = load > limit
    st = {"over": over, "named": dict(state.get("named", {}))}
    if not (over and state.get("over")):
        return None, st
    picks = [(n, g) for n, g in sorted(owners.items(), key=lambda kv: -kv[1]["cpu"])
             if n != OTHER and g["cpu"] >= (HOLDER_CPU if n in holders else MIN_CPU) and now - st["named"].get(n, -1e18) >= QUIET_S][:TOP]
    if not picks:
        return None, st
    for n, _ in picks:
        st["named"][n] = now
    lines = [f"kaiwu-flow CPU 点名：1 分钟负载 {load:.1f}（{ncpu} 核，连续两次采样超过 {limit:g}）。下面几家合计各占一个核以上，"
             "请自己停或降并发（并发 ≤4、负载 >10 先等、全量测试全机一次一个，#359）；kaiwu-flow 不动你的进程。"]
    for n, g in picks:
        held = "（持有 cpu-heavy，排过队，但超过了全机重活 6 核的上限）" if n in holders else ""
        lines.append(f"- {n}{held}：{g['cpu']:.0f}%，{g['n']} 个进程，最重的是 `{g['top'][:80]}`")
    return "\n".join(lines), st


def heavy_holders(root):
    """持有 keel 租约 cpu-heavy 的归属名（角色名与 worktree 相对路径都算）；读不到返回空。"""
    try:
        r = subprocess.run(["keel", "lock", "list", "--json"], capture_output=True, text=True, timeout=30)
        leases = json.loads(r.stdout or "{}").get("leases", [])
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return set()
    out = set()
    for lease in leases:
        if lease.get("resource") != "cpu-heavy":
            continue
        out.update(x for x in (lease.get("role"), lease.get("holder")) if x)
        k = owner_of(lease.get("worktree") or "", Path(root))
        if k:
            out.add(str(Path(k).relative_to(root)))
    return out


def render(load, ncpu, owners):
    rows = sorted(owners.items(), key=lambda kv: -kv[1]["cpu"])
    out = [f"1 分钟负载 {load:.1f}，{ncpu} 核", "", "| 归属 | CPU | 进程 | 最重的命令 |", "|---|---|---|---|"]
    out += [f"| {n} | {g['cpu']:.0f}% | {g['n']} | `{g['top'][:80]}` |" for n, g in rows if g["cpu"] >= 1.0]
    return "\n".join(out) + "\n"


def default_root():
    """归因范围：`KAIWU_WATCH_ROOT`，没设就是工作区根——本脚本所在仓的 git 公共目录（`<仓>/.git`）往上两级，
    主 checkout 与 worktree 一样。不写死工作区目录名：工作区目录改过名，用户 2026-10-25 定所有仓都不依赖这个名字。
    推不出来就退出 2，不回退到任何写死的路径（落空了归因全为空，也不报错）。"""
    if os.environ.get("KAIWU_WATCH_ROOT"):
        return Path(os.environ["KAIWU_WATCH_ROOT"])
    r = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--path-format=absolute",
                        "--git-common-dir"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        print("cpu_watch：推不出工作区根（本脚本不在 git 仓里？），用 KAIWU_WATCH_ROOT 指定", file=sys.stderr)
        sys.exit(2)
    return Path(r.stdout.strip()).parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--post", metavar="群", help="连续两次超载时在这个 keel chat 群里点名")
    a = ap.parse_args(argv)
    root = default_root()
    load, ncpu, owners = sample(root)
    print(render(load, ncpu, owners), end="")
    if not a.post:
        return 0
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    limit = float(os.environ.get("KAIWU_WATCH_LOAD", ncpu))
    msg, state = decide(load, ncpu, owners, state, time.time(), limit, heavy_holders(root))
    if msg:
        r = subprocess.run(["keel", "chat", "post", a.post, msg, "--not-a-loop", "定时 CPU 巡检"],
                           capture_output=True, text=True)
        print(msg if r.returncode == 0 else f"cpu_watch：发群消息失败：{r.stderr.strip()}", file=sys.stderr)
        if r.returncode != 0:
            return 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
