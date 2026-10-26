"""RTL 仿真失败的记录（内部#334，regen-sim-fail-and-root-waivers 1.2）。

失败时 run_experiment 立即停：不综合、不跑 STA，写一条 `synth` / `sta` 叶子全为 null 的记录
（`synth.sources_sha256` 照写），`make exp` 退出 1。读记录的工具要能读这类记录。

夹具按真实形态造：取实验记录（results/<设计根>/experiments.jsonl）里一条真实的 CBB_LZD 记录，把它的 synth / sta 叶子
置空做成失败记录 —— 字段集合与真实记录逐个相同，读者看到的就是将来会写出来的那种行。
"""
import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DESIGN = "CBB_LZD"


def _real_record():
    from flow import records
    if not records.source_files():   # 写法同 test_run_experiment 的 test_the_schema_only_grows（内部#365）
        pytest.skip("没有 results/<设计根>/experiments.jsonl：记录闭源，不在导出集合（open-export「导出结果自足」）")
    recs = [r for r in records.load(DESIGN) if r["sim"]["passed"]
            and (r.get("synth") or {}).get("area_breakdown") is not None]
    return recs[-1]


def _null_leaves(obj):
    if isinstance(obj, dict):
        return {k: _null_leaves(v) for k, v in obj.items()}
    return None


def _failure_from(rec):
    """真实记录 → 同形的失败记录：synth / sta 每个键照留、取值 null（含 corners / scenarios / area_breakdown），
    sources_sha256 照留。"""
    f = copy.deepcopy(rec)
    f["experiment_id"] = rec["experiment_id"] + "-fail"
    f["sim"] = {**rec["sim"], "passed": False, "cycles": None, "total_toggles": None, "gate_passed": None}
    f["synth"] = {k: None for k in rec["synth"]}
    f["synth"]["sources_sha256"] = rec["synth"]["sources_sha256"]
    f["sta"] = {k: None for k in rec["sta"]}
    f["reference"] = None
    return f


# --- run_experiment：仿真失败即停 ------------------------------------------------

def test_rtl_sim_failure_stops_before_synth_and_writes_a_failure_record(tmp_path, monkeypatch):
    import scripts.run_experiment as rx
    real = _real_record()
    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")
    monkeypatch.setattr(rx, "_assert_verified", lambda design: None)
    monkeypatch.setattr(rx, "corner_liberties", lambda lib: {})
    monkeypatch.setattr(rx, "run_dir", lambda *a: tmp_path.joinpath("runs", *a))
    monkeypatch.setattr(rx, "run_sim", lambda *a, **k: {"passed": False, "vcd_path": None, "build_dir": str(tmp_path)})
    monkeypatch.setattr(rx, "_sources_sha256", lambda design: "src-digest")
    monkeypatch.setattr(rx, "flow_fingerprint", lambda *a, **k: {"fingerprint": "fp-test"})

    def must_not_run(*a, **k):
        raise AssertionError("RTL 仿真失败后不该再调 search_fmax / 门级仿真 / STA")
    for name in ("search_fmax", "gate_activity", "run_sta", "vcd_stats"):
        monkeypatch.setattr(rx, name, must_not_run)

    rec = rx.run_experiment(DESIGN, dict(real["params"]), "x.lib")
    written = json.loads(log.read_text().strip())
    for r in (rec, written):
        assert r["sim"]["passed"] is False and r["sim"]["gate_passed"] is None
        assert set(r["synth"]) >= set(real["synth"]), "synth 段少了字段名（红线 2）"
        assert set(r["sta"]) >= set(real["sta"]), "sta 段少了字段名（红线 2）"
        assert r["synth"]["sources_sha256"] == "src-digest"
        assert all(v is None for k, v in r["synth"].items() if k != "sources_sha256"), r["synth"]
        assert all(v is None for v in r["sta"].values()), r["sta"]
        assert r["reference"] is None
        assert r["flow"]["fingerprint"] and r["design"] == DESIGN and r["params"]


def test_exp_exits_1_and_keeps_vcd_when_the_record_says_sim_failed(tmp_path, monkeypatch, capsys):
    from scripts import exp as exp_mod
    from scripts import sweep as sweep_mod
    root = tmp_path / "runs"
    (root / "e1" / "sim").mkdir(parents=True)
    (root / "e1" / "sim" / "TOP.vcd").write_text("x")
    monkeypatch.setattr(sweep_mod, "run_dir", lambda eid, stage=None: root / eid / stage if stage else root / eid)
    monkeypatch.setattr(exp_mod, "run_experiment",
                        lambda *a, **k: {"experiment_id": "e1", "sim": {"passed": False}})
    rc = exp_mod.main(["--design", DESIGN, "--param", "DAT_W=8", "--liberty", "x.lib"])
    assert rc == 1
    assert list(root.rglob("*.vcd")), "失败的实验要留 VCD 排查"
    assert "仿真失败" in capsys.readouterr().out


# --- 读者：扫参摘要、打分、报告、换代配对 -----------------------------------------

def _log_with(tmp_path, *recs):
    p = tmp_path / "experiments.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return p


def test_sweep_summary_prints_a_failure_row(tmp_path, capsys):
    from scripts import sweep
    real = _real_record()
    fail = _failure_from(real)
    log = _log_with(tmp_path, real, fail)
    sweep.print_table([real, fail], DESIGN, log_path=log)
    out = capsys.readouterr().out
    rows = out.strip().splitlines()
    assert len(rows) == 3, out
    assert any("False" in r for r in rows[1:]), out


def test_score_puts_the_failure_record_last_without_a_score(tmp_path):
    from scripts import score
    real = _real_record()
    fail = _failure_from(real)
    fail["params"] = {**real["params"], "DAT_W": -1}        # 另一组参数，免得被 latest_per_params 盖掉
    cfg = score.load_config()
    rows = score.score_rows(score.load_records(design=DESIGN) + [fail], DESIGN, cfg)   # 带上基线那条
    by_id = {r["experiment_id"]: r for r in rows}
    assert by_id[fail["experiment_id"]]["score"] is None
    assert rows[-1]["experiment_id"] == fail["experiment_id"]


def test_report_renders_with_a_failure_record():
    from scripts import gen_report
    real = _real_record()
    fail = _failure_from(real)
    fail["params"] = {**real["params"], "DAT_W": 999}
    text = gen_report.render(DESIGN, [real, fail])
    assert "仿真失败" in text, text[-2000:]


def test_pairing_treats_two_failures_as_equal_and_one_as_a_difference():
    from scripts import pair_generations as pg
    real = _real_record()
    fail = _failure_from(real)
    both = pg.compare([fail], [copy.deepcopy(fail)])
    one = pg.compare([real], [fail])
    assert not both["diffs"], both
    assert one["diffs"], one
