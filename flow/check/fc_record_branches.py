# fast_check 的记录与报告护栏（parallel-worktree「秒级护栏必须机械检查记录与报告的来源」、
# experiment-record「已提交记录的 git_commit 必须是 HEAD 的祖先」，内部#422）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_record_branches；每项打一行 `ok    <项>（…）` 或
# `FAIL  <项>：…`（明细缩进在下面），任一项失败退出 1。只看**已提交**的状态（HEAD 与各 ref），不看工作区。
#
# 四项：
#   记录与报告的来源   非白名单分支：HEAD 上不得有 main 与白名单分支都没有的记录行（按内容判：只搬不增的
#                      历史搬迁放行）；自己的提交不得改报告（按提交判，内部#81 的已无顶层的报告删除放行）
#   记录历史行原样保留 merge-base(HEAD, main) 与 HEAD 的每个父提交上，每个记录文件的行逐字节、按原相对顺序
#                      出现在 HEAD 同一路径；记录文件不许消失（旧单文件例外，但每行要在某个设计根文件里）
#   记录的 git_commit 可达 HEAD   rebase / squash 合并会让它失败
#   旧单文件已搬迁     HEAD 上不得有 results/experiments.jsonl（提示跑 python -m flow.records migrate）
import json
import subprocess
import sys
from pathlib import Path

import yaml

from flow.paths import DESIGN_TREES

LEGACY = "results/experiments.jsonl"
WHITELIST = "flow/record_branches.yaml"
SRC = "记录与报告的来源"
HIST = "记录历史行原样保留"
REACH = "记录的 git_commit 可达 HEAD"
MIGRATED = "旧单文件已搬迁"


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}：{r.stderr.strip()}")
    return r


def is_record_file(path):
    parts = path.split("/")
    return path == LEGACY or (len(parts) == 3 and parts[0] == "results" and parts[2] == "experiments.jsonl")


def record_files(ref):
    out = git("ls-tree", "-r", "--name-only", ref, "--", "results").stdout.split()
    return sorted(p for p in out if is_record_file(p))


def read_lines(ref, path):
    return [l for l in git("show", f"{ref}:{path}").stdout.splitlines() if l.strip()]


def lines_at(ref):
    return {p: read_lines(ref, p) for p in record_files(ref)}


