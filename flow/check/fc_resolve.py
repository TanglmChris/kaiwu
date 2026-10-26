# fast_check 的「设计根可解析」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_resolve [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
import sys
from pathlib import Path

sys.path.insert(0, ".")
from flow.paths import DESIGN_TREES, _spec_only, _top_index

try:
    _top_index(Path("."))
except Exception as e:
    print(f"{type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
roots = [p for t in DESIGN_TREES if Path(t).is_dir() for p in sorted(Path(t).iterdir()) if p.is_dir()]
print(f"{len(roots)} 个设计根，其中 {sum(1 for p in roots if _spec_only(p))} 个规格先行")
