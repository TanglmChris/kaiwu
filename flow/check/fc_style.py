# fast_check 的「RTL 书写风格」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_style [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG, local_cbb_copies as _LOCAL  # 设计树遍历（内部#305）
import glob, os, re, sys

LEGACY = "flow/lint/style_legacy.txt"
LP, RP = chr(40), chr(41)          # 不在源码里写单个括号：bash 3.2 在 $( … ) 里会数它们
FIELDS = ("File", "Module", "Purpose", "Spec", "Language")
REG_OK = re.compile(r"\w*(_r|_\d+ff)$")
REPL_BARE = re.compile(r"\{\s*([A-Za-z_0-9]+\s*[-+*/][^{},;]*?)\{")
def load_local(report):
    """本地 CBB 副本名单（rtl-structure-authority「模块名必须全大写」的例外）：{路径: 应有的模块名}。
    全仓的 flow/lint/local_cbb.txt 与各设计根的 local_cbb.txt 取并集（flow/paths.py::local_cbb_copies，内部#305）。"""
    found, problems = _LOCAL()
    if report:
        for msg in problems:
            print(msg, file=sys.stderr)
    return found, len(problems)


# 名单失效由模块名那一项报，这里只取有效条目：{模块名: 所在 rtl/ 目录}
LOCAL_MODS = {mod: os.path.dirname(p) for p, mod in load_local(report=False)[0].items()}
INST_RE = re.compile(r"(?<![\x60.\w])([A-Z][A-Z0-9_]*"
                     + "".join("|" + re.escape(mod) for mod in sorted(LOCAL_MODS))
                     + r")\s*(#\s*\x28)?")


def strip(text):
    """剥掉注释与字符串字面量，换行与长度保留（偏移与行号不变）。"""
    out, i, n = list(text), 0, len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"' and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
        else:
            i += 1
            continue
        for k in range(i, j):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def match_paren(t, i):
    """t[i] 是左括号，返回与之配对的右括号之后的位置。"""
    depth = 0
    while i < len(t):
        if t[i] == LP:
            depth += 1
        elif t[i] == RP:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(t)


def assertion_else(t, i):
    """t[i:] 以 else 开头：它紧跟在 assert / assume / cover property (...) 的右括号之后时
    是断言的失败动作，不是 generate 的 else 分支（内部#234）。"""
    j = i - 1
    while j >= 0 and t[j].isspace():
        j -= 1
    if j < 0 or t[j] != RP:
        return False
    depth = 0
    while j >= 0:
        if t[j] == RP:
            depth += 1
        elif t[j] == LP:
            depth -= 1
            if depth == 0:
                break
        j -= 1
    return bool(re.search(r"\b(assert|assume|cover)\s+property\s*$", t[:max(j, 0)]))


WORD = re.compile(r"[A-Za-z_][\w$]*")


def block_span(t, i):
    """从 i 起跳过空白，若是 begin，返回 (名字或 None, 名字后的位置, 与之配对的 end 之后的位置)；
    不是 begin 时返回 (None, i, 到下一个 ; 之后的位置) —— 单条语句。"""
    m = re.compile(r"\s*begin\b(\s*:\s*([A-Za-z_]\w*))?").match(t, i)
    if not m:
        j = t.find(";", i)
        return None, i, (len(t) if j == -1 else j + 1), False
    depth, k = 0, m.start()
    for w in WORD.finditer(t, m.start()):
        if w.group(0) in ("begin", "fork"):
            depth += 1
        elif w.group(0) in ("end", "join"):
            depth -= 1
            if depth == 0:
                k = w.end()
                break
    else:
        k = len(t)
    return m.group(2), m.end(), k, True


