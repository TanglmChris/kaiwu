# fast_check 的「同名源文件逐字节相同」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_dup [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG  # 设计树遍历（内部#305）
import collections, glob, hashlib, os, sys
seen = collections.defaultdict(list)
for pat in ("*/rtl/*.v", "*/tb/*.py", "*/tb/*.sv"):
    for f in _TG(pat):
        seen[os.path.basename(f)].append(f)
bad = 0
checked = 0
for name, paths in sorted(seen.items()):
    if len(paths) < 2:
        continue
    checked += 1
    digests = {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in paths}
    if len(set(digests.values())) > 1:
        bad += 1
        print(f"同名源文件内容不同：{name}", file=sys.stderr)
        for p, d in sorted(digests.items()):
            print(f"    {d[:12]}  {p}", file=sys.stderr)
        print("  两个设计根因此测的不是同一个东西，而记录里看不出来。"
              "要么让它们逐字节相同，要么把它搬进构件树。", file=sys.stderr)
print(checked)
sys.exit(1 if bad else 0)
