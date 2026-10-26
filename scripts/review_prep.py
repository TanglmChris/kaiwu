#!/usr/bin/env python3
"""评审开工的机械检查一键入口（内部#196，review-prep）：

    .venv/bin/python3 scripts/review_prep.py --rev <被评提交> --top <顶层> [--prev <上一轮被评提交>] [--out <文件>]

在被评提交的临时检出里：
1. 跑该提交自己的 `scripts/fast_check.sh`，记退出码与 lint 摘要行；
2. 不带豁免的 lint：命令与 fast_check 相同（`-Wall -Wno-DECLFILENAME -DCBB_PARAM_CHK_ON`），只是去掉全部 `waivers.vlt`；
   默认参数一行，该提交的 fast_check 参数组合一行（每类给最小～最大）。`--no-param-chk` 去掉宏，复现以前手跑的口径；
3. 给了 `--prev` 时，lint 豁免相对上一轮的增删，只换了 `-file` 的（代码搬家）单独算；
4. LRS / LLD（CBB 是 spec）的版本、行数、SHA256。

输出一张能直接贴进评审清单「所评版本」表的 Markdown，跑完删掉临时检出。源文件、参数组合、设计根都用被评提交
**自己的**流程代码取（旧提交的代码与现在不同）。只是报告：被评提交 fast_check 失败不算本脚本失败，退出 0；
检出失败或参数错误退出 2。以前每轮评审手工凑这套命令（内部#196），rtl-r2 手跑 lint 没带宏，多报了 3 条 UNUSEDPARAM。
"""
import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from at_ref import CheckoutError, checkout, git  # noqa: E402
from merge_check import tools_env  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flow import budget  # noqa: E402

LINT = ["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME"]
_WAIVER_FILE = re.compile(r"(flow/lint|(designs|cbb)/[^/]+)/waivers\.vlt$")
_FILE_OPT = re.compile(r'\s-file\s+"[^"]*"')
_WARN = re.compile(r"^%Warning-([A-Z0-9_]+):", re.M)
_VER = re.compile(r"^\|\s*v(\d+)\.(\d+)\s*\|", re.M)

# 在被评提交的检出里、用它自己的流程代码取：源文件、include、设计根、fast_check 的参数组合（D1、D2）
_PROBE = r"""
import itertools, json, os, sys, yaml
sys.path.insert(0, ".")
from flow.paths import include_dirs, resolve_design_root, rtl_candidates
top = sys.argv[1]
root = resolve_design_root(top)
cfg = (yaml.safe_load(open(root / "params.yaml")) or {})["tops"][top] or {}
how = "默认参数"
combos = []
try:
    from flow.param_exclude import fast_check_combos
    combos = fast_check_combos(top, cfg)[0]
    how = "fast_check_combos"
except ImportError:
    try:
        from flow.param_exclude import apply
        params = cfg.get("params") or {}
        names = list(params)
        combos = [dict(zip(names, c)) for c in itertools.product(*(params[n]["values"] for n in names))]
        combos = apply(top, params, cfg.get("exclude"), combos)[0]
        how = "叉乘 + param_exclude.apply"
    except ImportError:
        pass
print(json.dumps(dict(srcs=[os.path.relpath(p) for p in rtl_candidates(top)],
                      incs=["-I" + os.path.relpath(d) for d in include_dirs(top)],
                      root=os.path.relpath(root), combos=combos, how=how)))
"""


def waiver_lines(sha):
    """{(文件, 归一后的 lint_off 行)}：flow/lint/waivers.vlt 与 <设计树>/*/waivers.vlt。"""
    out = set()
    for f in git("ls-tree", "-r", "--name-only", sha).stdout.split():
        if _WAIVER_FILE.fullmatch(f):
            out.update((f, " ".join(ln.split())) for ln in git("show", f"{sha}:{f}").stdout.splitlines()
                       if ln.startswith("lint_off"))
    return out


def waiver_diff(old, new):
    """增删里「规则与 -match 相同、只换了 -file」的配成一对记为换文件（D4）。"""
    added, removed = sorted(new - old), sorted(old - new)
    key = lambda item: (item[0], _FILE_OPT.sub("", item[1]))  # noqa: E731
    pool = collections.defaultdict(list)
    for item in removed:
        pool[key(item)].append(item)
    moved, still_added = [], []
    for item in added:
        if pool.get(key(item)):
            moved.append((pool[key(item)].pop(0), item))
        else:
            still_added.append(item)
    still_removed = [i for lst in pool.values() for i in lst]
    return dict(added=still_added, removed=sorted(still_removed), moved=moved)


def tally(text):
    return dict(collections.Counter(_WARN.findall(text)))


def doc_version(text):
    vers = [(int(a), int(b)) for a, b in _VER.findall(text)]
    return f"v{max(vers)[0]}.{max(vers)[1]}" if vers else None


def _fmt_tally(t):
    if not t:
        return "0 条"
    return f"{sum(t.values())} 条 = " + " + ".join(f"{n} {k}" for k, n in sorted(t.items(), key=lambda kv: (-kv[1], kv[0])))


