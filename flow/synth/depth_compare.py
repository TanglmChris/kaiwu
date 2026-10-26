"""两次 `make depth BUDGET=N` 的超预算终点按**终点集合**比（内部#225）：哪些终点消失、哪些新出现、共有终点的组合单元数变了多少、
最深的起止点有没有换。按组名比会误判（一组「消失」可能只是终点换了组），所以一律按终点核。

    .venv/bin/python3 flow/synth/depth_compare.py <A> <B>

A、B 是 over_budget.tsv / over_budget.tsv.gz，或含它的 depth 产物目录（runs/depth/<模块>-<摘要>/）。
只看超预算的终点：两次的 BUDGET 要相同，否则集合不可比。不写记录，退出 0（报告工具）。

同一终点的路径按模块并排比（内部#340）：`--composition` 列共有终点里模块构成变了的（总数不变、只在模块间挪了
单元的也列），`--endpoint <终点>` 只列指定的；`--levels N` 取实例层次的前 N 级当模块（默认 2）。数据取
over_budget.tsv 第 5 列记下的路径引脚，不重跑 STA。
"""
import argparse
import gzip
import sys
from pathlib import Path


def _open(path):
    path = Path(path)
    if path.is_dir():
        for name in ("over_budget.tsv.gz", "over_budget.tsv"):
            if (path / name).exists():
                path = path / name
                break
        else:
            raise SystemExit(f"{path} 下没有 over_budget.tsv(.gz)：depth 要带 BUDGET 跑")
    return gzip.open(path, "rt") if path.suffix == ".gz" else open(path)


def load(path):
    """{终点: {comb_cells, stages, startpoint, endpoint}}，每个终点取组合单元数最大的那条。"""
    best = {}
    with _open(path) as f:
        for ln in f:
            if not ln.strip():
                continue
            cols = ln.rstrip("\n").split("\t")
            c, n, start, end = cols[:4]
            c, n = int(c), int(n)
            if end not in best or (c, n) > (best[end]["comb_cells"], best[end]["stages"]):
                best[end] = {"comb_cells": c, "stages": n, "startpoint": start, "endpoint": end,
                             "pins": cols[4].split(" ") if len(cols) > 4 and cols[4] else None}
    return best


def composition(pins, levels=2):
    """路径引脚 → {模块: 组合单元个数}。同一实例连续出现两个及以上引脚（输入 + 输出）才是组合单元；
    起点寄存器只有 Q / QN、终点寄存器只有 D、端口没有 `/`，都只有一个引脚，不算 —— 与 depth.py 的
    `_comb_cells` 逐行相等。模块 = 去掉单元名后的实例层次的前 levels 级，顶层自己的单元记为「（顶层）」。"""
    runs = []
    for p in pins:
        inst = p.rsplit("/", 1)[0] if "/" in p else None
        if runs and inst is not None and runs[-1][0] == inst:
            runs[-1][1] += 1
        else:
            runs.append([inst, 1])
    out = {}
    for inst, k in runs:
        if inst is None or k < 2:
            continue
        mod = "/".join(inst.split("/")[:-1][:levels]) or "（顶层）"
        out[mod] = out.get(mod, 0) + 1
    return out


def _need_pins(d, path):
    if any(p["pins"] is None for p in d.values()):
        raise SystemExit(f"{path} 没有路径引脚那一列（第 5 列）：这是旧版 depth 的产物，要重跑 depth 才能按模块比")


def _print_composition(e, a, b, levels):
    ca, cb = composition(a["pins"], levels), composition(b["pins"], levels)
    print(f"## 终点 {e}")
    print(f"   起点 A {a['startpoint']}；B {b['startpoint']}")
    rows = sorted(set(ca) | set(cb), key=lambda m: (-abs(cb.get(m, 0) - ca.get(m, 0)), m))
    w = max(len(m) for m in rows + ["合计"])
    for m in rows:
        x, y = ca.get(m, 0), cb.get(m, 0)
        print(f"{m:<{w}}  {x:>3}  {y:>3}  {y - x:+d}".replace("  +0", "   0"))
    print(f"{'合计':<{w}}  {a['comb_cells']:>3}  {b['comb_cells']:>3}  {b['comb_cells'] - a['comb_cells']:+d}"
          .replace("  +0", "   0"))


