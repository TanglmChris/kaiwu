"""fast_check 的失败豁免（内部#254，fast-check-waivers；用户 2026-10-12 定按「检查段 + 文件 glob」）。

豁免登记在 `flow/check_waivers.yaml`：

    waivers:
      - check: style                      # 检查段名，取 fast_check 的日志名，见 CHECKS
        files: designs/foo/rtl/a.v        # glob，字符串或列表，相对仓库根
        issue: 246                        # 本仓 issue 号
        until: 改完 A / B 方案之后          # 到期条件
        count: 2                          # 登记时这条豁免放行的违规条数（内部#330）

两个子命令，都由 scripts/fast_check.sh 调用：

- `apply <段名> <标题> <日志> <记账文件>`：某段失败时调。日志里每条违规（不缩进的非空行）按行首路径
  匹配该段的豁免；全部被覆盖、且每条豁免本次匹配的条数等于它的 `count` → 打 `WAIVED` 并退出 0，
  否则打 `FAIL` 并退出 1。认不出路径的违规行按未豁免算（D2）。条数多了是同一文件里有新违规（内部#330：
  按文件匹配会把它一起放过），少了要把 `count` 改小（余量会藏住以后的新违规）。放行过违规的豁免记进记账文件。
- `final <记账文件> <生效清单>`：跑完全部检查段后调。豁免文件有误、或某条豁免本次没放行任何违规
  （过时）→ FAIL（D4）；还在放行违规而挂的 issue 已关 → 只提示（内部#291）。生效的豁免写进 <生效清单>，由覆盖摘要打印。
"""
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

WAIVER_FILE = Path("flow/check_waivers.yaml")
# 仓名不写死（内部#329）：gh 的 {owner}/{repo} 占位符按当前目录所在仓的远端解析，导出到公开仓后查的是它自己；
# 解析不了（没有远端、没有 gh）就当「查不到」，落到「未核 issue 状态」提示。
REPO = "{owner}/{repo}"
# 按文件定位违规的检查段（D1）。名字与 fast_check 里 $LOGDIR/<段>.log 一致。
CHECKS = ("ports", "doc", "dup", "clean", "escape", "case", "naming", "enum", "style", "directive", "bind")
FIELDS = ("check", "files", "issue", "until", "count")
# 行首是路径：`路径[:行号]:` 后跟空白（多数检查段），或源文件路径后直接跟空格 / 全角冒号（doc 段的
# 「lrs.X.md 缺必填节：…」「lld.X.md：…」，内部#290）
VIOLATION = re.compile(r"^(\S+?)(?::\d+)?:(\s|$)|^(\S+?\.(?:md|v|vh|sv|py|yaml))(?::\d+)?(?:\s|：)")


