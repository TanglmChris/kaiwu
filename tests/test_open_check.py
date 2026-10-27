"""flow/export/open_check.py：开源预检一条命令（open-export-precheck）。

夹具是一个临时 git 仓，白名单随提交走（同 tests/test_leak_scan.py）。快速模式（--quick）只做导出、悬空引用、
死链与 git init；完整模式要建 venv、跑全量 pytest，只在真实仓库上实跑，这里测它的跳过原因核对。
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK = REPO_ROOT / "flow" / "export" / "open_check.py"

MANIFEST = """\
include:
  - flow/**
  - cbb/**
exclude:
  - cbb/cbb_secret/**
rules:
  block:
    - name: secret-name
      pattern: '\\bsecret_ip\\b'
  warn:
    - name: issue-ref
      pattern: '#\\d+'
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    files = {"flow/export/manifest.yaml": MANIFEST,
             "cbb/cbb_secret/tb/secret_regress.py": "pass\n",
             "results/x/experiments.jsonl": "{}\n",
             "cbb/cbb_open/rtl/open_core.v": "module open_core; endmodule\n",
             **files}
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _check(repo, out, *args):
    return subprocess.run([sys.executable, str(CHECK), "--repo", str(repo), "--ref", "HEAD",
                           "--out", str(out), "--quick", *args], capture_output=True, text=True)


DOC = ("见 cbb/cbb_secret/tb/secret_regress.py\n"
       "跑 secret_regress.py 即可\n"
       "记录在 results/x/experiments.jsonl\n"
       "白名单 flow/export/manifest.yaml 永远闭源\n")


def test_dangling_references_are_listed_as_warn(tmp_path):
    repo = _repo(tmp_path, {"flow/a.md": DOC})
    r = _check(repo, tmp_path / "out")
    assert "warn  悬空引用" in r.stdout, r.stdout + r.stderr
    for no in (1, 2, 3):
        assert f"flow/a.md:{no}:" in r.stdout
    assert "flow/a.md:4:" not in r.stdout          # 白名单本身永远闭源，引用它是有意的
    assert r.returncode == 0


def test_dead_links_are_listed_as_warn_and_placeholders_skipped(tmp_path):
    repo = _repo(tmp_path, {"flow/b.md": "[a](missing.md) 与 [b](doc/<图名>.svg) 与 [c](../flow/b.md)\n"})
    r = _check(repo, tmp_path / "out")
    assert "flow/b.md:1: missing.md" in r.stdout, r.stdout + r.stderr
    assert "warn  死链" in r.stdout
    assert "<图名>" not in r.stdout
    assert r.returncode == 0


def test_export_failure_fails_and_stops(tmp_path):
    repo = _repo(tmp_path, {"flow/c.md": "secret_ip here\n"})
    out = tmp_path / "out"
    r = _check(repo, out)
    assert "FAIL  导出" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 1
    assert not (out / ".git").exists()


def test_quick_mode_leaves_a_git_repo_on_main(tmp_path):
    repo = _repo(tmp_path, {"flow/d.md": "ok\n"})
    out = tmp_path / "out"
    r = _check(repo, out)
    branch = subprocess.run(["git", "-C", str(out), "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip() if out.exists() else ""
    count = subprocess.run(["git", "-C", str(out), "rev-list", "--count", "HEAD"],
                           capture_output=True, text=True).stdout.strip() if out.exists() else ""
    assert (branch, count) == ("main", "1"), (branch, count, r.stdout + r.stderr)
    assert r.returncode == 0


# ---- 完整模式：pytest 跳过原因核对（open-export-precheck 1.2）----
# 样本照真实输出造：冻结 861502a3 的导出目录里 pytest -rs 的 short test summary 原样。

SKIPS_OK = """\
=========================== short test summary info ============================
SKIPPED [5] tests/test_fail_record.py:25: 没有 results/<设计根>/experiments.jsonl：记录闭源，不在导出集合（open-export「导出结果自足」）
SKIPPED [1] tests/test_team_layout.py:42: 没有 flow/export/manifest.yaml：白名单闭源，不在导出集合（open-export「导出结果自足」）
991 passed, 6 skipped, 2 warnings in 421.03s (0:07:01)
"""


def test_skip_reasons_only_allow_closed_files():
    sys.path.insert(0, str(REPO_ROOT / "flow" / "export"))
    import open_check
    bad_line = "SKIPPED [1] tests/test_x.py:3: verilator not on PATH"
    assert hasattr(open_check, "skip_reasons"), f"open_check 没有 skip_reasons，判不出 {bad_line}"
    ok, bad = open_check.skip_reasons(SKIPS_OK)
    assert (ok, bad) == (True, []), bad
    ok, bad = open_check.skip_reasons(SKIPS_OK.replace("991 passed", bad_line + "\n991 passed"))
    assert not ok and bad == ["tests/test_x.py:3: verilator not on PATH"], bad


def test_links_inside_inline_code_are_not_links(tmp_path):
    # 规格里拿链接当例子时写在反引号里，Markdown 不渲染成链接，不算死链（open-export / repo-layout 主规格里各有一处）
    repo = _repo(tmp_path, {"flow/e.md": "例子：`[a](missing.md)` 与 `![框图](doc/top.svg)`，真链接 [b](gone.md)\n"})
    r = _check(repo, tmp_path / "out")
    assert "flow/e.md:1: gone.md" in r.stdout, r.stdout + r.stderr
    assert "missing.md" not in r.stdout and "doc/top.svg" not in r.stdout, r.stdout
