# fast_check 的「可综合 RTL 里没有仿真专用构造」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_escape [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG  # 设计树遍历（内部#305）
import glob, re, sys
PATTERNS = [
    (r"\$f(open|write|close|scanf|read|display)\b", "$f* 文件/输出系统任务"),
    (r"\$system\b", "$system"),
    (r"\$u?random\b", "$random / $urandom"),
    (r"\$readmem[bh]\b", "$readmem*"),
    (r"\$dump(file|vars|ports)\b", "$dump*"),
    (r'(im|ex)port\s+"DPI', 'DPI 导入/导出'),
    (r"\binitial\b", "initial 块"),
    (r"(?<![\w$])#\s*\d", "#<数字> 延时"),
]
def blank_noncode(text):
    """同长度的副本，注释（`//` 与 `/* */`）和字符串字面量里的字符换成空格。"""
    out = list(text)
    n, i = len(text), 0
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            end = n if end == -1 else end
            for k in range(i, end):
                out[k] = " "
            i = end
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for k in range(i, end):
                out[k] = "\n" if text[k] == "\n" else " "
            i = end
        elif ch == '"':
            out[i] = " "
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    out[i] = " "
                    i += 1
                out[i] = "\n" if text[i] == "\n" else " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


files = _TG("*/rtl/*.v")
bad = 0
for path in files:
    raw = open(path).read()
    code = blank_noncode(raw)
    raw_lines = raw.splitlines()
    for lineno, line in enumerate(code.splitlines(), 1):
        for pat, label in PATTERNS:
            if re.search(pat, line):
                bad += 1
                print(f"{path}:{lineno}: 可综合 RTL 里有仿真专用构造：{label}",
                      file=sys.stderr)
                # 原文那一行，不是挖空后的副本 —— 挖空只为定位
                print(f"    {raw_lines[lineno - 1].strip()}", file=sys.stderr)
if bad:
    print("  仿真看到的电路与综合出的电路会当场分家，而两边都不报错。",
          file=sys.stderr)
    print("  这类构造属于 tb/，不属于 rtl/。", file=sys.stderr)
print(len(files))
sys.exit(1 if bad else 0)