def load():
    """返回 (有效豁免列表, 错误列表)。每条豁免是 dict，另带 `_n`（从 1 起的序号）。"""
    if not WAIVER_FILE.exists():
        return [], []
    try:
        import yaml
        data = yaml.safe_load(WAIVER_FILE.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001 —— 读不了就是错，原样报出
        return [], [f"{WAIVER_FILE} 读不了：{e}"]
    items = data.get("waivers") if isinstance(data, dict) else None
    if items is None:
        return [], [] if data == {} else [f"{WAIVER_FILE} 顶层要是 `waivers:` 列表"]
    if not isinstance(items, list):
        return [], [f"{WAIVER_FILE} 的 `waivers:` 要是列表"]
    good, errors = [], []
    for n, w in enumerate(items, 1):
        if not isinstance(w, dict):
            errors.append(f"第 {n} 条不是映射")
            continue
        missing = [f for f in FIELDS if w.get(f) in (None, "", [])]
        if missing:
            errors.append(f"第 {n} 条缺 {'、'.join(missing)}（五项都必填：{'、'.join(FIELDS)}）")
            continue
        if w["check"] not in CHECKS:
            errors.append(f"第 {n} 条的 check `{w['check']}` 不认识，可用：{'、'.join(CHECKS)}")
            continue
        if not str(w["issue"]).lstrip("#").isdigit():
            errors.append(f"第 {n} 条的 issue `{w['issue']}` 不是 issue 号")
            continue
        if not (isinstance(w["count"], int) and not isinstance(w["count"], bool) and w["count"] > 0):
            errors.append(f"第 {n} 条的 count `{w['count']}` 要是正整数：登记时这条豁免放行的违规条数（#330）")
            continue
        files = w["files"] if isinstance(w["files"], list) else [w["files"]]
        good.append(dict(w, files=[str(f) for f in files], issue=int(str(w["issue"]).lstrip("#")), _n=n))
    return good, errors


def apply(check, title, log, ledger):
    waivers = [w for w in load()[0] if w["check"] == check]
    lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    out, used, uncovered, covered, hits = [], set(), 0, 0, {}
    for line in lines:
        if not line.strip() or line[:1].isspace() or not waivers:
            out.append(line)
            continue
        m = VIOLATION.match(line)
        hit = None
        if m:
            hit = next((w for w in waivers if any(fnmatch.fnmatch(m.group(1) or m.group(3), g) for g in w["files"])), None)
        if hit is None:
            uncovered += 1
            out.append(f"[未豁免] {line}")
        else:
            covered += 1
            used.add(hit["_n"])
            hits[hit["_n"]] = hits.get(hit["_n"], 0) + 1
            out.append(f"[豁免 #{hit['issue']}] {line}")
    if used:
        with open(ledger, "a", encoding="utf-8") as f:
            f.writelines(f"{n}\n" for n in sorted(used))
    # 按条数核（内部#330）：按文件匹配会把同一文件里新加的违规一起放过
    off = []
    for w in waivers:
        m = hits.get(w["_n"], 0)
        if m and m != w["count"]:
            why = ("同一文件里有新违规，修掉或改登记" if m > w["count"]
                   else f"修掉了一部分，把 count 改成 {m}（余量会藏住以后的新违规）")
            off.append(f"      第 {w['_n']} 条（#{w['issue']}，{', '.join(w['files'])}）：登记 {w['count']} 条，本次 {m} 条：{why}")
    if waivers and covered and not uncovered and not off:
        print(f"WAIVED  {title}（{covered} 条违规全部在登记的豁免内，见 {WAIVER_FILE}）")
        print("\n".join(out))
        return 0
    print(f"FAIL  {title}")
    if waivers and covered and uncovered:
        print(f"      {covered} 条在豁免内，{uncovered} 条不在 —— 不在的要修，或登记豁免（{WAIVER_FILE}）")
    for line in off:
        print(line)
    print("\n".join(out))
    return 1


def _issue_state(n):
    """返回 'open' / 'closed'，查不到返回 None。"""
    try:
        r = subprocess.run(["gh", "api", f"repos/{REPO}/issues/{n}", "-q", ".state"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    state = r.stdout.strip()
    return state if r.returncode == 0 and state in ("open", "closed") else None


def final(ledger, active_out):
    waivers, errors = load()
    used = {int(x) for x in Path(ledger).read_text().split()} if Path(ledger).exists() else set()
    rc = 0
    if errors:
        print(f"FAIL  失败豁免文件有误（{WAIVER_FILE}）")
        for e in errors:
            print(f"      {e}")
        rc = 1
    stale = [w for w in waivers if w["_n"] not in used]
    if stale:
        print("FAIL  失败豁免过时：本次没有放行任何违规（已修好，或 check / files 写错了），删掉这几条")
        for w in stale:
            print(f"      第 {w['_n']} 条：{w['check']} {', '.join(w['files'])}（#{w['issue']}）")
        rc = 1
    live = [w for w in waivers if w["_n"] in used]
    if live:
        if os.environ.get("FAST_CHECK_WAIVER_ISSUE_CHECK", "1") == "0":
            print("note  未核 issue 状态（FAST_CHECK_WAIVER_ISSUE_CHECK=0）—— 推 main 前在联网环境下再跑一次")
        else:
            states = {w["issue"]: _issue_state(w["issue"]) for w in live}
            closed = [n for n, s in states.items() if s == "closed"]
            unknown = [n for n, s in states.items() if s is None]
            for n in closed:
                # 还在放行违规而 issue 已关：多半是修复已交付、还没进本分支（内部#291，用户 10-13 定方案 3）。只提示不拦，
                # 否则会卡住所有基于 main 的分支；修复进来后豁免不再放行任何违规，上面「过时」那条会判 FAIL。
                # 规则：挂着失败豁免的 issue，删豁免的提交进 main 后才关（toolchain「推送、授权」，内部#218 的例外）
                print(f"note  豁免挂的 #{n} 已关，修复还没进本分支（豁免仍在放行违规）—— "
                      "推 main 时确认修复在这一批里，进 main 后删豁免")
            if unknown:
                print("note  未核 issue 状态（查不到：" + "、".join(f"#{n}" for n in unknown)
                      + "）—— 推 main 前在联网环境下再跑一次")
    Path(active_out).write_text("".join(
        f"  豁免  {w['check']}  {', '.join(w['files'])}  #{w['issue']}  到期：{w['until']}\n" for w in live),
        encoding="utf-8")
    if rc == 0:
        print(f"ok    失败豁免没有过时（{len(waivers)} 条，生效 {len(live)} 条）")
    return rc


if __name__ == "__main__":
    # 判定本身出错以 3 退出，与「判定为 FAIL」的 1 区分开：fast_check 据此照旧报原始失败（D2）
    try:
        cmd, args = sys.argv[1], sys.argv[2:]
        rc = apply(*args) if cmd == "apply" else final(*args)
    except Exception as e:  # noqa: BLE001
        print(f"check_waivers 出错：{type(e).__name__}: {e}")
        rc = 3
    sys.exit(rc)
