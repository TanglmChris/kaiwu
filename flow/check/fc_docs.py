# fast_check 的「LRS / LLD 等设计文档」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_docs [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG  # 设计树遍历（内部#305）
import glob, os, re, sys, yaml

# 一项可以是几个名字的元组，任一个都算（lrs-writing-rules D1、D2：「术语与约定」改名「术语」，
# 旧名以「术语」开头仍算；第 0 节叫「文档信息」或「修订记录」都行）
LRS_SECTIONS = (("文档信息", "修订记录"), "概述", "配置与应用场景", "术语", "参数", "接口", "功能描述",
                "异常与 DFX", "性能需求")
# LLD 按模块组织（内部#203，用户 2026-10-05 定 Q1 选 A；lld-restructure D1）：参数化实现、功能设计、综合与 PPA 预期、
# 子模块详述不再必填，参数 / PPA / 时序另立 param / ppa / timing 文档
LLD_SECTIONS = (("文档信息", "修订记录"), ("概述", "设计概述"), "框图与模块划分", "DFX", "设计断言")
DEF_RE = re.compile(r"\*\*(R\.[0-9A-Za-z]+)\*\*")
REF_RE = re.compile(r"R\.[0-9A-Za-z]+")
ID_RE = re.compile(r"R\.\d{3}")
bad, hints, flat = [], [], []   # flat：不缩进打印的违规（路径打头），失败豁免认得出

def missing_sections(path, required):
    heads = [re.sub(r"^[\d.\s]+", "", m.group(1)).strip()
             for m in re.finditer(r"^##[ \t]+(.+?)\s*$", open(path, encoding="utf-8").read(), re.M)]
    names = lambda sec: sec if isinstance(sec, tuple) else (sec,)
    return ["/".join(names(sec)) for sec in required
            if not any(h.startswith(n) for h in heads for n in names(sec))]

def trace_ids(path):
    """第一张表头含「需求」列的表里，该列出现的全部 R；没有这样的表返回 None。"""
    col, ids = None, set()
    for line in open(path, encoding="utf-8"):
        if not line.lstrip().startswith("|"):
            if col is not None:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if col is None:
            if "需求" in cells:
                col = cells.index("需求")
            continue
        if not "".join(cells).strip("-: ") or col >= len(cells):
            continue
        ids.update(REF_RE.findall(cells[col]))
    return ids if col is not None else None

def section(text, name):
    """「## <编号> <name>…」这一节的正文（到下一个 ## 为止）；没有返回空串。"""
    m = re.search(r"^##[ \t]+[\d.\s]*" + re.escape(name) + r".*$", text, re.M)
    if not m:
        return ""
    n = re.search(r"^##[ \t]", text[m.end():], re.M)
    return text[m.end():m.end() + n.start()] if n else text[m.end():]

def first_col(text, head):
    """第一列表头为 head 的表合起来，各行第一格（去反引号）。"""
    out, state = [], None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            state = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if state is None:
            state = "t" if cells[0] == head else "o"
            continue
        if state == "t" and "".join(cells).strip("-: "):
            out.append(cells[0].strip("\x60 "))
    return out

def first_cells(text):
    """各表数据行的第一格（去反引号），不看表头：断言表第一列叫「断言」或「编号」都认。"""
    out, state = [], None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            state = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if state is None:
            state = "t"
            continue
        if "".join(cells).strip("-: "):
            out.append(cells[0].strip("\x60 "))
    return out

ART = re.compile("[\u2500-\u257f\u25b6\u25c0\u2190-\u2193]")

A_REF = re.compile(r"(?<![A-Za-z0-9_])A(\d+)(?![A-Za-z0-9_])")

