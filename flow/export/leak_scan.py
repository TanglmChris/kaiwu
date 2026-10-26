"""开源集合的泄漏扫描（open-export，内部#305）。

用法:
    .venv/bin/python3 flow/export/leak_scan.py                      # 扫 HEAD，有 block 命中退出 1
    .venv/bin/python3 flow/export/leak_scan.py --ref <提交> --only 'flow/**' --only 'scripts/**'
    .venv/bin/python3 flow/export/leak_scan.py --list                # 只列开源集合，不扫

- 开源集合由 `flow/export/manifest.yaml` 的白名单决定，**默认闭源**：没有被 `include`
  匹配的已跟踪文件一律不算开源；`exclude` 从已匹配的里再排除。`substitute:` 写「发布路径: 源路径」：
  发布路径属于开源集合、内容取自源路径，源路径不以自己的名字算开源；源不在树里、同一源对应两个
  发布路径、发布与源相同，都以退出 2 报错（open-export-substitute）。
- 扫描对象是 `--ref` 那个**提交**的树（清单也取自那个提交），不是工作区 —— 导出的是
  提交，工作区里没提交的东西不该影响结论。`--manifest` 可改用工作区里的一份清单。
- 规则分两级：`block` 命中即退出 1；`warn` 只计数。路径本身也按规则查（行号记 0）。
- 清单写了 `closed_vocab:` 时多一条 block 规则 `closed-vocab`（open-export-closed-vocab）：从 `--ref` 树里的
  闭源设计根（`roots` 的 glob 匹配到、没有文件进开源集合的目录）抽出 `rtl/` 下 RTL 的模块名、参数名、端口名
  和代码文件名，去掉开源根也有的、短于 `min_len` 的、`allow` / `allow_patterns` 豁免的，剩下的按标识符整词匹配。
  抽出的词切词器切不出、或闭源 RTL 一个词也抽不出时以退出 2 报自检失败。`--show-terms` 在命中行后面打印命中的词。
  `history: true` 时还从 git 历史里删掉的设计根文件（删除前最后一版）抽词，现在仍开源的根与 `history_open_roots`
  匹配的根跳过；历史文件抽不出词不报错（open-export-closed-vocab-history）。
- 二进制文件（前 8 KB 含 NUL）跳过。
- 清单自己**永远闭源**：它的 block 规则与 `closed_vocab` 豁免表就是一份闭源名字表，公开它等于公开要藏的东西。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = "flow/export/manifest.yaml"


class ManifestError(ValueError):
    """白名单本身有错（如 substitute 的源不在树里）：扫描与导出都以退出 2 报出，不当成泄漏命中。"""


def glob_to_regex(pattern):
    """仓库根相对的 glob：`**` 跨目录，`*` 与 `?` 不跨 `/`。"""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _match_any(path, regexes):
    return any(r.match(path) for r in regexes)


def _git(repo, *args, data=None):
    proc = subprocess.run(["git", "-C", str(repo), *args], input=data,
                          capture_output=True, check=True)
    return proc.stdout


def load_manifest(repo, ref, manifest_path=None):
    if manifest_path:
        text = Path(manifest_path).read_text()
    else:
        text = _git(repo, "show", f"{ref}:{MANIFEST}").decode()
    m = yaml.safe_load(text) or {}
    rules = []
    for level in ("block", "warn"):
        for r in (m.get("rules") or {}).get(level) or []:
            flags = re.IGNORECASE if r.get("ignore_case") else 0
            rules.append((level, r["name"], re.compile(r["pattern"], flags)))
    manifest = {
        "include": [glob_to_regex(g) for g in m.get("include") or []],
        "exclude": [glob_to_regex(g) for g in m.get("exclude") or []],
        "rules": rules,
        # 下面两项只有导出器用（export.py）
        "verbatim": [glob_to_regex(g) for g in m.get("verbatim") or []],
        "issue_repos": list((m.get("rewrite") or {}).get("issue_repos") or []),
        "substitute": _substitutes(m.get("substitute")),
    }
    if "closed_vocab" in m:
        # 插在 block 规则的末尾：scan_blobs 只调 search / findall，泄漏门禁与导出器不用改就带上它。
        # 不给 ref 的调用方（tests/test_team_layout.py 扫工作区）按 HEAD 的树抽词
        at = sum(1 for level, _, _ in rules if level == "block")
        rules.insert(at, ("block", "closed-vocab", closed_vocab(repo, ref or "HEAD", manifest, m["closed_vocab"] or {})))
    return manifest


# ---- 闭源词表（open-export-closed-vocab）----
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
RTL_EXT = (".v", ".sv", ".vh", ".svh")
CODE_EXT = (".py", ".v", ".sv", ".sh", ".tcl")
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_SUBPROGRAM = re.compile(r"\b(function|task)\b.*?\bend\1\b", re.S)   # 函数 / 任务的参数不是端口
_MODULE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
_PARAM = re.compile(r"\b(?:parameter|localparam)\s+(?:(?:integer|int|logic|bit|reg|signed|unsigned)\s+)*"
                    r"(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)")
_PORT = re.compile(r"\b(?:input|output|inout)\s+(?:(?:wire|reg|logic|var|signed|unsigned)\s+)*"
                   r"(?:\[[^\]]*\]\s*)*([A-Za-z_]\w*)")


class VocabMatcher:
    """按标识符整词匹配一张词表；与正则一样提供 scan_blobs 用的 search / findall。"""

    def __init__(self, terms):
        self.terms = frozenset(terms)

    def findall(self, text):
        return [t for t in TOKEN.findall(text) if t in self.terms]

    def search(self, text):
        return any(t in self.terms for t in TOKEN.findall(text))


def _design_roots(listed, root_globs):
    """{根目录: [文件]}：每个文件归到第一个被 `root_globs` 匹配的祖先目录。"""
    roots = {}
    for p in listed:
        parts = p.split("/")
        for k in range(1, len(parts)):
            d = "/".join(parts[:k])
            if _match_any(d, root_globs):
                roots.setdefault(d, []).append(p)
                break
    return roots


def _root_terms(repo, ref, root, files, self_check):
    """一个设计根的词：`rtl/` 下 RTL 的模块 / 参数 / 端口名，加代码文件名（第一个 `.` 之前）。
    `self_check` 时，抽出的每个词都要能被 TOKEN 在来源文件里切出来，闭源 RTL 也不能一个词都抽不出。"""
    rtl = [f for f in files if f.startswith(root + "/rtl/") and f.endswith(RTL_EXT)]
    terms = _rtl_terms(_blobs(repo, ref, rtl), self_check)
    if self_check and rtl and not terms:
        raise ManifestError(f"闭源词表自检失败：{root} 的 rtl/ 下有 {len(rtl)} 个 RTL 文件，却一个词也没抽出来")
    return terms | _code_stems(files)


def _rtl_terms(blobs, self_check):
    """(路径, 内容) 序列里 RTL 的模块 / 参数 / 端口名；`self_check` 时每个词都要能被 TOKEN 在来源里切出来。"""
    terms = set()
    for path, data in blobs:
        text = _COMMENT.sub(" ", data.decode("utf-8", errors="replace"))
        found = set(_MODULE.findall(text)) | set(_PARAM.findall(text)) | set(_PORT.findall(_SUBPROGRAM.sub(" ", text)))
        if self_check:
            missing = found - set(TOKEN.findall(text))
            if missing:
                raise ManifestError(f"闭源词表自检失败：{path} 里抽出的 {', '.join(sorted(missing)[:10])} 切词器切不出来")
        terms |= found
    return terms


def _code_stems(files):
    terms = set()
    for f in files:
        if f.endswith(CODE_EXT):
            stem = f.rsplit("/", 1)[-1].split(".", 1)[0]
            if TOKEN.fullmatch(stem):
                terms.add(stem)
    return terms


def closed_vocab(repo, ref, manifest, cfg):
    """`closed_vocab:` 段 → VocabMatcher。闭源根 = 没有文件进开源集合的设计根。"""
    root_globs = [glob_to_regex(g) for g in cfg.get("roots") or ["designs/*", "cbb/*"]]
    min_len = int(cfg.get("min_len", 4))
    allow = set(cfg.get("allow") or [])
    allow_res = [re.compile(p) for p in cfg.get("allow_patterns") or []]
    listed = [p for p in _git(repo, "ls-tree", "-r", "--name-only", "-z", ref).decode().split("\0") if p]
    open_set = set(open_files(repo, ref, manifest))
    closed, opened, open_roots = set(), set(), set()
    for root, files in sorted(_design_roots(listed, root_globs).items()):
        if any(f in open_set for f in files):
            opened |= _root_terms(repo, ref, root, files, self_check=False)
            open_roots.add(root)
        else:
            closed |= _root_terms(repo, ref, root, files, self_check=True)
    if cfg.get("history"):
        hist_open = [glob_to_regex(g) for g in cfg.get("history_open_roots") or []]
        closed |= _history_terms(repo, ref, cfg.get("roots") or ["designs/*", "cbb/*"], root_globs,
                                 set(listed), open_roots, hist_open)
    return VocabMatcher(t for t in closed - opened
                        if len(t) >= min_len and t not in allow and not any(r.fullmatch(t) for r in allow_res))


def _history_terms(repo, ref, roots, root_globs, present, open_roots, hist_open):
    """git 历史里删掉、`ref` 树里没有的设计根文件，取最近一次删除前的一版抽词（open-export-closed-vocab-history）。
    现在仍开源的根、`history_open_roots` 匹配的根跳过；历史文件抽不出词不报错（历史改不了），切词自检照查。"""
    prefixes = sorted({re.split(r"[*?\[]", g, 1)[0].rstrip("/") or "." for g in roots})
    log = _git(repo, "log", "--diff-filter=D", "--name-only", "--format=@%H", ref, "--", *prefixes).decode()
    deleted, commit = {}, None
    for line in log.splitlines():
        if line.startswith("@"):
            commit = line[1:]
        elif line and line not in present and line not in deleted:   # log 新的在前：第一次见到的就是最近一次删除
            deleted[line] = commit
    terms = set()
    for root, files in sorted(_design_roots(sorted(deleted), root_globs).items()):
        if root in open_roots or _match_any(root, hist_open):
            continue
        rtl = [f for f in files if f.startswith(root + "/rtl/") and f.endswith(RTL_EXT)]
        terms |= _rtl_terms(_blobs_at(repo, [(f, f"{deleted[f]}^:{f}") for f in rtl]), self_check=True)
        terms |= _code_stems(files)
    return terms


def _blobs_at(repo, items):
    """[(标签, "<提交>:<路径>")] → 产出 (标签, 内容)；读不到的（如合并提交的第一个父提交里没有）跳过。"""
    if not items:
        return
    out = _git(repo, "cat-file", "--batch", data="".join(f"{spec}\n" for _, spec in items).encode())
    pos = 0
    for label, _ in items:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        if header[-1] == b"missing":
            pos = nl + 1
            continue
        size = int(header[2])
        yield label, out[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1


def _substitutes(raw):
    """{发布路径: 源路径}；同一源对应两个发布路径、发布与源相同、不是字符串都算白名单无效。"""
    subst = {}
    for pub, src in (raw or {}).items():
        if not isinstance(pub, str) or not isinstance(src, str):
            raise ManifestError(f"substitute 的项要写成「发布路径: 源路径」：{pub!r}: {src!r}")
        if pub == src:
            raise ManifestError(f"substitute 的发布路径与源路径相同：{pub}")
        if src in subst.values():
            raise ManifestError(f"substitute 的源 {src} 对应了不止一个发布路径")
        subst[pub] = src
    return subst


def open_files(repo, ref, manifest):
    """`ref` 树里属于开源集合的文件（仓库根相对路径，排序）：白名单匹配的，去掉替代文件的源、加上发布路径。"""
    listed = _git(repo, "ls-tree", "-r", "--name-only", "-z", ref).decode().split("\0")
    subst = manifest["substitute"]
    for pub, src in subst.items():
        if src not in listed:
            raise ManifestError(f"substitute 的源 {src} 不在 {ref} 的树里（发布路径 {pub}）")
    sources = set(subst.values())
    return sorted({p for p in listed if p and p != MANIFEST and p not in sources
                   and _match_any(p, manifest["include"])
                   and not _match_any(p, manifest["exclude"])} | set(subst))


def _blobs(repo, ref, paths, subst=None):
    """按顺序产出 (路径, 内容字节)：一次 `git cat-file --batch` 读完，不逐个起进程。
    `subst` 里的发布路径读的是它的源路径，产出时仍用发布路径。"""
    if not paths:
        return
    subst = subst or {}
    req = "".join(f"{ref}:{subst.get(p, p)}\n" for p in paths).encode()
    out = _git(repo, "cat-file", "--batch", data=req)
    pos = 0
    for p in paths:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        size = int(header[2])
        yield p, out[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1


def scan(repo, ref, manifest, only=None):
    """[(路径, 行号, 级别, 规则名, 次数)]；行号 0 表示命中的是路径本身，次数是该行里的出现次数。"""
    files = open_files(repo, ref, manifest)
    if only:
        only_re = [glob_to_regex(g) for g in only]
        files = [p for p in files if _match_any(p, only_re)]
    return scan_blobs(manifest["rules"], _blobs(repo, ref, files, manifest["substitute"]))


def scan_blobs(rules, blobs):
    """按 `rules` 扫 (路径, 内容字节) 序列，返回值同 `scan`。导出器拿它复扫改写后的内容。"""
    hits = []
    for path, data in blobs:
        for level, name, rx in rules:
            if rx.search(path):
                hits.append((path, 0, level, name, len(rx.findall(path))))
        if b"\0" in data[:8192]:
            continue
        for no, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            for level, name, rx in rules:
                if rx.search(line):
                    hits.append((path, no, level, name, len(rx.findall(line))))
    return hits


def _hit_terms(repo, ref, manifest, hits):
    """{(路径, 行号): [命中的词]}，只算 closed-vocab 的命中；行号 0 是路径本身。"""
    matcher = next((rx for _, name, rx in manifest["rules"] if name == "closed-vocab"), None)
    want = {}
    for path, no, _level, name, _n in hits:
        if name == "closed-vocab":
            want.setdefault(path, set()).add(no)
    out = {}
    for path, data in _blobs(repo, ref, sorted(want), manifest["substitute"]):
        lines = data.decode("utf-8", errors="replace").splitlines()
        for no in want[path]:
            text = path if no == 0 else lines[no - 1]
            out[(path, no)] = sorted(set(matcher.findall(text)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(REPO_ROOT))
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--manifest", help="改用这份清单文件（默认取 --ref 提交里的 %s）" % MANIFEST)
    ap.add_argument("--only", action="append", help="只报告开源集合里匹配这个 glob 的文件，可重复")
    ap.add_argument("--list", action="store_true", help="只列开源集合")
    ap.add_argument("--show-terms", action="store_true", help="closed-vocab 命中行后面打印命中的词（本地清理用）")
    a = ap.parse_args(argv)

    try:
        manifest = load_manifest(a.repo, a.ref, a.manifest)
        if a.list:
            print("\n".join(open_files(a.repo, a.ref, manifest)))
            return 0
        hits = scan(a.repo, a.ref, manifest, a.only)
    except ManifestError as e:
        print(f"白名单无效：{e}")
        return 2
    terms = _hit_terms(a.repo, a.ref, manifest, hits) if a.show_terms else {}
    counts = {}
    for path, no, level, name, n in hits:
        shown = terms.get((path, no)) if name == "closed-vocab" else None
        print(f"{path}:{no}: {name} [{level}]" + (f" {' '.join(shown)}" if shown else ""))
        counts[(level, name)] = counts.get((level, name), 0) + n
    print("---")
    for level, name, _ in manifest["rules"]:
        print(f"{level} {name}: {counts.get((level, name), 0)}")
    blocked = sum(n for (lv, _), n in counts.items() if lv == "block")
    print(f"block 命中 {blocked} 处，{'不可导出' if blocked else '可导出'}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
