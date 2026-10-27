"""签名逐作业比对（内部#224，flow/verify/sigeq.py）：同 TB、两个提交的 RTL，逐作业比 DONE 行的 sig=。

夹具是一个独立的小 git 仓：designs/foo 一个组合模块，TB 把它的输出折成签名打在 DONE 行里。用 Icarus（快、不要构建缓存）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.verify import sigeq  # noqa: E402

needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog 不在 PATH")

RTL = """module FOO (input wire [3:0] a, input wire [3:0] b, output wire [3:0] y);
    assign y = a & b;
endmodule
"""
TB = """module tb;
  parameter SIGOK = 1;
  parameter K = 0;
  reg [3:0] a, b; wire [3:0] y; reg [31:0] sig; integer i;
  FOO u (.a(a), .b(b), .y(y));
  initial begin
    sig = 0;
    for (i = 0; i < 256; i = i + 1) begin a = i[3:0]; b = i[7:4]; #1 sig = sig * 32'd16777619 + y + 1; end
    if (SIGOK) $display("DONE k=%0d sig=%h err=0", K, sig);
    else $display("DONE k=%0d err=0", K);
    $finish;
  end
endmodule
"""
MANIFEST = """tb: tb_foo.sv
top: tb
done: '^DONE'
pass: '\\berr=0\\b'
groups:
  - name: g
    tiers: [inner]
    params: {K: [0, 1]}
"""


def _git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    root = r / "designs" / "foo"
    (root / "rtl").mkdir(parents=True)
    (root / "tb").mkdir()
    (r / "cbb").mkdir()
    (r / "cbb" / ".keep").write_text("")
    (root / "params.yaml").write_text("tops:\n  FOO:\n    params: {}\n")
    (root / "rtl" / "foo.v").write_text(RTL)
    (root / "tb" / "tb_foo.sv").write_text(TB)
    (root / "tb" / "regress.FOO.yaml").write_text(MANIFEST)
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _run(repo, *args):
    return sigeq.main(["--design", "FOO", "--repo", str(repo), "--manifest",
                       str(repo / "designs" / "foo" / "tb" / "regress.FOO.yaml"), "--sim", "icarus", "-j", "2", *args])


def _commit(repo, rtl, msg):
    (repo / "designs" / "foo" / "rtl" / "foo.v").write_text(rtl)
    _git(repo, "commit", "-qam", msg)
    return _git(repo, "rev-parse", "HEAD")


@needs_iverilog
def test_equivalent_rewrite_passes(repo, monkeypatch, capsys):
    monkeypatch.setattr(sigeq, "rtl_candidates", lambda d, root: [root / "designs" / "foo" / "rtl" / "foo.v"])
    monkeypatch.setattr(sigeq, "include_dirs", lambda d, root: [])
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RTL.replace("a & b", "~(~a | ~b)"), "rewrite")
    assert _run(repo, "--old", base) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "相同 2，不同 0" in out and "designs/foo/rtl/foo.v" in out, out


@needs_iverilog
def test_real_change_is_reported(repo, monkeypatch, capsys):
    monkeypatch.setattr(sigeq, "rtl_candidates", lambda d, root: [root / "designs" / "foo" / "rtl" / "foo.v"])
    monkeypatch.setattr(sigeq, "include_dirs", lambda d, root: [])
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RTL.replace("a & b", "a | b"), "change")
    assert _run(repo, "--old", base) == 1
    out = capsys.readouterr().out
    assert "DIFF" in out and "不同 2" in out, out


@needs_iverilog
def test_mutant_must_be_caught(repo, monkeypatch, capsys):
    monkeypatch.setattr(sigeq, "rtl_candidates", lambda d, root: [root / "designs" / "foo" / "rtl" / "foo.v"])
    monkeypatch.setattr(sigeq, "include_dirs", lambda d, root: [])
    assert _run(repo, "--old", "HEAD", "--mutate", "designs/foo/rtl/foo.v::a & b::a ^ b") == 0
    out = capsys.readouterr().out
    assert "改了 2 行" in out and "被抓到" in out, out


def test_mutant_pattern_must_match_exactly_once(tmp_path):
    f = tmp_path / "x.v"
    f.write_text("a & b; a & b;\n")
    with pytest.raises(SystemExit, match="出现 2 次"):
        sigeq.mutate(tmp_path, "x.v::a & b::a | b")


@needs_iverilog
def test_missing_signature_is_a_problem(repo, monkeypatch, capsys):
    monkeypatch.setattr(sigeq, "rtl_candidates", lambda d, root: [root / "designs" / "foo" / "rtl" / "foo.v"])
    monkeypatch.setattr(sigeq, "include_dirs", lambda d, root: [])
    tb = repo / "designs" / "foo" / "tb" / "tb_foo.sv"
    tb.write_text(TB.replace("parameter SIGOK = 1", "parameter SIGOK = 0"))
    assert _run(repo, "--old", "HEAD") == 1
    assert "没有 sig=" in capsys.readouterr().out


@needs_iverilog
def test_real_source_resolution(repo, capsys):
    """不打桩：源文件经 flow.paths.rtl_candidates 从导出树取（本根 rtl/*.v）。"""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, RTL.replace("a & b", "a | b"), "change")
    assert _run(repo, "--old", base) == 1
    assert "不同 2" in capsys.readouterr().out


def test_export_takes_every_design_tree_and_tolerates_missing_ones(tmp_path):
    """export 按 DESIGN_TREES 导出；某棵树在该提交里不存在时跳过而不是让 git archive 失败（内部#305）。
    ip_designs/ 不是设计树（2026-10-15 搬回），里面的文件不导出。"""
    r = tmp_path / "r"
    for rel in ("designs/foo/rtl/foo.v", "ip_designs/bar/rtl/bar.v", "flow/y.py"):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text("// x\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")                    # 没有 cbb/ 这棵树
    dest = tmp_path / "out"
    sigeq.export(r, "HEAD", dest)
    got = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*.v"))
    assert got == ["designs/foo/rtl/foo.v"]
    assert not (dest / "flow").exists()


