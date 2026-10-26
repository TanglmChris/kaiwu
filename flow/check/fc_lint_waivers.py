# fast_check 的「lint 豁免没有过时」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_lint_waivers [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG  # 设计树遍历（内部#305）
import fnmatch, glob, re, sys
rtl = _TG("*/rtl/*")
text = {}
bad = []
for vlt in sys.argv[1:]:
    for no, line in enumerate(open(vlt, encoding="utf-8"), 1):
        if not line.startswith("lint_off"):
            continue
        fm = re.search(r'-file\s+"([^"]+)"', line)
        if not fm:
            continue
        files = [f for f in rtl if fnmatch.fnmatch(f, fm.group(1))]
        if not files:
            bad.append(f"{vlt}:{no}：-file \"{fm.group(1)}\" 在各设计树的 */rtl 下匹配不到文件")
            continue
        mm = re.search(r'-match\s+"([^"]+)"', line)
        ident = re.search(r"'([A-Za-z_][A-Za-z0-9_$]*)'", mm.group(1)) if mm else None
        if not ident:
            continue
        name = ident.group(1)
        pat = re.compile(r"(?<![A-Za-z0-9_$])" + re.escape(name) + r"(?![A-Za-z0-9_$])")
        if not any(pat.search(text.setdefault(f, open(f, encoding="utf-8", errors="replace").read()))
                   for f in files):
            bad.append(f"{vlt}:{no}：{name} 在 {', '.join(files)} 里一处都没有")
for b in bad:
    print(b)
sys.exit(1 if bad else 0)