def module_checks(lld):
    """D2：模块划分表里每个模块在某个标题里出现；D3：标题含「死锁」的节至多一个。
    还带旧结构「子模块详述」这一 ## 节的 LLD，这两项只提示（过渡，lld-restructure 的 design）。"""
    text = open(lld, encoding="utf-8").read()
    heads = [(no, h) for no, h in ((text.count("\n", 0, m.start()) + 1, m.group(1))
                                   for m in re.finditer(r"^#{2,6}[ \t]+(.+?)\s*$", text, re.M))]
    out = []
    mods = []
    # 只认第一格里用反引号写、整体是大写标识符的名字（`SUB_X`（`MODE=1`）取 SUB_X）；
    # 「CMD PART」「地址计算」这类分组行没有这样的名字，不查
    # 表头第一格为「小模块」的整张表跳过：小模块在表里写一行，不单开节（内部#239，lld-small-modules D2）
    sec = section(text, "框图与模块划分")
    header, small = None, False
    for line in sec.splitlines():
        if not line.lstrip().startswith("|"):
            header = None
            continue
        cell = line.strip().strip("|").split("|")[0]
        if header is None:
            header = cell.strip()
            small = header == "小模块"
        if small:
            continue
        for name in re.findall("\x60([A-Z][A-Z0-9_]*)\x60", cell):
            if name not in mods:
                mods.append(name)
    for mod in mods:
        word = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(mod) + r"(?![A-Za-z0-9_])")
        if not any(word.search(h) for _, h in heads):
            out.append(f"{lld}：模块划分表里的 {mod} 没有自己的节（每个子模块一节，标题含模块名）")
    dl = [f"{no} 行「{h}」" for no, h in heads if "死锁" in h]
    if len(dl) > 1:
        out.append(f"{lld}：死锁与冒险分析写了 {len(dl)} 处（整个设计只写一处）：{'、'.join(dl)}")
    old = re.search(r"^##[ \t]+[\d.\s]*子模块详述", text, re.M) is not None
    return ([], [m + "（还是旧结构，按新模板重写后致命）" for m in out]) if old else (out, [])

# S1 / S2 / S5（内部#203，docs/spec-writing.md §5，lld-restructure D5）：现有文档清零后转为致命（内部#221）；
# S9（内部#253）仍只作提示（用户 2026-10-19 定，内部#221）
CODE_SPAN = re.compile("\x60[^\x60]*\x60")
PAREN = re.compile(r"（[^（）]*）|\([^()]*\)")
SENT_END = re.compile(r"[。！？]")
LINK_TARGET = re.compile(r"\]\([^)]*\)")      # 链接 / 图片的目标路径不算正文用词（S5）

def _plain(text):
    return PAREN.sub("", CODE_SPAN.sub("", text)).strip()

def _body_lines(text):
    """(行号, 行) —— 跳过代码块与表格行。"""
    fence = False
    for no, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("\x60\x60\x60"):
            fence = not fence
            continue
        if not fence and not line.lstrip().startswith("|"):
            yield no, line

def _lld_items(text):
    """(行号, 条目文字) —— LLD 的条目：`- ` / `* ` 列表项、`1.` 编号项、表格单元格（分隔行不算；内部#238）。"""
    fence = False
    for no, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("\x60\x60\x60"):
            fence = not fence
            continue
        if fence:
            continue
        if line.lstrip().startswith("|"):
            for cell in CODE_SPAN.sub("", line).strip().strip("|").split("|"):
                if cell.strip().strip("-: "):
                    yield no, cell
            continue
        m = re.match(r"\s*(?:[-*]|\d+[.)])\s+(.*)$", line)
        if m:
            yield no, m.group(1)

INFO_SEC = re.compile(r"##[ \t]+[\d.\s]*(文档信息|修订记录)")

def _info_lines(text):
    """文档信息 / 修订记录两节的行号：那里记的是历史改动说明，句子检查不看（内部#331，同 S9）。"""
    out, skip = set(), False
    for no, line in enumerate(text.splitlines(), 1):
        if re.match(r"##[ \t]", line):
            skip = INFO_SEC.match(line) is not None
        elif skip:
            out.add(no)
    return out

def _banned_words(text):
    """术语表里表头为「不用」或「不用的说法」那一列的词（按、，, / 拆开）。"""
    words, col = set(), None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            col = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if col is None:
            col = next((i for i, c in enumerate(cells) if c in ("不用", "不用的说法")), -1)
            continue
        if col >= 0 and col < len(cells) and "".join(cells).strip("-: "):
            words.update(w.strip().strip("\x60") for w in re.split(r"[、，,/]", cells[col]) if w.strip())
    return words

