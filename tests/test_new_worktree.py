"""并行开发用的 worktree 不得让任何工作区变脏（parallel-worktree spec）。

为什么值得有这个测试：`run_experiment.py` 的脏树守卫把 `git status --porcelain`
的任何条目（`results/experiments.jsonl` 除外）都当成没提交的代码，拒绝写记录。
2026-09-27 实测过两处 worktree 带来的未跟踪条目：放在 `.claude/worktrees/` 下的
worktree 让**主工作区**出现 `?? .claude/worktrees/`，拦下 main 上所有设计的实验；
worktree 里软链的 `.venv` 不被 `.venv/`（带斜杠只匹配目录）忽略，拦下**它自己**
的实验。两处都不会报错，只会在跑实验时撞上守卫。

夹具是一个**独立的最小 git 仓**，带着本仓真实的 `.gitignore` 和脚本 —— 被测的
正是这两个文件，拿本仓自己建 worktree 会在测试之外留下分支。
"""
import os
import shutil
import subprocess

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "new_worktree.sh"
HEAL = REPO_ROOT / "scripts" / "heal_hooks_path.sh"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def _porcelain(repo):
    return _git(repo, "status", "--porcelain")


def _fixture_repo(tmp_path):
    """本仓的 .gitignore 与脚本 + 一个假的 .venv（有 bin/python3 即可）+ 一次提交，分支 main。"""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(REPO_ROOT / ".gitignore", repo / ".gitignore")
    if SCRIPT.exists():
        shutil.copy(SCRIPT, repo / "scripts" / "new_worktree.sh")
    if HEAL.exists():
        shutil.copy(HEAL, repo / "scripts" / "heal_hooks_path.sh")
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python3").write_text("")
    (repo / ".venv" / "bin" / "python3").chmod(0o755)
    (repo / "README").write_text("x\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)
    # 本仓的 pre-push 钩子靠 core.hooksPath 挂载（guardrail-scope「挂载状态」），夹具照真仓配上
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
    assert _porcelain(repo) == "", "夹具本身必须是干净的，否则后面的断言没有意义"
    return repo


def _run(repo, name, cwd=None):
    return subprocess.run([str(repo / "scripts" / "new_worktree.sh"), name],
                          cwd=str(cwd or repo), capture_output=True, text=True)


def test_worktree_in_default_location_keeps_main_clean(tmp_path):
    repo = _fixture_repo(tmp_path)
    _git(repo, "worktree", "add", "-q", "-b", "worktree-foo",
         str(repo / ".claude" / "worktrees" / "foo"))
    assert _porcelain(repo) == ""


def test_symlinked_venv_keeps_worktree_clean(tmp_path):
    repo = _fixture_repo(tmp_path)
    wt = repo / ".claude" / "worktrees" / "foo"
    _git(repo, "worktree", "add", "-q", "-b", "worktree-foo", str(wt))
    (wt / ".venv").symlink_to(repo / ".venv")
    assert _porcelain(wt) == ""


def test_script_creates_linked_clean_worktree(tmp_path):
    repo = _fixture_repo(tmp_path)
    r = _run(repo, "foo")
    assert r.returncode == 0, r.stdout + r.stderr
    wt = repo / ".claude" / "worktrees" / "foo"
    assert _git(wt, "branch", "--show-current").strip() == "worktree-foo"
    assert _git(wt, "rev-parse", "HEAD") == _git(repo, "rev-parse", "main")
    assert (wt / ".venv").is_symlink()
    assert (wt / ".venv").resolve() == (repo / ".venv").resolve()
    assert _porcelain(repo) == ""
    assert _porcelain(wt) == ""


def test_script_is_idempotent_on_existing_worktree(tmp_path):
    """Claude Code 的 worktree 功能建的 worktree 没有 .venv：对它再跑一次脚本只补软链。"""
    repo = _fixture_repo(tmp_path)
    wt = repo / ".claude" / "worktrees" / "foo"
    _git(repo, "worktree", "add", "-q", "-b", "worktree-foo", str(wt))
    r = _run(repo, "foo")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (wt / ".venv").is_symlink()
    r = _run(repo, "foo", cwd=wt)  # 从 worktree 里面跑也认得主仓
    assert r.returncode == 0, r.stdout + r.stderr
    assert (wt / ".venv").resolve() == (repo / ".venv").resolve()
    assert _porcelain(wt) == ""


def test_script_fails_and_lists_entries_when_main_is_dirty(tmp_path):
    repo = _fixture_repo(tmp_path)
    (repo / "stray.v").write_text("")
    r = _run(repo, "foo")
    assert r.returncode != 0
    assert "stray.v" in r.stdout + r.stderr


def test_script_rejects_bad_name(tmp_path):
    repo = _fixture_repo(tmp_path)
    r = _run(repo, "../escape")
    assert r.returncode != 0
    assert not (repo.parent / "escape").exists()


# ---- 指定基线与占用诊断（design-verify-branches，内部#80）----
# 设计与验证分属两条分支以后，两边的工作区都可能留着对方不知道的未提交成果；
# 脚本自动「修正」分支或工作区，等于替其中一方丢掉成果。所以凡是不符一律报错、不动现场。

_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def _run_args(repo, *args, cwd=None):
    return subprocess.run([str(repo / "scripts" / "new_worktree.sh"), *args],
                          cwd=str(cwd or repo), capture_output=True, text=True)


def _side_commit(repo, branch):
    """在 main 之外的一条分支上做一次提交，返回提交号；仓库回到 main。"""
    _git(repo, "checkout", "-q", "-b", branch)
    (repo / f"{branch}.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=_ENV)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", branch], check=True, env=_ENV)
    sha = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "main")
    return sha