def _lint(wt, env, top, info, params, param_chk):
    cmd = LINT + (["-DCBB_PARAM_CHK_ON"] if param_chk else []) + ["--top-module", top]
    cmd += [f"-G{k}={v}" if isinstance(v, int) or str(v).lstrip("-").isdigit() else f'-G{k}="{v}"'
            for k, v in (params or {}).items()]
    r = subprocess.run(cmd + info["incs"] + info["srcs"], cwd=wt, env=env, capture_output=True, text=True)
    return tally(r.stdout + r.stderr)


def prepare(rev, top, prev=None, param_chk=True, jobs=None):
    env, missing = tools_env()
    if missing:
        raise CheckoutError(f"EDA 工具不在 PATH：{' '.join(missing)}（先 source ~/tools/env.sh）")
    rows = []
    with checkout(rev) as (wt, sha):
        probe = subprocess.run([str(wt / ".venv/bin/python3"), "-c", _PROBE, top], cwd=wt, env=env,
                               capture_output=True, text=True)
        if probe.returncode != 0:
            raise CheckoutError(f"在 {sha[:8]} 上取 {top} 的源文件 / 参数组合失败：{probe.stderr.strip()[-500:]}")
        info = json.loads(probe.stdout.strip().splitlines()[-1])
        rows.append(("被评提交", f"`{rev}` @ `{sha}`"))
        for doc in ("lrs", "lld", "spec"):
            p = wt / info["root"] / f"{doc}.{top}.md"
            if p.exists():
                text = p.read_text(encoding="utf-8")
                rows.append((f"`{doc}.{top}.md`", f"{doc_version(text) or '（没有版本表）'}，{len(text.splitlines())} 行，"
                                                  f"SHA256 `{hashlib.sha256(p.read_bytes()).hexdigest()}`"))
        fc = subprocess.run(["./scripts/fast_check.sh"], cwd=wt, env=env, capture_output=True, text=True)
        lint_lines = [ln.strip() for ln in (fc.stdout + fc.stderr).splitlines()
                      if re.search(rf"\bRTL lint {re.escape(top)}（", ln)]
        rows.append(("fast_check", f"在被评提交上 `./scripts/fast_check.sh` 退出 {fc.returncode}"
                                   + ("；" + "；".join(lint_lines) if lint_lines else "")))
        mac = "" if param_chk else "，不带 `-DCBB_PARAM_CHK_ON`"
        rows.append(("无豁免 lint（默认参数）",
                     f"`verilator --lint-only -Wall` 不带 waivers{mac}：{_fmt_tally(_lint(wt, env, top, info, None, param_chk))}"))
        if info["combos"]:
            with ThreadPoolExecutor(max_workers=jobs or budget.jobs()) as ex:
                per = list(ex.map(lambda c: _lint(wt, env, top, info, c, param_chk), info["combos"]))
            cats = sorted({k for t in per for k in t})
            span = "、".join(f"{k} {min(t.get(k, 0) for t in per)}～{max(t.get(k, 0) for t in per)}" for k in cats) or "全部 0 条"
            totals = [sum(t.values()) for t in per]
            rows.append((f"无豁免 lint（{len(per)} 个参数组合）",
                         f"按 {info['how']} 取组合{mac}；每组合合计 {min(totals)}～{max(totals)} 条；各类 {span}"))
        else:
            rows.append(("无豁免 lint（参数组合）", "被评提交没有 fast_check_combos / param_exclude.apply，只跑了默认参数"))
    if prev:
        r = git("rev-parse", "-q", "--verify", f"{prev}^{{commit}}")
        if r.returncode != 0:
            raise CheckoutError(f"上一轮提交 {prev} 不存在（先 git fetch？）")
        old, new = waiver_lines(r.stdout.strip()), waiver_lines(sha)
        d = waiver_diff(old, new)
        detail = "".join(f"<br>+ `{f}`：`{l}`" for f, l in d["added"]) + \
            "".join(f"<br>− `{f}`：`{l}`" for f, l in d["removed"])
        rows.append(("豁免增减", f"相对 `{prev}`：{len(old)} → {len(new)} 条，净 {len(new) - len(old):+d}"
                                 f"（新增 {len(d['added'])}、删除 {len(d['removed'])}、换文件 {len(d['moved'])}）{detail}"))
    return rows


def render(rows):
    return "| 项 | 内容 |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rev", required=True, help="被评提交")
    ap.add_argument("--top", required=True, help="被测顶层")
    ap.add_argument("--prev", help="上一轮的被评提交：列出 lint 豁免的增减")
    ap.add_argument("--out", help="表另存到这个文件")
    ap.add_argument("--no-param-chk", action="store_true", help="无豁免 lint 不带 -DCBB_PARAM_CHK_ON（复现以前手跑的口径）")
    ap.add_argument("--jobs", type=int, help="逐组合 lint 的并发数（默认 KAIWU_JOBS，即 4，#359）")
    a = ap.parse_args(argv)
    try:
        with budget.heavy("review_prep", say=lambda m: print(m, file=sys.stderr, flush=True)):   # 全机大活（内部#359）
            rows = prepare(a.rev, a.top, a.prev, param_chk=not a.no_param_chk, jobs=a.jobs)
    except (CheckoutError, budget.BudgetError) as e:
        print(f"review_prep：{e}", file=sys.stderr)
        return 2
    except budget.WaitTimeout as e:
        print(f"review_prep：{e}", file=sys.stderr)
        return 3
    table = render(rows)
    print(table, end="")
    if a.out:
        Path(a.out).write_text(table, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
