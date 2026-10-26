"""单条 make exp 算完功耗也删 VCD（内部#222 ②）：scripts/exp.py 包一层 run_experiment，成功后删 sim / sim_gate 下的 VCD。

run_experiment 在 METRIC_MODULES 里，改它全仓换代；删 VCD 不改任何测量值，所以放在外面这一层（与 sweep 同理，内部#172）。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import exp as exp_mod  # noqa: E402
from scripts import sweep as sweep_mod  # noqa: E402


@pytest.fixture
def runs(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    for stage in ("sim", "sim_gate", "synth"):
        d = root / "e1" / stage
        d.mkdir(parents=True)
        (d / ("TOP_netlist.v" if stage == "synth" else "TOP.vcd")).write_text("x" * 10)
    monkeypatch.setattr(sweep_mod, "run_dir", lambda eid, stage=None: root / eid / stage if stage else root / eid)
    calls = []

    def fake(design, params, liberty, sim, period_ns, reference=False):
        calls.append((design, params, reference))
        return {"experiment_id": "e1"}
    monkeypatch.setattr(exp_mod, "run_experiment", fake)
    return root, calls


ARGS = ["--design", "CBB_LZD", "--param", "DAT_W=8", "--liberty", "x.lib"]


def test_vcd_deleted_after_success(runs, capsys):
    root, calls = runs
    assert exp_mod.main(ARGS) == 0
    assert calls == [("CBB_LZD", {"DAT_W": "8"}, False)]
    assert list(root.rglob("*.vcd")) == []
    assert list(root.rglob("*_netlist.v")), "网表不该被删"
    assert "删了 VCD" in capsys.readouterr().out


def test_keep_vcd_keeps_them(runs):
    root, _ = runs
    assert exp_mod.main(ARGS + ["--keep-vcd"]) == 0
    assert len(list(root.rglob("*.vcd"))) == 2


def test_failure_keeps_vcd(runs, monkeypatch):
    root, _ = runs

    def boom(*a, **k):
        raise RuntimeError("synth failed")
    monkeypatch.setattr(exp_mod, "run_experiment", boom)
    with pytest.raises(RuntimeError):
        exp_mod.main(ARGS)
    assert len(list(root.rglob("*.vcd"))) == 2


def test_makefile_exp_goes_through_wrapper():
    mk = (REPO_ROOT / "flow" / "Makefile").read_text()
    exp_block = mk.split("\nexp: require-design", 1)[1].split("\n\n", 1)[0]
    assert "scripts/exp.py" in exp_block and "--keep-vcd" in exp_block, exp_block


# --- 内部#222 ①：TRIAL=1 试跑，记录不进 results/experiments.jsonl，也不要求工作区干净 ---

def test_trial_writes_outside_results_and_skips_dirty_guard(tmp_path, monkeypatch, capsys):
    from scripts import run_experiment as rx
    seen = {}

    def fake(design, params, liberty, sim, period_ns, reference=False):
        seen["log"] = rx.EXPERIMENTS_LOG
        rx._assert_clean_worktree("?? designs/foo/rtl/new.v\n M flow/synth/synth.py\n")   # 脏着也不拦
        rec = {"experiment_id": "t1"}
        rx.EXPERIMENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        rx.EXPERIMENTS_LOG.write_text('{"experiment_id": "t1"}\n')
        return rec
    monkeypatch.setattr(exp_mod, "run_experiment", fake)
    monkeypatch.setattr(exp_mod, "TRIAL_ROOT", tmp_path / "trial")
    monkeypatch.setattr(sweep_mod, "run_dir", lambda eid, stage=None: tmp_path / "runs" / eid / (stage or ""))
    real_log = rx.EXPERIMENTS_LOG
    assert exp_mod.main(ARGS + ["--trial"]) == 0
    assert seen["log"] != real_log and seen["log"].parent.parent == tmp_path / "trial"
    assert rx.EXPERIMENTS_LOG == real_log, "试跑完要恢复正式记录路径"
    assert rx._assert_clean_worktree is not None
    with pytest.raises(RuntimeError):
        rx._assert_clean_worktree(" M flow/synth/synth.py\n")              # 守卫恢复原样
    status = list((tmp_path / "trial").rglob("git_status.txt"))
    assert status, "要存下试跑时的 git status"
    assert "试跑" in capsys.readouterr().out


# --- 内部#422：正式 exp 的记录写进本设计根的记录文件 ---

def test_formal_exp_writes_to_its_design_root_file(runs, monkeypatch):
    from flow import records
    from scripts import run_experiment as rx
    seen = {}

    def fake(design, params, liberty, sim, period_ns, reference=False):
        seen["log"], seen["rel"] = rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS
        rx._assert_clean_worktree("?? results/cbb_lzd/experiments.jsonl\n")      # 本设计根的文件不算脏
        with pytest.raises(RuntimeError):
            rx._assert_clean_worktree(" M results/cbb_fifo/experiments.jsonl\n")  # 别的设计根的算
        return {"experiment_id": "e1"}
    monkeypatch.setattr(exp_mod, "run_experiment", fake)
    saved = (rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS, rx._worktree_status)
    assert exp_mod.main(ARGS) == 0
    assert seen["log"] == records.log_path("CBB_LZD") == REPO_ROOT / "results" / "cbb_lzd" / "experiments.jsonl"
    assert seen["rel"] == "results/cbb_lzd/experiments.jsonl"
    assert (rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS, rx._worktree_status) == saved, "跑完要复原"
