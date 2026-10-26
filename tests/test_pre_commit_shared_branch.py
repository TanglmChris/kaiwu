"""pre-commit：同一分支被两个 worktree 检出时拒绝提交（内部#374）。

夹具是临时 git 仓库，core.hooksPath 指向本仓的 .githooks；第二个 worktree 用 --force 检出同一分支
（git 默认拒绝，事故里就是绕过了这一层）。
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def _git(root, *a, env=None, check=True):
    return subprocess.run(["git", *a], cwd=root, check=check, capture_output=True, text=True, env={**_ENV, **(env or {})})


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "core.hooksPath", str(REPO_ROOT / ".githooks"))
    (root / "a.txt").write_text("a\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-qm", "base", "--no-verify")
    _git(root, "branch", "design")
    return root, tmp_path


def _commit(wt, name, env=None):
    (wt / name).write_text("x\n")
    _git(wt, "add", name)
    return _git(wt, "commit", "-qm", name, env=env, check=False)


def test_own_branch_commits(repo):
    root, tmp = repo
    _git(root, "worktree", "add", "-q", str(tmp / "spec"), "-b", "spec", "design")
    r = _commit(tmp / "spec", "s.txt")
    assert r.returncode == 0, r.stderr


def test_a_branch_checked_out_twice_is_refused(repo):
    root, tmp = repo
    _git(root, "worktree", "add", "-q", str(tmp / "d1"), "design")
    _git(root, "worktree", "add", "-q", "--force", str(tmp / "d2"), "design")
    r = _commit(tmp / "d2", "d.txt")
    assert r.returncode != 0 and "拒绝提交" in r.stderr and str(tmp / "d1") in r.stderr, r.stderr
    assert "KAIWU_ALLOW_SHARED_BRANCH=1" in r.stderr, "没给出具名放行开关\n" + r.stderr


def test_the_named_switch_lets_it_through(repo):
    root, tmp = repo
    _git(root, "worktree", "add", "-q", str(tmp / "d1"), "design")
    _git(root, "worktree", "add", "-q", "--force", str(tmp / "d2"), "design")
    r = _commit(tmp / "d2", "d.txt", env={"KAIWU_ALLOW_SHARED_BRANCH": "1"})
    assert r.returncode == 0 and "放行" in r.stderr, r.stderr


def test_detached_head_is_not_checked(repo):
    root, tmp = repo
    _git(root, "worktree", "add", "-q", "--detach", str(tmp / "x"), "design")
    r = _commit(tmp / "x", "x.txt")
    assert r.returncode == 0, r.stderr
