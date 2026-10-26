"""按扫参点名取参数（POINT= / POINTS=）与按提交量 depth（REF=）（内部#332，run-by-point-name）。

夹具设计 tests/fixtures/designs/point_root：声明了 3 个带名字的 sweep_points，每个点给全参数，其中 NUM 是
cross: false —— 内部#332 说的「手抄全部参数、抄错没人拦」的那种形态，只是参数少。原来读的是闭源设计的 params.yaml，
导出到开源仓后用例会失败（内部#365），所以换成夹具。
"""
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TOP = "POINT_TOP"
PARAMS = REPO_ROOT / "tests" / "fixtures" / "designs" / "point_root" / "params.yaml"


def _declared_points():
    cfg = yaml.safe_load(PARAMS.read_text())["tops"][TOP]
    return {p["name"]: {k: v for k, v in p.items() if k != "name"} for p in cfg["sweep_points"]}


# --- 1.1 POINT= / POINTS= ------------------------------------------------------

def test_point_params_equal_the_declared_point(fixture_designs):
    from flow.param_exclude import point_params
    pts = _declared_points()
    assert len(pts) >= 2
    for name, params in pts.items():
        assert point_params(TOP, name) == params, name


def test_unknown_point_lists_every_name(fixture_designs):
    from flow.param_exclude import ExcludeError, point_params
    with pytest.raises(ExcludeError) as e:
        point_params(TOP, "pt_b9")
    for name in _declared_points():
        assert name in str(e.value), str(e.value)


def test_exp_point_passes_the_declared_params(fixture_designs, monkeypatch):
    from scripts import exp as exp_mod
    seen = {}

    def fake(design, params, liberty, sim, period_ns, reference=False):
        seen["params"] = params
        return {"experiment_id": "e1", "sim": {"passed": True}}
    monkeypatch.setattr(exp_mod, "run_experiment", fake)
    monkeypatch.setattr(exp_mod, "prune_vcd", lambda eid: 0)
    assert exp_mod.main(["--design", TOP, "--point", "pt_b1", "--liberty", "x.lib"]) == 0
    assert seen["params"] == _declared_points()["pt_b1"]


@pytest.mark.parametrize("entry", ["exp", "depth"])
def test_point_and_param_together_is_refused(entry, fixture_designs, capsys):
    if entry == "exp":
        from scripts import exp as mod
    else:
        from flow.synth import depth as mod
    with pytest.raises(SystemExit) as e:
        mod.main(["--design", TOP, "--point", "pt_b1", "--param", "DAT_W=16", "--liberty", "x.lib"])
    assert e.value.code != 0
    assert "--point 与 --param 不能同时给" in capsys.readouterr().err


def test_depth_point_measures_the_declared_params(fixture_designs, monkeypatch):
    from flow.synth import depth
    seen = {}

    def fake(design, module, params, liberty, **k):
        seen["params"] = params
        raise SystemExit(0)          # 只看参数，不真量
    monkeypatch.setattr(depth, "measure", fake)
    with pytest.raises(SystemExit):
        depth.main(["--design", TOP, "--point", "pt_a1"])
    assert {k: str(v) for k, v in seen["params"].items()} == {k: str(v) for k, v in _declared_points()["pt_a1"].items()}


def test_depth_point_on_a_submodule_is_refused(capsys):
    from flow.synth import depth
    with pytest.raises(SystemExit) as e:
        depth.main(["--design", TOP, "--module", "POINT_SUB", "--point", "pt_a1"])
    assert e.value.code != 0
    assert "--point 取的是被测顶层的参数" in capsys.readouterr().err


def test_sweep_points_runs_only_the_named_points(fixture_designs, tmp_path, monkeypatch):
    from scripts import sweep as sweep_mod
    calls = []

    def fake(design, params, liberty, sim="icarus", period_ns=5.0):
        calls.append(dict(params))
        return {"experiment_id": f"e{len(calls)}", "design": design, "params": params,
                "sim": {"passed": True}, "flow": {"fingerprint": "fp"}, "synth": {"sources_sha256": "s"}}
    monkeypatch.setattr(sweep_mod, "run_experiment", fake)
    monkeypatch.setattr(sweep_mod, "flow_fingerprint", lambda *a, **k: {"fingerprint": "fp"}, raising=False)
    monkeypatch.setattr(sweep_mod, "current_sources_sha256", lambda design: "s", raising=False)
    log = tmp_path / "experiments.jsonl"
    log.touch()
    sweep_mod.sweep(TOP, "x.lib", log_path=log, points=["pt_b1", "pt_a0"])
    pts = _declared_points()
    assert sorted(map(str, calls)) == sorted(map(str, [pts["pt_b1"], pts["pt_a0"]]))


def test_sweep_unknown_point_is_refused(fixture_designs, tmp_path):
    from flow.param_exclude import ExcludeError
    from scripts import sweep as sweep_mod
    log = tmp_path / "experiments.jsonl"
    log.touch()
    with pytest.raises((ExcludeError, sweep_mod.SweepError)) as e:
        sweep_mod.sweep(TOP, "x.lib", log_path=log, points=["pt_b9"])
    assert "pt_b1" in str(e.value)


