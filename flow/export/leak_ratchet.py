"""开源集合的泄漏只许减少（内部#365，leak-ratchet；用户 2026-10-20 定先做门禁再清理）。

    .venv/bin/python3 flow/export/leak_ratchet.py [--ref HEAD] [--base-branch main]

扫 `--ref` 提交的开源集合（`leak_scan.py` 的口径：白名单、block 规则的出现次数），与 `flow/export/leak_baseline.txt`
里的基线比：
- 超过基线 → 退出 1，并用同一份清单扫 merge-base（`git merge-base <ref> <base-branch>`），按文件列出多出来的次数；
  只列文件与次数，不打印命中的那一行（那一行就是闭源名字）；
- 基线比 merge-base 上的高 → 退出 1：基线只许调低，要抬高只能在 main 上改并在 内部#365 写明理由；
- 低于基线 → 退出 0，提示可以调到的值（清理与调低基线可以分两个提交）。
清单或基线在 merge-base 上有、这里被删掉 → 退出 1；两边都没有（夹具仓）→ 退出 2；基线写错时 merge-base 上有基线退出 1，没有退出 2（fast_check 记为未执行）。
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leak_scan  # noqa: E402

BASELINE = "flow/export/leak_baseline.txt"


class RatchetError(RuntimeError):
    """环境不全或基线写错（退出 2）。"""


def _show(repo, ref, path):
    r = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def parse_baseline(text, where):
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if len(lines) != 1 or not lines[0].isdigit():
        raise RatchetError(f"{where} 里要有且只有一个非负整数（# 开头的行是注释）")
    return int(lines[0])


def blocked_by_file(repo, ref, manifest):
    out = {}
    for path, _no, level, _name, n in leak_scan.scan(repo, ref, manifest):
        if level == "block":
            out[path] = out.get(path, 0) + n
    return out


def check(repo, ref="HEAD", base_branch="main"):
    """(退出码, 输出行)。"""
    mb = subprocess.run(["git", "-C", str(repo), "merge-base", ref, base_branch], capture_output=True, text=True)
    base = mb.stdout.strip() if mb.returncode == 0 else None
    for path, what in ((leak_scan.MANIFEST, "开源白名单"), (BASELINE, "基线")):
        if _show(repo, ref, path) is None:
            # merge-base 上有、这里没有：是被删掉的，判失败——不能靠删文件把门禁变成「未执行」（layout 10-20 复核）。
            # 两边都没有（夹具仓、门禁进 main 之前）才算环境不全
            if base and _show(repo, base, path) is not None:
                return 1, [f"{ref} 删掉了{what} {path}（merge-base {base[:12]} 上还有）：门禁不能靠删文件绕过，"
                           "要排除文件改 manifest 的 exclude，要改基线只许调低"]
            raise RatchetError(f"{ref} 里没有 {path}（{what}）")
    try:
        cap = parse_baseline(_show(repo, ref, BASELINE), f"{ref}:{BASELINE}")
    except RatchetError as e:
        if base and _show(repo, base, BASELINE) is not None:   # 同理：写坏基线也不能变成「未执行」
            return 1, [str(e)]
        raise
    manifest = leak_scan.load_manifest(repo, ref)
    head = blocked_by_file(repo, ref, manifest)
    total = sum(head.values())
    rc, lines = 0, []
    if base:
        base_text = _show(repo, base, BASELINE)
        if base_text is not None:
            base_cap = parse_baseline(base_text, f"{base[:12]}:{BASELINE}")
            if cap > base_cap:
                rc = 1
                lines.append(f"基线只许调低：merge-base {base[:12]} 上是 {base_cap}，这里改成了 {cap}（{base_cap} → {cap}）；"
                             "要抬高只能在 main 上改，并在 #365 写明理由")
    if total > cap:
        rc = 1
        lines.append(f"block 命中 {total} 处，超过基线 {cap}：新写进开源路径的闭源名字（只列文件与多出的次数）")
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True).stdout.strip()
        grew = []
        if base and base != sha:
            old = blocked_by_file(repo, base, manifest)   # 同一份清单，清单改了也可比
            grew = sorted((p, n - old.get(p, 0)) for p, n in head.items() if n > old.get(p, 0))
            lines += [f"  {p} +{d}" for p, d in grew]
        if not grew:   # 在 main 上（merge-base 就是自己）或没有哪个文件变多：列命中最多的文件
            lines.append("  相对 merge-base 看不出新增，按文件列命中最多的 10 个：")
            lines += [f"  {p} {n}" for p, n in sorted(head.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
        lines.append(f"  逐行看：.venv/bin/python3 flow/export/leak_scan.py --ref {ref} --only '<文件>'；"
                     "改成开源构件或造出来的名字，见 #365")
    else:
        lines.append(f"block 命中 {total} 处，基线 {cap}")
        if total < cap:
            lines.append(f"  可以把基线调到 {total}（{BASELINE}），清理和调低可以分两个提交")
    return rc, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(leak_scan.REPO_ROOT))
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--base-branch", default="main", help="求 merge-base 的分支（默认 main）")
    a = ap.parse_args(argv)
    try:
        rc, lines = check(a.repo, a.ref, a.base_branch)
    except RatchetError as e:
        print(f"leak_ratchet：{e}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main())