def _state(repo):
    """分支表 + 工作区表：报错的用例要求这两样都不变。"""
    return (_git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
            _git(repo, "worktree", "list", "--porcelain"))


def test_base_creates_the_branch_at_that_commit(tmp_path):
    repo = _fixture_repo(tmp_path)
    sha = _side_commit(repo, "design")
    r = _run_args(repo, "--base", sha, "v")
    assert r.returncode == 0, r.stdout + r.stderr
    wt = repo / ".claude" / "worktrees" / "v"
    assert _git(wt, "rev-parse", "HEAD").strip() == sha
    assert _git(wt, "branch", "--show-current").strip() == "worktree-v"


def test_unresolvable_base_fails_without_creating_anything(tmp_path):
    repo = _fixture_repo(tmp_path)
    before = _state(repo)
    r = _run_args(repo, "--base", "no-such-ref", "v")
    assert r.returncode != 0, r.stdout + r.stderr
    assert "no-such-ref" in r.stdout + r.stderr
    assert _state(repo) == before
    assert not (repo / ".claude" / "worktrees" / "v").exists()


def test_existing_worktree_on_another_branch_fails_untouched(tmp_path):
    repo = _fixture_repo(tmp_path)
    wt = repo / ".claude" / "worktrees" / "v"
    _git(repo, "worktree", "add", "-q", "-b", "worktree-other", str(wt))
    before = _state(repo)
    r = _run_args(repo, "v")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "worktree-other" in out, out
    assert not (wt / ".venv").exists(), "分支不对时不得补 .venv"
    assert _state(repo) == before


def test_base_with_an_existing_branch_fails_and_keeps_the_branch(tmp_path):
    repo = _fixture_repo(tmp_path)
    sha = _side_commit(repo, "design")
    _git(repo, "branch", "worktree-v", "main")
    before = _state(repo)
    r = _run_args(repo, "--base", sha, "v")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "worktree-v" in out, out
    assert _state(repo) == before
    assert not (repo / ".claude" / "worktrees" / "v").exists()


def test_branch_checked_out_elsewhere_names_that_worktree(tmp_path):
    """占着分支的工作区可能在 .claude/worktrees/ 之外（如 codex 的工作区）。"""
    repo = _fixture_repo(tmp_path)
    elsewhere = tmp_path / "codex" / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "worktree-v", str(elsewhere))
    before = _state(repo)
    r = _run_args(repo, "v")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert str(elsewhere) in out, out
    assert _state(repo) == before
    assert not (repo / ".claude" / "worktrees" / "v").exists()


def test_help_prints_usage_and_creates_nothing(tmp_path):
    """内部#82：`--help` 曾被当成名字，建出 .claude/worktrees/--help。"""
    repo = _fixture_repo(tmp_path)
    before = _state(repo)
    for flag in ("--help", "-h"):
        r = _run_args(repo, flag)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "--base" in r.stdout, r.stdout
    assert _state(repo) == before
    assert not (repo / ".claude" / "worktrees").exists()


def test_name_starting_with_dash_is_rejected(tmp_path):
    repo = _fixture_repo(tmp_path)
    before = _state(repo)
    r = _run_args(repo, "-x")
    assert r.returncode != 0, r.stdout + r.stderr
    assert _state(repo) == before
    assert not (repo / ".claude" / "worktrees").exists()


@pytest.mark.parametrize("hooks,ok", [(None, False), (".githooks", True), ("ABS", False), ("/elsewhere/hooks", False)])
def test_hooks_path_must_point_to_githooks(tmp_path, hooks, ok):
    """内部#254 C：pre-push 钩子没挂上时建 worktree 要报出来，不让「钩子没跑」与「跑了且通过」看起来一样。

    夹具里没有 .githooks/pre-push，自愈不动手，这里只测核查那一步。绝对路径也拒（内部#417：工作区改名后悬空）。"""
    repo = _fixture_repo(tmp_path)
    if hooks is None:
        _git(repo, "config", "--unset", "core.hooksPath")
    else:
        _git(repo, "config", "core.hooksPath", str(repo / ".githooks") if hooks == "ABS" else hooks)
    r = _run(repo, "wt_hooks")
    assert (r.returncode == 0) == ok, f"core.hooksPath={hooks}：退出码 {r.returncode}\n" + r.stdout + r.stderr
    if not ok:
        assert "git config core.hooksPath .githooks" in r.stderr, r.stderr


