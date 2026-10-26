#!/usr/bin/env python3
"""两个提交之间的规格差分（内部#228，spec-diff）：

    .venv/bin/python3 scripts/spec_diff.py --from <提交> --to <提交> [--top <顶层>] [--same R,接口表] [--out <文件>]

评审答复轮复核「声称没动的东西确实没动」用（内部#213 F-a、G11）。直接 `git show` 读两个提交里的规格文档，
不建检出、不跑工具。按顶层、按文档比：

- R 定义：含 `**R.xxx**` 的那一行，按编号比；
- 接口表：表头含「方向」「信号/端口」「位宽/宽度」的表（与 fast_check「spec 端口表与 RTL 一致」同一读法），
  按信号名比 方向 与 位宽；
- 图注：`**图 X-Y**` 那一行，按图号比；
- 设计断言：「设计断言」一节里第一格为 `A<编号>` 的表格行，按编号比；
- 节标题：`##`～`####` 标题；
- 图片文件：文档引用的 `![…](相对路径)` 在该提交里不存在的，两侧各列一次（不算差异）。

退出码：正常 0；`--same` 列出的项有差异 1；提交解析不到、参数错 2。
"""
import argparse
import posixpath
import re
import subprocess
import sys

DOC_RE = re.compile(r"^(?:designs/[^/]+/(?:lrs|lld|param|ppa|timing|verify)|cbb/[^/]+/spec)\.([A-Z0-9_]+)\.md$")
DEF_RE = re.compile(r"\*\*(R\.[0-9A-Za-z]+)\*\*")
FIG_RE = re.compile(r"^\s*\*\*(图\s*[0-9A-Za-z]+(?:-[0-9A-Za-z]+)*)\*\*")
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
HEAD_RE = re.compile(r"^(#{2,4})[ \t]+(.+?)\s*$", re.M)
A_RE = re.compile(r"A\d+")
ITEMS = ("R", "接口表", "图注", "设计断言", "节标题")
LIMIT = 50


class SpecDiffError(RuntimeError):
    """提交解析不到或参数错（退出 2）。"""


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def resolve(rev):
    r = git("rev-parse", "-q", "--verify", f"{rev}^{{commit}}")
    if r.returncode != 0:
        raise SpecDiffError(f"提交 {rev} 不存在（先 git fetch？）")
    return r.stdout.strip()


def docs(files, top=None):
    """{顶层: [路径…]}。"""
    out = {}
    for f in sorted(files):
        m = DOC_RE.match(f)
        if m and (top is None or m.group(1) == top):
            out.setdefault(m.group(1), []).append(f)
    return out


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def r_defs(text):
    out = {}
    for line in text.splitlines():
        for rid in DEF_RE.findall(line):
            out.setdefault(rid, line.strip())
    return out


def ports(text):
    rows, state, cols = {}, None, None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            state = None
            continue
        cells = _cells(line)
        if state is None:
            idx = {c: i for i, c in enumerate(cells)}
            name, width = idx.get("信号", idx.get("端口")), idx.get("位宽", idx.get("宽度"))
            if "方向" in idx and name is not None and width is not None:
                state, cols = "port", (name, idx["方向"], width)
            else:
                state = "other"
            continue
        if state != "port" or not "".join(cells).strip("-: ") or max(cols) >= len(cells):
            continue
        if not cells[cols[1]].strip("` "):
            continue  # 方向为空：端口下的字段行
        rows[cells[cols[0]].strip("` ")] = f"{cells[cols[1]].strip('` ').lower()} {cells[cols[2]].strip('` ')}"
    return rows


def figures(text):
    out = {}
    for line in text.splitlines():
        m = FIG_RE.match(line)
        if m:
            out.setdefault(re.sub(r"\s+", " ", m.group(1)), line.strip())
    return out


def _section(text, name):
    m = re.search(r"^##[ \t]+[\d.\s]*" + re.escape(name) + r".*$", text, re.M)
    if not m:
        return ""
    n = re.search(r"^##[ \t]", text[m.end():], re.M)
    return text[m.end():m.end() + n.start()] if n else text[m.end():]


def asserts(text):
    out = {}
    for line in _section(text, "设计断言").splitlines():
        if line.lstrip().startswith("|"):
            first = _cells(line)[0].strip("` ")
            if A_RE.fullmatch(first):
                out.setdefault(first, line.strip())
    return out


def headings(text):
    return {f"{h} {t}": f"{h} {t}" for h, t in HEAD_RE.findall(text)}


EXTRACT = {"R": r_defs, "接口表": ports, "图注": figures, "设计断言": asserts, "节标题": headings}


