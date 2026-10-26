"""按格式生成发布出口的附注 tag（内部#300）。

    python scripts/release_tag.py CBB_FOO R006 --commit 240d00a \\
        --design 1b64e8c --verify 12fe4e2 --spec e0e444b --spec-base "LRS v1.42 / LLD v1.53" \\
        --exit "全配置回归 4 种子、SVA 314/314，fast_check rc=0" \\
        --issue 209 --exit-link https://github.com/…#issuecomment-…
    python scripts/release_tag.py … --create      # 核对通过后在本地打 tag，不推

默认只打印 tag 名与正文（dry-run）。核对：名字格式、正文必填项、集成提交在 main 上、
设计 / 验证提交都包含在集成提交里、同名 tag 本地与远端都不存在。

**打不打由用户逐版决定**（内部#300）：kaiwu-chief 在推 main 时问。这个脚本只负责
名字和正文写对；推送用 `git push --follow-tags origin main`（见 docs/toolchain.md
「发布 → 验证 → 交付 → 集成」第 5 步）。
"""
import argparse
import re
import subprocess
import sys

TOP_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
RELEASE_RE = re.compile(r"^R\d{3}(\.[1-9]\d*)?$")   # 修订版 R009.1（内部#303）


def tag_name(top, release):
    return f"{top.lower()}-{release}"


def tag_body(a):
    return (
        f"{a.top} {a.release} 可出口\n"
        f"设计提交 {a.design}  验证提交 {a.verify}  规格提交 {a.spec}（{a.spec_base}）\n"
        f"出口判据：{a.exit}\n"
        f"发布单 #{a.issue}，可出口结论 {a.exit_link}\n"
    )


def git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def resolve(rev, cwd=None):
    r = git(["rev-parse", "-q", "--verify", f"{rev}^{{commit}}"], cwd)
    return r.stdout.strip() if r.returncode == 0 else None


def problems(a, cwd=None):
    out = []
    if not TOP_RE.match(a.top):
        out.append(f"顶层名 {a.top!r} 应为大写，如 CBB_FOO")
    if not RELEASE_RE.match(a.release):
        out.append(f"版本号 {a.release!r} 应为 R 加三位数字，修订版再加 .<n>（n 从 1 起），如 R009、R009.1")
    for field in ("design", "verify", "spec", "spec_base", "exit", "exit_link"):
        if not str(getattr(a, field) or "").strip():
            out.append(f"--{field.replace('_', '-')} 必填")
    if out:
        return out
    commit = resolve(a.commit, cwd)
    if not commit:
        return [f"集成提交 {a.commit} 不存在"]
    main = resolve(a.main_ref, cwd)
    if not main:
        out.append(f"{a.main_ref} 不存在（先 git fetch）")
    elif git(["merge-base", "--is-ancestor", commit, main], cwd).returncode != 0:
        out.append(f"集成提交 {a.commit} 不在 {a.main_ref} 上")
    for field in ("design", "verify", "spec"):
        rev = getattr(a, field)
        sha = resolve(rev, cwd)
        if not sha:
            out.append(f"--{field} {rev} 不存在")
        elif git(["merge-base", "--is-ancestor", sha, commit], cwd).returncode != 0:
            out.append(f"--{field} {rev} 不包含在集成提交 {a.commit} 里")
    name = tag_name(a.top, a.release)
    if git(["rev-parse", "-q", "--verify", f"refs/tags/{name}"], cwd).returncode == 0:
        out.append(f"本地已有 tag {name}")
    if not a.no_remote:
        r = git(["ls-remote", "--tags", a.remote, f"refs/tags/{name}"], cwd)
        if r.returncode != 0:
            out.append(f"查不了远端 {a.remote} 的 tag（{r.stderr.strip()}）；离线时加 --no-remote")
        elif r.stdout.strip():
            out.append(f"远端 {a.remote} 已有 tag {name}")
    return out


def parse(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("top", help="被测顶层名，如 CBB_FOO")
    p.add_argument("release", help="版本号，如 R009；修订版如 R009.1")
    p.add_argument("--commit", required=True, help="进 main 后的集成提交（设计与 TB 都在里面）")
    p.add_argument("--design", help="设计提交")
    p.add_argument("--verify", help="验证提交（TB）")
    p.add_argument("--spec", help="规格提交")
    p.add_argument("--spec-base", help="规格基线，如 \"LRS v1.42 / LLD v1.53\"")
    p.add_argument("--exit", help="出口判据摘要：交付脚本各套件 通过/总数、fast_check、iodeps")
    p.add_argument("--issue", type=int, required=True, help="发布单 issue 号")
    p.add_argument("--exit-link", help="可出口结论的 issue 评论链接")
    p.add_argument("--main-ref", default="origin/main")
    p.add_argument("--remote", default="origin")
    p.add_argument("--no-remote", action="store_true", help="不查远端是否已有同名 tag")
    p.add_argument("--create", action="store_true", help="核对通过后在本地打附注 tag（不推）")
    return p.parse_args(argv)


def main(argv=None):
    a = parse(argv)
    errs = problems(a)
    if errs:
        for e in errs:
            print(f"release_tag: {e}", file=sys.stderr)
        return 1
    name = tag_name(a.top, a.release)
    body = tag_body(a)
    print(f"tag: {name} -> {resolve(a.commit)}")
    print(body, end="")
    if not a.create:
        print("（dry-run：未打 tag；加 --create 在本地打）")
        return 0
    r = subprocess.run(["git", "tag", "-a", name, a.commit, "-F", "-"], input=body, text=True)
    if r.returncode != 0:
        return r.returncode
    print(f"已在本地打 {name}；推送：git push --dry-run --follow-tags origin main 核对后再去掉 --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