VAGUE_BOUND = ("有限", "尽快", "适当", "较少", "足够", "若干", "很快", "及时", "最终", "迟早", "无限", "一段时间", "合理", "必要时", "尽量")
HS_EXCEPTION = re.compile(r"(握手|握手之|未握手)前[^。；\n]{0,16}(可以|可|允许|会)[^。；\n]{0,8}(改|变|撤)")

def sentence_violations(lrs, lld):
    """S1 / S2 / S5 每处一行，以 路径:行号: 开头（失败豁免认得出，flow/check/check_waivers.py）。"""
    out = []
    def add(rule, path, no, note=""):
        out.append(f"{path}:{no}: {rule}{note}")
    lrs_t, lld_t = open(lrs, encoding="utf-8").read(), open(lld, encoding="utf-8").read()
    info = {lrs: _info_lines(lrs_t), lld: _info_lines(lld_t)}
    for no, line in _body_lines(lrs_t):
        if no in info[lrs]:
            continue
        m = re.search(r"\*\*R\.\d{3}\*\*(.*)$", line)
        if not m:
            continue
        body = _plain(m.group(1))
        if len(body) > 80:
            add("S1 句长（R 条文 > 80 字）", lrs, no)
        if body.count("；") + body.count(";") >= 2 or len(SENT_END.findall(body)) >= 3:
            add("S2 一句一事（R 条文分号 ≥ 2 或句数 ≥ 3）", lrs, no)
    for no, item in _lld_items(lld_t):
        if no in info[lld]:
            continue
        body = _plain(item)
        if len(body) > 200 or len(SENT_END.findall(body)) > 4:
            add("S1 句长（LLD 条目 > 200 字或 > 4 句）", lld, no)
    banned = _banned_words(lrs_t)
    for path, text in ((lrs, lrs_t), (lld, lld_t)):
        for no, line in _body_lines(text):
            if no in info[path]:
                continue
            hit = sorted(w for w in banned if w and w in LINK_TARGET.sub("]", CODE_SPAN.sub("", line)))
            if hit:
                add("S5 一词一义（用了术语表「不用」列的词）", path, no, f"（{'、'.join(hit)}）")
    return out

EXAMPLES = 3

def vague_bound_hints(lrs):
    """S9 只作提示（用户 2026-10-19 定，内部#221）：给处数与前 3 处的 文件:行号。"""
    found = []
    lrs_t = open(lrs, encoding="utf-8").read()
    # S9（内部#253）：上界、延时、深度、次数写数字或参数公式；「有限拍内」「尽快」这类词不可检验。只看 LRS 正文：
    # 跳过代码块、行内代码与修订记录 / 文档信息两节（那里记的是改动说明）
    skip_sec, fence = False, False
    for no, line in enumerate(lrs_t.splitlines(), 1):
        if line.lstrip().startswith("\x60\x60\x60"):
            fence = not fence
            continue
        if re.match(r"##[ \t]", line):
            skip_sec = re.match(r"##[ \t]+[\d.\s]*(文档信息|修订记录)", line) is not None
            continue
        if fence or skip_sec:
            continue
        hit = [w for w in VAGUE_BOUND if w in CODE_SPAN.sub("", line)]
        if hit:
            found.append(f"{lrs}:{no}（{'、'.join(hit)}）")
    if not found:
        return []
    return [f"S9 上界写数字（上界 / 延时 / 深度 / 次数写数字或参数公式，不写「有限」「尽快」一类）：{len(found)} 处，例如 {'；'.join(found[:EXAMPLES])}"]

def handshake_exceptions(lrs, lld):
    """H1（内部#284）：握手规则（docs/spec-writing.md §3）的例外要标「例外」并注出处。handshake-depth-contracts
    （内部#286，用户 10-13）起致命；违规行不缩进、以 路径:行号: 开头，失败豁免才认得出（flow/check/check_waivers.py）。"""
    out = []
    for path in (lrs, lld):
        for no, line in _body_lines(open(path, encoding="utf-8").read()):
            if HS_EXCEPTION.search(line) and not ("例外" in line and re.search(r"出处|#\d+", line)):
                out.append(f"{path}:{no}: H1 握手规则例外没标出处（「握手前可以改 / 撤回」一类要写「例外，出处：…」，"
                           "docs/spec-writing.md §3）")
    return out