def check(path, raw):
    probs = []
    t = strip(raw)

    def line(off):
        return raw.count("\n", 0, off) + 1

    def bad(off, item, msg):
        probs.append(f"{path}:{line(off)}: [{item}] {msg}")

    for m in re.finditer(r"\t", raw):
        bad(m.start(), "tab", "出现 tab（D1：缩进 4 空格）")
        break
    for m in re.finditer(r"[^\x00-\x7f]", raw):
        bad(m.start(), "非 ASCII", "出现非 ASCII 字符（D2：只许 ASCII，注释用英文）")
        break

    # 位复制的计数是表达式时要加括号：{(W+1){x}}，不写 {W+1{x}}（handshake-depth-contracts D5，内部#286）
    for m in REPL_BARE.finditer(t):
        bad(m.start(), "位复制计数", f"复制计数 {m.group(1).strip()} 是表达式，要加括号（#286）")

    mods = list(re.finditer(r"\bmodule\s+([A-Za-z_]\w*)", t))
    names = [m.group(1) for m in mods]
    base = os.path.basename(path)
    if len(mods) != 1:
        bad(mods[1].start() if len(mods) > 1 else 0, "一个文件一个模块",
            f"声明了 {len(mods)} 个模块 {names}（D5）")
    elif base != names[0].lower() + ".v":
        bad(mods[0].start(), "一个文件一个模块",
            f"模块 {names[0]} 应当在 {names[0].lower()}.v，不是 {base}（D5）")

    head = raw.split("\n")[:12]
    got = {}
    for ln in head:
        fm = re.match(r"//\s*(File|Module|Purpose|Spec|Language)\s*:\s*(.*?)\s*$", ln)
        if fm:
            got[fm.group(1)] = fm.group(2)
    if not head or not head[0].startswith("//===="):
        bad(0, "头注释", "文件要以 //==== 横幅头开始（D3）")
    for f in FIELDS:
        if not got.get(f):
            bad(0, "头注释", f"头注释缺 {f} 字段（D3）")
    if got.get("File") and got["File"] != base:
        bad(0, "头注释", f"File 写的是 {got['File']}，文件是 {base}")
    if got.get("Module") and names and got["Module"] != names[0]:
        bad(0, "头注释", f"Module 写的是 {got['Module']}，文件里的模块是 {names[0]}")
    spec_path = got.get("Spec", "").split(" ")[0]       # 路径后面可以跟括号里的章节号
    if spec_path and not os.path.isfile(spec_path):
        bad(0, "头注释", f"Spec 指向的 {spec_path} 不存在")

    for m in re.finditer(r"\bcase[xz]\b", t):
        bad(m.start(), "casex / casez", f"用了 {m.group(0)}（D10）")

    # 第 11–14 项：rtl-structure-authority「RTL 的书写约定」的四条 MUST（内部#101，rtl-style-four-rules）
    for m in re.finditer(r"\x60default_nettype\b", t):
        bad(m.start(), "default_nettype", "出现 \x60default_nettype（书写约定不许用）")
    for m in re.finditer(r"\b(wire|reg)\b([^;]*);", t):
        if re.search(r"(?<![=!<>])=(?!=)", m.group(2)):
            bad(m.start(), "定义带赋值", f"{m.group(1)} 的定义里带赋值：先定义，再用 assign 或时序块赋值")
    for m in re.finditer(r"\blocalparam\s+integer\b", t):
        bad(m.start(), "localparam integer", "用了 localparam integer（书写约定不许用）")
    for g in re.finditer(r"\bgenerate\b(.*?)\bendgenerate\b", t, re.S):
        for m in re.finditer(r"\blocalparam\b", g.group(1)):
            bad(g.start(1) + m.start(), "generate 内 localparam",
                "generate 块内定义了 localparam：依赖 genvar 的表达式内联到使用点（书写约定）")

    stack = []
    for w in re.finditer(r"\b(case[xz]?|endcase|default)\b", t):
        k = w.group(1)
        if k.startswith("case"):
            stack.append([w.start(), False])
        elif k == "endcase" and stack:
            st, has = stack.pop()
            if not has:
                bad(st, "case 缺 default", "case 没有 default 分支（D10）")
        elif k == "default" and stack:
            stack[-1][1] = True

    # always / function / task 的范围；always 的块名与 for 块名、时序块的 <= 目标
    proc = []
    for m in re.finditer(r"\b(function|task)\b", t):
        e = re.compile(r"\bend" + m.group(1) + r"\b").search(t, m.end())
        proc.append((m.start(), e.end() if e else len(t)))
    for m in re.finditer(r"\balways\b", t):
        i = m.end()
        sm = re.compile(r"\s*@\s*").match(t, i)
        if sm and t[sm.end():sm.end() + 1] == LP:
            j = match_paren(t, sm.end())
            sens = t[sm.end():j]
        elif sm and t[sm.end():sm.end() + 1] == "*":
            j, sens = sm.end() + 1, "*"
        else:
            j, sens = i, ""
        name, body_start, end, is_block = block_span(t, j)
        proc.append((m.start(), end))
        if not is_block or name is None:
            bad(m.start(), "always 块名", "always 块没有块名（D19：begin : BLK_<NAME>）")
        elif not name.startswith("BLK_"):
            bad(m.start(), "always 块名", f"always 块名 {name} 要以 BLK_ 开头（D19）")
        body = t[body_start:end]
        for f in re.finditer(r"\bfor\s*\x28", body):
            fname, _, _, fblk = block_span(body, match_paren(body, f.end() - 1))
            if not fname or not fname.startswith("BLK_FOR"):
                bad(body_start + f.start(), "always 块名",
                    f"always 内的 for 块名 {fname} 要以 BLK_FOR 开头（D19）")
        if "posedge" not in sens:
            continue
        # 块名（begin : NAME）抹成空白，免得往回找赋值目标时停在它的冒号上
        body = re.sub(r"\bbegin\s*:\s*[A-Za-z_]\w*", lambda b: " " * len(b.group(0)), body)
        for a in re.finditer(r"<=", body):
            pre = body[:a.start()]
            if pre.count(LP) > pre.count(RP):
                continue                          # 括号里的 <= 是比较
            k, depth = a.start() - 1, 0
            while k >= 0:
                c = body[k]
                if c in "]}":
                    depth += 1
                elif c in "[{":
                    depth -= 1
                elif depth == 0 and c in ";:" + RP:
                    break
                k -= 1
            lhs = body[k + 1:a.start()]
            lhs = re.sub(r"^\s*(begin|end|else)\b", "", re.sub(r"\b(begin|end|else)\b", " ", lhs)).strip()
            targets = lhs[1:-1].split(",") if lhs.startswith("{") else [lhs]
            for tg in targets:
                nm = re.match(r"\s*([A-Za-z_]\w*)", tg)
                if nm and not REG_OK.match(nm.group(1)):
                    bad(body_start + a.start(), "寄存器后缀",
                        f"时序块里 <= 的目标 {nm.group(1)} 要以 _r 或 _<n>ff 结尾（D6）")

    def in_proc(off):
        return any(s <= off < e for s, e in proc)

    # generate 里（过程块之外）的 if / else / for 块名
    for g in re.finditer(r"\bgenerate\b(.*?)\bendgenerate\b", t, re.S):
        gs = g.start(1)
        seg = g.group(1)
        for k in re.finditer(r"\b(if|for)\s*\x28|\belse\b(?!\s+if\b)", seg):
            off = gs + k.start()
            if in_proc(off):
                continue
            kind = k.group(1) or "else"
            if kind == "else" and assertion_else(seg, k.start()):
                continue
            after =match_paren(t, gs + k.end() - 1) if kind != "else" else gs + k.end()
            name, _, _, _ = block_span(t, after)
            want = "GEN_FOR" if kind == "for" else "GEN_"
            if not name or not name.startswith(want):
                bad(off, "generate 块名", f"generate 里的 {kind} 块名 {name} 要以 {want} 开头（D19）")

    # 例化：<大写模块名> [#(...)] <例化名> (...)；名单里的本地 CBB 副本另有写法（D4）
    if names:
        cur = names[0]
        for m in INST_RE.finditer(t):
            if in_proc(m.start()) or m.group(1) == cur:
                continue
            j = match_paren(t, m.end() - 1) if m.group(2) else m.end()
            im = re.compile(r"\s*([A-Za-z_]\w*)\s*\x28").match(t, j)
            if not im or (not m.group(2) and not re.search(r"[;\x29\n]\s*$", t[:m.start()])):
                continue
            inst = im.group(1)
            mod = m.group(1)
            if LOCAL_MODS.get(mod) == os.path.dirname(path):
                base, sfx = mod.rsplit("_", 1)
                prefix, sfx = "U_" + base.upper(), "_" + sfx.upper()
                if not ((inst == prefix or inst.startswith(prefix + "_"))
                        and re.fullmatch(r"[A-Z][A-Z0-9_]*", inst) and not inst.endswith(sfx)):
                    bad(m.start(), "例化名",
                        f"本地 CBB 例化名 {inst} 要写成 {prefix}[_<功能>]，全大写、不带 {sfx} 后缀")
                continue
            if not (inst.startswith(f"U_{cur}_") and inst.endswith(f"_{mod}")
                    and len(inst) > len(f"U_{cur}__{mod}")):
                bad(m.start(), "例化名",
                    f"例化名 {inst} 要写成 U_{cur}_<功能>_{m.group(1)}（D7）")
    return probs


