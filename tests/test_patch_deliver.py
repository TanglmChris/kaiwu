"""给应用的补丁一步交付并自证可还原（内部#340，design-side-tools 1.2）。

夹具是临时 git 仓，形态照 内部#282：基线 B 上两个 RTL 修复提交 F1、F2（交付范围），之后是 TB 提交 T（不交付）。
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "scripts" / "patch_deliver.py"
_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": "/tmp"}


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True, env=_ENV).stdout.strip()


def _commit(root, files, msg):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    b = _commit(root, {"designs/foo/rtl/foo.v": "module FOO; wire a; endmodule\n",
                       "designs/foo/tb/test_foo.py": "# tb v0\n"}, "base R006")
    _commit(root, {"designs/foo/rtl/foo.v": "module FOO; wire a, b; endmodule\n"}, "fix 1")
    f = _commit(root, {"designs/foo/rtl/bar.v": "module BAR; endmodule\n"}, "fix 2")
    t = _commit(root, {"designs/foo/tb/test_foo.py": "# tb ported from R008\n"}, "tb port")
    return root, b, f, t


def _run(root, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=root, capture_output=True, text=True,
                          env={**_ENV, "PATH": "/usr/bin:/bin"})


def test_two_fix_commits_restore_head_and_leave_a_delivery_note(repo, tmp_path):
    root, b, f, _ = repo
    out = tmp_path / "deliver"
    r = _run(root, "--base", b, "--head", f, "--out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    patches = sorted(out.glob("*.patch"))
    assert len(patches) == 2, patches
    note = (out / "DELIVERY.txt").read_text()
    tree = _git(root, "rev-parse", f"{f}^{{tree}}")
    assert note.count(tree) == 2, note                      # head 的树与还原出的树都写着，且相同
    assert b in note and f in note, note
    for p in patches:
        assert hashlib.sha256(p.read_bytes()).hexdigest() in note, (p, note)
    assert _git(root, "worktree", "list").count("\n") == 0, "临时检出要删掉"


def test_a_plain_merge_in_the_range_still_restores(repo, tmp_path):
    """普通合并不影响：format-patch 不导出合并本身，但会导出合并带进来的提交，排成一条直线照样还原出 head。"""
    root, b, f, _ = repo
    _git(root, "checkout", "-q", "-b", "side", b)
    _commit(root, {"designs/foo/rtl/side.v": "module SIDE; endmodule\n"}, "side change")
    _git(root, "checkout", "-q", "-b", "with_merge", f)
    _git(root, "merge", "-q", "--no-ff", "--no-edit", "side")
    r = _run(root, "--base", b, "--head", _git(root, "rev-parse", "HEAD"), "--out", str(tmp_path / "d"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "合并提交 1 个" in r.stdout, r.stdout


def test_changes_made_inside_a_merge_are_lost_and_caught(repo, tmp_path):
    """合并时另改了内容（不在任何一边的提交里）：补丁里没有这部分，树哈希对不上。"""
    root, b, f, _ = repo
    _git(root, "checkout", "-q", "-b", "side", b)
    _commit(root, {"designs/foo/rtl/side.v": "module SIDE; endmodule\n"}, "side change")
    _git(root, "checkout", "-q", "-b", "with_merge", f)
    _git(root, "merge", "-q", "--no-ff", "--no-commit", "side")
    (root / "designs/foo/rtl/bar.v").write_text("module BAR; wire only_in_merge; endmodule\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "merge with an extra edit")
    head = _git(root, "rev-parse", "HEAD")
    r = _run(root, "--base", b, "--head", head, "--out", str(tmp_path / "d"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert _git(root, "rev-parse", f"{head}^{{tree}}") in r.stdout and "不一致" in r.stdout, r.stdout


def test_patches_that_do_not_apply_fail(repo, tmp_path):
    """解了冲突的合并：两边改了同一行，排成直线后后一个补丁的上下文对不上，打不上。"""
    root, b, f, _ = repo
    _git(root, "checkout", "-q", "-b", "side", b)
    _commit(root, {"designs/foo/rtl/foo.v": "module FOO; wire side; endmodule\n"}, "side edits the same line")
    _git(root, "checkout", "-q", "-b", "with_merge", f)
    subprocess.run(["git", "merge", "-q", "--no-ff", "--no-edit", "side"], cwd=root, capture_output=True, env=_ENV)
    (root / "designs/foo/rtl/foo.v").write_text("module FOO; wire a, b, side; endmodule\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "resolve conflict")
    r = _run(root, "--base", b, "--head", _git(root, "rev-parse", "HEAD"), "--out", str(tmp_path / "d"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "打不上" in r.stdout + r.stderr, r.stdout + r.stderr
    assert _git(root, "worktree", "list").count("\n") == 0, "失败也要删掉临时检出"


def test_existing_out_dir_is_refused(repo, tmp_path):
    root, b, f, _ = repo
    out = tmp_path / "d"
    out.mkdir()
    r = _run(root, "--base", b, "--head", f, "--out", str(out))
    assert r.returncode == 2 and "已存在" in r.stdout + r.stderr, r.stdout + r.stderr


def test_unknown_ref_is_refused(repo, tmp_path):
    root, b, _, _ = repo
    r = _run(root, "--base", b, "--head", "no-such-ref", "--out", str(tmp_path / "d"))
    assert r.returncode == 2 and "no-such-ref" in r.stdout + r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "d").exists()