def _add_pre_push(repo):
    hooks = repo / ".githooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    (hooks / "pre-push").chmod(0o755)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "hooks"], check=True, env=env)


def test_stale_absolute_hooks_path_is_healed_everywhere(tmp_path):
    """内部#417：工作区改名后 core.hooksPath 的绝对值悬空，公共配置与别的 worktree 的 config.worktree 都要改回 .githooks。

    config.worktree 优先于公共配置，只改公共那份时别的 worktree 照样跳过钩子（10-25 实撞）。"""
    repo = _fixture_repo(tmp_path)
    _add_pre_push(repo)
    stale = str(tmp_path / "old_name" / "repo" / ".githooks")
    _git(repo, "config", "extensions.worktreeConfig", "true")
    _git(repo, "config", "core.hooksPath", stale)
    other = repo / ".claude" / "worktrees" / "other"
    _git(repo, "worktree", "add", "-q", "-b", "worktree-other", str(other))
    _git(other, "config", "--worktree", "core.hooksPath", stale)
    assert _git(other, "config", "core.hooksPath").strip() == stale

    r = _run(repo, "healed")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "已自愈" in r.stdout, r.stdout
    assert _git(repo, "config", "--local", "core.hooksPath").strip() == ".githooks"
    assert _git(other, "config", "core.hooksPath").strip() == ".githooks"
    # git 自己真能找到钩子（不只是配置字符串对）
    run = subprocess.run(["git", "-C", str(other), "hook", "run", "pre-push"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_heal_is_silent_noop_when_already_right_or_no_hooks(tmp_path):
    repo = _fixture_repo(tmp_path)
    # 没有 .githooks/pre-push：不动手（夹具仓、别的仓）
    _git(repo, "config", "core.hooksPath", "/elsewhere/hooks")
    r = subprocess.run([str(HEAL), str(repo)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "", r.stdout + r.stderr
    assert _git(repo, "config", "core.hooksPath").strip() == "/elsewhere/hooks"
    # 值已经对：不写、不打印
    _add_pre_push(repo)
    _git(repo, "config", "core.hooksPath", ".githooks")
    r = subprocess.run([str(HEAL), str(repo)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "", r.stdout + r.stderr


# --- 内部#229：--detach <提交> 一次性模式（评审、外部 agent、按提交跑 fast_check）-------------------

def test_detach_creates_no_branch_and_links_venv(tmp_path):
    repo = _fixture_repo(tmp_path)
    sha = _side_commit(repo, "design")
    heads_before = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    r = _run_args(repo, "--detach", sha, "rv")
    assert r.returncode == 0, r.stdout + r.stderr
    wt = repo / ".claude" / "worktrees" / "rv"
    assert _git(wt, "rev-parse", "HEAD").strip() == sha
    assert _git(wt, "branch", "--show-current").strip() == "", "detach 模式不该检出分支"
    assert _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads") == heads_before, "不该新建分支"
    assert (wt / ".venv").is_symlink()
    assert _porcelain(wt) == "" and _porcelain(repo) == ""
    assert f"git worktree remove {wt}" in r.stdout, "要打印清理命令"


def test_detach_unresolvable_commit_fails_untouched(tmp_path):
    repo = _fixture_repo(tmp_path)
    before = _state(repo)
    r = _run_args(repo, "--detach", "no-such-ref", "rv")
    assert r.returncode != 0
    assert _state(repo) == before
    assert not (repo / ".claude" / "worktrees" / "rv").exists()


def test_detach_existing_path_fails_untouched(tmp_path):
    repo = _fixture_repo(tmp_path)
    assert _run(repo, "rv").returncode == 0
    before = _state(repo)
    r = _run_args(repo, "--detach", "main", "rv")
    assert r.returncode != 0 and "已存在" in r.stderr, r.stderr
    assert _state(repo) == before


def test_detach_with_base_is_rejected(tmp_path):
    repo = _fixture_repo(tmp_path)
    r = _run_args(repo, "--base", "main", "--detach", "main", "rv")
    assert r.returncode != 0


def test_venv_link_is_relative_and_survives_moving_the_workspace(tmp_path):
    """软链写相对路径：工作区目录改名（用户 10-25：工作区目录改名）后 worktree 的 .venv 照样能用。"""
    repo = _fixture_repo(tmp_path)
    r = _run(repo, "foo")
    assert r.returncode == 0, r.stdout + r.stderr
    link = repo / ".claude" / "worktrees" / "foo" / ".venv"
    assert not os.path.isabs(os.readlink(link)), os.readlink(link)
    moved = tmp_path / "renamed"
    repo.rename(moved)
    assert (moved / ".claude" / "worktrees" / "foo" / ".venv" / "bin" / "python3").is_file()