def ref_exists(ref):
    return git("rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def whitelist_refs(names):
    refs = []
    for n in names:
        for r in (f"refs/heads/{n}", f"refs/remotes/origin/{n}"):
            if ref_exists(r):
                refs.append(r)
    return refs


def is_subsequence(old, new):
    it = iter(new)
    return all(any(o == n for n in it) for o in old)


def report_pathspecs():
    return [f":(glob){t}/*/REPORT.*.md" for t in DESIGN_TREES]


def top_gone(path):
    """内部#81：被删的 `<树>/<根>/REPORT.<顶层>.md` 在 HEAD 上已没有对应顶层。解析不了按顶层仍在处理。"""
    tree, root, name = path.split("/")
    top = name[len("REPORT."):-len(".md")]
    r = git("show", f"HEAD:{tree}/{root}/params.yaml", check=False)
    if r.returncode != 0:
        return True
    try:
        tops = (yaml.safe_load(r.stdout) or {}).get("tops") or {}
    except yaml.YAMLError:
        return False
    return top not in tops


def check_source(branch, names, head):
    if branch in names:
        return [f"ok    {SRC}（当前分支 {branch} 在白名单里）"], True
    refs = whitelist_refs(["main"] + [n for n in names if n != "main"])
    allowed = set()
    for r in refs:
        for ls in lines_at(r).values():
            allowed.update(ls)
    out, ok = [], True
    new = {p: [l for l in ls if l not in allowed] for p, ls in head.items()}
    new = {p: ls for p, ls in new.items() if ls}
    if new:
        ok = False
        out.append(f"FAIL  {SRC}：分支 {branch or '（分离 HEAD）'} 上有 main 与白名单分支都没有的记录行")
        out += [f"        {p}：{len(ls)} 行" for p, ls in sorted(new.items())]
        out.append(f"      正式记录只在白名单分支（{WHITELIST}）上提交：开发运行的记录留在工作区、不提交，")
        out.append("      正式扫参交给 report 会话在白名单分支上跑。把这些行从分支的提交里拿掉。")
    commits = git("rev-list", "HEAD", "--not", *refs, "--", *report_pathspecs()).stdout.split()
    blocked, allowed_del = [], []
    for c in commits:
        st = git("show", "--no-renames", "--name-status", "--format=", c, "--", *report_pathspecs()).stdout
        for line in st.splitlines():
            status, path = line.split("\t", 1)
            if status == "D" and len(path.split("/")) == 3 and top_gone(path):
                allowed_del.append(path)
            else:
                blocked.append((c[:8], path))
    if allowed_del:
        out.append(f"      {SRC}：分支删除了 {len(set(allowed_del))} 份已没有对应顶层的报告，不算违规（#81）：")
        out += [f"        放行  {p}" for p in sorted(set(allowed_del))]
    if blocked:
        ok = False
        out.append(f"FAIL  {SRC}：分支自己的提交改了报告（不在 main 与白名单分支里的提交）")
        out += [f"        {c}  {p}" for c, p in blocked]
        out.append("      REPORT 由记录生成，只在白名单分支上用 make report 刷新。")
    if ok:
        out.append(f"ok    {SRC}（分支 {branch or '（分离 HEAD）'} 不在白名单里：没有新记录行，"
                   f"自己的提交没改报告；对照 {len(refs)} 个白名单 ref）")
    return out, ok


def check_history(head):
    bases = []
    mb = git("merge-base", "HEAD", "main").stdout.strip()
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").stdout.split()[1:]
    for b in [mb] + parents:
        if b not in bases:
            bases.append(b)
    union = {l for ls in head.values() for l in ls}
    bad = []
    for b in bases:
        for p, old in lines_at(b).items():
            if p == LEGACY and p not in head:
                lost = sum(1 for l in old if l not in union)
                if lost:
                    bad.append(f"{b[:8]} 的 {p} 消失了，其中 {lost} 行不在任何设计根文件里")
            elif p not in head:
                bad.append(f"{b[:8]} 的 {p} 在 HEAD 上被删了（{len(old)} 行）")
            elif not is_subsequence(old, head[p]):
                lost = len([l for l in old if l not in set(head[p])])
                bad.append(f"{b[:8]} 的 {p}：{lost} 行丢失或被改写，或原有行的相对顺序变了")
    if bad:
        return [f"FAIL  {HIST}：合并或改动破坏了已有记录（红线 2）"] + [f"        {x}" for x in bad], False
    return [f"ok    {HIST}（对照 merge-base 与 {len(bases) - 1} 个父提交，共 {len(bases)} 个基点）"], True


def check_reach(head):
    commits = {}
    for p, ls in head.items():
        for l in ls:
            c = json.loads(l).get("git_commit")
            if c:
                commits.setdefault(c, []).append(p)
    revs = set(git("rev-list", "HEAD").stdout.split())
    bad = {c: ps for c, ps in commits.items() if c not in revs}
    if bad:
        out = [f"FAIL  {REACH}：{sum(len(v) for v in bad.values())} 条记录的 git_commit 不是 HEAD 的祖先"
               "（集成分支用 rebase / squash 合了进来？只许 merge 或快进）"]
        for c, ps in sorted(bad.items()):
            files = sorted(set(ps))
            out.append(f"        {c[:12]}  {len(ps)} 条  {', '.join(files)}")
        return out, False
    return [f"ok    {REACH}（{len(commits)} 个不同的 git_commit）"], True


def check_migrated(head):
    if LEGACY in head or git("cat-file", "-e", f"HEAD:{LEGACY}", check=False).returncode == 0:
        return [f"FAIL  {MIGRATED}：HEAD 上还有 {LEGACY}；跑 python -m flow.records migrate 把它搬进各设计根文件再提交"], False
    return [f"ok    {MIGRATED}（{len(head)} 个设计根记录文件）"], True


def main():
    if git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        print(f"FAIL  {SRC}：不在 git 仓库里，无法确定相对 main 的 merge-base")
        return 1
    if not ref_exists("refs/heads/main"):
        print(f"FAIL  {SRC}：没有名为 main 的分支，无法确定 merge-base")
        print("      （默认分支改过名的话，这里的 main 要跟着改）")
        return 1
    try:
        names = (yaml.safe_load(Path(WHITELIST).read_text()) or {}).get("branches") or []
    except (OSError, yaml.YAMLError) as e:
        print(f"FAIL  {SRC}：读不到记录分支白名单 {WHITELIST}（{e}）")
        return 1
    if not names:
        print(f"FAIL  {SRC}：{WHITELIST} 的 branches: 是空的")
        return 1
    branch = git("branch", "--show-current").stdout.strip()
    head = lines_at("HEAD")
    ok = True
    for fn, args in ((check_source, (branch, names, head)), (check_history, (head,)),
                     (check_reach, (head,)), (check_migrated, (head,))):
        lines, good = fn(*args)
        print("\n".join(lines))
        ok = ok and good
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
