#!/usr/bin/env python3
"""给应用的补丁一步交付并自证可还原（内部#340，design-side-tools D4）：

    .venv/bin/python3 scripts/patch_deliver.py --base <基线提交> --head <最后一个修复提交> --out <新目录>

1. `git format-patch <base>..<head>` 导出到 `<out>`；
2. 在 base 的临时检出里逐个 `git am`；
3. 比还原结果与 head 的树哈希；检出里留下 `.orig` / `.rej` 也算失败；
4. 写 `<out>/DELIVERY.txt`：base、head、两个树哈希、每个补丁的 sha256。临时检出跑完就删（出错也删）。

退出码：一致 0；还原不出 head 或补丁打不上 1；ref 解析不到、`<out>` 已存在 2。范围里的普通合并不碍事
（format-patch 不导出合并本身，但会导出合并带进来的提交，排成直线照样还原）；会出问题的是合并提交里自带的改动：
合并时另改了内容 → 树哈希对不上；解了冲突 → 后面的补丁打不上。范围里有合并提交时报告里会提示。
以前（内部#282）这几步都是手工做的。

给旧版本打补丁时，提交顺序是 基线 → RTL 修复（交付范围）→ TB 移植；失败臂与交付的完整做法见
team/roles/kaiwu-verify/README.md「给旧版本打补丁：失败臂与交付」。
"""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from at_ref import CheckoutError, checkout, git  # noqa: E402


def _sha(ref):
    r = git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    if r.returncode != 0:
        raise CheckoutError(f"提交 {ref} 不存在（先 git fetch？）")
    return r.stdout.strip()


def _tree(ref, cwd=None):
    return git("rev-parse", f"{ref}^{{tree}}", cwd=cwd).stdout.strip()


def deliver(base, head, out):
    """返回 (退出码, 报告行)。"""
    out = Path(out)
    if out.exists():
        return 2, [f"输出目录已存在：{out}（每次交付用新目录，旧的不覆盖）"]
    try:
        b, h = _sha(base), _sha(head)
    except CheckoutError as e:
        return 2, [str(e)]
    if git("merge-base", "--is-ancestor", b, h).returncode != 0:
        return 2, [f"{base} 不是 {head} 的祖先，补丁范围无从谈起"]
    out.mkdir(parents=True)
    fp = git("format-patch", "-q", "-o", str(out.resolve()), f"{b}..{h}")
    patches = sorted(out.glob("*.patch"))
    if fp.returncode != 0 or not patches:
        return 1, [f"format-patch 没导出补丁：{fp.stderr.strip() or f'{b[:8]}..{h[:8]} 里没有非合并提交'}"]
    merges = git("rev-list", "--merges", "--count", f"{b}..{h}").stdout.strip()
    lines = [f"base {b}", f"head {h}"]
    if merges != "0":
        lines.append(f"注意：范围里有合并提交 {merges} 个 —— 合并本身不导出，合并时解冲突或另改的内容不在补丁里")
    lines.append(f"补丁 {len(patches)} 个：")
    lines += [f"  {hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in patches]
    with checkout(b) as (wt, _):
        am = subprocess.run(["git", "am", "--keep-cr", "-q", *map(str, patches)], cwd=wt, capture_output=True, text=True)
        if am.returncode != 0:
            subprocess.run(["git", "am", "--abort"], cwd=wt, capture_output=True)
            lines.append(f"补丁在 base 上打不上：{(am.stdout + am.stderr).strip().splitlines()[0] if (am.stdout + am.stderr).strip() else am.returncode}")
            return 1, lines
        leftovers = [ln[3:] for ln in git("status", "--porcelain", "--ignored", cwd=wt).stdout.splitlines()
                     if ln[3:].rstrip("/").endswith((".orig", ".rej"))]
        got, want = _tree("HEAD", cwd=wt), _tree(h)
    lines += [f"head 的树       {want}", f"base + 补丁的树 {got}"]
    if leftovers:
        lines.append(f"检出里留下了 {'、'.join(leftovers)}")
        rc = 1
    elif got != want:
        lines.append("结论：不一致 —— 补丁还原不出 head（合并提交里另改的内容不在补丁里？）")
        rc = 1
    else:
        lines.append("结论：一致 —— 在干净的 base 上依次 git am 这些补丁，得到的就是 head 的树")
        rc = 0
    (out / "DELIVERY.txt").write_text("\n".join(lines) + "\n")
    return rc, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="应用手里的基线提交")
    ap.add_argument("--head", required=True, help="最后一个 RTL 修复提交（TB 移植提交不在交付范围）")
    ap.add_argument("--out", required=True, help="新目录：放补丁与 DELIVERY.txt；已存在则拒绝")
    a = ap.parse_args(argv)
    try:
        rc, lines = deliver(a.base, a.head, a.out)
    except CheckoutError as e:
        rc, lines = 2, [str(e)]
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