COMMON_ROWS = ("握手保持", "valid 不依赖 ready", "汇聚口屏蔽", "活性", "写数据不等命令", "功能不依赖打拍配置")

def common_verify_table(path):
    """D2（handshake-depth-contracts，内部#286）：verify 计划要有表头第一格为「通用规范」的表，6 行齐、覆盖格非空。"""
    rows, cover, in_table = {}, None, False
    for line in open(path, encoding="utf-8"):
        if not line.lstrip().startswith("|"):
            if in_table:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not in_table:
            if cells and cells[0] == "通用规范":
                in_table = True
                cover = cells.index("覆盖") if "覆盖" in cells else len(cells) - 1
            continue
        if not "".join(cells).strip("-: "):
            continue
        rows[cells[0]] = cells[cover] if cover < len(cells) else ""
    if not in_table:
        return [f"{path}: 没有「通用规范」表（全仓通用规范的验证项，模板 flow/templates/design-root/verify.md，#286）"]
    out = [f"{path}: 「通用规范」表缺一行：{r}" for r in COMMON_ROWS if r not in rows]
    out += [f"{path}: 「通用规范」表「{r}」一行的覆盖格是空的（没有握手接口写「不适用」加原因）"
            for r in COMMON_ROWS if r in rows and not rows[r]]
    return out

def extra_checks(lrs, lld, declared):
    """参数表、断言编号、版本表（内部#113，flow-guard-feedback D4–D6）。"""
    out = []
    lrs_t, lld_t = open(lrs, encoding="utf-8").read(), open(lld, encoding="utf-8").read()
    listed = set(first_col(section(lrs_t, "参数"), "参数"))
    for name in sorted(set(declared) - listed):
        out.append(f"{lrs} 的参数表漏了 {name}（params.yaml 声明了它）")
    defs = [a for a in first_cells(section(lld_t, "设计断言")) if re.fullmatch(r"A\d+", a)]
    for a in sorted({a for a in defs if defs.count(a) > 1}, key=lambda x: int(x[1:])):
        out.append(f"{lld} 的设计断言表里 {a} 定义了 {defs.count(a)} 次")
    refs = {f"A{n}" for n in A_REF.findall(lrs_t + lld_t)}
    for a in sorted(refs - set(defs), key=lambda x: int(x[1:])):
        out.append(f"{lrs} / {lld} 引用了断言 {a}，设计断言表里没有它")
    # 字符画结构图（内部#126，lrs-writing-rules-2 D3）：代码块里出现框线或箭头字符就算，改用 draw.io 图
    fence, in_code = "\x60" * 3, False
    for no, line in enumerate(lrs_t.splitlines(), 1):
        if line.lstrip().startswith(fence):
            in_code = not in_code
            continue
        if in_code and ART.search(line):
            out.append(f"{lrs}:{no} 代码块里是字符画结构图：结构图用 draw.io 画，导出 SVG 放 doc/ 再引用")
            break
    # 图注（内部#137，spec-readability D1；LLD 同样要，内部#226）：代码块外的图片引用之后，第一个非空行要是「**图 」开头的图注
    for path, text in ((lrs, lrs_t), (lld, lld_t)):
        in_code, want = False, None
        for no, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(fence):
                in_code = not in_code
                continue
            if in_code or not line.strip():
                continue
            if want is not None and not line.lstrip().startswith("**图 "):
                out.append(f"{path}:{want} 的图没有图注：下一个非空行要写「**图 <章>-<序>** 标题 —— 看什么」"
                           "（docs/spec-writing.md 第 6 节）")
            want = no if re.search(r"!\[[^\]]*\]\x28[^\x29]*\x29", line) else None
        if want is not None:
            out.append(f"{path}:{want} 的图没有图注：下一个非空行要写「**图 <章>-<序>** 标题 —— 看什么」"
                       "（docs/spec-writing.md 第 6 节）")
    for path, text in ((lrs, lrs_t), (lld, lld_t)):
        vers = []
        for cell in first_col(text, "版本"):
            m = re.fullmatch(r"v(\d+)\.(\d+)", cell)
            if m:
                vers.append(((int(m.group(1)), int(m.group(2))), cell))
        for (a, ca), (b, cb) in zip(vers, vers[1:]):
            if b <= a:
                out.append(f"{path} 的版本表要按版本号升序：{cb} 排在 {ca} 后面")
                break
        # 文档信息表里「版本」一行要等于修订记录最后一行（内部#226）：两处各记一份，改了一处常漏另一处
        info = re.search(r"^\|\s*版本\s*\|\s*(v\d+\.\d+)\s*\|\s*$", section(text, "文档信息"), re.M)
        if info and vers and info.group(1) != vers[-1][1]:
            out.append(f"{path} 文档信息表的版本是 {info.group(1)}，修订记录最后一行是 {vers[-1][1]}：两处要一致（#226）")
    return out

