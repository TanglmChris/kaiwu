"""全机 CPU 巡检（flow/cpu_watch.py，内部#359，cpu-watch）。

夹具按本机真实输出造：`ps -Ao pid=,ppid=,pcpu=,rss=,command=` 在中文 locale 下 %CPU 用逗号作小数点、
命令带空格；`lsof -a -d cwd -Fpn -p …` 每个进程是一行 `p<pid>`、一行 `fcwd`、一行 `n<路径>`。
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from flow import cpu_watch as cw  # noqa: E402

PS = """    1     0   0,5  11984 /sbin/launchd
  604     1  26,5  63904 /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer
 5000     1   2,0 460608 claude bg-spare
 5100  5000   0,3  20000 /bin/zsh -c .venv/bin/python3 scripts/merge_check.py --base origin/main
 5101  5100   1,2  90000 .venv/bin/python3 scripts/merge_check.py --base origin/main
 5102  5101  95,0 300000 .venv/bin/python3 -m pytest tests/ -q -n 4
 5103  5102  88,5 280000 .venv/bin/python3 -c import xdist worker
 5104  5102  91,0 281000 .venv/bin/python3 -c import xdist worker
 6000     1  70,2 130000 npm test
 6001  6000  60,1 100000 node --test test/a.test.js
 7000     1  40,0  50000 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT
