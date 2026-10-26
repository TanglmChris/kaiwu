# fast_check 的「RTL 命名约定」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_naming [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG  # 设计树遍历（内部#305）
import glob, re, sys

import yaml

KEYWORDS = {"wire", "reg", "logic", "signed", "unsigned", "integer", "var", "tri"}
DIRS = ("input", "output", "inout")
BANNED = {"valid": "vld", "ready": "rdy", "data": "dat", "din": "dat",
          "dout": "dat", "count": "cnt"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
PORT_OK = re.compile(r"[a-z][a-z0-9_]*$")
PARAM_OK = re.compile(r"[A-Z][A-Z0-9_]*$")
# 多时钟构件的时钟 / 复位口（D11，用户 2026-09-28 定）：与单时钟的 clk / rst_n 对称，
# 只放行**输入**、只放行小写域名 —— `rd_clk` 当输出、`wr_clock`、`WR_clk` 照样拦。
DOMAIN_CLK_OK = re.compile(r"[a-z][a-z0-9]*_(clk|rst_n)$")


def strip_comments(text):
    """去掉注释，换行保留（行号不变）。"""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            seg = text[i:n if j == -1 else j + 2]
            out.append("\n" * seg.count("\n"))
            i = n if j == -1 else j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def scan_decl(text, start):
    """从 start 起取一段声明，到顶层的 `;` / `)` 为止，或到下一个方向 / parameter
    关键字之前的顶层逗号为止。返回 (段落, 结束位置)。"""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return text[start:i], i
            depth -= 1
        elif c == ";" and depth == 0:
            return text[start:i], i
        elif c == "," and depth == 0:
            nxt = re.match(r",\s*(input|output|inout|parameter|localparam)\b", text[i:])
            if nxt:
                return text[start:i], i
        i += 1
    return text[start:], n


def split_top(seg):
    """按顶层逗号切。"""
    parts, depth, buf = [], 0, []
    for c in seg:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    parts.append("".join(buf))
    return parts


def drop_ranges(s):
    out, depth = [], 0
    for c in s:
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif depth == 0:
            out.append(c)
    return "".join(out)


def param_problem(name):
    if not PARAM_OK.match(name):
        return "参数名要全大写（[A-Z][A-Z0-9_]*）"
    if len(name) == 1:
        return "参数名不许是单个字母"
    if name == "WIDTH":
        return "不许叫 WIDTH：主数据位宽叫 DAT_W，其余位宽叫 <名>_W"
    if name.endswith("W") and not name.endswith("_W"):
        return "位宽参数要以 _W 结尾（例：DW → DAT_W、CW → C_W）"
    return None


def port_problem(direction, name):
    if name in ("clk", "rst_n"):
        return None
    if direction == "input" and DOMAIN_CLK_OK.match(name):
        return None
    if direction == "inout":
        return "不许用 inout"
    want = "i_" if direction == "input" else "o_"
    if not name.startswith(want):
        return f"{direction} 端口要以 {want} 开头"
    rest = name[2:]
    if not PORT_OK.match(rest):
        return "前缀之后要全小写（[a-z][a-z0-9_]*）"
    for tok in rest.split("_"):
        if tok in BANNED:
            return f"缩写要统一：{tok} → {BANNED[tok]}"
    return None


def ip_port_problem(direction, name):
    if direction == "inout":
        return "不许用 inout"
    if not PORT_OK.match(name):
        return "端口名要全小写（[a-z][a-z0-9_]*）"
    if name.startswith(("i_", "o_")):
        want = "i_" if direction == "input" else "o_"
        if not name.startswith(want):
            return f"{direction} 端口用 i_ / o_ 前缀时要与方向一致（{want}）"
    for tok in name.split("_"):
        if tok in BANNED:
            return f"缩写要统一：{tok} → {BANNED[tok]}"
    return None


def ip_param_problem(name):
    if not PARAM_OK.match(name):
        return "参数名要全大写（[A-Z][A-Z0-9_]*）"
    if len(name) == 1:
        return "参数名不许是单个字母"
    return None


def strip_subprograms(text):
    """抹掉 function / task 体，换行保留（行号不变）。"""
    return re.sub(r"\b(function|task)\b.*?\bend\1\b",
                  lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


bad = []
n_mod = n_param = n_port = n_ip = 0
ip_roots = set()
for pfile in _TG("*/params.yaml"):
    role = (yaml.safe_load(open(pfile)) or {}).get("role")
    if role is None:
        continue
    if role != "ip":
        bad.append((pfile, 0, "-", "role", role, "role 只许取 ip（不写即为非 IP）"))
        continue
    ip_roots.add(pfile.rsplit("/", 1)[0])


def root_of(path):
    return "/".join(path.split("/")[:2])


files = _TG("**/*.v", recursive=True)
for path in files:
    text = strip_subprograms(strip_comments(open(path).read()))
    is_ip = root_of(path) in ip_roots
    pcheck = ip_param_problem if is_ip else param_problem
    for mm in re.finditer(r"\bmodule\s+\\?([A-Za-z_][\w$]*)(.*?)\bendmodule\b", text, re.S):
        mod, body, base = mm.group(1), mm.group(2), mm.start(2)
        n_mod += 1
        n_ip += is_ip

        def line_of(off):
            return text.count("\n", 0, base + off) + 1

        for km in re.finditer(r"\b(parameter|localparam)\b", body):
            seg, _ = scan_decl(body, km.end())
            for piece in split_top(seg):
                lhs = drop_ranges(piece.split("=", 1)[0])
                ids = [t for t in IDENT.findall(lhs) if t not in KEYWORDS]
                if not ids:
                    continue
                n_param += 1
                why = pcheck(ids[-1])
                if why:
                    bad.append((path, line_of(km.start()), mod, "参数", ids[-1], why))
        for km in re.finditer(r"\b(input|output|inout)\b", body):
            seg, _ = scan_decl(body, km.end())
            for piece in split_top(drop_ranges(seg)):
                ids = [t for t in IDENT.findall(piece.split("=", 1)[0]) if t not in KEYWORDS]
                if not ids:
                    continue
                n_port += 1
                why = (ip_port_problem if is_ip else port_problem)(km.group(1), ids[-1])
                if why:
                    bad.append((path, line_of(km.start()), mod, "端口", ids[-1], why))

for pfile in _TG("*/params.yaml"):
    cfg = yaml.safe_load(open(pfile)) or {}
    pcheck = ip_param_problem if pfile.rsplit("/", 1)[0] in ip_roots else param_problem
    for top, tcfg in (cfg.get("tops") or {}).items():
        for key in ((tcfg or {}).get("params") or {}):
            n_param += 1
            why = pcheck(str(key))
            if why:
                bad.append((pfile, 0, top, "params.yaml 参数键", key, why))

for path, line, mod, kind, name, why in bad:
    where = f"{path}:{line}" if line else path
    print(f"{where}: 模块 {mod} 的{kind} {name}：{why}", file=sys.stderr)
if bad:
    print(f"  共 {len(bad)} 处不合命名约定（rtl-structure-authority 的"
          "「模块接口与参数必须遵守统一命名约定」，映射表见 "
          "openspec/changes/archive/*unify-rtl-naming*/design.md 的 D2）。", file=sys.stderr)
print(f"{n_mod} 个模块、{n_param} 个参数、{n_port} 个端口"
      + (f"；按 IP 级约定 {n_ip} 个模块" if n_ip else ""))
sys.exit(1 if bad else 0)
