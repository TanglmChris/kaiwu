# fast_check 的「参数组合展开」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_combos [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
import sys, yaml
from flow.param_exclude import ExcludeError, fast_check_combos
spec = yaml.safe_load(open(sys.argv[1])) or {}
# 一个设计根可以挂多个被测顶层，每个顶层各带一份 sim/sta/params
# （openspec/specs/repo-layout/spec.md 的「设计根可以声明多个被测顶层」）。
# 这里**不接受**没有 tops: 的旧形态，也不回退到目录名 —— 回退会让一份漏写
# tops: 的 params.yaml 静默按目录名跑，而那正是最该报错的时刻。
tops = spec.get("tops")
if not isinstance(tops, dict) or not tops:
    sys.exit("没有 `tops:` 段（一个设计根 MUST 显式声明它的被测顶层，"
             "只有一个顶层时同样要写）")
for top, cfg in tops.items():
    params = (cfg or {}).get("params") or {}
    names = list(params)
    if not names:
        sys.exit(f"{top}: params 段是空的")
    for n in names:
        decl = params[n] or {}
        if "values" not in decl:
            sys.exit(f"{top}.{n}: 没有 values 键")
        if not decl["values"]:
            sys.exit(f"{top}.{n}: values 是空列表")
    # 「叉乘 − exclude」∪ sweep_points（内部#138、内部#214）：exclude 声明的非法组合不展开，cross: false 的参数叉乘里
    # 只取 values[0]、其余取值经 sweep_points 覆盖；展开与校验在 flow/param_exclude.py，写错当场失败
    try:
        combos, n_excl, n_pts = fast_check_combos(top, cfg or {})
    except ExcludeError as e:
        sys.exit(str(e))
    if n_excl or n_pts:
        print(f"#EXCLUDE\t{top}\t{n_excl}\t{n_pts}")
    for combo in combos:
        # 一行一个组合，字段间用 tab 分隔；**第一个字段是顶层名**。
        # 名字就是 RTL 参数名，无映射层。
        print("\t".join([top] + [f"{n}={v}" for n, v in combo.items()]))