# --- 1.2 REF=：在提交的临时检出里跑（scripts/at_ref.py）-----------------------------

import subprocess  # noqa: E402

AT_REF = REPO_ROOT / "scripts" / "at_ref.py"
_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True, env=_ENV).stdout.strip()


@pytest.fixture
def two_commits(tmp_path):
    """主仓（带 .venv 目录与 .gitignore 的 .venv）两个提交：f.txt 先是 old 后是 new。"""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text(".venv\n")
    (root / ".venv").mkdir()
    (root / ".venv" / "marker").write_text("venv\n")
    (root / "f.txt").write_text("old\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "old")
    old = _git(root, "rev-parse", "HEAD")
    (root / "f.txt").write_text("new\n")
    _git(root, "commit", "-qam", "new")
    return root, old


def _at_ref(root, ref, *cmd):
    return subprocess.run([sys.executable, str(AT_REF), "--ref", ref, "--", *cmd],
                          cwd=root, capture_output=True, text=True)


def test_at_ref_runs_in_the_commits_checkout_and_cleans_up(two_commits):
    root, old = two_commits
    r = _at_ref(root, old[:8], "sh", "-c", "cat f.txt; cat .venv/marker; test -L .venv && echo LINK")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "old" in r.stdout and "new" not in r.stdout, r.stdout
    assert "venv" in r.stdout and "LINK" in r.stdout, r.stdout
    assert f"ref {old}" in r.stdout, r.stdout
    assert _git(root, "worktree", "list").count("\n") == 0, _git(root, "worktree", "list")


def test_at_ref_removes_the_worktree_even_when_the_command_fails(two_commits):
    root, old = two_commits
    r = _at_ref(root, old, "sh", "-c", "exit 3")
    assert r.returncode == 3, r.stdout + r.stderr
    assert _git(root, "worktree", "list").count("\n") == 0, _git(root, "worktree", "list")


def test_at_ref_unknown_ref_fails_before_running(two_commits):
    root, _ = two_commits
    r = _at_ref(root, "no-such-ref", "sh", "-c", "echo RAN")
    assert r.returncode == 2 and "RAN" not in r.stdout, r.stdout + r.stderr
    assert "no-such-ref" in r.stdout + r.stderr


def test_makefile_depth_goes_through_at_ref_when_ref_is_given():
    r = subprocess.run(["make", "-n", "-f", str(REPO_ROOT / "flow" / "Makefile"), "depth", "DESIGN=CBB_LZD", "REF=abc123"],
                       capture_output=True, text=True)
    assert "scripts/at_ref.py --ref abc123 --" in r.stdout, r.stdout + r.stderr
    assert "REF=abc123" not in r.stdout.split("--", 1)[-1], r.stdout   # 里层的 make 不再带 REF，不然无穷递归


# --- 内部#397：make … REF= 经 MAKEFLAGS 把 REF 传进 at_ref 里的子 make，无限递归、写满磁盘 ---

REC_MAKEFILE = """\
# 与 flow/Makefile 的 depth 同形：给了 REF 就经 at_ref 在那个提交里再调自己。MAKELEVEL 到 3 就停，
# 免得红臂真的无限递归（10-21 实撞 872 层，#397）
ifneq ($(filter 3 4 5 6,$(MAKELEVEL)),)
$(error RECURSED at MAKELEVEL=$(MAKELEVEL))
endif
t:
ifneq ($(REF),)
\t{py} {at_ref} --ref $(REF) -- make -f Makefile t
else
\t@echo LEAF
endif
"""


def test_make_with_ref_runs_the_command_once_without_recursing(two_commits, tmp_path):
    root, old = two_commits
    (root / "Makefile").write_text(REC_MAKEFILE.format(py=sys.executable, at_ref=AT_REF))
    _git(root, "add", "Makefile")
    _git(root, "commit", "-qm", "makefile")
    ref = _git(root, "rev-parse", "HEAD")
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    import os
    r = subprocess.run(["make", "-s", "-f", "Makefile", "t", f"REF={ref}"], cwd=root, capture_output=True, text=True,
                       timeout=120, env=dict(os.environ, TMPDIR=str(tmp)))
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "RECURSED" not in out, out
    assert out.count("LEAF") == 1 and out.count(f"ref {ref}") == 1, out
    assert list(tmp.iterdir()) == [], f"临时目录没删干净：{list(tmp.iterdir())}"


def test_at_ref_refuses_to_nest_on_the_same_commit(two_commits):
    root, old = two_commits
    r = _at_ref(root, old, sys.executable, str(AT_REF), "--ref", old, "--", "sh", "-c", "echo RAN")
    assert r.returncode == 2 and "RAN" not in r.stdout, r.stdout + r.stderr
    assert "嵌套" in r.stderr, r.stderr