def _cur_version(text):
    """修订记录最后一行的版本（内部#226 已保证文档信息表的版本与它一致）；没有返回 None。"""
    vers = [c for c in first_col(text, "版本") if re.fullmatch(r"v\d+\.\d+", c)]
    return vers[-1] if vers else None

def version_line_hints(root, top, lrs_t, lld_t):
    """内部#331 ①：LLD / param / ppa / timing 文档信息表「对应 LRS / LLD」一行写的版本 = 两份文档当前版本。
    只作提示：LRS / LLD 每改一版，另几份不一定要跟着改，但写着的版本号不能是假的。"""
    cur = {"lrs": _cur_version(lrs_t), "lld": _cur_version(lld_t)}
    out = []
    for kind in ("lld", "param", "ppa", "timing"):
        path = os.path.join(root, f"{kind}.{top}.md")
        if not os.path.exists(path):
            continue
        for line in section(open(path, encoding="utf-8").read(), "文档信息").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not line.lstrip().startswith("|") or not cells[0].startswith("对应 LRS"):
                continue
            for doc, ver in re.findall(r"(lrs|lld)\." + re.escape(top) + r"\.md\x60?\s*(v\d+\.\d+)", line):
                if cur[doc] and ver != cur[doc]:
                    out.append(f"{path} 文档信息表写对应 {doc}.{top}.md {ver}，它现在是 {cur[doc]}："
                               "核一遍本文是否还对得上，对得上就改版本号（#331）")
    return out

LLD_NAME = re.compile(r"U_[A-Z0-9_]+|[a-z][a-z0-9_]*_r")

def lld_name_hints(root, lld, lld_t):
    """内部#331 ③：LLD 反引号里的例化名（U_*）与寄存器名（*_r）在本设计树的 RTL 里找不到就提示（名字过时，rtl-r9-01、内部#295）。
    只认整段反引号就是一个名字的；带通配（advance_*_r）的不查；修订记录 / 文档信息两节不看。"""
    rtl = "".join(open(f, encoding="utf-8").read() for f in sorted(glob.glob(os.path.join(root, "rtl", "*.v"))))
    if not rtl:
        return []
    words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rtl))
    info, miss = _info_lines(lld_t), {}
    for no, line in enumerate(lld_t.splitlines(), 1):
        if no in info:
            continue
        for name in CODE_SPAN.findall(line):
            name = name.strip("\x60")
            if LLD_NAME.fullmatch(name) and name not in words:
                miss.setdefault(name, []).append(no)
    return [f"{lld}:{nos[0]} 的 \x60{name}\x60 在 {root}/rtl/*.v 里找不到（例化名 / 寄存器名改了没同步？#331）"
            for name, nos in sorted(miss.items(), key=lambda kv: kv[1][0])]

