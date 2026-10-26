"""flow/equiv/rev_equiv.py：按提交比一个模块（内部#339，add-rev-equiv）。

夹具是一个临时 git 仓库（带本仓的 flow/paths.py），一个带寄存器的小模块，提交序列：
基线 → 只改注释、空白与内部网名 → 加一根中间网 → 寄存器改名 → 改一位逻辑 → 设计根搬目录。
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

pytestmark = [pytest.mark.flow,
              pytest.mark.skipif(shutil.which("yosys") is None, reason="需要 yosys（source ~/tools/env.sh）")]

BASE = """\
module FOO #(parameter W = 4) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [W-1:0] i_a,
    output wire [W-1:0] o_y
);
    reg [W-1:0] acc_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) acc_r <= {W{1'b0}};
        else        acc_r <= acc_r ^ i_a;
    end
    assign o_y = acc_r;
endmodule
"""
# 只改注释、空白、内部网名：text 级判完
STYLE = BASE.replace("    reg [W-1:0] acc_r;\n", "    // 累加寄存器（只改写法）\n    reg  [W-1:0]   state_r;\n").replace(
    "acc_r", "state_r")
# 改表达结构（加一根中间网）：单元创建顺序变了，规整文本不同，落到归纳
RESTRUCT = BASE.replace("    reg [W-1:0] acc_r;\n",
                        "    reg  [W-1:0] acc_r;\n    wire [W-1:0] next_acc_w = acc_r ^ i_a;\n").replace(
                        "acc_r <= acc_r ^ i_a;", "acc_r <= next_acc_w;")
RENAME = BASE.replace("acc_r", "sum_r")
LOGIC = BASE.replace("assign o_y = acc_r;", "assign o_y = acc_r ^ {{(W-1){1'b0}}, 1'b1};")


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("revrepo")
    (root / "flow").mkdir()
    shutil.copy(REPO_ROOT / "flow" / "paths.py", root / "flow" / "paths.py")
    (root / "cbb").mkdir()
    (root / "cbb" / ".keep").write_text("")
    rtl = root / "designs" / "foo" / "rtl"
    rtl.mkdir(parents=True)
    (root / "designs" / "foo" / "params.yaml").write_text("tops:\n  FOO:\n    params:\n      W: {values: [4]}\n")
    _git(root, "init", "-q", "-b", "main")
    shas = {}
    for name, text in (("base", BASE), ("style", STYLE), ("restruct", RESTRUCT), ("rename", RENAME),
                       ("logic", LOGIC)):
        (rtl / "foo.v").write_text(text)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", name)
        shas[name] = _git(root, "rev-parse", "HEAD")
    (rtl / "foo.v").write_text(BASE)
    _git(root, "commit", "-qam", "back to base")
    _git(root, "mv", "designs/foo", "cbb/foo")
    _git(root, "commit", "-qm", "move")
    shas["moved"] = _git(root, "rev-parse", "HEAD")
    return root, shas


def _run(repo, *args):
    root, _ = repo
    r = subprocess.run([sys.executable, str(REPO_ROOT / "flow" / "equiv" / "rev_equiv.py"), "--repo", str(root),
                        "--design", "FOO", "--top", "FOO", *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_style_only_change_is_text_equivalent_with_negative_control(repo):
    _, s = repo
    rc, out = _run(repo, "--gold-ref", s["base"], "--gate-ref", s["style"])
    assert rc == 0, out
    assert "EQUIV(text)" in out, out
    assert "neg:" in out and "判不等" in out, out


def test_restructured_expression_falls_through_to_induction(repo):
    """加中间网改了单元的创建顺序，text 级判不同；auto 落到归纳并证明等价（text 级的边界，design D3）。"""
    _, s = repo
    rc, out = _run(repo, "--gold-ref", s["base"], "--gate-ref", s["restruct"])
    assert rc == 0, out
    assert "text: 不同" in out and "EQUIV(induct" in out, out


def test_register_rename_is_proved_by_induction(repo):
    _, s = repo
    rc, out = _run(repo, "--gold-ref", s["base"], "--gate-ref", s["rename"], "--mode", "induct")
    assert rc == 0, out
    assert "self: gold ≡ gold 证明" in out and "EQUIV(induct" in out, out


def test_logic_change_is_not_equivalent(repo):
    _, s = repo
    rc, out = _run(repo, "--gold-ref", s["base"], "--gate-ref", s["logic"])
    assert rc == 1, out
    assert "结论 EQUIV" not in out and "NOT EQUIV" in out, out


def test_moved_design_root_is_compared_by_each_commits_own_rules(repo):
    _, s = repo
    rc, out = _run(repo, "--gold-ref", s["base"], "--gate-ref", s["moved"])
    assert rc == 0, out
    assert "EQUIV(text)" in out, out


def test_unknown_ref_is_a_usage_error(repo):
    rc, out = _run(repo, "--gold-ref", "no-such-ref", "--gate-ref", "HEAD")
    assert rc == 2, out
    assert "no-such-ref" in out, out


def test_a_toothless_negative_control_fails_the_run(repo, monkeypatch, capsys):
    """负对照失效（翻转掩码桩成 0，gate 原样）时整次运行判自检失败，不给等价结论。"""
    root, s = repo
    from flow.equiv import rev_equiv
    monkeypatch.setattr(rev_equiv, "NEG_FLIP", 0)
    rc = rev_equiv.main(["--repo", str(root), "--design", "FOO", "--top", "FOO",
                         "--gold-ref", s["base"], "--gate-ref", s["style"]])
    out = capsys.readouterr().out
    assert rc == 3, out
    assert "判据失效" in out, out
