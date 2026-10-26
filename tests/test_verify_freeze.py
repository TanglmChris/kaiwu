"""功能验证按提交取设计版本、冻结输入并记录两侧出处（design-verify-collaboration，内部#80）。

为什么值得有这个测试：设计与验证分属两条分支以后，验证侧最容易出的错不是「跑不通」，
而是「测的不是自己以为的那一版」——按工作区路径取设计时，设计侧还没提交的 RTL 会被
悄悄测进去，结果指不回任何一个提交；运行期间设计侧又改了文件，同一轮里前后两个用例
读到的可能是两版 RTL。两种都不会报错。

夹具是一个独立的最小 git 仓：main 上是「设计侧」的提交（一个设计根 + 一个 cbb 依赖），
分支 verify 在其上改了 TB、verify 文档与 params.yaml 的 sim 段。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import rtl_candidates  # noqa: E402
from flow.verify.freeze import FreezeError, freeze  # noqa: E402

_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

FOO_PARAMS = """\
design_root: foo
tops:
  FOO:
    deps: [CBB_BAR]
    sim:
      clock_signal: clk
    params:
      DAT_W:
        values: [4]
"""
BAR_PARAMS = "design_root: cbb_bar\ntops:\n  CBB_BAR:\n    params:\n      DAT_W:\n        values: [4]\n"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, env=_ENV).stdout


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)
    return _git(repo, "rev-parse", "HEAD").strip()


def _make_repo(tmp_path, dtree="designs", ctree="cbb"):
    """main = 设计侧提交；verify = 验证侧提交（只改 tb/、verify 文档、sim 段）。

    `dtree` / `ctree` 是专用设计与构件所在的设计树（默认 designs/、cbb/）。
    """
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _write(r, f"{dtree}/foo/params.yaml", FOO_PARAMS)
    _write(r, f"{dtree}/foo/rtl/foo.v", "module FOO; CBB_BAR U_FOO_X_CBB_BAR (); endmodule\n")
    _write(r, f"{dtree}/foo/spec.FOO.md", "# FOO spec v1\n")
    _write(r, f"{dtree}/foo/tb/test_foo.py", "# design smoke tb\n")
    _write(r, f"{dtree}/foo/verify.FOO.md", "# verify v0\n")
    _write(r, f"{ctree}/cbb_bar/params.yaml", BAR_PARAMS)
    _write(r, f"{ctree}/cbb_bar/rtl/cbb_bar.v", "module CBB_BAR; endmodule\n")
    _write(r, "flow/x.py", "")
    _commit(r, "design")
    _git(r, "checkout", "-q", "-b", "verify")
    _write(r, f"{dtree}/foo/tb/test_foo.py", "# verify tb v1\n")
    _write(r, f"{dtree}/foo/tb/test_more.py", "# verify only\n")
    _write(r, f"{dtree}/foo/verify.FOO.md", "# verify v1\n")
    _write(r, f"{dtree}/foo/params.yaml", FOO_PARAMS.replace("clock_signal: clk", "clock_signal: clk_v"))
    _commit(r, "verify")
    _git(r, "checkout", "-q", "main")
    return r


@pytest.fixture
def repo(tmp_path):
    return _make_repo(tmp_path)


def _freeze(repo, tmp_path, **kw):
    kw.setdefault("tb_ref", "verify")
    kw.setdefault("repo", repo)
    kw.setdefault("flow_root", repo)
    return freeze("FOO", tmp_path / "out", **kw)


# ---- M1：按提交取、冻结只读、两侧各取各的 ----

def test_design_ref_ignores_uncommitted_design_changes(repo, tmp_path):
    committed = (repo / "designs/foo/rtl/foo.v").read_text()
    (repo / "designs/foo/rtl/foo.v").write_text("module FOO; /* uncommitted */ endmodule\n")
    freeze_out = _freeze(repo, tmp_path, design_ref="main")
    tree = Path(freeze_out["tree"])
    assert (tree / "designs/foo/rtl/foo.v").read_text() == committed


def test_frozen_tree_is_read_only_and_unaffected_by_later_edits(repo, tmp_path):
    m = _freeze(repo, tmp_path, design_ref="main")
    tree = Path(m["tree"])
    rtl = tree / "designs/foo/rtl/foo.v"
    assert not os.access(rtl, os.W_OK)
    assert not os.access(rtl.parent, os.W_OK), "目录也要只读，否则能往冻结树里加文件"
    (repo / "designs/foo/rtl/foo.v").write_text("module FOO; /* later */ endmodule\n")
    import hashlib
    assert hashlib.sha256(rtl.read_bytes()).hexdigest() == m["files"]["designs/foo/rtl/foo.v"]["sha256"]
    saved = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert saved["files"] == m["files"]


def test_each_side_contributes_its_own_files(repo, tmp_path):
    m = _freeze(repo, tmp_path, design_ref="main")
    tree = Path(m["tree"])
    assert (tree / "designs/foo/tb/test_foo.py").read_text() == "# verify tb v1\n"
    assert (tree / "designs/foo/tb/test_more.py").exists()
    assert (tree / "designs/foo/verify.FOO.md").read_text() == "# verify v1\n"
    assert (tree / "designs/foo/spec.FOO.md").read_text() == "# FOO spec v1\n"
    import yaml
    params = yaml.safe_load((tree / "designs/foo/params.yaml").read_text())
    assert params["tops"]["FOO"]["sim"] == {"clock_signal": "clk_v"}, "sim 段归验证"
    assert params["tops"]["FOO"]["deps"] == ["CBB_BAR"], "其余归设计"
    f = m["files"]
    assert f["designs/foo/tb/test_foo.py"]["side"] == "tb"
    assert f["designs/foo/verify.FOO.md"]["side"] == "tb"
    assert f["designs/foo/rtl/foo.v"]["side"] == "design"
    assert f["cbb/cbb_bar/rtl/cbb_bar.v"]["side"] == "design"
    assert f["designs/foo/params.yaml"]["side"] == "design+tb(sim)"
    assert not (tree / "flow").exists(), "冻结树只含 designs/ 与 cbb/"


def test_rtl_candidates_resolve_inside_the_frozen_tree(repo, tmp_path):
    m = _freeze(repo, tmp_path, design_ref="main")
    tree = Path(m["tree"])
    names = sorted(p.relative_to(tree).as_posix() for p in rtl_candidates("FOO", repo_root=tree))
    assert names == ["cbb/cbb_bar/rtl/cbb_bar.v", "designs/foo/rtl/foo.v"]


# ---- M2：出处与 deliverable、失败路径 ----

def test_both_sides_from_commits_is_deliverable(repo, tmp_path):
    m = _freeze(repo, tmp_path, design_ref="main")
    assert m["deliverable"] is True, m["not_deliverable_because"]
    assert m["not_deliverable_because"] == []
    assert m["design"]["commit"] == _git(repo, "rev-parse", "main").strip()
    assert m["tb"]["commit"] == _git(repo, "rev-parse", "verify").strip()
    assert m["top"] == "FOO" and m["design_root"] == "designs/foo"
    assert len(m["flow"]["commit"]) == 40 and m["flow"]["dirty"] is False


def test_design_from_worktree_is_not_deliverable(repo, tmp_path):
    (repo / "designs/foo/rtl/foo.v").write_text("module FOO; /* wip */ CBB_BAR U (); endmodule\n")
    m = _freeze(repo, tmp_path, design_worktree=repo)
    assert m["deliverable"] is False
    assert any("设计侧取自工作区" in r for r in m["not_deliverable_because"]), m
    assert m["design"]["dirty"] is True
    assert "wip" in (Path(m["tree"]) / "designs/foo/rtl/foo.v").read_text()


def test_dirty_tb_worktree_is_not_deliverable(repo, tmp_path):
    _git(repo, "checkout", "-q", "verify")
    (repo / "designs/foo/tb/test_foo.py").write_text("# uncommitted tb\n")
    m = _freeze(repo, tmp_path, design_ref="main", tb_ref=None, tb_worktree=repo)
    assert m["deliverable"] is False
    assert any("TB 有未提交的改动" in r for r in m["not_deliverable_because"]), m
    assert (Path(m["tree"]) / "designs/foo/tb/test_foo.py").read_text() == "# uncommitted tb\n"


def test_missing_dependency_fails_and_names_it(repo, tmp_path):
    _git(repo, "rm", "-rq", "cbb/cbb_bar")
    _commit(repo, "drop dep")
    with pytest.raises(FreezeError, match="CBB_BAR"):
        _freeze(repo, tmp_path, design_ref="main")


def test_unresolvable_design_ref_fails_with_push_fetch_hint(repo, tmp_path):
    with pytest.raises(FreezeError, match="fetch"):
        _freeze(repo, tmp_path, design_ref="origin/nowhere")
    assert not (tmp_path / "out").exists(), "失败时不留半棵树"


# ---- 内部#341 freeze-overlay：把设计树的某个路径换成另一个提交或本地文件 ----

def _cbb_commit(repo):
    """一个只改了 cbb/cbb_bar 的提交（挂在分支 cbbnew 上），回到 main。"""
    _git(repo, "checkout", "-q", "-b", "cbbnew")
    _write(repo, "cbb/cbb_bar/rtl/cbb_bar.v", "module CBB_BAR; /* new */ endmodule\n")
    _write(repo, "designs/foo/rtl/foo.v", "module FOO; /* not taken */ CBB_BAR U (); endmodule\n")
    c = _commit(repo, "cbb new")
    _git(repo, "checkout", "-q", "main")
    return c


def test_overlay_from_a_commit_takes_only_that_path_and_stays_deliverable(repo, tmp_path):
    c = _cbb_commit(repo)
    m = _freeze(repo, tmp_path, design_ref="main", overlays=["cbbnew:cbb/cbb_bar"])
    tree = Path(m["tree"])
    assert "/* new */" in (tree / "cbb/cbb_bar/rtl/cbb_bar.v").read_text()
    assert "not taken" not in (tree / "designs/foo/rtl/foo.v").read_text(), "叠加以外的路径仍取设计提交"
    assert m["deliverable"] is True, m["not_deliverable_because"]
    assert m["overlays"] == [{"path": "cbb/cbb_bar", "ref": "cbbnew", "commit": c}]
    assert m["files"]["cbb/cbb_bar/rtl/cbb_bar.v"]["side"] == "overlay"
    assert m["files"]["designs/foo/rtl/foo.v"]["side"] == "design"


def test_local_overlay_takes_the_mutant_and_is_not_deliverable(repo, tmp_path):
    mut = tmp_path / "mut.v"
    mut.write_text("module FOO; /* mutant */ CBB_BAR U (); endmodule\n")
    m = _freeze(repo, tmp_path, design_ref="main", overlays_local=[f"{mut}:designs/foo/rtl/foo.v"])
    assert "mutant" in (Path(m["tree"]) / "designs/foo/rtl/foo.v").read_text()
    assert m["deliverable"] is False
    assert any(str(mut) in r for r in m["not_deliverable_because"]), m["not_deliverable_because"]
    assert m["overlays"] == [{"path": "designs/foo/rtl/foo.v", "local": str(mut)}]
    assert m["files"]["designs/foo/rtl/foo.v"]["side"] == "overlay"


@pytest.mark.parametrize("kw, msg", [
    ({"overlays_local": ["{mut}:designs/foo/tb/test_foo.py"]}, "tb"),
    ({"overlays_local": ["{mut}:designs/foo/verify.FOO.md"]}, "verify"),
    ({"overlays_local": ["{mut}:flow/x.py"]}, "designs/"),
    ({"overlays_local": ["{mut}:designs/../flow/x.py"]}, "designs/"),
    ({"overlays": ["main:cbb/no_such"]}, "cbb/no_such"),
    ({"overlays": ["cbb/cbb_bar"]}, "冒号"),
])
def test_bad_overlay_fails_and_leaves_no_output(repo, tmp_path, kw, msg):
    mut = tmp_path / "mut.v"
    mut.write_text("x\n")
    kw = {k: [s.format(mut=mut) for s in v] for k, v in kw.items()}
    with pytest.raises(FreezeError, match=msg):
        _freeze(repo, tmp_path, design_ref="main", **kw)
    assert not (tmp_path / "out").exists(), "失败时不留半棵树"


def test_cli_overlay_flags_reach_freeze(repo, tmp_path, capsys):
    from flow.verify import freeze as fz
    c = _cbb_commit(repo)
    rc = fz.main(["--top", "FOO", "--design-ref", "main", "--tb-ref", "verify", "--repo", str(repo),
                  "--out", str(tmp_path / "out"), "--overlay", "cbbnew:cbb/cbb_bar"])
    assert rc == 0, capsys.readouterr()
    saved = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert saved["overlays"] == [{"path": "cbb/cbb_bar", "ref": "cbbnew", "commit": c}]
