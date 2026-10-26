# fast_check 的「RTL 结构枚举」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_enum [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG  # 设计树遍历（内部#305）
import glob, re, sys

import yaml

INT_LIT = re.compile(r"(\d+|\d*\s*'[sS]?[dDhHbBoO]\s*[0-9a-fA-F_]+)$")
DECL = re.compile(r"\b(?:parameter|localparam)\b(?:\s+(?:integer|signed|\[[^\]]*\]))*\s+"
                  r"((?:[A-Z][A-Z0-9_]*_)?SCHEME)\s*=\s*([^,;)\n]+)")
LABEL_OK = re.compile(r"[A-Z][A-Z0-9_]*$")


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


bad = []
n_rtl = n_yaml = 0
for path in _TG("**/*.v", recursive=True):
    text = strip_comments(open(path).read())
    for mm in re.finditer(r"\bmodule\s+([A-Za-z_][\w$]*)(.*?)\bendmodule\b", text, re.S):
        for dm in DECL.finditer(mm.group(2)):
            n_rtl += 1
            val = dm.group(2).strip()
            if not INT_LIT.match(val):
                line = text.count("\n", 0, mm.start(2) + dm.start()) + 1
                bad.append(f"{path}:{line}: 模块 {mm.group(1)} 的 {dm.group(1)} = {val}："
                           "结构枚举要取整数（名字写进 params.yaml 的 labels）")

for pfile in _TG("*/params.yaml"):
    cfg = yaml.safe_load(open(pfile)) or {}
    for top, tcfg in (cfg.get("tops") or {}).items():
        for name, spec in ((tcfg or {}).get("params") or {}).items():
            if not re.fullmatch(r"(?:[A-Z][A-Z0-9_]*_)?SCHEME", str(name)):
                continue
            n_yaml += 1
            spec = spec or {}
            values, labels = spec.get("values") or [], spec.get("labels")
            where = f"{pfile}: 设计 {top} 的 {name}"
            if labels is None:
                bad.append(f"{where}：缺 labels（每个编号一个大写名字）")
                continue
            if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values):
                bad.append(f"{where}：取值要是非负整数，现在是 {values}")
                continue
            keys = {int(k) if str(k).isdigit() else k for k in labels}
            missing = sorted(set(values) - keys)
            extra = sorted(keys - set(values), key=str)
            if missing:
                bad.append(f"{where}：缺名字的编号 {missing}")
            if extra:
                bad.append(f"{where}：多出的编号 {extra}")
            seen = {}
            for k, v in labels.items():
                v = str(v)
                if not LABEL_OK.match(v):
                    bad.append(f"{where}：名字要大写 {v}（编号 {k}）")
                if v in seen:
                    bad.append(f"{where}：名字重复 {v}（编号 {seen[v]} 与 {k}）")
                seen.setdefault(v, k)

for b in bad:
    print(b, file=sys.stderr)
print(f"{n_rtl} 处 RTL 声明、{n_yaml} 个 params.yaml 声明")
sys.exit(1 if bad else 0)
