"""开源集合导出器（open-export，open-export-tool，内部#305）。

用法:
    .venv/bin/python3 flow/export/export.py --out <空目录>                    # 导出 HEAD
    .venv/bin/python3 flow/export/export.py --ref <提交> --out <空目录> [--manifest <清单>]

- 开源集合与 `leak_scan.py` 同一份白名单（默认取 `--ref` 提交里的 `flow/export/manifest.yaml`），
  取的是**提交**的树，不是工作区。`--out` 必须不存在或为空。
- 清单 `substitute:` 里的发布路径写的是源路径的内容，可执行位与符号链接也随源；改写与 `verbatim:`
  按发布路径判断（open-export-substitute）。白名单无效（如源不在树里）时退出 2，什么都不写。
- 私有 issue 引用改写成 `内部#N`（D3）：裸 `#N`；清单 `rewrite.issue_repos` 里那些仓的 issue
  链接，链接整个去掉，链接文字不是 `#N` 时留下文字。
- 只改说明文字，不改代码（D4）：`.md` `.txt` 整个文件；`.py` 只改注释与 docstring；Verilog 与
  Verilator 配置只改 `//` 之后；其他文本只改行首或空白之后第一个 `#` 起的部分。清单 `verbatim:`
  里的文件、二进制文件、符号链接原样导出，可执行位保留。
- 改写后的内容按清单的全部规则复扫：block 有命中就退出 1，什么都不写；warn 的剩余命中按文件
  报出，不拦导出。
- 不建 git 仓、不提交、不推送：建公开仓与推送是后续阶段的对外动作。
"""
import argparse
import io
import os
import re
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leak_scan  # noqa: E402

PREFIX = "内部"
ISSUE_REF = re.compile(r"(?<![\w&])#(\d+)\b")
PROSE = (".md", ".txt")
SLASH_COMMENT = (".v", ".sv", ".svh", ".vh", ".vlt")
HASH_COMMENT = re.compile(r"(?:^|(?<=\s))#")


def make_rewriter(issue_repos):
    """返回 rw(text)：把一段说明文字里的私有 issue 引用改成 `内部#N`。"""
    link = bare = None
    if issue_repos:
        url = (r"https?://github\.com/(?:%s)/issues/(\d+)(?:#[\w-]+)?"
               % "|".join(re.escape(r) for r in issue_repos))
        link = re.compile(r"\[([^\]\n]*)\]\(" + url + r"\)")
        bare = re.compile(url)

    def md(m):
        text, num = m.group(1).strip(), m.group(2)
        return f"{PREFIX}#{num}" if text in (num, f"#{num}") else f"{text}（{PREFIX}#{num}）"

    def rw(s):
        if link:
            s = link.sub(md, s)
            s = bare.sub(lambda m: f"{PREFIX}#{m.group(1)}", s)
        return ISSUE_REF.sub(lambda m: f"{PREFIX}#{m.group(1)}", s)
    return rw


_STMT_START = (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)


def _py_spans(text):
    """注释与 docstring 的 [起, 止) 字符偏移。docstring 指单独成句的字符串字面量。"""
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    spans = []
    for i, tk in enumerate(toks):
        if tk.type == tokenize.STRING:
            j = i - 1
            while j >= 0 and toks[j].type in (tokenize.NL, tokenize.COMMENT):
                j -= 1
            k = i + 1
            while k < len(toks) and toks[k].type == tokenize.NL:
                k += 1
            opens = j < 0 or toks[j].type in _STMT_START or toks[j].string == ":"
            closes = k < len(toks) and toks[k].type in (tokenize.NEWLINE, tokenize.ENDMARKER)
            if not (opens and closes):
                continue
        elif tk.type != tokenize.COMMENT:
            continue
        spans.append((starts[tk.start[0] - 1] + tk.start[1], starts[tk.end[0] - 1] + tk.end[1]))
    return spans


def rewrite_text(path, text, rw):
    """按文件类型只改说明文字（D4）。"""
    if path.endswith(PROSE):
        return rw(text)
    if path.endswith(".py"):
        for a, b in reversed(_py_spans(text)):
            text = text[:a] + rw(text[a:b]) + text[b:]
        return text
    out = []
    for line in text.splitlines(keepends=True):
        if path.endswith(SLASH_COMMENT):
            i = line.find("//")
        else:
            m = HASH_COMMENT.search(line)
            i = m.start() if m else -1
        out.append(line if i < 0 else line[:i] + rw(line[i:]))
    return "".join(out)


def _modes(repo, ref):
    modes = {}
    for entry in leak_scan._git(repo, "ls-tree", "-r", "-z", ref).decode().split("\0"):
        if entry:
            meta, path = entry.split("\t", 1)
            modes[path] = meta.split()[0]
    return modes


def build(repo, ref, manifest):
    """[(路径, git 模式, 导出内容字节, 是否改写过)]。"""
    files = leak_scan.open_files(repo, ref, manifest)
    subst = manifest["substitute"]
    modes = _modes(repo, ref)
    rw = make_rewriter(manifest["issue_repos"])
    out = []
    for path, data in leak_scan._blobs(repo, ref, files, subst):
        mode = modes[subst.get(path, path)]
        new = data
        if (mode != "120000" and b"\0" not in data[:8192]
                and not leak_scan._match_any(path, manifest["verbatim"])):
            text = data.decode("utf-8")
            try:
                new = rewrite_text(path, text, rw).encode("utf-8")
            except (tokenize.TokenError, SyntaxError) as e:
                print(f"{path}: 解析不了（{e}），原样导出")
        out.append((path, mode, new, new != data))
    return out


def write(out_dir, entries):
    for path, mode, data, _ in entries:
        dst = out_dir / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if mode == "120000":
            os.symlink(data.decode(), dst)
            continue
        dst.write_bytes(data)
        if mode == "100755":
            dst.chmod(0o755)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(leak_scan.REPO_ROOT))
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--manifest", help="改用这份清单文件（默认取 --ref 提交里的 %s）" % leak_scan.MANIFEST)
    ap.add_argument("--out", required=True, help="导出目录，必须不存在或为空")
    a = ap.parse_args(argv)

    out_dir = Path(a.out)
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        print(f"拒绝导出：{out_dir} 不是空目录")
        return 2

    sha = leak_scan._git(a.repo, "rev-parse", a.ref).decode().strip()
    try:
        manifest = leak_scan.load_manifest(a.repo, a.ref, a.manifest)
        entries = build(a.repo, sha, manifest)
    except leak_scan.ManifestError as e:
        print(f"白名单无效：{e}，不导出")
        return 2
    hits = leak_scan.scan_blobs(manifest["rules"], [(p, d) for p, _, d, _ in entries])

    blocked = [h for h in hits if h[2] == "block"]
    if blocked:
        for path, no, level, name, _ in blocked:
            print(f"{path}:{no}: {name} [{level}]")
        print(f"block 命中 {sum(h[4] for h in blocked)} 处，不导出")
        return 1

    write(out_dir, entries)
    print(f"导出 {a.ref}（{sha[:12]}）→ {out_dir}：文件 {len(entries)} 个，"
          f"改写 {sum(1 for e in entries if e[3])} 个")
    for level, name, _ in manifest["rules"]:
        if level != "warn":
            continue
        per_file = {}
        for path, _, lv, nm, n in hits:
            if nm == name:
                per_file[path] = per_file.get(path, 0) + n
        print(f"剩余 {name} [warn]: {sum(per_file.values())}")
        for path in sorted(per_file):
            print(f"  {path}: {per_file[path]}")
    print("block 命中 0 处，已导出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
