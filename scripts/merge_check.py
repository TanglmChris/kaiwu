"""推 main 前的合并检查（内部#344，merge-check-script）：

    .venv/bin/python3 scripts/merge_check.py --base origin/main --head <合并结果的提交>

在 head 的临时检出里跑 `./scripts/fast_check.sh` 与全量 `pytest tests/ -n <KAIWU_JOBS，默认 4>`，在 base 与 head 的临时检出里各收一次
`pytest --collect-only` 的用例 ID，打三行结论，再列删去 / 新增 / 改名 / 搬家的用例 ID（同一「文件::函数」里删去不多于新增的，
按参数化 ID 改名配对，不算删去，内部#385；剩下的删去在新增里有只差文件路径的，按搬家配对，也不算删去，内部#336）。退出码：三项都合格 0（fast_check 0、pytest 无失败无跳过、用例 ID 没有删去），
否则 1；检出或工具环境出错 2。

EDA 工具（yosys / verilator / sta）不在 PATH 时先补 `~/tools/env.sh`，补完仍缺就退出 2 —— 不带 EDA PATH 的 pytest
会静默跳过一百多条用例。要求的工具清单可用环境变量 MERGE_CHECK_TOOLS（空格分隔）改。

全量模式是全机大活（内部#359）：开跑前经 flow/budget.py 等负载 / 内存、拿 keel 租约 `cpu-heavy`，跑完释放；等不到退出 3。
轻量模式（只改文档）不拿锁，只像 fast_check 那样等负载（内部#440）。

通过的结果按「base 树、head 树、跑检查的脚本、EDA 工具、Python 环境」记在 git 公共目录的 kaiwu-merge-check/ 下，所有 worktree
共用；同一组输入再跑直接复用（打印「复用」与当时的三行结论，不排队、不建检出），`--no-cache` 强制重跑。只记通过的（内部#379）。

base..head 只改了文档（DOC_SUFFIXES 的文件、且都在 DOC_DIRS 下）时走轻量：pytest 串行只跑 DOC_TESTS（环境变量
MERGE_CHECK_DOC_TESTS 可覆盖），fast_check 带 --docs-only（不跑 RTL lint），清单里的文件在 head 上缺了就回退全量；`--full` 强制全量。新增读仓内文档的测试要加进 DOC_TESTS。
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from at_ref import CheckoutError, checkout  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flow import budget  # noqa: E402

TOOLS = ("yosys", "verilator", "sta")
TOOLS_ENV = Path.home() / "tools" / "env.sh"
PYTEST = [".venv/bin/python3", "-m", "pytest", "tests/", "-p", "no:cacheprovider"]
# 只改文档的判据与轻量清单：用户 2026-10-20 定（内部#379）。test_fast_check（202 s）与 test_review_prep（96 s）
# 测的是工具代码（读 adder32 的 RTL / 豁免、用夹具），不读被改的文档，实测后用户定从清单里拿掉。
DOC_DIRS = ("designs", "cbb", "docs", "knowledge", "team")
DOC_SUFFIXES = (".md", ".drawio", ".png", ".svg", ".jpg", ".jpeg", ".gif")
DOC_TESTS = ("tests/test_team_layout.py", "tests/test_spec_diff.py", "tests/test_export.py", "tests/test_leak_scan.py")
# 读入集合缓存（flow/synth/synth.py）：带 -n 时 tests/conftest.py 先算全部顶层，新检出里没有就单核从头算，
# 10-20 实测 544 s（内部#384）。缓存按内容核键，拷进去的过期条目照样重算（D7）。
SOURCE_SETS = Path("runs") / ".source_sets"


def tools_env():
    """(环境, 缺的工具)。缺工具时 source ~/tools/env.sh 再看一次。"""
    need = os.environ.get("MERGE_CHECK_TOOLS", " ".join(TOOLS)).split()
    env = dict(os.environ)
    missing = [t for t in need if not shutil.which(t, path=env.get("PATH"))]
    if missing and TOOLS_ENV.exists():
        r = subprocess.run(["bash", "-c", f'source "{TOOLS_ENV}" >/dev/null 2>&1; env -0'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            env = dict(kv.split("=", 1) for kv in r.stdout.split("\0") if "=" in kv)
            env.setdefault("MERGE_CHECK_TOOLS", " ".join(need))
            missing = [t for t in need if not shutil.which(t, path=env.get("PATH"))]
    return env, missing


def collect_ids(wt, env):
    r = subprocess.run(PYTEST + ["--collect-only", "-q"], cwd=wt, env=env, capture_output=True, text=True)
    return {line.strip() for line in r.stdout.splitlines() if "::" in line}, r


def pair_renames(gone, new):
    """(删去, 新增, 改名)。按「文件::函数」（去掉参数化的 [...]）分组：一组里删去不多于新增时，删去的按排序与新增一一
    配成改名；删去多于新增（含整个函数没了）时整组照算删去（内部#385，用户 2026-10-21 定同函数内自动配对）。"""
    def group(t):
        return t.split("[", 1)[0]
    by_g, by_n = {}, {}
    for t in gone:
        by_g.setdefault(group(t), []).append(t)
    for t in new:
        by_n.setdefault(group(t), []).append(t)
    still_gone, renamed, added = [], [], []
    for k in sorted(set(by_g) | set(by_n)):
        g, n = sorted(by_g.get(k, [])), sorted(by_n.get(k, []))
        if g and len(g) <= len(n):
            renamed += list(zip(g, n))
            added += n[len(g):]
        else:
            still_gone += g
            added += n
    return still_gone, added, renamed


