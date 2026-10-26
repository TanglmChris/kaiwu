"""在一个提交的临时检出里跑命令（内部#332，run-by-point-name D3）：

    .venv/bin/python3 scripts/at_ref.py --ref <提交> -- <命令…>
    make -f flow/Makefile depth DESIGN=<顶层> POINT=<点名> REF=<提交>     # Makefile 经这里转一次
    ./scripts/fast_check.sh --rev <提交>                                # 内部#344

`git worktree add --detach` 到临时目录，软链主仓的 `.venv`，核检出是干净的，在那里跑命令，打印 `ref <完整提交号>`，
最后删掉临时 worktree（命令失败也删）。退出码：命令自己的；提交不存在或检出不干净为 2。
`checkout(ref)` 给 scripts/merge_check.py 复用（内部#344）。

以前量某个提交的级数要手工建 detached worktree、软链 .venv、抄参数（内部#332）。

子命令的环境里去掉 make 传下来的 MAKEFLAGS / MFLAGS / MAKELEVEL / MAKEOVERRIDES，以及 MAKEFLAGS 里列出的命令行变量
（GNU make 3.81 实测：`make … REF=<提交>` 的 REF 既写进 MAKEFLAGS，也导出成环境变量）：不清掉，检出里的子 make
又看到 REF、再开一层 at_ref，10-21 无限递归 872 层、每层一份检出，写满了磁盘（内部#397）。
兜底：同一个仓的同一个提交已经在检出里跑着（KAIWU_AT_REF 记着），再嵌套一层就退出 2。
"""
import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


class CheckoutError(Exception):
    pass


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _raise_exit(signum, frame):
    raise SystemExit(128 + signum)


@contextlib.contextmanager
def _exit_on_term():
    """SIGTERM / SIGHUP 转成 SystemExit，让下面删检出的 finally 照常执行（内部#368；与 flow/budget.py 的 exit_on_term 同一做法）。"""
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
def checkout(ref, cwd=None):
    """ref 的临时 detached 检出：yield (检出路径, 完整提交号)；退出时删掉（出错、被 SIGTERM 停掉也删）。"""
    with _exit_on_term():
        with _checkout(ref, cwd) as got:
            yield got


@contextlib.contextmanager
def _checkout(ref, cwd=None):
    r = git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}", cwd=cwd)
    if r.returncode != 0:
        raise CheckoutError(f"提交 {ref} 不存在（先 git fetch？）")
    sha = r.stdout.strip()
    main_root = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd).stdout.strip()).parent
    wt = Path(tempfile.mkdtemp(prefix="at_ref_")) / "wt"
    try:
        # add 也在 try 里：add 进行中被 SIGTERM 打断，git 留下一个锁着（initializing）的检出，同样要删（内部#368）
        add = git("worktree", "add", "--detach", str(wt), sha, cwd=cwd)
        if add.returncode != 0:
            raise CheckoutError(f"建临时 worktree 失败：{add.stderr.strip()}")
        venv = main_root / ".venv"
        if venv.exists():
            # 绝对链接是有意的：临时检出跑完就删，撑不到工作区改名；相对链接从 /var（→ /private/var）算会指错
            (wt / ".venv").symlink_to(venv)
        dirty = git("status", "--porcelain", cwd=wt).stdout.strip()
        if dirty:
            raise CheckoutError(f"{sha} 的检出不干净：\n{dirty}")
        yield wt, sha
    finally:
        git("worktree", "remove", "--force", "--force", str(wt), cwd=cwd)  # 两个 --force 才删得掉锁着的检出
        git("worktree", "prune", cwd=cwd)
        shutil.rmtree(wt.parent, ignore_errors=True)   # mkdtemp 的那一层也删，不留空的 at_ref_*（内部#397）


def _make_vars(environ):
    """make 传给子进程的变量名：它自己的几个，加上 MAKEFLAGS 里 `--` 之后列出的命令行变量（`s -- REF=abc POINT=x`）。"""
    names = {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES"}
    flags = environ.get("MAKEFLAGS", "")
    if " -- " in f" {flags} ":
        tail = f" {flags} ".split(" -- ", 1)[1]
        names |= {w.split("=", 1)[0] for w in tail.split() if "=" in w}
    return names


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", required=True, help="要检出的提交（任何 git 认的写法）")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- 之后是要跑的命令")
    a = ap.parse_args(argv)
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.error("要在 -- 之后给出命令")
    r = git("rev-parse", "-q", "--verify", f"{a.ref}^{{commit}}")
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    key = f"{common}@{r.stdout.strip()}"
    nested = os.environ.get("KAIWU_AT_REF", "").split(os.pathsep)
    if r.returncode == 0 and key in nested:
        print(f"at_ref: 嵌套——已经在 {r.stdout.strip()} 的临时检出里跑着，又要检出同一个提交；"
              "多半是 make 的 MAKEFLAGS 把 REF 带进了子 make（#397）", file=sys.stderr)
        return 2
    env = {k: v for k, v in os.environ.items() if k not in _make_vars(os.environ)}
    env["KAIWU_AT_REF"] = os.pathsep.join([*filter(None, nested), key])
    try:
        with checkout(a.ref) as (wt, sha):
            print(f"ref {sha}", flush=True)
            return subprocess.run(cmd, cwd=wt, env=env).returncode
    except CheckoutError as e:
        print(f"at_ref: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
