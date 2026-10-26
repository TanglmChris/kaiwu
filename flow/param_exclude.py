"""params.yaml 的 `exclude`：声明为非法的参数组合不展开（内部#138，param-exclude）。

    tops:
      CBB_FOO:
        exclude:
          - {MODE: 1, WIDTH: 64}   # 组合与某一项的全部键值相同即排除

fast_check 的 elaborate / lint 与 `scripts/sweep.py` 都调这里，不各写一份（D3）。
本模块只决定**跑哪些组合**，不决定组合怎么测，所以不在 METRIC_MODULES 里、不进指纹。
显式给全参数的单次实验（`make exp`）不经过这里。

内部#214（sweep-points）另有两个键，展开也只在这里：

    tops:
      CBB_FOO:
        sweep_points:                      # 声明了它，sweep 只跑这张表
          - {name: pt_a1, DAT_W: 256, ...全部声明的参数...}
        params:
          DEPTH: {values: [2, 16], cross: false}   # 叉乘里只取 values[0]

- fast_check_combos：「叉乘 − exclude」∪ 点表（elaborate / lint 的覆盖）；
- sweep_combos：有点表就是点表，否则「叉乘（尊重 sweep: false）− exclude」；
- declared_combos：叉乘 ∪ 点表，不减 exclude（`flow/synth/synth.py` 探读入集合用，口径同以前）。
"""
import itertools


class ExcludeError(ValueError):
    pass


def _check(top, declared, exclude):
    """写错的排除项逐条点名（D2）；值按 YAML 原样比较，与 values 的写法一致。"""
    if not isinstance(exclude, list):
        raise ExcludeError(f"{top}: exclude 要写成列表，每项是一组参数取值")
    bad = []
    for i, entry in enumerate(exclude):
        if not isinstance(entry, dict) or not entry:
            bad.append(f"{top}: exclude[{i}] 是空的或不是映射，每项要写成 {{参数: 取值, ...}}")
            continue
        for name, value in entry.items():
            if name not in declared:
                bad.append(f"{top}: exclude[{i}] 的 {name} 不是声明过的参数（{', '.join(declared)}）")
            elif value not in ((declared[name] or {}).get("values") or []):
                bad.append(f"{top}: exclude[{i}] 的 {name}={value!r} 不在它的 values "
                           f"{declared[name]['values']} 里（values 收窄后这一项已过期？）")
    if bad:
        raise ExcludeError("\n".join(bad))


def matches(params, entry):
    return all(k in params and params[k] == v for k, v in entry.items())


def apply(top, declared, exclude, combos):
    """返回 (保留的组合, 排除的个数)；exclude 为空时原样返回。写错时抛 ExcludeError。"""
    if not exclude:
        return list(combos), 0
    _check(top, declared, exclude)
    combos = list(combos)
    kept = [c for c in combos if not any(matches(c, e) for e in exclude)]
    if not kept:
        raise ExcludeError(f"{top}: exclude 排除了全部 {len(combos)} 个组合")
    return kept, len(combos) - len(kept)


def load_excludes(design):
    from flow.paths import load_design_config
    return load_design_config(design).get("exclude")