def pair_moves(gone, new):
    """(删去, 新增, 搬家)。删去的 ID 在新增里有一条只差文件路径（第一个 :: 之后逐字相同，含类名与 [...]）时配成搬家，
    按排序一一配对，一条新增只配一次（内部#336，用户 2026-10-21 定补跨文件搬家配对：拆测试文件时用例原样换文件）。"""
    def key(t):
        return t.split("::", 1)[1] if "::" in t else t
    free = {}
    for t in sorted(new):
        free.setdefault(key(t), []).append(t)
    still_gone, moved = [], []
    for t in sorted(gone):
        cand = free.get(key(t))
        if cand:
            moved.append((t, cand.pop(0)))
        else:
            still_gone.append(t)
    taken = {t for _, t in moved}
    return still_gone, [t for t in new if t not in taken], moved


def pytest_summary(text):
    """pytest -q 末行的 passed / failed / skipped / error 计数。"""
    counts = {k: 0 for k in ("passed", "failed", "skipped", "error")}
    last = [l for l in text.splitlines() if re.search(r"\b(passed|failed|error|skipped)\b", l)]
    for n, k in re.findall(r"(\d+) (passed|failed|skipped|errors?)", last[-1] if last else ""):
        counts["error" if k.startswith("error") else k] += int(n)
    return counts


RUNNER = (Path(__file__).resolve(), Path(__file__).resolve().parent / "at_ref.py",
          Path(__file__).resolve().parents[1] / "flow" / "budget.py")


def seed_source_sets(wt):
    """把调用方 worktree 的读入集合缓存拷进检出（拷不软链：缓存写法不是原子的，检出里重算的不写回调用方）。"""
    top = _git("rev-parse", "--show-toplevel")
    src = Path(top) / SOURCE_SETS if top else None
    if not src or not src.is_dir():
        return
    dst = Path(wt) / SOURCE_SETS
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.json"):
        shutil.copy2(f, dst / f.name)


