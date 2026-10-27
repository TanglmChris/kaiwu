"""开源预检一条命令（open-export-precheck，内部#441）。

    .venv/bin/python3 flow/export/open_check.py --ref <提交> [--out <空目录>] [--quick]

按顺序做评审要跑的机械检查，打一张逐项结论表（ok / FAIL / warn）：
- 导出：调 `export.py`（含泄漏扫描），block 命中或白名单无效即 FAIL，后面不再跑；
- 悬空引用（warn）：导出文本里形如路径的词，在被扫提交的树里存在、却不在开源集合里；或只出现在闭源文件里的代码文件名
  （`.py` / `.v` / `.sv` / `.sh` / `.tcl`，私有脚本名那一类；`experiments.jsonl` 这类通用的数据文件名不算）。
  白名单本身永远闭源，引用它是有意的，不报；
- 闭源归档引用（FAIL）：上面的悬空引用里，目标在 `openspec/changes/archive/` 下的单列，命中即 FAIL，不中断后面的步骤（内部#444）。
  归档路径里带 `*` 的按树展开，匹配到的全是闭源内容才算；别处的通配（`results/*/experiments.jsonl` 这类讲概念的写法）不展开；
- 死链（warn）：导出目录里 Markdown 的相对链接目标不存在；代码块与行内代码里的、含 `<`、`…` 的模板占位不报；
- 导出目录 `git init -b main` 并提交一次（公开仓的读者拿到的是 git 仓库）。
`--quick` 到此为止。完整模式接着照 quickstart 第 1 步在导出目录从零建 venv（不复用、不软链），EDA 工具不在 PATH 时
补 `~/tools/env.sh`、仍缺退出 2；以激活该 venv 的 PATH 跑 fast_check 与 `pytest -m 'not flow'`。pytest 的跳过只认
「不在导出集合」（读闭源记录 / 白名单的用例），其余跳过判 FAIL。完整模式经 flow/budget.py 拿 cpu-heavy，等不到退出 3。
任一 FAIL 退出 1，全部合格退出 0；warn 不影响退出码。
"""
import argparse
import fnmatch
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leak_scan  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import merge_check  # noqa: E402  tools_env / pytest_summary
from flow import budget  # noqa: E402  merge_check 已把仓库根放进 sys.path

EXPORT = Path(__file__).resolve().parent / "export.py"
ALLOWED_SKIP = "不在导出集合"      # 读闭源记录 / 白名单的用例，跳过原因里都带这一句（open-export「导出结果自足」）
_SKIPPED = re.compile(r"^SKIPPED \[\d+\] (.+)$", re.M)
_PATHLIKE = re.compile(r"[A-Za-z0-9_.*\-]+(?:/[A-Za-z0-9_.*\-]+)+")     # 带 `*` 的是通配写法，归档路径的按树展开
ARCHIVE = "openspec/changes/archive/"     # 归档 change：有开源的、有闭源的，引用闭源的那些判 FAIL
_FILENAME = re.compile(r"(?<![\w/.\-])[A-Za-z0-9_\-]+\.(?:py|v|sv|sh|tcl)(?![\w/\-])")   # 只看代码文件名，同 closed_vocab
_INLINE_CODE = re.compile(r"`[^`\n]*`")    # 反引号里的「链接」是例子，Markdown 不渲染
_MDLINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]\n]*\]\(([^)\s]+)\)")


def _text_files(out):
    for p in sorted(out.rglob("*")):
        if ".git" in p.relative_to(out).parts or p.is_symlink() or not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data[:8192]:
            continue
        yield p.relative_to(out).as_posix(), data.decode("utf-8", errors="replace").splitlines()


def dangling_refs(repo, ref, out):
    """[(文件, 行号, 引用)]：导出文本里指向闭源文件 / 目录的路径，或只有闭源文件才有的文件名。"""
    manifest = leak_scan.load_manifest(repo, ref)
    listed = [p for p in leak_scan._git(repo, "ls-tree", "-r", "--name-only", "-z", ref).decode().split("\0") if p]
    opened = set(leak_scan.open_files(repo, ref, manifest))
    closed = set(listed) - opened - {leak_scan.MANIFEST}
    open_dirs = {"/".join(p.split("/")[:k]) for p in opened for k in range(1, p.count("/") + 1)}
    closed_dirs = {"/".join(p.split("/")[:k]) for p in closed for k in range(1, p.count("/") + 1)} - open_dirs
    names = ({p.rsplit("/", 1)[-1] for p in closed} - {p.rsplit("/", 1)[-1] for p in opened}
             - {leak_scan.MANIFEST.rsplit("/", 1)[-1]})
    closed_all, open_all = closed | closed_dirs, opened | open_dirs

    def dangling(tok):
        if "*" not in tok:
            return tok in closed or tok.rstrip("/") in closed_dirs
        if not tok.startswith(ARCHIVE):
            return False
        pat = tok.rstrip("/")       # fnmatch 的 * 也跨 /，只会多匹配，「全闭源」更难成立
        return (any(fnmatch.fnmatchcase(p, pat) for p in closed_all)
                and not any(fnmatch.fnmatchcase(p, pat) for p in open_all))

    hits = []
    for path, lines in _text_files(out):
        for no, line in enumerate(lines, 1):
            found = []
            for tok in _PATHLIKE.findall(line):
                tok = tok.strip(".").removeprefix("./")
                if tok != leak_scan.MANIFEST and dangling(tok):
                    found.append(tok)
            found += [t for t in _FILENAME.findall(line) if t in names and not any(t in f for f in found)]
            hits += [(path, no, t) for t in dict.fromkeys(found)]
    return hits


