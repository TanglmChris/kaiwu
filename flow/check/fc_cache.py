"""fast_check 通过结果的复用（内部#382，budget-renew-fast-check-load D4 / D5）。

    "$PY" flow/check/fc_cache.py key [--docs-only]     # 可复用时打印键、退出 0；不可复用时打印原因到 stderr、退出 1
    "$PY" flow/check/fc_cache.py get <键>              # 命中：打印「复用：…」与当时的覆盖摘要、退出 0；没有：退出 1
    "$PY" flow/check/fc_cache.py put <键> <摘要文件>   # 记下一次通过（只在 fast_check 退出 0 时调）

键是 HEAD 树、相对本地 main 的 merge-base、参数、iverilog / verilator（解析后的路径、大小、mtime）、Python 环境
（pip freeze 与版本）的 sha256。只在工作区干净时可复用：没有未提交的改动，设计根下也没有被忽略的散落文件
（设计根洁净度检查看得到它们），且没设 FAST_CHECK_ALLOW_MISSING_TOOLS（降级运行的结果不复用）。
记录放在 git 公共目录下，所有 worktree 共用；fast_check.sh 与它调的检查脚本都在 HEAD 树里。
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = ("iverilog", "verilator")
DESIGN_TREES = ("designs", "cbb")


def _git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def why_not_cacheable(env=None):
    env = os.environ if env is None else env
    if env.get("FAST_CHECK_ALLOW_MISSING_TOOLS") == "1":
        return "设了 FAST_CHECK_ALLOW_MISSING_TOOLS（降级运行不复用）"
    if _git("status", "--porcelain") != "":
        return "工作区有未提交的改动"
    if _git("status", "--porcelain", "--ignored", "--", *DESIGN_TREES) != "":
        return "设计根下有被忽略的散落文件"
    return None


def key_parts(docs_only, env=None):
    env = os.environ if env is None else env
    tools = {}
    for t in TOOLS:
        w = shutil.which(t, path=env.get("PATH"))
        st = os.stat(os.path.realpath(w)) if w else None
        tools[t] = [os.path.realpath(w), st.st_size, st.st_mtime_ns] if w else None
    pip = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    return {"head_tree": _git("rev-parse", "HEAD^{tree}"), "merge_base": _git("merge-base", "HEAD", "main"),
            "docs_only": bool(docs_only), "tools": tools,
            "python": [sys.version, hashlib.sha256(pip.encode()).hexdigest()]}


def key_of(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def store():
    d = _git("rev-parse", "--git-common-dir")
    return Path(d).resolve() / "kaiwu-fast-check" if d else None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else ""
    if cmd == "key":
        why = why_not_cacheable()
        if why:
            print(why, file=sys.stderr)
            return 1
        parts = key_parts("--docs-only" in argv[1:])
        if not parts["head_tree"]:
            print("不在 git 仓库里", file=sys.stderr)
            return 1
        print(key_of(parts))
        return 0
    s = store()
    if cmd == "get" and len(argv) == 2:
        p = s / f"{argv[1]}.json" if s else None
        if not p or not p.exists():
            return 1
        rec = json.loads(p.read_text())
        print(f"复用：{rec['time']} {rec['cwd']} 在 HEAD 树 {rec['head_tree'][:12]}（merge-base "
              f"{(rec.get('merge_base') or '无')[:12]}）上的通过结果（同一份内容、检查脚本、工具与 Python 环境；--no-cache 可重跑）")
        print(rec["summary"], end="")
        return 0
    if cmd == "put" and len(argv) == 3 and s:
        s.mkdir(parents=True, exist_ok=True)
        rec = {"time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "cwd": os.getcwd(),
               "head_tree": _git("rev-parse", "HEAD^{tree}"), "merge_base": _git("merge-base", "HEAD", "main"),
               "summary": Path(argv[2]).read_text()}
        tmp = s / f".{argv[1]}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        tmp.replace(s / f"{argv[1]}.json")
        return 0
    print(__doc__.split("\n\n")[0], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