n_tops = n_reqs = 0
for pfile in _TG("*/params.yaml", kind="design"):
    root = os.path.dirname(pfile)
    tops = (yaml.safe_load(open(pfile)) or {}).get("tops") or {}
    for top in tops:
        n_tops += 1
        lrs, lld = os.path.join(root, f"lrs.{top}.md"), os.path.join(root, f"lld.{top}.md")
        here = []
        for path in (lrs, lld):
            if not os.path.exists(path):
                here.append(f"{path} 不存在（专用设计树下每个被测顶层要有 LRS 与 LLD；旧格式 spec / design 已退役，#134）")
        if here:
            bad += here
            continue
        for path, req in ((lrs, LRS_SECTIONS), (lld, LLD_SECTIONS)):
            miss = missing_sections(path, req)
            if miss:
                bad.append(f"{path} 缺必填节：{'、'.join(miss)}")
        defs = DEF_RE.findall(open(lrs, encoding="utf-8").read())
        for d in sorted({d for d in defs if not ID_RE.fullmatch(d)}):
            bad.append(f"{lrs}：需求编号 {d} 格式不对，要写成 R. 加三位数字（如 R.001）")
        defs = [d for d in defs if ID_RE.fullmatch(d)]
        for d in sorted({d for d in defs if defs.count(d) > 1}):
            bad.append(f"{lrs}：{d} 定义了 {defs.count(d)} 次（加粗的 R 编号是定义，只能有一处）")
        if not defs:
            bad.append(f"{lrs} 没有定义任何需求：LRS 至少要有一条加粗的 R.00X")
        n_reqs += len(set(defs))
        bad += extra_checks(lrs, lld, (tops[top] or {}).get("params") or {})
        mb, mh = module_checks(lld)
        bad += mb
        hints += mh
        bad += sentence_violations(lrs, lld)
        hints += vague_bound_hints(lrs)
        lrs_t, lld_t = open(lrs, encoding="utf-8").read(), open(lld, encoding="utf-8").read()
        hints += version_line_hints(root, top, lrs_t, lld_t)
        hints += lld_name_hints(root, lld, lld_t)
        flat += handshake_exceptions(lrs, lld)
        # D4：param / ppa / timing 三份文档；LLD 还是旧结构时只提示（同 module_checks 的过渡）
        old = re.search(r"^##[ \t]+[\d.\s]*子模块详述", open(lld, encoding="utf-8").read(), re.M) is not None
        for kind in ("param", "ppa", "timing"):
            path = os.path.join(root, f"{kind}.{top}.md")
            if not os.path.exists(path):
                msg = f"{path} 不存在（参数 / PPA / 时序各一份文档，模板在 flow/templates/design-root/{kind}.md，#203）"
                (hints if old else bad).append(msg + ("（LLD 还是旧结构，按新模板重写后致命）" if old else ""))
        traced = trace_ids(lld)
        if traced is None:
            bad.append(f"{lld} 没有追溯表（表头含「需求」列的表，列出 LRS 的全部 R）")
            continue
        for d in sorted(set(defs) - traced):
            bad.append(f"{lld} 的追溯表漏了 {d}（LRS 有这条需求，LLD 没写在哪里实现）")
        for d in sorted(traced - set(defs)):
            bad.append(f"{lld} 的追溯表引用了 {d}，LRS 没有定义它")
        # 反向追溯（内部#140，spec-readability D2）：LLD 全文引用的 R 都要在 LRS 有定义；修订记录一节可以记已删编号
        skip_sec, seen = False, set(traced)
        for no, line in enumerate(open(lld, encoding="utf-8"), 1):
            if re.match(r"##[ \t]", line):
                skip_sec = re.match(r"##[ \t]+[\d.\s]*(文档信息|修订记录)", line) is not None
                continue
            if skip_sec:
                continue
            for d in re.findall(r"(?<![0-9A-Za-z])R\.\d{3}(?![0-9])", line):
                if d not in defs and d not in seen:
                    seen.add(d)
                    bad.append(f"{lld}:{no} 引用了 {d}，LRS 没有定义它（已删除的需求换成取代它的编号，见跟踪文档）")

for vpath in _TG("*/verify.*.md"):
    flat += common_verify_table(vpath)
for msg in flat:
    print(msg, file=sys.stderr)
for msg in bad:      # 路径打头、不缩进：失败豁免按行首路径匹配（内部#290）
    print(msg, file=sys.stderr)
for msg in hints:
    print(f"  提示：{msg}", file=sys.stderr)
if bad:
    print("  契约：openspec/specs/repo-layout/spec.md「专用设计的 LRS 与 LLD 必须有必填节与需求追溯」；"
          "模板在 flow/templates/design-root/。", file=sys.stderr)
print(f"{n_tops}\t{n_reqs}")
sys.exit(1 if bad or flat else 0)
