"""scripts/release_tag.py：名字与正文格式、各项核对（内部#300）。"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/release_tag.py"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """main 上：spec → design → verify → 集成；另有一个不在 main 上的提交。"""
    remote = tmp_path / "remote.git"
    w = tmp_path / "w"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(w)], check=True)
    git(w, "config", "user.email", "t@t")
    git(w, "config", "user.name", "t")
    shas = {}
    for name in ("spec", "design", "verify", "integ"):
        git(w, "commit", "-q", "--allow-empty", "-m", name)
        shas[name] = git(w, "rev-parse", "HEAD")
    git(w, "remote", "add", "origin", str(remote))
    git(w, "push", "-q", "origin", "main")
    git(w, "fetch", "-q", "origin")
    git(w, "switch", "-q", "-c", "side")
    git(w, "commit", "-q", "--allow-empty", "-m", "side")
    shas["side"] = git(w, "rev-parse", "HEAD")
    git(w, "switch", "-q", "main")
    return w, shas


def run(w, shas, *extra, **over):
    fields = {"commit": shas["integ"], "design": shas["design"], "verify": shas["verify"],
              "spec": shas["spec"], "spec-base": "LRS v1.0 / LLD v1.0",
              "exit": "交付主回归 10/10，fast_check rc=0",
              "issue": "9", "exit-link": "https://example/issues/9#issuecomment-1"}
    fields.update(over)
    argv = ["CBB_FOO", "R006"]
    for k, v in fields.items():
        if v is not None:
            argv += [f"--{k}", v]
    return subprocess.run([sys.executable, str(SCRIPT), *argv, *extra], cwd=w,
                          capture_output=True, text=True)


def test_dry_run_prints_name_and_body_without_tagging(repo):
    w, shas = repo
    r = run(w, shas)
    assert r.returncode == 0, r.stderr
    assert f"tag: cbb_foo-R006 -> {shas['integ']}" in r.stdout
    assert "CBB_FOO R006 可出口" in r.stdout
    assert f"设计提交 {shas['design']}  验证提交 {shas['verify']}" in r.stdout
    assert "发布单 #9，可出口结论 https://example/issues/9#issuecomment-1" in r.stdout
    assert git(w, "tag", "-l") == ""


def test_create_makes_annotated_tag_on_integration_commit(repo):
    w, shas = repo
    r = run(w, shas, "--create")
    assert r.returncode == 0, r.stderr
    assert git(w, "cat-file", "-t", "cbb_foo-R006") == "tag"
    assert git(w, "rev-parse", "cbb_foo-R006^{commit}") == shas["integ"]
    assert "出口判据：交付主回归 10/10" in git(w, "tag", "-l", "-n9", "cbb_foo-R006")
    again = run(w, shas, "--create")
    assert again.returncode == 1 and "本地已有 tag" in again.stderr


def test_existing_remote_tag_refused(repo):
    w, shas = repo
    git(w, "tag", "-a", "cbb_foo-R006", "-m", "x", shas["verify"])
    git(w, "push", "-q", "origin", "cbb_foo-R006")
    git(w, "tag", "-d", "cbb_foo-R006")
    r = run(w, shas)
    assert r.returncode == 1 and "远端 origin 已有 tag" in r.stderr
    assert run(w, shas, "--no-remote").returncode == 0


@pytest.mark.parametrize("over, msg", [
    ({"commit": "side"}, "不在 origin/main 上"),
    ({"commit": "design", "verify": "verify"}, "不包含在集成提交"),
    ({"exit": None}, "--exit 必填"),
    ({"exit-link": None}, "--exit-link 必填"),
])
def test_refusals(repo, over, msg):
    w, shas = repo
    over = {k: shas.get(v, v) if v else v for k, v in over.items()}
    r = run(w, shas, **over)
    assert r.returncode == 1
    assert msg in r.stderr, r.stderr
    assert git(w, "tag", "-l") == ""


@pytest.mark.parametrize("top, rel, msg", [
    ("cbb_foo", "R006", "应为大写"),
    ("CBB_FOO", "R6", "R 加三位数字"),
    ("CBB_FOO", "R009.0", "R 加三位数字"),
    ("CBB_FOO", "R009.1.2", "R 加三位数字"),
    ("CBB_FOO", "R9.1", "R 加三位数字"),
])
def test_name_format(repo, top, rel, msg):
    w, shas = repo
    r = subprocess.run([sys.executable, str(SCRIPT), top, rel, "--commit", shas["integ"],
                        "--issue", "9"], cwd=w, capture_output=True, text=True)
    assert r.returncode == 1 and msg in r.stderr


def test_revision_release_name(repo):
    """修订版 R009.1（内部#303）：名字与正文照常生成。"""
    w, shas = repo
    r = subprocess.run([sys.executable, str(SCRIPT), "CBB_FOO", "R009.1", "--commit", shas["integ"],
                        "--design", shas["design"], "--verify", shas["verify"], "--spec", shas["spec"],
                        "--spec-base", "LRS v1 / LLD v1", "--exit", "x", "--issue", "303",
                        "--exit-link", "https://example/303"], cwd=w, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert f"tag: cbb_foo-R009.1 -> {shas['integ']}" in r.stdout
    assert "CBB_FOO R009.1 可出口" in r.stdout
