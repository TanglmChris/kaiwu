"""flow/export/leak_ratchet.py：开源集合的泄漏只许减少（内部#365，leak-ratchet）。

夹具照 tests/test_leak_scan.py：临时 git 仓，清单随提交走，名字都是造的（secret_ip）。
main 上一个提交带基线，再从它拉一个分支改。
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RATCHET = REPO_ROOT / "flow" / "export" / "leak_ratchet.py"

MANIFEST = """\
include:
  - flow/**
  - tests/**
rules:
  block:
    - name: secret-name
      pattern: '\\bsecret_ip\\b'
      ignore_case: true
  warn:
    - name: issue-ref
      pattern: '#\\d+'
"""


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _write(repo, files):
    for rel, text in files.items():
        p = repo / rel
        if text is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c")


def _repo(tmp_path, baseline="2\n"):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    files = {"flow/export/manifest.yaml": MANIFEST,
             "tests/test_a.py": "x = 'secret_ip'\ny = 'SECRET_IP'  # 1\n",   # 2 处 block、1 处 warn
             "flow/ok.py": "x = 1\n"}
    if baseline is not None:
        files["flow/export/leak_baseline.txt"] = "# 开源集合 block 命中数的上限（#365）\n" + baseline
    _write(repo, files)
    _git(repo, "switch", "-q", "-c", "feature")
    return repo


def _run(repo, *args):
    return subprocess.run([sys.executable, str(RATCHET), "--repo", str(repo), *args],
                          capture_output=True, text=True)


def test_at_baseline_passes(tmp_path):
    r = _run(_repo(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "block 命中 2 处，基线 2" in r.stdout


def test_new_hits_fail_with_file_counts_but_no_text(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_b.py": "a = 'secret_ip'\nb = 'secret_ip secret_ip'\n",
                  "flow/ok.py": "x = 1  # secret_ip\n"})
    r = _run(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "block 命中 6 处，超过基线 2" in out
    assert "tests/test_b.py +3" in out and "flow/ok.py +1" in out
    assert "tests/test_a.py" not in out          # 没变的文件不列
    assert "secret_ip" not in out.lower().replace("secret-name", "")  # 不打印命中的原文


def test_below_baseline_passes_and_hints(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_a.py": "x = 'clean'\n"})
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "block 命中 0 处，基线 2" in r.stdout
    assert "可以把基线调到 0" in r.stdout


def test_raising_baseline_on_branch_fails(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, {"flow/export/leak_baseline.txt": "5\n", "tests/test_b.py": "secret_ip\n"})
    r = _run(repo)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "基线只许调低" in r.stdout + r.stderr and "2 → 5" in r.stdout + r.stderr


def test_lowering_baseline_on_branch_passes(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, {"flow/export/leak_baseline.txt": "0\n", "tests/test_a.py": "x = 1\n"})
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_baseline_on_merge_base_only_checks_cap(tmp_path):
    repo = _repo(tmp_path, baseline=None)
    _write(repo, {"flow/export/leak_baseline.txt": "2\n"})
    r = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_on_both_sides_exits_2(tmp_path):
    """merge-base 与 HEAD 上都没有基线（夹具仓、门禁进 main 之前）：退出 2，fast_check 记未执行。"""
    repo = _repo(tmp_path, baseline=None)
    r = _run(repo)
    assert r.returncode == 2 and "leak_baseline.txt" in r.stderr


def test_bad_baseline_on_branch_fails(tmp_path):
    """merge-base 上基线有效、分支上写坏：判失败（不能变成「未执行」）；两边都没有效基线时退出 2。"""
    repo = _repo(tmp_path)
    _write(repo, {"flow/export/leak_baseline.txt": "many\n"})
    r = _run(repo)
    assert r.returncode == 1 and "leak_baseline.txt" in r.stdout, r.stdout + r.stderr
    (tmp_path / "z").mkdir()
    repo2 = _repo(tmp_path / "z", baseline=None)
    _write(repo2, {"flow/export/leak_baseline.txt": "many\n"})
    r = _run(repo2)
    assert r.returncode == 2 and "leak_baseline.txt" in r.stderr


def test_repo_baseline_matches_main_at_introduction():
    """本仓的基线文件存在且是一个非负整数（取 10-20 main 的现值，清理后只许往下调）。"""
    lines = [l for l in (REPO_ROOT / "flow" / "export" / "leak_baseline.txt").read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    assert len(lines) == 1 and lines[0].strip().isdigit()


def test_deleting_baseline_or_manifest_on_branch_fails(tmp_path):
    """merge-base 上有基线 / 清单、分支上删掉了：判失败，不能靠删文件把门禁变成「未执行」（layout 10-20 复核的漏洞 D）。"""
    repo = _repo(tmp_path)
    _write(repo, {"flow/export/leak_baseline.txt": None})
    r = _run(repo)
    assert r.returncode == 1 and "leak_baseline.txt" in r.stdout + r.stderr, r.stdout + r.stderr
    (tmp_path / "y").mkdir()
    repo2 = _repo(tmp_path / "y")
    _write(repo2, {"flow/export/manifest.yaml": None})
    r = _run(repo2)
    assert r.returncode == 1 and "manifest" in r.stdout + r.stderr, r.stdout + r.stderr
