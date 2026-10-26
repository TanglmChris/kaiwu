"""自检型 TB 的分层回归（`flow/verify/regress.py`，内部#83 的 A、B、D）。

为什么值得有这组测试：回归入口自己判「过没过」。判据松一点（没打结论行当通过、编译失败
没人看），全量 504 个作业就会静默地少验一截；去重键错一点（省略的参数不按 TB 默认值补齐），
同一个作业会跑两遍，或者两个不同的作业被当成一个。
"""
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import flow.verify.regress as rg  # noqa: E402

SIMS = [
    pytest.param("verilator", marks=pytest.mark.skipif(not shutil.which("verilator"), reason="需要 verilator")),
    pytest.param("icarus", marks=pytest.mark.skipif(
        not (shutil.which("iverilog") and shutil.which("vvp")), reason="需要 iverilog / vvp")),
]

TB = """\
module tb;
parameter A = 0, B = 1;
parameter MODE = 2;   // 行尾注释
parameter BROKEN = 0;
integer seed;
generate if (BROKEN) begin : g_bad
  NO_SUCH_MODULE u ();
end endgenerate
initial begin
  seed = 0;
  if (!$value$plusargs("SEED=%d", seed)) seed = 0;
  // 不打 DONE 要用 if 绕开：$finish 之后同一块里的语句在 Verilator 下照样执行
  if (A != 9) $display("DONE A=%0d B=%0d MODE=%0d seed=%0d err=%0d", A, B, MODE, seed, (A == 1));
  $finish;
end
endmodule
"""


def _manifest(tmp_path, text):
    (tmp_path / "tb_x.sv").write_text(TB)
    p = tmp_path / "regress.X.yaml"
    p.write_text(text)
    return p


BASE = """\
tb: tb_x.sv
top: tb
done: '^DONE'
pass: '\\berr=0\\b'
sets:
  cfg:
    - {A: 0, B: 1}
    - {A: 0, B: 3}
"""


def test_tb_defaults_are_read_from_parameter_declarations(tmp_path):
    p = _manifest(tmp_path, BASE + "groups: []\n")
    assert rg.tb_defaults(p.parent / "tb_x.sv") == {"A": "0", "B": "1", "MODE": "2", "BROKEN": "0"}


def test_groups_expand_sets_and_omitted_params_dedup_against_tb_defaults(tmp_path):
    p = _manifest(tmp_path, BASE + """\
groups:
  - name: g1
    tiers: [full]
    params: {cfg: [$cfg], MODE: [2, 5]}
  - name: g2
    tiers: [inner, full]
    params: {cfg: [$cfg]}
""")
    m = rg.load_manifest(p)
    jobs, raw = rg.expand(m, "full")
    assert raw == 6
    # g2 不写 MODE，补默认值 2 之后与 g1 的 MODE=2 两个作业重复
    assert len(jobs) == 4
    assert {rg.job_key(j) for j in jobs} == {
        "A=0,B=1,BROKEN=0,MODE=2", "A=0,B=1,BROKEN=0,MODE=5",
        "A=0,B=3,BROKEN=0,MODE=2", "A=0,B=3,BROKEN=0,MODE=5"}
    inner, raw_inner = rg.expand(m, "inner")
    assert raw_inner == 2 and len(inner) == 2


def test_unknown_parameter_names_are_refused(tmp_path):
    p = _manifest(tmp_path, BASE + "groups:\n  - {name: g, tiers: [full], params: {NOPE: [1]}}\n")
    with pytest.raises(ValueError, match="NOPE"):
        rg.expand(rg.load_manifest(p), "full")


def test_slower_jobs_go_first_and_unmeasured_ones_lead(tmp_path):
    jobs = [{"A": "1"}, {"A": "2"}, {"A": "3"}]
    durations = {"A=1": 2.0, "A=3": 9.0}
    assert [j["A"] for j in rg.order(jobs, durations)] == ["2", "3", "1"]


@pytest.mark.parametrize("sim", SIMS)
def test_all_passing_jobs_exit_zero_and_record_durations(tmp_path, sim):
    p = _manifest(tmp_path, BASE + "groups:\n  - {name: g, tiers: [inner], params: {cfg: [$cfg]}}\n")
    out = tmp_path / "out"
    rc, results = rg.run(p, "inner", jobs_n=2, out_dir=out, durations_path=tmp_path / "d.json", sim=sim)
    assert rc == 0 and len(results) == 2 and all(r["ok"] for r in results)
    assert set(rg.load_durations(tmp_path / "d.json")) == {rg.job_key(r["params"]) for r in results}


@pytest.mark.parametrize("sim", SIMS)
def test_failures_are_named_failed_err_missing_done_and_broken_build(tmp_path, sim):
    p = _manifest(tmp_path, BASE + """\
groups:
  - name: g
    tiers: [full]
    params: {A: [0, 1, 9]}
  - name: bad
    tiers: [full]
    params: {BROKEN: [1]}
""")
    rc, results = rg.run(p, "full", jobs_n=2, out_dir=tmp_path / "out",
                         durations_path=tmp_path / "d.json", sim=sim)
    assert rc != 0
    by = {(r["params"]["A"], r["params"]["BROKEN"]): r for r in results}
    assert by[("0", "0")]["ok"]
    assert not by[("1", "0")]["ok"] and "err=1" in by[("1", "0")]["info"]
    assert not by[("9", "0")]["ok"] and "DONE" in by[("9", "0")]["info"]
    assert not by[("0", "1")]["ok"] and "编译" in by[("0", "1")]["info"]


@pytest.mark.parametrize("sim", SIMS)
def test_runtime_params_share_one_build(tmp_path, sim):
    p = _manifest(tmp_path, BASE + """\
runtime: [SEED]
groups:
  - {name: g, tiers: [inner], params: {SEED: [1, 2, 3]}}
""")
    (tmp_path / "tb_x.sv").write_text(TB.replace("parameter BROKEN = 0;", "parameter BROKEN = 0;\nparameter SEED = 0;"))
    rc, results = rg.run(p, "inner", jobs_n=3, out_dir=tmp_path / "out",
                         durations_path=tmp_path / "d.json", sim=sim)
    assert rc == 0
    assert sorted(r["info"].split("seed=")[1].split()[0] for r in results) == ["1", "2", "3"]
    assert len(list((tmp_path / "out").glob("b*"))) == 1, "三个种子应共用一次编译"


def test_unknown_simulator_is_refused(tmp_path):
    p = _manifest(tmp_path, BASE + "groups: []\n")
    with pytest.raises(ValueError, match="sim"):
        rg.run(p, "inner", out_dir=tmp_path / "out", durations_path=tmp_path / "d.json", sim="xcelium")
