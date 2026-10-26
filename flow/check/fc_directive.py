# fast_check 的「可综合 RTL 里没有综合指令属性」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_directive [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG  # 设计树遍历（内部#305）
import glob, re, sys

# 名单在这里。加名字的判据见上面的注释。
DIRECTIVES = ("keep_hierarchy", "dont_touch", "keep")
ATTR = re.compile(r"\(\*([^*]|\*(?!\)))*\*\)")


def blank_comments(text):
    """同长度的副本，注释里的字符换成空格（行号与列号保持不变）。"""
    out = list(text)
    n, i, in_block = len(text), 0, False
    while i < n:
        if in_block:
            if text.startswith("*/", i):
                out[i] = out[i + 1] = " "
                i += 2
                in_block = False
            else:
                if text[i] != "\n":
                    out[i] = " "
                i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif text.startswith("/*", i):
            out[i] = out[i + 1] = " "
            i += 2
            in_block = True
        else:
            i += 1
    return "".join(out)


files = _TG("**/*.v", recursive=True)
bad = 0
for path in files:
    raw = open(path).read()
    code = blank_comments(raw)
    raw_lines = raw.splitlines()
    for lineno, line in enumerate(code.splitlines(), 1):
        for m in ATTR.finditer(line):
            for d in DIRECTIVES:
                if re.search(rf"\b{d}\b", m.group(0)):
                    bad += 1
                    print(f"{path}:{lineno}: 可综合 RTL 里有综合指令属性：{d}",
                          file=sys.stderr)
                    print(f"    {raw_lines[lineno - 1].strip()}", file=sys.stderr)
if bad:
    print("  这类意图由该顶层的 params.yaml 声明、由 flow/synth/synth.py 施加",
          file=sys.stderr)
    print("  （`tops:<顶层>:synth:keep_hierarchy:`，本仓 #46 的 2.2）。"
          "留在 RTL 里等于同一个意图有两个来源。", file=sys.stderr)
print(len(files))
sys.exit(1 if bad else 0)