files = sorted(_TG("*/rtl/*.v") + glob.glob("flow/templates/*.v"))
# 参数片段（rtl/inc/*.vh，内部#76）没有模块与头注释，只查前两项：tab 与非 ASCII
fragments = _TG("*/rtl/inc/*.vh")
legacy = []
if os.path.isfile(LEGACY):
    legacy = [ln.strip() for ln in open(LEGACY)
              if ln.strip() and not ln.lstrip().startswith("#")]
out = []
for entry in legacy:
    if not os.path.isfile(entry):
        out.append(f"{LEGACY}: 列出的 {entry} 不存在 —— 改名或删除后要从清单里移出（D15）")
    elif not check(entry, open(entry, encoding="utf-8", errors="replace").read()):
        out.append(f"{LEGACY}: {entry} 已合规 —— 从清单里移出（清单只减不增，D15）")
checked = [f for f in files if f not in legacy]
for f in checked:
    out += check(f, open(f, encoding="utf-8", errors="replace").read())
# 带参数的被测顶层要有参数合法性检查块（handshake-depth-contracts D6，内部#286）；子模块的参数由上层检查后传入，不查
sys.path.insert(0, ".")
try:
    from flow.paths import _top_index
    tops_idx = _top_index(".")
except Exception:      # noqa: BLE001 —— 设计根解析失败由「设计根可解析」一段报，这里不重复
    tops_idx = {}
