"""签名逐作业比对（内部#224，team/roles/kaiwu-design/README.md「改动的等价证据分三级」的 ①）：同一份 TB、同一组作业，分别编译两个提交的 RTL，
逐作业比 DONE 行里的 `sig=`。零差异类改动（重构、搬家、等价重定时、挪切点）用它当证据。

    .venv/bin/python3 flow/verify/sigeq.py --design <顶层> --old <提交> [--new <提交，默认 HEAD>] [--tier inner] [-j 4]
    .venv/bin/python3 flow/verify/sigeq.py --design <顶层> --old HEAD --mutate 'designs/<根>/rtl/x.v::a & b::a | b'

- TB 与回归清单都取**当前工作区**的（`tb/regress.<顶层>.yaml`）；两边只换 RTL：各自 `git archive` 导出各设计树（`DESIGN_TREES`），
  源文件取导出树里的 `rtl_candidates`（本根与 deps 根的全部 `rtl/*.v`）。所以未提交的 RTL 改动不在比对之内，先提交。
- 判据：每个作业两边都要有 DONE 行且带 `sig=`，签名逐个相同；任一作业缺签名、跑挂或签名不同就退出 1。
- 签名只覆盖 TB 例化到的模块。开跑前列出两个提交之间改过的 RTL 文件，改动若落在 TB 不例化的模块上，签名相同不能当证据。
- `--mutate 文件::原文::替换`：在「新」的一侧植入一个变异体（原文必须在该文件里恰好出现一次），打印改了几行；
  这时判据反过来 —— 至少一个作业签名不同（变异体被抓到）才退出 0，证明这组作业确实能看到这处改动。
不进 `METRIC_MODULES`，不产生实验记录。产物在 `runs/sigeq/<时间>/`。
"""
import argparse
import difflib
import re
import subprocess
import sys
import tarfile
import io
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import DESIGN_TREES, include_dirs, rtl_candidates  # noqa: E402
from flow.verify import regress  # noqa: E402

SIG = re.compile(r"\bsig=([0-9a-fA-FxXzZ_]+)")


def export(repo, ref, dest):
    """把 ref 里存在的各设计树（`DESIGN_TREES`）导出到 dest；返回完整提交号。

    某棵树在该提交里不存在时跳过 —— `git archive` 遇到不匹配的路径会整个失败。
    """
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
                         capture_output=True, text=True, check=True).stdout.strip()
    present = [t for t in DESIGN_TREES
               if subprocess.run(["git", "-C", str(repo), "ls-tree", "--name-only", sha, "--", t],
                                 capture_output=True, text=True, check=True).stdout.strip()]
    dest.mkdir(parents=True, exist_ok=True)
    if not present:
        return sha
    data = subprocess.run(["git", "-C", str(repo), "archive", sha, "--", *present],
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest)
    return sha


def mutate(root, spec):
    """spec = '相对路径::原文::替换'，原文必须恰好出现一次。返回改动的行数。"""
    try:
        rel, old, new = spec.split("::", 2)
    except ValueError:
        raise SystemExit(f"--mutate 要写成 文件::原文::替换：{spec!r}")
    f = root / rel
    text = f.read_text()
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"--mutate：{rel} 里「{old}」出现 {n} 次，要恰好 1 次")
    out = text.replace(old, new)
    f.write_text(out)
    return sum(1 for ln in difflib.unified_diff(text.splitlines(), out.splitlines(), lineterm="", n=0)
               if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")))


def changed_rtl(repo, a, b):
    out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", a, b, "--", *DESIGN_TREES],
                         capture_output=True, text=True, check=True).stdout.split()
    return [p for p in out if "/rtl/" in p and p.endswith((".v", ".vh", ".sv"))]


def side(design, root):
    return rtl_candidates(design, root), include_dirs(design, root)


def compare(old_res, new_res):
    """两边结果按作业键配对。返回 (相同数, 不同 [(键, 旧签名, 新签名)], 问题 [(键, 说明)])。"""
    key = regress.job_key
    o = {key(r["params"]): r for r in old_res}
    n = {key(r["params"]): r for r in new_res}
    same, diff, bad = 0, [], []
    for k in sorted(set(o) | set(n)):
        if k not in o or k not in n:
            bad.append((k, "只在一边跑了"))
            continue
        so, sn = SIG.search(o[k]["info"]), SIG.search(n[k]["info"])
        if not so or not sn:
            bad.append((k, "DONE 行没有 sig=：" + (o[k]["info"] if not so else n[k]["info"])[-200:]))
        elif so.group(1) != sn.group(1):
            diff.append((k, so.group(1), sn.group(1)))
        else:
            same += 1
    return same, diff, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design", required=True)
    ap.add_argument("--old", required=True, help="旧 RTL 的提交")
    ap.add_argument("--new", default="HEAD", help="新 RTL 的提交（默认 HEAD）")
    ap.add_argument("--tier", choices=regress.TIERS, default="inner")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--sim", choices=regress.SIMS, default="verilator")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--mutate", help="文件::原文::替换，在新的一侧植入一个变异体")
    ap.add_argument("--repo", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    ap.add_argument("--manifest", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    manifest = Path(a.manifest) if a.manifest else regress.manifest_for(a.design)
    out = repo / "runs" / "sigeq" / time.strftime("%Y%m%d-%H%M%S")
    sha = {}
    for name, ref in (("old", a.old), ("new", a.new)):
        sha[name] = export(repo, ref, out / name)
    print(f"# sigeq {a.design}：旧 {sha['old'][:12]}（{a.old}）↔ 新 {sha['new'][:12]}（{a.new}），{a.tier}，产物 {out}")
    ch = changed_rtl(repo, sha["old"], sha["new"])
    print(f"# 两个提交之间改过的 RTL：{len(ch)} 个" + "".join(f"\n#   {p}" for p in ch)
          + "\n#   签名只覆盖 TB 例化到的模块；改动落在 TB 不例化的模块上时，签名相同不能当证据")
    if a.mutate:
        print(f"# 变异体：{a.mutate}（改了 {mutate(out / 'new', a.mutate)} 行，只在新的一侧）")
    res = {}
    for name in ("old", "new"):
        src, inc = side(a.design, out / name)
        _, res[name] = regress.run(manifest, a.tier, a.jobs, out_dir=out / f"build_{name}",
                                   durations_path=out / f"durations.{name}.json", timeout=a.timeout,
                                   sim=a.sim, sources=src, incs=inc)
    same, diff, bad = compare(res["old"], res["new"])
    for k, why in bad:
        print(f"PROBLEM {k}：{why}")
    for k, so, sn in diff[:20]:
        print(f"DIFF    {k}：{so} → {sn}")
    print(f"# 结果：相同 {same}，不同 {len(diff)}，有问题 {len(bad)}（共 {same + len(diff) + len(bad)} 个作业）")
    if bad:
        return 1
    if a.mutate:
        ok = bool(diff)
        print("# 变异体" + ("被抓到：这组作业看得到这处改动" if ok else "没被抓到：这组作业看不到这处改动，签名相同不能当证据"))
        return 0 if ok else 1
    return 0 if not diff else 1


if __name__ == "__main__":
    sys.exit(main())
