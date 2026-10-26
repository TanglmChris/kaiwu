"""depth 两次结果按终点集合比（内部#225）；over_budget.tsv 只留每终点一条并 gzip。不跑 yosys / OpenSTA，用手写的 tsv。"""
import gzip
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.synth import depth, depth_compare  # noqa: E402


def _row(c, start, end, n=None):
    pins = f"{start} u/a/x/Y u/b/y/Y {end}"
    return f"{c}\t{n or c + 3}\t{start}\t{end}\t{pins}"


def _tsv(path, rows, gz=False):
    text = "\n".join(rows) + "\n"
    if gz:
        with gzip.open(path, "wt") as f:
            f.write(text)
    else:
        path.write_text(text)
    return path


def test_shrink_keeps_best_row_per_endpoint(tmp_path):
    raw = _tsv(tmp_path / "over_budget.tsv", [_row(31, "s1", "e1"), _row(33, "s2", "e1"), _row(32, "s3", "e2")])
    out = depth.shrink_over_budget(raw)
    assert out.name == "over_budget.tsv.gz" and not raw.exists()
    rows = gzip.open(out, "rt").read().splitlines()
    assert len(rows) == 2
    assert any(r.startswith("33\t") and "\te1\t" in r for r in rows), rows


def test_compare_reports_gone_new_and_changed(tmp_path, capsys):
    a = _tsv(tmp_path / "a.tsv", [_row(31, "s1", "e1"), _row(35, "s2", "e2"), _row(32, "s3", "e3")])
    b = _tsv(tmp_path / "b.tsv.gz", [_row(31, "s1", "e1"), _row(33, "s2", "e2"), _row(34, "s4", "e4")], gz=True)
    r = depth_compare.compare(depth_compare.load(a), depth_compare.load(b))
    assert r["gone"] == ["e3"] and r["new"] == ["e4"]
    assert r["changed"] == [("e2", 35, 33)]
    assert r["worst_a"]["endpoint"] == "e2" and r["worst_b"]["endpoint"] == "e4"
    assert depth_compare.main([str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "消失 1" in out and "新出现 1" in out and "e3" in out and "e4" in out, out


def test_compare_flags_worst_endpoint_moved(tmp_path, capsys):
    a = _tsv(tmp_path / "a.tsv", [_row(35, "s1", "e1"), _row(31, "s2", "e2")])
    b = _tsv(tmp_path / "b.tsv", [_row(31, "s1", "e1"), _row(34, "s2", "e2")])
    depth_compare.main([str(a), str(b)])
    out = capsys.readouterr().out
    assert "最深终点变了" in out and "s1 → e1" in out and "s2 → e2" in out, out


def test_compare_accepts_run_dirs(tmp_path):
    for d, rows in (("a", [_row(31, "s1", "e1")]), ("b", [_row(31, "s1", "e1")])):
        (tmp_path / d).mkdir()
        _tsv(tmp_path / d / "over_budget.tsv.gz", rows, gz=True)
    assert depth_compare.main([str(tmp_path / "a"), str(tmp_path / "b")]) == 0


# --- 内部#340 design-side-tools 1.1：同一终点的路径按模块并排比 ---------------------------------
# 夹具在测试里现造（内部#365：原来的夹具取自闭源设计的真实网表，改名也藏不住层级与级数）。形态照 depth.py 写的
# 报告：每行「组合单元数、级数、起点、终点、空格分隔的路径引脚」；组合单元是同一实例连续两个引脚（A、Y），
# 起点寄存器只有 QN、终点寄存器只有 D。三个终点，第 1 行经过 MUX 里 4 个、RDAT 本体 13 个、ECC 子块 17 个单元；
# B 把第 1 行 ECC 子块里的 2 个单元改挂到 RDAT 本体下（总数 34 不变），另两行 A、B 相同。
MUX = "U_DEMO_TOP_MUX/U_DEMO_PIPE_M"
RDAT = "U_DEMO_TOP_BUF/U_DEMO_BUF_RDAT"
ECC = RDAT + "/GEN_FOR_CW[0].U_DEMO_ECC_DIR"


def _depth_row(start, end, parts, extra_stages=3):
    pins, n = [start], 100
    for inst, cells in parts:
        for _ in range(cells):
            pins += [f"{inst}/_{n:04d}_/A", f"{inst}/_{n:04d}_/Y"]
            n += 1
    pins.append(end)
    comb = sum(c for _, c in parts)
    return f"{comb}\t{comb + extra_stages}\t{start}\t{end}\t{' '.join(pins)}\n"


def _depth_report(path, moved):
    ecc, rdat = (15, 15) if moved else (17, 13)
    path.write_text(
        _depth_row(f"{MUX}/_0001_/QN", f"{ECC}/_0900_/D", [(MUX, 4), (RDAT, rdat), (ECC, ecc)])
        + _depth_row(f"{MUX}/_0002_/QN", f"{ECC}/_0901_/D", [(MUX, 4), (RDAT, 12), (ECC, 17)])
        + _depth_row(f"{MUX}/_0003_/QN", f"{RDAT}/_0902_/D", [(MUX, 3), (RDAT, 29)]))
    return path


@pytest.fixture
def reports(tmp_path):
    return _depth_report(tmp_path / "a.tsv", moved=False), _depth_report(tmp_path / "b.tsv", moved=True)


def test_composition_sums_to_the_recorded_comb_cells(reports):
    for f in reports:
        for e, p in depth_compare.load(f).items():
            comp = depth_compare.composition(p["pins"], levels=3)
            assert sum(comp.values()) == p["comb_cells"], (f, e, comp)


def test_module_drops_the_cell_name_before_taking_levels(reports):
    """浅层级不能把单元名本身当成模块：MUX 里的 4 个单元在 levels=3 时归一个模块。"""
    p = depth_compare.load(reports[0])
    comp = depth_compare.composition(next(iter(p.values()))["pins"], levels=3)
    assert comp[MUX] == 4, comp
    assert not any(m.split("/")[-1].startswith("_") for m in comp), comp


def test_endpoint_shows_cells_moving_between_modules(reports, capsys):
    a = depth_compare.load(reports[0])
    e = max(a, key=lambda k: a[k]["comb_cells"])
    rc = depth_compare.main([str(reports[0]), str(reports[1]), "--endpoint", e, "--levels", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    rows = {ln.split()[0]: ln.split()[1:] for ln in out.splitlines() if ln.startswith(("U_", "合计"))}
    assert rows[ECC] == ["17", "15", "-2"], out
    assert rows[RDAT] == ["13", "15", "+2"], out
    assert rows["合计"] == ["34", "34", "0"], out


def test_composition_lists_endpoints_whose_make_up_changed_even_at_the_same_total(reports, capsys):
    depth_compare.main([str(reports[0]), str(reports[1]), "--composition", "--levels", "3"])
    out = capsys.readouterr().out
    assert out.count("## 终点") == 1, out            # 只有第 1 行的构成变了，另两行一模一样
    assert "_0900_/D" in out, out


def test_composition_without_pins_column_fails(reports, tmp_path):
    old = tmp_path / "old.tsv"
    old.write_text("".join("\t".join(ln.split("\t")[:4]) + "\n" for ln in reports[0].read_text().splitlines()))
    with pytest.raises(SystemExit) as e:
        depth_compare.main([str(old), str(reports[1]), "--composition"])
    assert "重跑 depth" in str(e.value), e.value
