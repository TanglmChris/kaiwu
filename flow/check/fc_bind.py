# fast_check 的「SVA bind 连接名」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_bind [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG, DESIGN_TREES as _TREES  # 设计树遍历（内部#305）
import glob, os, re, subprocess, sys


def blank_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)


def balanced(text, i):
    """text[i] 是 '('：返回与它配对的 ')' 之后的位置。"""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    raise ValueError("括号不配对")


LITERAL = re.compile(r"\d*'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|\b\d[\d_]*\b")
BQ = chr(96)   # 反引号：这段 Python 在 bash 的 $(...) 里，字面反引号会被 bash 当命令替换
IDENT = re.compile(r"(?<![\w$.'" + BQ + r"])([A-Za-z_]\w*)(?:\s*\.\s*([A-Za-z_]\w*))?")
KEYWORDS = {"posedge", "negedge", "or", "and", "not", "if", "else", "signed", "unsigned"}


def idents(expr):
    """[(名字, 点号后的名字或 None)]。预处理行（ifdef 等）整行跳过。"""
    expr = "\n".join(l for l in expr.splitlines() if not l.lstrip().startswith(BQ))
    expr = LITERAL.sub(" ", expr)
    return [(m.group(1), m.group(2)) for m in IDENT.finditer(expr) if m.group(1) not in KEYWORDS]


rtl_files = sorted(set(_TG("**/*.v", recursive=True) + _TG("**/*.sv", recursive=True)))
REF = os.environ.get("SVA_BIND_DESIGN_REF", "").strip()
if REF:
    try:
        listed = subprocess.run(["git", "ls-tree", "-r", "--name-only", REF, "--", *_TREES],
                                capture_output=True, text=True, check=True).stdout.split()
    except subprocess.CalledProcessError as e:
        print(f"SVA_BIND_DESIGN_REF={REF} 不是这个仓库里的提交：{e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    design_files = sorted(p for p in listed if p.endswith((".v", ".sv")) and "/tb/" not in p)


def read_design(path):
    if REF:
        return subprocess.run(["git", "show", f"{REF}:{path}"], capture_output=True, text=True,
                              errors="replace", check=True).stdout
    return open(path, errors="replace").read()


bodies = {}
for path in (design_files + [p for p in rtl_files if "/tb/" in p]) if REF else rtl_files:
    code = blank_comments(read_design(path) if (REF and "/tb/" not in path) else open(path, errors="replace").read())
    for m in re.finditer(r"^\s*module\s+(\w+)\b(.*?)^\s*endmodule\b", code, re.M | re.S):
        bodies.setdefault(m.group(1), []).append((path, m.group(0)))

sva_files = [p for p in rtl_files if "/tb/" in p]
bad, n_bind = 0, 0
for path in sva_files:
    code = blank_comments(open(path, errors="replace").read())
    for m in re.finditer(r"^\s*bind\s+(\w+)\s+(\w+)\s*", code, re.M):
        n_bind += 1
        target, sva = m.group(1), m.group(2)
        lineno = code.count("\n", 0, m.start()) + 1
        where = f"{path}:{lineno}: bind {target} {sva}"
        i, names = m.end(), []
        try:
            if code.startswith("#", i):
                j = code.index("(", i)
                k = balanced(code, j)
                names += idents(re.sub(r"\.\w+\s*\(", "(", code[j:k]))
                i = k
            inst = re.match(r"\s*\w+\s*", code[i:])
            j = i + inst.end()
            k = balanced(code, j)
            conns = code[j:k]
        except ValueError as e:
            bad += 1
            print(f"{where}：读不懂这条 bind（{e}）", file=sys.stderr)
            continue
        if re.search(r"\.\*", conns):
            sva_body = [b for _, b in bodies.get(sva, [])]
            names += [(n, None) for n in
                      re.findall(r"\b(?:input|inout)\b[^;,)]*?(\w+)\s*[,;)]", sva_body[0] if sva_body else "")]
        names += idents(re.sub(r"\.\w+\s*\(", "(", conns.replace(".*", "")))
        if target not in bodies:
            bad += 1
            print(f"{where}：各设计树的 RTL 里找不到模块 {target}", file=sys.stderr)
            continue
        def words(mod):
            return set(re.findall(r"\w+", " ".join(b for _, b in bodies[mod])))
        here = words(target)
        for n, sub in sorted(set(names)):
            if n in here:
                continue
            if sub is not None and n in bodies:     # 上行引用 <模块>.<名字>：到那个模块里查后半段
                if sub not in words(n):
                    bad += 1
                    print(f"{where}：上行引用 {n}.{sub} 的 {sub} 在 {n} 里不存在", file=sys.stderr)
                continue
            bad += 1
            print(f"{where}：连接里的 {n} 在 {target} 里不存在（Verilator 会把它当隐式线接成悬空，断言静默失效）",
                  file=sys.stderr)
if bad:
    print("  改了 RTL 的信号名就同步改 SVA 的 bind；改完用验证回归的 SVA 模式跑一次（inner / full 回归不编 SVA，#194）",
          file=sys.stderr)
print(f"{n_bind} 条 bind、{len(sva_files)} 个 tb 文件" + (f"，被绑 RTL 按 {REF}" if REF else ""))
sys.exit(1 if bad else 0)