def missing_images(text, path, files):
    base = posixpath.dirname(path)
    refs = {ref for ref in IMG_RE.findall(text) if not re.match(r"[a-z]+://", ref)}
    return sorted(ref for ref in refs if posixpath.normpath(posixpath.join(base, ref)) not in files)


def compare(old, new):
    """(删, 增, 改)：删 / 增是键列表，改是 [(键, 旧, 新)]。"""
    gone = sorted(k for k in old if k not in new)
    added = sorted(k for k in new if k not in old)
    changed = [(k, old[k], new[k]) for k in sorted(old) if k in new and old[k] != new[k]]
    return gone, added, changed


def diff(frm, to, top=None):
    """(from 提交, to 提交, 行, 缺图)。行：(文档, 项, 删, 增, 改, from 有此文档, to 有此文档)；缺图：(文档, 侧, 列表)。"""
    a, b = resolve(frm), resolve(to)
    fa = set(git("ls-tree", "-r", "--name-only", a).stdout.splitlines())
    fb = set(git("ls-tree", "-r", "--name-only", b).stdout.splitlines())
    da, db = docs(fa, top), docs(fb, top)
    if top is not None and not da and not db:
        raise SpecDiffError(f"两个提交里都没有顶层 {top} 的规格文档")
    rows, imgs = [], []
    for t in sorted(set(da) | set(db)):
        for path in sorted(set(da.get(t, [])) | set(db.get(t, []))):
            ta = git("show", f"{a}:{path}").stdout if path in fa else None
            tb = git("show", f"{b}:{path}").stdout if path in fb else None
            for item in ITEMS:
                old = EXTRACT[item](ta) if ta is not None else {}
                new = EXTRACT[item](tb) if tb is not None else {}
                rows.append((path, item, *compare(old, new), ta is not None, tb is not None))
            for side, files, text in (("from", fa, ta), ("to", fb, tb)):
                miss = missing_images(text, path, files) if text is not None else []
                if miss:
                    imgs.append((path, side, miss))
    return a, b, rows, imgs


def render(a, b, rows, imgs):
    out = [f"# 规格差分 {a[:12]} → {b[:12]}", "", f"- from `{a}`", f"- to   `{b}`", "",
           "| 文档 | 项 | 删 | 增 | 改 |", "|---|---|---|---|---|"]
    detail = []
    for path, item, gone, added, changed, in_a, in_b in rows:
        if not (gone or added or changed or item == "R"):
            continue  # 没有差异的项只留 R 一行，表明这份文档比过
        note = "" if in_a and in_b else ("（新文档）" if in_b else "（文档已删）")
        out.append(f"| `{path}`{note} | {item} | {len(gone)} | {len(added)} | {len(changed)} |")
        lines = [f"  删 {k}" for k in gone] + [f"  增 {k}" for k in added]
        for k, old, new in changed:
            lines += [f"  改 {k}", f"    - {old}", f"    + {new}"]
        if lines:
            more = [f"  …另 {len(lines) - LIMIT} 行"] if len(lines) > LIMIT else []
            detail += [f"### `{path}` · {item}", "", "```", *lines[:LIMIT], *more, "```", ""]
    out += ["", "## 逐项", "", *detail] if detail else ["", "比过的项全部没有差异。", ""]
    if imgs:
        out += ["## 引用了但该提交里没有的图片", ""]
        out += [f"- `{path}`（{side}）：{'、'.join(f'`{m}`' for m in miss)}" for path, side, miss in imgs]
    return "\n".join(out).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="frm", required=True, help="旧提交（如上一轮被评提交）")
    ap.add_argument("--to", required=True, help="新提交（如答复提交）")
    ap.add_argument("--top", help="只比这个顶层（默认两个提交里出现的全部顶层）")
    ap.add_argument("--same", help=f"逗号分隔，这些项必须没有差异，否则退出 1；可选 {','.join(ITEMS)}")
    ap.add_argument("--out", help="表另存到这个文件")
    a = ap.parse_args(argv)
    same = [s.strip() for s in (a.same or "").split(",") if s.strip()]
    try:
        bad = [s for s in same if s not in ITEMS]
        if bad:
            raise SpecDiffError(f"--same 里不认识的项：{'、'.join(bad)}（可选 {'、'.join(ITEMS)}）")
        sha_a, sha_b, rows, imgs = diff(a.frm, a.to, a.top)
    except SpecDiffError as e:
        print(f"spec_diff：{e}", file=sys.stderr)
        return 2
    text = render(sha_a, sha_b, rows, imgs)
    print(text, end="")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    hit = sorted({item for _, item, g, ad, ch, _, _ in rows if item in same and (g or ad or ch)})
    if hit:
        print(f"spec_diff：--same 要求不变的项有差异：{'、'.join(hit)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