def _git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def check_mode(base, head, force_full, env):
    """(模式, 首行, 轻量时跑的测试)。模式是 full 或 docs（D4、D5）。"""
    if force_full:
        return "full", "模式：全量（--full）", None
    out = _git("diff", "--name-only", "--no-renames", base, head)
    if out is None:
        return "full", "模式：全量", None
    files = [f for f in out.splitlines() if f]
    if any(f.split("/", 1)[0] not in DOC_DIRS or "/" not in f or not f.lower().endswith(DOC_SUFFIXES) for f in files):
        return "full", "模式：全量", None
    tests = env.get("MERGE_CHECK_DOC_TESTS", " ".join(DOC_TESTS)).split()
    gone = [t for t in tests if subprocess.run(["git", "cat-file", "-e", f"{head}:{t}"], capture_output=True).returncode != 0]
    if gone or not tests:
        return "full", f"模式：全量（只改文档，但文档测试清单在 head 上缺 {'、'.join(gone) or '全部'}，回退全量）", None
    return "docs", f"模式：轻量（只改文档，{len(files)} 个文件）", tests


def reuse_key(base, head, env, mode="full"):
    """(键, 键的各项)。base / head 取树，同内容不同提交号也命中；工具按解析后的路径、大小、mtime 认（D1）。"""
    base_tree, head_tree = _git("rev-parse", f"{base}^{{tree}}"), _git("rev-parse", f"{head}^{{tree}}")
    if not base_tree or not head_tree:
        return None, None
    tools = {}
    for t in env.get("MERGE_CHECK_TOOLS", " ".join(TOOLS)).split():
        w = shutil.which(t, path=env.get("PATH"))
        st = os.stat(os.path.realpath(w)) if w else None
        tools[t] = [os.path.realpath(w), st.st_size, st.st_mtime_ns] if w else None
    pip = subprocess.run([".venv/bin/python3", "-m", "pip", "freeze"], capture_output=True, text=True)
    parts = {"base_tree": base_tree, "head_tree": head_tree, "mode": mode,
             "runner": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RUNNER if p.exists()},
             "tools": tools, "python": hashlib.sha256(pip.stdout.encode()).hexdigest()}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest(), parts


def reuse_dir():
    d = _git("rev-parse", "--git-common-dir")
    return (Path(d).resolve() / "kaiwu-merge-check") if d else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="合入前（比用例 ID 的基准），通常是 origin/main")
    ap.add_argument("--head", default="HEAD", help="合入后的提交（默认 HEAD）")
    ap.add_argument("--no-cache", action="store_true", help="不复用以前通过的结果，照常跑（照样记下这次的结果）")
    ap.add_argument("--full", action="store_true", help="只改文档也跑全量 pytest")
    a = ap.parse_args(argv)
    env, missing = tools_env()
    mode, mode_line, a.doc_tests = check_mode(a.base, a.head, a.full, env)
    key, parts = reuse_key(a.base, a.head, env, mode) if not missing else (None, None)
    store = reuse_dir()
    rec = store / f"{key}.json" if key and store else None
    if rec and rec.exists() and not a.no_cache:
        old = json.loads(rec.read_text())
        print(mode_line)
        print(f"复用：{old['when']} {old['cwd']} 在 base {old['base'][:12]} / head {old['head'][:12]} 上的通过结果"
              f"（同一组 base 树、head 树、检查脚本、工具与 Python 环境；--no-cache 可重跑）")
        print("\n".join(old["lines"]))
        return 0
    lines = []
    print(mode_line, flush=True)
    try:
        say = lambda m: print(m, file=sys.stderr, flush=True)   # noqa: E731
        # 轻量模式不拿 cpu-heavy：只串行跑文档用例与不跑 lint 的 fast_check，占用与 fast_check 同量级，
        # 按它的办法等负载即可（内部#440：只改一行文档曾排在别人的全量回归后面约 40 分钟）。全量模式照旧排队。
        lock = budget.heavy("merge_check", say=say) if mode == "full" else contextlib.nullcontext()
        if mode != "full":
            budget.wait_load("merge_check", say=say)
        with lock:
            rc = _run(a, env, missing, lines)
        if rc == 0 and rec:
            rec.parent.mkdir(parents=True, exist_ok=True)
            rec.write_text(json.dumps({"when": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                                       "cwd": os.getcwd(), "base": _git("rev-parse", a.base), "head": _git("rev-parse", a.head),
                                       "key": parts, "lines": lines}, ensure_ascii=False, indent=1))
        return rc
    except budget.BudgetError as e:
        print(f"merge_check: {e}", file=sys.stderr)
        return 2
    except budget.WaitTimeout as e:
        print(f"merge_check: {e}", file=sys.stderr)
        return 3