CHK_BLOCK = "\x60ifdef CBB_PARAM_CHK_ON"
for top, (root, _cfg) in sorted(tops_idx.items()):
    for f in sorted(glob.glob(os.path.join(os.path.relpath(root), "rtl", "*.v"))):
        raw = open(f, encoding="utf-8", errors="replace").read()
        t = strip(raw)
        if not re.search(r"\bmodule\s+" + re.escape(top) + r"\b", t):
            continue
        if f in legacy:      # 列在豁免清单里的文件整份不查书写风格（D15）
            break
        if re.search(r"\bparameter\b", t) and CHK_BLOCK not in t:
            out.append(f"{f}: [参数检查块] 被测顶层 {top} 带参数，要有 {CHK_BLOCK} 检查块（#286）")
        break
for f in fragments:
    raw = open(f, encoding="utf-8", errors="replace").read()
    for item, pat, msg in (("tab", "\t", "出现 tab（D1）"),
                           ("非 ASCII", "[^\x00-\x7f]", "出现非 ASCII 字符（D2）")):
        m = re.search(pat, raw)
        if m:
            out.append(f"{f}:{raw.count(chr(10), 0, m.start()) + 1}: [{item}] {msg}")
for o in out:
    print(o, file=sys.stderr)
print(f"检查 {len(checked)} 个文件、豁免 {len([e for e in legacy if e in files])} 个"
      + (f"、参数片段 {len(fragments)} 个" if fragments else ""))
sys.exit(1 if out else 0)