"""


def _lsof(cwds):
    return "".join(f"p{pid}\nfcwd\nn{path}\n" for pid, path in cwds.items())


def _root(tmp_path):
    root = tmp_path / "workspace"   # 工作区目录名不重要（用户 10-25：仓不依赖工作区目录名）
    kc = root / "demo-repo" / ".git" / "keel-chat"
    kc.mkdir(parents=True)
    wt = root / "demo-repo" / ".claude" / "worktrees"
    (kc / "roles.json").write_text(json.dumps({str(wt / "demo_pm"): "kaiwu-pm-demo"}))
    return root


def _cwds(root):
    pm = root / "demo-repo" / ".claude" / "worktrees" / "demo_pm"
    tmpwt = "/private/var/folders/92/x/T/at_ref_2j6n0rsl/wt"
    return {
        1: "/", 604: "/", 5000: str(pm), 5100: str(pm), 5101: str(pm), 5102: tmpwt, 5103: tmpwt, 5104: tmpwt,
        6000: str(root / "keel" / ".claude" / "worktrees" / "keel-maint-0cb8d4" / "src"),
        6001: str(root / "keel" / ".claude" / "worktrees" / "keel-maint-0cb8d4"),
        7000: "/",
    }


def test_parse_ps_reads_comma_decimals_and_commands():
    procs = cw.parse_ps(PS)
    p = {x["pid"]: x for x in procs}
    assert p[5102]["cpu"] == 95.0 and p[5102]["ppid"] == 5101
    assert p[1]["cpu"] == 0.5
    assert p[5102]["cmd"] == ".venv/bin/python3 -m pytest tests/ -q -n 4"
    assert cw.parse_ps(PS.replace(",", "."))[1]["cpu"] == 26.5


def test_parse_lsof():
    assert cw.parse_lsof("p12\nfcwd\nn/a b/c\np13\nfcwd\nn/\n") == {12: "/a b/c", 13: "/"}


def test_attribute_walks_parents_and_names_roles(tmp_path):
    root = _root(tmp_path)
    owners = cw.attribute(cw.parse_ps(PS), _cwds(root), root)
    pm = "kaiwu-pm-demo"
    keel = "keel/.claude/worktrees/keel-maint-0cb8d4"
    assert set(owners) == {pm, keel, cw.OTHER}, owners
    # 临时检出里的 pytest 与 worker 沿父进程链归到启动 merge_check 的 PM worktree
    assert round(owners[pm]["cpu"], 1) == round(2.0 + 0.3 + 1.2 + 95.0 + 88.5 + 91.0, 1)
    assert owners[pm]["n"] == 6
    assert owners[pm]["top"] == ".venv/bin/python3 -m pytest tests/ -q -n 4"
    # 子目录也归到 worktree 一级；没有 roles.json 的仓用路径
    assert round(owners[keel]["cpu"], 1) == 130.3 and owners[keel]["n"] == 2
    assert round(owners[cw.OTHER]["cpu"], 1) == 67.0


def _owners():
    return {"kaiwu-pm-demo": {"cpu": 278.0, "n": 6, "top": "pytest -n 4"},
            "keel/.claude/worktrees/keel-maint-0cb8d4": {"cpu": 130.3, "n": 2, "top": "npm test"},
            "kaiwu-design-demo": {"cpu": 60.0, "n": 1, "top": "verilator"},
            cw.OTHER: {"cpu": 300.0, "n": 40, "top": "WindowServer"}}


def test_decide_needs_two_consecutive_samples_then_rate_limits():
    msg, st = cw.decide(30.0, 10, _owners(), {}, now=1000.0)
    assert msg is None and st["over"] is True  # 第一次超载只记下
    msg, st = cw.decide(31.0, 10, _owners(), st, now=1300.0)
    assert msg is not None
    assert "kaiwu-pm-demo" in msg and "278%" in msg and "pytest -n 4" in msg
    assert "keel/.claude/worktrees/keel-maint-0cb8d4" in msg and "130%" in msg
    assert "kaiwu-design-demo" not in msg  # 不足一个核
    assert cw.OTHER not in msg  # 「其他」不点名
    assert "#359" in msg and "31.0" in msg
    msg2, st = cw.decide(31.0, 10, _owners(), st, now=1300.0 + 29 * 60)
    assert msg2 is None  # 30 分钟内同一家不重复
    msg3, st = cw.decide(31.0, 10, _owners(), st, now=1300.0 + 31 * 60)
    assert msg3 is not None and "kaiwu-pm-demo" in msg3


def test_heavy_lock_holder_named_only_above_six_cores():
    """持有 cpu-heavy 的会话是排过队的大活：278% 不点，超过 600% 才点并注明持锁（10-19 20:35 误点了 PM 的 merge_check）。"""
    _, st = cw.decide(30.0, 10, _owners(), {}, now=0.0, holders={"kaiwu-pm-demo"})
    msg, st = cw.decide(30.0, 10, _owners(), st, now=300.0, holders={"kaiwu-pm-demo"})
    assert "kaiwu-pm-demo" not in msg and "keel-maint" in msg
    big = dict(_owners(), **{"kaiwu-pm-demo": {"cpu": 680.0, "n": 30, "top": "verilator_bin"}})
    msg, _ = cw.decide(30.0, 10, big, {"over": True}, now=0.0, holders={"kaiwu-pm-demo"})
    assert "kaiwu-pm-demo（持有 cpu-heavy" in msg and "680%" in msg


def test_decide_resets_when_load_drops():
    _, st = cw.decide(30.0, 10, _owners(), {}, now=0.0)
    msg, st = cw.decide(4.0, 10, _owners(), st, now=300.0)
    assert msg is None and st["over"] is False
    msg, st = cw.decide(30.0, 10, _owners(), st, now=600.0)
    assert msg is None  # 降下来之后又只超了一次


def test_table_lists_owners_by_cpu():
    text = cw.render(12.5, 10, _owners())
    lines = [l for l in text.splitlines() if l.startswith("|") and "%" in l]
    assert re.search(r"kaiwu-pm-demo", lines[0]) or cw.OTHER in lines[0]
    assert "12.5" in text


def test_never_touches_other_processes():
    src = (REPO_ROOT / "flow" / "cpu_watch.py").read_text()
    for bad in ("os.kill", "SIGSTOP", "SIGKILL", "renice", "taskpolicy", '"kill"', "'kill'"):
        assert bad not in src, bad


# ---- 默认工作区根由仓库推出（cpu-watch-root-from-repo，用户 10-25：工作区目录可能改名）----

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _default_root(flow_dir, **env):
    e = {k: v for k, v in os.environ.items() if k != "KAIWU_WATCH_ROOT"}
    e.update(env)
    code = f"import sys; sys.path.insert(0, {str(flow_dir)!r}); import cpu_watch; print(cpu_watch.default_root())"
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=e, cwd="/")


def _ws_repo(tmp_path):
    """工作区目录故意换一个名字；里面一个仓、一个 worktree，各放一份真 cpu_watch.py。"""
    ws = tmp_path / "ws-renamed"
    repo = ws / "demo-repo"
    (repo / "flow").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "flow" / "cpu_watch.py", repo / "flow" / "cpu_watch.py")
    env = dict(os.environ, **_GIT_ENV)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "x"],
                 ["worktree", "add", "-q", str(repo / ".claude" / "worktrees" / "w1")]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)
    return ws.resolve(), repo


def test_default_root_is_the_workspace_above_the_repo(tmp_path):
    ws, repo = _ws_repo(tmp_path)
    for flow_dir in (repo / "flow", repo / ".claude" / "worktrees" / "w1" / "flow"):
        r = _default_root(flow_dir)
        assert r.returncode == 0 and Path(r.stdout.strip()) == ws, f"{flow_dir}：{r.stdout}{r.stderr}"


def test_watch_root_env_still_overrides(tmp_path):
    ws, repo = _ws_repo(tmp_path)
    r = _default_root(repo / "flow", KAIWU_WATCH_ROOT=str(tmp_path / "elsewhere"))
    assert r.returncode == 0 and Path(r.stdout.strip()) == tmp_path / "elsewhere", r.stdout + r.stderr


def test_outside_a_git_repo_it_says_so_instead_of_guessing(tmp_path):
    lone = tmp_path / "lone" / "flow"
    lone.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "flow" / "cpu_watch.py", lone / "cpu_watch.py")
    r = _default_root(lone, GIT_CEILING_DIRECTORIES=str(tmp_path))
    assert r.returncode == 2 and "KAIWU_WATCH_ROOT" in r.stderr, r.stdout + r.stderr