def _run(a, env, missing, lines):
    def say(text):
        print(text)
        lines.append(text)
    if missing:
        print(f"merge_check: 补过 {TOOLS_ENV} 之后仍缺 {'、'.join(missing)}；不带 EDA PATH 的 pytest 会静默跳过用例，不跑",
              file=sys.stderr)
        return 2
    try:
        with checkout(a.base) as (wt, base_sha):
            base_ids, r = collect_ids(wt, env)
            if r.returncode != 0:
                print(f"merge_check: base {base_sha[:12]} 收集用例失败：\n{r.stdout[-2000:]}{r.stderr[-2000:]}", file=sys.stderr)
                return 2
        with checkout(a.head) as (wt, head_sha):
            print(f"base {base_sha}\nhead {head_sha}", flush=True)
            seed_source_sets(wt)
            # 轻量模式不跑 RTL lint（D8）；head 上的 fast_check 不认这个开关时照常全跑
            fc = subprocess.run(["./scripts/fast_check.sh", *(["--docs-only"] if a.doc_tests else [])],
                                cwd=wt, env=env, capture_output=True, text=True)
            # 轻量串行跑：带 -n 时 tests/conftest.py 先算全部顶层的读入集合，临时检出里没缓存，实测 544 s（D5）
            cmd = PYTEST + ["-n", str(budget.jobs())] if not a.doc_tests else [*PYTEST[:3], *a.doc_tests, *PYTEST[4:]]
            pt = subprocess.run(cmd + ["-q"], cwd=wt, env=env, capture_output=True, text=True)
            head_ids, r = collect_ids(wt, env)
    except CheckoutError as e:
        print(f"merge_check: {e}", file=sys.stderr)
        return 2
    c = pytest_summary(pt.stdout)
    gone, new, renamed = pair_renames(sorted(base_ids - head_ids), sorted(head_ids - base_ids))
    gone, new, moved = pair_moves(gone, new)
    ok_fc = fc.returncode == 0
    ok_pt = pt.returncode == 0 and c["failed"] == 0 and c["error"] == 0 and c["skipped"] == 0 and c["passed"] > 0
    ok_ids = not gone
    say(f"{'ok  ' if ok_fc else 'FAIL'}  fast_check rc={fc.returncode}")
    say(f"{'ok  ' if ok_pt else 'FAIL'}  pytest {c['passed']} passed, {c['failed']} failed, {c['skipped']} skipped"
          + (f", {c['error']} error" if c["error"] else "") + f"（rc={pt.returncode}）")
    say(f"{'ok  ' if ok_ids else 'FAIL'}  用例 ID 删 {len(gone)}、增 {len(new)}、改名 {len(renamed)}、搬家 {len(moved)}"
        f"（base {len(base_ids)} → head {len(head_ids)}）")
    for t in gone:
        say(f"  删  {t}")
    for t in new:
        say(f"  增  {t}")
    for old, t in renamed:
        say(f"  改名  {old} → {t}")
    for old, t in moved:
        say(f"  搬家  {old} → {t}")
    if not ok_fc:
        print("--- fast_check 末尾 ---\n" + "\n".join(fc.stdout.splitlines()[-30:]))
    if not ok_pt:
        print("--- pytest 末尾 ---\n" + "\n".join(pt.stdout.splitlines()[-30:]))
    return 0 if ok_fc and ok_pt and ok_ids else 1


if __name__ == "__main__":
    sys.exit(main())
