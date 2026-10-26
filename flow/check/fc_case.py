# fast_check 的「RTL 模块名大小写」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_case [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG, local_cbb_copies as _LOCAL  # 设计树遍历（内部#305）
import glob, os, re, sys

DECL = re.compile(r"^\s*module\s+\\?([A-Za-z_][\w$]*)")
def load_local(report):
    """本地 CBB 副本名单（rtl-structure-authority「模块名必须全大写」的例外）：{路径: 应有的模块名}。
    全仓的 flow/lint/local_cbb.txt 与各设计根的 local_cbb.txt 取并集（flow/paths.py::local_cbb_copies，内部#305）。"""
    found, problems = _LOCAL()
    if report:
        for msg in problems:
            print(msg, file=sys.stderr)
    return found, len(problems)


def strip_comments(lines):
    """逐行去掉注释，行数与行号保持不变。"""
    out, in_block = [], False
    for line in lines:
        buf, i, n = [], 0, len(line)
        while i < n:
            if in_block:
                end = line.find("*/", i)
                if end == -1:
                    i = n
                else:
                    in_block = False
                    i = end + 2
            elif line.startswith("//", i):
                i = n
            elif line.startswith("/*", i):
                in_block = True
                i += 2
            else:
                buf.append(line[i])
                i += 1
        out.append("".join(buf))
    return out


files = _TG("**/*.v", recursive=True)
local, bad = load_local(report=True)
seen = 0
for path in files:
    raw = open(path).read().splitlines()
    for lineno, line in enumerate(strip_comments(raw), 1):
        m = DECL.match(line)
        if not m:
            continue
        seen += 1
        name = m.group(1)
        # 名单里的本地 CBB 副本：模块名等于文件名去掉 .v（小写，内部#246）
        if path in local:
            if name == local[path]:
                continue
            bad += 1
            print(f"{path}:{lineno}: 本地 CBB 模块名必须是 {local[path]}，实际 {name}", file=sys.stderr)
            continue
        if name == name.upper():
            continue
        bad += 1
        print(f"{path}:{lineno}: 模块名不是全大写：{name} —— 应当改成 {name.upper()}",
              file=sys.stderr)
        print(f"    {raw[lineno - 1].strip()}", file=sys.stderr)
if bad:
    print("  模块名全大写是 repo-layout 的约定（2026-09-21，本仓 #46 的 2.1）；",
          file=sys.stderr)
    print("  小写名不会让任何东西失败，所以只有这里拦得住。改名时记得同步"
          "params.yaml 的 tops:、TB 里的实例化与四类文档的文件名。", file=sys.stderr)
print(seen)
sys.exit(1 if bad else 0)
