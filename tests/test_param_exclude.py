"""params.yaml 的 `exclude`：非法参数组合不展开，写错的排除项当场报错（内部#138，param-exclude）。"""
import itertools
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.param_exclude import ExcludeError, apply  # noqa: E402

DECLARED = {"WIDTH": {"values": [64, 256]}, "MODE": {"values": [0, 1]}}


def _all():
    names = list(DECLARED)
    return [dict(zip(names, c)) for c in itertools.product(*(DECLARED[n]["values"] for n in names))]


def test_a_partial_assignment_excludes_every_matching_combo():
    kept, n = apply("TOP", DECLARED, [{"MODE": 1, "WIDTH": 64}], _all())
    assert n == 1
    assert {"WIDTH": 64, "MODE": 1} not in kept and len(kept) == 3


def test_no_exclude_keeps_everything():
    kept, n = apply("TOP", DECLARED, None, _all())
    assert n == 0 and kept == _all()


@pytest.mark.parametrize("exclude, named", [
    ([{"COMP": 1}], "COMP"),
    ([{"WIDTH": 128}], "128"),
    ([{"MODE": 1}, {"MODE": 0}], "全部"),
    ([{}], "空"),
    ({"MODE": 1}, "列表"),
])
def test_a_wrong_exclude_entry_is_named(exclude, named):
    with pytest.raises(ExcludeError) as e:
        apply("TOP", DECLARED, exclude, _all())
    assert named in str(e.value) and "TOP" in str(e.value)


# --- 内部#214 sweep_points 与 cross: false（sweep-points）-------------------------------------

def _cfg(points=None, cross_values=(2, 16), exclude=None):
    params = {"DAT_W": {"values": [128, 256]}, "WIDTH": {"values": [64, 256]},
              "MB_NUM": {"values": list(cross_values), "cross": False},
              "META_EN": {"values": [1, 0], "sweep": False}}
    cfg = {"params": params}
    if points is not None:
        cfg["sweep_points"] = points
    if exclude is not None:
        cfg["exclude"] = exclude
    return cfg


P16 = {"name": "pa16", "DAT_W": 256, "WIDTH": 64, "MB_NUM": 16, "META_EN": 0}
P2 = {"name": "pb2", "DAT_W": 256, "WIDTH": 256, "MB_NUM": 2, "META_EN": 1}


def test_sweep_points_and_cross_false_expand_three_ways():
    from flow.param_exclude import declared_combos, fast_check_combos, sweep_combos
    cfg = _cfg([P16, P2])
    fc, n_excl, n_pts = fast_check_combos("TOP", cfg)
    # 叉乘：DAT_W × WIDTH × META_EN（MB_NUM 只取 2）= 8；加点 pa16（新）；pb2 已在叉乘里
    assert len(fc) == 9 and n_excl == 0 and n_pts == 2
    assert all(c["MB_NUM"] == 2 for c in fc[:8])
    assert {k: v for k, v in P16.items() if k != "name"} in fc
    sw, _, n = sweep_combos("TOP", cfg)
    assert n == 2 and sw == [{k: v for k, v in p.items() if k != "name"} for p in (P16, P2)]
    assert declared_combos("TOP", cfg) == fc


def test_without_points_sweep_keeps_the_cross_minus_exclude():
    from flow.param_exclude import sweep_combos
    sw, n_excl, n = sweep_combos("TOP", _cfg(cross_values=(2,), exclude=[{"DAT_W": 128, "WIDTH": 64}]))
    assert n == 0 and n_excl == 1 and len(sw) == 3
    assert all(c["META_EN"] == 1 and c["MB_NUM"] == 2 for c in sw)       # sweep: false 与 cross: false 都取首项


@pytest.mark.parametrize("points, exclude, named", [
    ([{k: v for k, v in P16.items() if k != "META_EN"}, P2], None, "META_EN"),
    ([{**P16, "X": 1}, P2], None, "X"),
    ([{**P16, "MB_NUM": 8}, P2], None, "8"),
    ([P16, P2], [{"WIDTH": 64, "MB_NUM": 16}], "exclude"),
    ([P16, {**P2, "name": "pa16"}], None, "pa16"),
    ([P16, {**P16, "name": "again"}], None, "again"),
    ([{k: v for k, v in P16.items() if k != "name"}, P2], None, "name"),
    ([P2], None, "16"),
    (None, None, "16"),
])
def test_a_wrong_sweep_point_is_named(points, exclude, named):
    from flow.param_exclude import fast_check_combos, sweep_combos
    for fn in (fast_check_combos, sweep_combos):
        with pytest.raises(ExcludeError) as e:
            fn("TOP", _cfg(points, exclude=exclude))
        assert named in str(e.value) and "TOP" in str(e.value), str(e.value)