def _delta(pa, pb, levels):
    ca, cb = composition(pa["pins"], levels), composition(pb["pins"], levels)
    return {m: cb.get(m, 0) - ca.get(m, 0) for m in set(ca) | set(cb)}


def compare(a, b):
    worst = lambda d: max(d.values(), key=lambda p: (p["comb_cells"], p["stages"])) if d else None  # noqa: E731
    common = sorted(set(a) & set(b))
    return {
        "gone": sorted(set(a) - set(b)),
        "new": sorted(set(b) - set(a)),
        "changed": [(e, a[e]["comb_cells"], b[e]["comb_cells"]) for e in common
                    if a[e]["comb_cells"] != b[e]["comb_cells"]],
        "common": len(common),
        "worst_a": worst(a),
        "worst_b": worst(b),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--show", type=int, default=20, help="每类最多列几条")
    ap.add_argument("--composition", action="store_true", help="共有终点里模块构成变了的，按模块并排列（#340）")
    ap.add_argument("--endpoint", action="append", default=[], help="只按模块列这个终点（可重复）")
    ap.add_argument("--levels", type=int, default=2, help="模块取实例层次的前几级（默认 2）")
    x = ap.parse_args(argv)
    a, b = load(x.a), load(x.b)
    if x.composition or x.endpoint:
        _need_pins(a, x.a)
        _need_pins(b, x.b)
        if x.endpoint:
            missing = [e for e in x.endpoint if e not in a or e not in b]
            if missing:
                raise SystemExit(f"这些终点不是 A、B 共有的超预算终点：{'、'.join(missing)}")
            ends = x.endpoint
        else:
            moved = lambda e: composition(a[e]["pins"], x.levels) != composition(b[e]["pins"], x.levels)  # noqa: E731
            score = lambda e: sum(abs(v) for v in _delta(a[e], b[e], x.levels).values())  # noqa: E731
            ends = sorted((e for e in set(a) & set(b) if moved(e)), key=lambda e: (-score(e), e))
            print(f"# 共有终点里路径的模块构成变了的：{len(ends)} 个，列前 {min(len(ends), x.show)} 个"
                  f"（levels={x.levels}，列 A、B、差值）")
            ends = ends[:x.show]
        for e in ends:
            _print_composition(e, a[e], b[e], x.levels)
        return 0
    r = compare(a, b)
    print(f"# 超预算终点：A {len(a)} 个，B {len(b)} 个；共有 {r['common']}，消失 {len(r['gone'])}，新出现 {len(r['new'])}，"
          f"共有里组合单元数变了 {len(r['changed'])}")
    for title, items in (("消失", [(e, a[e]) for e in r["gone"]]), ("新出现", [(e, b[e]) for e in r["new"]])):
        for e, p in sorted(items, key=lambda t: -t[1]["comb_cells"])[:x.show]:
            print(f"  {title}  {p['comb_cells']:>3}  {p['startpoint']} → {e}")
    for e, ca, cb in sorted(r["changed"], key=lambda t: t[2] - t[1])[:x.show]:
        print(f"  变化  {ca:>3} → {cb:<3} {e}")
    wa, wb = r["worst_a"], r["worst_b"]
    fmt = lambda p: f"{p['comb_cells']}（{p['startpoint']} → {p['endpoint']}）" if p else "无"  # noqa: E731
    moved = bool(wa and wb and (wa["startpoint"], wa["endpoint"]) != (wb["startpoint"], wb["endpoint"]))
    print(f"# 最深：A {fmt(wa)}；B {fmt(wb)}" + ("；最深终点变了" if moved else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