def _points(top, declared, cfg):
    """校验点表与 cross: false，返回点表（去掉 name 的参数字典，按声明顺序）。写错的逐条点名。"""
    points = cfg.get("sweep_points")
    if points is None:
        points = []
    elif not isinstance(points, list) or not points:
        raise ExcludeError(f"{top}: sweep_points 要写成非空列表，每项是 {{name: ..., <全部参数>: 取值}}")
    exclude = cfg.get("exclude") or []
    bad, out, names, seen = [], [], set(), {}
    for i, pt in enumerate(points):
        tag = f"{top}: sweep_points[{i}]"
        if not isinstance(pt, dict):
            bad.append(f"{tag} 不是映射")
            continue
        name = pt.get("name")
        if not isinstance(name, str) or not name:
            bad.append(f"{tag} 没有 name（每个点要有名字，同一顶层内唯一）")
        elif name in names:
            bad.append(f"{tag} 的 name {name} 重复")
        else:
            names.add(name)
            tag = f"{top}: sweep_points[{i}]（{name}）"
        given = {k: v for k, v in pt.items() if k != "name"}
        missing = [n for n in declared if n not in given]
        extra = [n for n in given if n not in declared]
        if missing:
            bad.append(f"{tag} 缺参数 {', '.join(missing)}（点要给全全部声明的参数，含 sweep: false 的）")
        if extra:
            bad.append(f"{tag} 的 {', '.join(extra)} 不是声明过的参数")
        for n, v in given.items():
            if n in declared and v not in ((declared[n] or {}).get("values") or []):
                bad.append(f"{tag} 的 {n}={v!r} 不在它的 values {declared[n]['values']} 里")
        for j, e in enumerate(exclude if isinstance(exclude, list) else []):
            if isinstance(e, dict) and e and matches(given, e):
                bad.append(f"{tag} 命中 exclude[{j}] {e}（点表里只能是合法组合）")
        combo = {n: given[n] for n in declared if n in given}
        key = tuple(sorted((k, repr(v)) for k, v in combo.items()))
        if not missing and not extra and key in seen:
            bad.append(f"{tag} 与 {seen[key]} 的参数完全相同")
        seen.setdefault(key, name)
        out.append(combo)
    for n, d in declared.items():
        if (d or {}).get("cross", True) is False:
            for v in (d.get("values") or [])[1:]:
                if not any(c.get(n) == v for c in out):
                    bad.append(f"{top}: {n} 声明了 cross: false，它的取值 {v!r} 不在任何 sweep_points 里"
                               "（叉乘只取 values[0]，这个取值永远 elaborate 不到）")
    if bad:
        raise ExcludeError("\n".join(bad))
    return out


def _cross(declared, respect_sweep):
    """叉乘：cross: false 的参数只取 values[0]；respect_sweep 时 sweep: false 的也只取 values[0]。键按声明顺序。"""
    def axis(d):
        d = d or {}
        if d.get("cross", True) is False or (respect_sweep and d.get("sweep", True) is False):
            return d["values"][:1]
        return d["values"]
    names = list(declared)
    return [dict(zip(names, c)) for c in itertools.product(*(axis(declared[n]) for n in names))]


def _union(a, b):
    out = list(a)
    for c in b:
        if c not in out:
            out.append(c)
    return out


def fast_check_combos(top, cfg):
    """返回 (组合, exclude 排除的个数, 点数)：「叉乘 − exclude」∪ 点表。"""
    declared = cfg.get("params") or {}
    pts = _points(top, declared, cfg)
    kept, n_excl = apply(top, declared, cfg.get("exclude"), _cross(declared, False))
    return _union(kept, pts), n_excl, len(pts)


def point_params(top, name, cfg=None):
    """sweep_points 里名为 name 的那一项（去掉 name）—— `POINT=` / `POINTS=` 用（内部#332）。
    先照常校验整张点表；点名不存在时报错并列出全部点名。"""
    if cfg is None:
        from flow.paths import load_design_config
        cfg = load_design_config(top)
    _points(top, cfg.get("params") or {}, cfg)
    pts = {p["name"]: {k: v for k, v in p.items() if k != "name"} for p in (cfg.get("sweep_points") or [])}
    if name not in pts:
        have = "、".join(pts) if pts else "（没有声明 sweep_points）"
        raise ExcludeError(f"{top} 没有名为 {name} 的扫参点；已声明：{have}")
    return pts[name]


def sweep_combos(top, cfg):
    """返回 (组合, exclude 排除的个数, 点数)。有点表时就是点表（点数 > 0），否则「叉乘（尊重 sweep: false）− exclude」。"""
    declared = cfg.get("params") or {}
    pts = _points(top, declared, cfg)
    if pts:
        return pts, 0, len(pts)
    kept, n_excl = apply(top, declared, cfg.get("exclude"), _cross(declared, True))
    return kept, n_excl, 0


def declared_combos(top, cfg):
    """读入集合要探的组合：叉乘 ∪ 点表，不减 exclude（`flow/synth/synth.py`）。"""
    declared = cfg.get("params") or {}
    return _union(_cross(declared, False), _points(top, declared, cfg))