def dead_links(out):
    """[(文件, 行号, 目标)]：Markdown 相对链接目标不存在；代码块与行内代码里的、模板占位（含 `<` 或 `…`）不算。"""
    hits = []
    for path, lines in _text_files(out):
        if not path.endswith(".md"):
            continue
        in_code = False
        for no, line in enumerate(lines, 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for m in _MDLINK.finditer(_INLINE_CODE.sub("", line)):
                target = m.group(1) or m.group(2)
                if re.match(r"^[a-z]+:", target) or target.startswith("#") or "<" in target or "…" in target:
                    continue
                if not (out / path).parent.joinpath(target.split("#")[0]).exists():
                    hits.append((path, no, target))
    return hits


def skip_reasons(pytest_output):
    """(合格, 不认的跳过)：`pytest -rs` 的每条 SKIPPED 原因都要含 ALLOWED_SKIP。"""
    bad = [r for r in _SKIPPED.findall(pytest_output) if ALLOWED_SKIP not in r]
    return not bad, bad


def full_checks(out, python):
    """完整模式：从零建 venv、补 EDA 环境、fast_check、pytest。返回退出码（0 / 1 / 2）。"""
    venv = out / ".venv"
    for cmd in ([python, "-m", "venv", str(venv)], [str(venv / "bin" / "pip"), "install", "-q", "-r", "requirements.txt"]):
        r = subprocess.run(cmd, cwd=out, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAIL  建环境：{' '.join(cmd[:3])} 退出 {r.returncode}")
            print("\n".join("  " + l for l in (r.stdout + r.stderr).strip().splitlines()[-10:]))
            return 1
    env, missing = merge_check.tools_env()
    if missing:
        print(f"FAIL  EDA 工具：补过 {merge_check.TOOLS_ENV} 之后仍缺 {'、'.join(missing)}；不带它们 pytest 会静默跳过用例")
        return 2
    env = {**env, "VIRTUAL_ENV": str(venv), "PATH": f"{venv / 'bin'}:{env.get('PATH', '')}"}   # 等同 source .venv/bin/activate
    ver = subprocess.run(["python3", "--version"], cwd=out, env=env, capture_output=True, text=True).stdout.strip()
    print(f"ok    建环境：{venv}（PATH 上的 python3 = {ver}）")
    fc = subprocess.run(["./scripts/fast_check.sh"], cwd=out, env=env, capture_output=True, text=True)
    print(f"{'ok  ' if fc.returncode == 0 else 'FAIL'}  fast_check rc={fc.returncode}")
    if fc.returncode != 0:
        print("\n".join("  " + l for l in fc.stdout.splitlines() if l.startswith("FAIL")))
    pt = subprocess.run(["python3", "-m", "pytest", "tests/", "-q", "-n", str(budget.jobs()), "-m", "not flow",
                         "-p", "no:cacheprovider", "-rs"], cwd=out, env=env, capture_output=True, text=True)
    c = merge_check.pytest_summary(pt.stdout)
    skips_ok, bad = skip_reasons(pt.stdout)
    ok_pt = pt.returncode == 0 and c["failed"] == 0 and c["error"] == 0 and c["passed"] > 0 and skips_ok
    print(f"{'ok  ' if ok_pt else 'FAIL'}  pytest {c['passed']} passed, {c['failed']} failed, {c['skipped']} skipped"
          + (f", {c['error']} error" if c["error"] else "") + f"（rc={pt.returncode}；跳过只认「{ALLOWED_SKIP}」）")
    for r in bad:
        print(f"  不认的跳过：{r}")
    return 0 if fc.returncode == 0 and ok_pt else 1


def git_init(out):
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.name=open_check", "-c", "user.email=open_check@localhost", "commit", "-qm", "open_check"]):
        subprocess.run(["git", "-C", str(out), *cmd], check=True, capture_output=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(leak_scan.REPO_ROOT))
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--out", help="导出目录，必须不存在或为空（默认新建临时目录）")
    ap.add_argument("--quick", action="store_true", help="只做导出、悬空引用、死链与 git init")
    ap.add_argument("--python", default="python3.11", help="建 venv 用的解释器（quickstart 要求 ≥ 3.11）")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="open_check-"))
    print(f"open_check：{a.ref} → {out}")

    exp = subprocess.run([sys.executable, str(EXPORT), "--repo", a.repo, "--ref", a.ref, "--out", str(out)],
                         capture_output=True, text=True)
    last = (exp.stdout.strip().splitlines() or [""])[-1]
    if exp.returncode != 0:
        print(f"FAIL  导出：{last}")
        print("\n".join("  " + l for l in (exp.stdout + exp.stderr).strip().splitlines()[-20:]))
        return 1
    print(f"ok    导出：{last}")

    refs = dangling_refs(a.repo, a.ref, out)
    archive = [h for h in refs if h[2].startswith(ARCHIVE)]
    for level, name, hits in (("FAIL", "闭源归档引用", archive),
                              ("warn", "悬空引用", [h for h in refs if h not in archive]),
                              ("warn", "死链", dead_links(out))):
        print(f"{level if hits else 'ok  '}  {name} {len(hits)} 处")
        for path, no, target in hits:
            print(f"  {path}:{no}: {target}")
    failed = 1 if archive else 0

    git_init(out)
    print("ok    导出目录已 git init（main，1 个提交）")
    if a.quick:
        return failed
    try:
        with budget.heavy("open_check", say=lambda m: print(m, file=sys.stderr, flush=True)):
            return full_checks(out, a.python) or failed
    except budget.BudgetError as e:
        print(f"open_check: {e}", file=sys.stderr)
        return 2
    except budget.WaitTimeout as e:
        print(f"open_check: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
