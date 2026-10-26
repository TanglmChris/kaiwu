"""推 main 前的合并检查（scripts/merge_check.py）与 fast_check.sh --rev（内部#344，merge-check-script）。

夹具是一个临时 git 仓库：scripts/fast_check.sh 是桩（退出码取仓内 fc_rc 文件），tests/ 下几条真 pytest 用例，
.venv 软链到本仓的 .venv（与 scripts/new_worktree.sh 建的 worktree 同一形态）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MERGE_CHECK = REPO_ROOT / "scripts" / "merge_check.py"
_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}

STUB_FC = "#!/bin/sh\necho 'stub fast_check'\n[ -n \"$FC_LOG\" ] && echo \"run $*\" >> \"$FC_LOG\"\nexit $(cat fc_rc)\n"
TESTS = "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n"


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True, env=_ENV).stdout.strip()


def _commit(root, msg):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / ".gitignore").write_text(".venv\n")
    (root / ".venv").symlink_to(REPO_ROOT / ".venv")
    fc = root / "scripts" / "fast_check.sh"
    fc.write_text(STUB_FC)
    fc.chmod(0o755)
    (root / "fc_rc").write_text("0\n")
    (root / "tests" / "test_a.py").write_text(TESTS)
    _git(root, "init", "-q", "-b", "main")
    base = _commit(root, "base")
    return root, base


def _run(root, *args, tools="sh", fc_log=None, doc_tests=None):
    env = dict(os.environ, MERGE_CHECK_TOOLS=tools)
    if fc_log:
        env["FC_LOG"] = str(fc_log)
    if doc_tests is not None:
        env["MERGE_CHECK_DOC_TESTS"] = doc_tests
    return subprocess.run([sys.executable, str(MERGE_CHECK), *args], cwd=root, capture_output=True, text=True, env=env)


def _fc_runs(log):
    return log.read_text().count("run") if log.exists() else 0


def test_all_good_exits_zero_with_three_verdicts(repo):
    root, base = repo
    (root / "tests" / "test_b.py").write_text("def test_three():\n    assert True\n")
    head = _commit(root, "add a test")
    r = _run(root, "--base", base, "--head", head)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "fast_check rc=0" in out, out
    assert "pytest 3 passed, 0 failed, 0 skipped" in out, out
    assert "用例 ID 删 0、增 1" in out and "tests/test_b.py::test_three" in out, out


def test_a_deleted_test_fails_and_is_named(repo):
    root, base = repo
    (root / "tests" / "test_a.py").write_text("def test_one():\n    assert True\n")
    head = _commit(root, "drop test_two")
    r = _run(root, "--base", base, "--head", head)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "用例 ID 删 1" in out and "tests/test_a.py::test_two" in out, out


def test_a_failing_fast_check_fails(repo):
    root, base = repo
    (root / "fc_rc").write_text("1\n")
    head = _commit(root, "break fast_check")
    r = _run(root, "--base", base, "--head", head)
    assert r.returncode == 1 and "fast_check rc=1" in r.stdout, r.stdout + r.stderr


def test_a_skipped_test_fails(repo):
    root, base = repo
    (root / "tests" / "test_a.py").write_text(TESTS + "\n\nimport pytest\n\n\n@pytest.mark.skip\ndef test_skip():\n    pass\n")
    head = _commit(root, "add a skipped test")
    r = _run(root, "--base", base, "--head", head)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "1 skipped" in out, out


def test_missing_tools_fail_naming_them(repo):
    root, base = repo
    r = _run(root, "--base", base, "--head", base, tools="sh no_such_tool_xyz")
    out = r.stdout + r.stderr
    assert r.returncode == 2 and "no_such_tool_xyz" in out, out


def test_no_temporary_worktree_is_left_behind(repo):
    root, base = repo
    _run(root, "--base", base, "--head", base)
    assert _git(root, "worktree", "list").count("\n") == 0, _git(root, "worktree", "list")


def test_fast_check_rev_runs_that_commits_script(repo):
    """HEAD 上是真 fast_check.sh（带 --rev 分支）与 at_ref.py；--rev 指向 base，里层跑的是 base 的桩。"""
    root, base = repo
    shutil.copy(REPO_ROOT / "scripts" / "fast_check.sh", root / "scripts" / "fast_check.sh")
    shutil.copy(REPO_ROOT / "scripts" / "at_ref.py", root / "scripts" / "at_ref.py")
    _commit(root, "real fast_check")
    r = subprocess.run([str(root / "scripts" / "fast_check.sh"), "--rev", base[:8]], cwd=root,
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert f"ref {base}" in out and "stub fast_check" in out, out


def test_at_ref_removes_checkout_on_sigterm(repo):
    """at_ref 被 SIGTERM 停掉也删临时检出（内部#368：PM 10-19 停 merge_check 后 at_ref_*/wt 留在 worktree list 里）。"""
    import signal
    import time
    root, base = repo
    # 只认 at_ref 的检出路径（…/at_ref_xxxx/wt）：本用例的临时目录名 test_at_ref_… 里也有 at_ref_
    listed = lambda: [l for l in _git(root, "worktree", "list", "--porcelain").splitlines()
                      if l.startswith("worktree ") and "/at_ref_" in l]
    p = subprocess.Popen([sys.executable, str(REPO_ROOT / "scripts" / "at_ref.py"), "--ref", base, "--", "sleep", "60"],
                         cwd=root)
    end = time.monotonic() + 20
    while not listed() and time.monotonic() < end:
        time.sleep(0.1)
    assert listed(), "临时检出应已建好"
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=60) == 128 + signal.SIGTERM
    assert listed() == [], listed()



# ---- 复用通过的结果（merge-check-reuse 1.1，内部#379）----

def test_second_run_reuses_and_skips_the_checks(repo, tmp_path):
    root, base = repo
    (root / "tests" / "test_b.py").write_text("def test_three():\n    assert True\n")
    head = _commit(root, "add a test")
    log = tmp_path / "fc.log"
    first = _run(root, "--base", base, "--head", head, fc_log=log)
    assert first.returncode == 0 and "复用" not in first.stdout, first.stdout + first.stderr
    second = _run(root, "--base", base, "--head", head, fc_log=log)
    out = second.stdout + second.stderr
    assert second.returncode == 0, out
    assert "复用" in out and "pytest 3 passed, 0 failed, 0 skipped" in out, out
    assert _fc_runs(log) == 1, "第二次不该再跑 fast_check"


def test_reuse_works_from_another_worktree(repo, tmp_path):
    root, base = repo
    head = base
    log = tmp_path / "fc.log"
    assert _run(root, "--base", base, "--head", head, fc_log=log).returncode == 0
    other = tmp_path / "other_wt"
    _git(root, "worktree", "add", "-q", "--detach", str(other), base)
    (other / ".venv").symlink_to(REPO_ROOT / ".venv")
    r = _run(other, "--base", base, "--head", head, fc_log=log)
    assert r.returncode == 0 and "复用" in r.stdout + r.stderr, r.stdout + r.stderr
    assert _fc_runs(log) == 1


def test_same_tree_different_commit_is_reused(repo, tmp_path):
    root, base = repo
    log = tmp_path / "fc.log"
    assert _run(root, "--base", base, "--head", base, fc_log=log).returncode == 0
    _git(root, "commit", "-q", "--allow-empty", "-m", "empty")
    head2 = _git(root, "rev-parse", "HEAD")
    r = _run(root, "--base", base, "--head", head2, fc_log=log)
    assert r.returncode == 0 and "复用" in r.stdout + r.stderr, r.stdout + r.stderr


def test_a_failed_result_is_not_reused(repo, tmp_path):
    root, base = repo
    (root / "fc_rc").write_text("1\n")
    head = _commit(root, "break fast_check")
    log = tmp_path / "fc.log"
    assert _run(root, "--base", base, "--head", head, fc_log=log).returncode == 1
    r = _run(root, "--base", base, "--head", head, fc_log=log)
    assert r.returncode == 1 and "复用" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert _fc_runs(log) == 2


def test_no_cache_forces_a_rerun(repo, tmp_path):
    root, base = repo
    log = tmp_path / "fc.log"
    assert _run(root, "--base", base, "--head", base, fc_log=log).returncode == 0
    r = _run(root, "--base", base, "--head", base, "--no-cache", fc_log=log)
    assert r.returncode == 0 and "复用" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert _fc_runs(log) == 2


def test_a_different_tool_set_is_not_reused(repo, tmp_path):
    root, base = repo
    log = tmp_path / "fc.log"
    assert _run(root, "--base", base, "--head", base, fc_log=log).returncode == 0
    r = _run(root, "--base", base, "--head", base, tools="sh git", fc_log=log)
    assert r.returncode == 0 and "复用" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert _fc_runs(log) == 2


# ---- 只改文档走轻量检查（merge-check-reuse 1.2，内部#379）----

DOC_TESTS = "tests/test_doc.py"


@pytest.fixture
def docrepo(repo):
    """base 上多一个只有一条用例的「文档测试」：轻量模式只跑它（1 passed），全量跑全部（3 passed）。"""
    root, _ = repo
    (root / "tests" / "test_doc.py").write_text("def test_doc():\n    assert True\n")
    return root, _commit(root, "doc test")


def _touch(root, rel, text="x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_design_doc_only_runs_the_light_check(docrepo):
    root, base = docrepo
    _touch(root, "designs/x/lrs.X.md")
    head = _commit(root, "doc only")
    r = _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "模式：轻量（只改文档，1 个文件）" in out, out
    assert "pytest 1 passed, 0 failed, 0 skipped" in out, out


def test_a_script_change_runs_the_full_check(docrepo):
    root, base = docrepo
    _touch(root, "docs/toolchain.md")
    _touch(root, "scripts/x.py", "X = 1\n")
    head = _commit(root, "doc and script")
    r = _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "模式：全量" in out and "pytest 3 passed" in out, out


@pytest.mark.parametrize("rel", ["CLAUDE.md", "openspec/specs/x/spec.md", ".claude/skills/x/SKILL.md", "designs/x/params.yaml"])
def test_paths_outside_the_doc_set_run_the_full_check(docrepo, rel):
    root, base = docrepo
    _touch(root, rel)
    head = _commit(root, f"touch {rel}")
    r = _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS)
    out = r.stdout + r.stderr
    assert "模式：全量" in out and "pytest 3 passed" in out, out


def test_a_missing_doc_test_falls_back_to_full(docrepo):
    root, base = docrepo
    _touch(root, "knowledge/x.md")
    head = _commit(root, "doc only")
    r = _run(root, "--base", base, "--head", head, doc_tests="tests/test_doc.py tests/test_gone.py")
    out = r.stdout + r.stderr
    assert "模式：全量" in out and "tests/test_gone.py" in out and "pytest 3 passed" in out, out


def test_full_flag_forces_the_full_check(docrepo):
    root, base = docrepo
    _touch(root, "team/x.md")
    head = _commit(root, "doc only")
    r = _run(root, "--base", base, "--head", head, "--full", doc_tests=DOC_TESTS)
    out = r.stdout + r.stderr
    assert "模式：全量" in out and "pytest 3 passed" in out, out


def test_light_and_full_results_are_kept_apart(docrepo, tmp_path):
    root, base = docrepo
    _touch(root, "cbb/x/spec.X.md")
    head = _commit(root, "doc only")
    log = tmp_path / "fc.log"
    assert _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS, fc_log=log).returncode == 0
    full = _run(root, "--base", base, "--head", head, "--full", doc_tests=DOC_TESTS, fc_log=log)
    assert "复用" not in full.stdout + full.stderr and _fc_runs(log) == 2, full.stdout + full.stderr
    again = _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS, fc_log=log)
    assert "复用" in again.stdout + again.stderr and "模式：轻量" in again.stdout + again.stderr, again.stdout


# 本仓 tests/conftest.py 在 `-n` 时先在主进程里算全部顶层的读入集合；临时检出里没有 runs/.source_sets 缓存，
# 10-20 实测这一步 544 s（最慢的一个顶层 508 s），而四个文档测试串行只要 5 s。所以轻量模式串行跑。
N_LOG_CONFTEST = ("import os\n\n\ndef pytest_configure(config):\n"
                  "    if os.environ.get('N_LOG') and not config.option.collectonly and not hasattr(config, 'workerinput'):\n"
                  "        with open(os.environ['N_LOG'], 'a') as f:\n"
                  "            f.write(f\"{getattr(config.option, 'numprocesses', None)}\\n\")\n")


def test_the_light_check_runs_pytest_serially(docrepo, tmp_path, monkeypatch):
    root, _ = docrepo
    (root / "tests" / "conftest.py").write_text(N_LOG_CONFTEST)
    base = _commit(root, "conftest")
    _touch(root, "designs/x/lrs.X.md")
    head = _commit(root, "doc only")
    log = tmp_path / "n.log"
    monkeypatch.setenv("N_LOG", str(log))
    light = _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS)
    assert "模式：轻量" in light.stdout and log.read_text().split() == ["None"], light.stdout + light.stderr
    log.unlink()
    full = _run(root, "--base", base, "--head", head, "--full", doc_tests=DOC_TESTS)
    assert "模式：全量" in full.stdout and log.read_text().split() not in ([], ["None"]), full.stdout + full.stderr



# ---- 轻量模式不拿 cpu-heavy（merge-check-light-no-lock，内部#440）----
# 桩 keel：acquire 一律失败（锁被别人占着），每次调用记一行。等锁上限压到约 1 秒。

HELD_KEEL = """#!/bin/sh
echo "$*" >> "$STUB_KEEL_LOG"
case "$1 $2" in
  "lock acquire") echo "held by kaiwu-other" >&2; exit 1 ;;
  "lock list") echo '{"leases":[{"resource":"cpu-heavy","holder":"kaiwu-other","note":"regress: /x"}]}' ;;
esac
exit 0
"""


@pytest.fixture
def held(tmp_path, monkeypatch):
    bindir = tmp_path / "keelbin"
    bindir.mkdir()
    k = bindir / "keel"
    k.write_text(HELD_KEEL)
    k.chmod(0o755)
    log = tmp_path / "keel.log"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_KEEL_LOG", str(log))
    monkeypatch.delenv("KAIWU_HEAVY_HELD", raising=False)   # conftest 默认当已持有
    monkeypatch.setenv("KAIWU_WAIT_MIN", "0.02")
    monkeypatch.setenv("KAIWU_MAX_LOAD", "1e9")
    monkeypatch.setenv("KAIWU_MAX_MEM_PRESSURE", "4")
    return log


def test_the_light_check_does_not_wait_for_cpu_heavy(docrepo, held):
    """有人持有 cpu-heavy 时，只改文档的 merge_check 不去拿锁，照常跑完。"""
    root, base = docrepo
    _touch(root, "designs/x/lrs.X.md")
    head = _commit(root, "doc only")
    r = _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS)
    out = r.stdout + r.stderr
    assert "模式：轻量" in out, out
    assert r.returncode == 0, out
    calls = held.read_text() if held.exists() else ""
    assert "lock acquire" not in calls, calls


def test_the_full_check_still_waits_for_cpu_heavy(docrepo, held):
    """同一组提交带 --full：仍排队等锁，等满时限退出 3 并点名持有者。"""
    root, base = docrepo
    _touch(root, "designs/x/lrs.X.md")
    head = _commit(root, "doc only")
    r = _run(root, "--base", base, "--head", head, "--full", doc_tests=DOC_TESTS)
    out = r.stdout + r.stderr
    assert "模式：全量" in out, out
    assert r.returncode == 3, out
    assert "kaiwu-other" in out and "lock acquire" in held.read_text(), out

# ---- 临时检出带上读入集合缓存（merge-check-reuse 1.3，内部#384）----

# 夹具的 conftest 在每次 pytest 起来时记下：是不是只收集、检出里有没有 runs/.source_sets/X.json、内容是什么
CACHE_CONFTEST = ("import os\nfrom pathlib import Path\n\n\ndef pytest_configure(config):\n"
                  "    if os.environ.get('CACHE_LOG') and not hasattr(config, 'workerinput'):\n"
                  "        p = Path('runs/.source_sets/X.json')\n"
                  "        with open(os.environ['CACHE_LOG'], 'a') as f:\n"
                  "            f.write(f\"{'collect' if config.option.collectonly else 'run'} \"\n"
                  "                    f\"{p.read_text().strip() if p.exists() else '-'}\\n\")\n")


@pytest.fixture
def cacherepo(repo, tmp_path, monkeypatch):
    root, _ = repo
    (root / ".gitignore").write_text(".venv\nruns/\n")
    (root / "tests" / "conftest.py").write_text(CACHE_CONFTEST)
    base = _commit(root, "conftest")
    (root / "tests" / "test_b.py").write_text("def test_three():\n    assert True\n")
    head = _commit(root, "head")
    log = tmp_path / "cache.log"
    monkeypatch.setenv("CACHE_LOG", str(log))
    return root, base, head, log


def test_the_head_checkout_gets_the_callers_source_set_cache(cacherepo):
    root, base, head, log = cacherepo
    (root / "runs" / ".source_sets").mkdir(parents=True)
    (root / "runs" / ".source_sets" / "X.json").write_text('{"key": "k"}\n')
    r = _run(root, "--base", base, "--head", head, "--no-cache")
    assert r.returncode == 0, r.stdout + r.stderr
    # 顺序：base 收集、head 跑 pytest、head 收集
    assert log.read_text().splitlines() == ["collect -", 'run {"key": "k"}', 'collect {"key": "k"}'], \
        "head 检出里没有调用方的 runs/.source_sets/X.json（或 base 里也有）：\n" + log.read_text()


def test_no_cache_in_the_caller_still_runs(cacherepo):
    root, base, head, log = cacherepo
    r = _run(root, "--base", base, "--head", head, "--no-cache")
    assert r.returncode == 0 and "pytest 3 passed" in r.stdout, r.stdout + r.stderr
    assert log.read_text().splitlines() == ["collect -", "run -", "collect -"], log.read_text()


# ---- 只改文档时 fast_check 不跑 lint（merge-check-reuse 1.4）----

def test_the_light_check_passes_docs_only_to_fast_check(docrepo, tmp_path):
    root, base = docrepo
    _touch(root, "designs/x/lrs.X.md")
    head = _commit(root, "doc only")
    log = tmp_path / "fc.log"
    light = _run(root, "--base", base, "--head", head, doc_tests=DOC_TESTS, fc_log=log)
    assert "模式：轻量" in light.stdout and log.read_text().split("\n")[0].strip() == "run --docs-only", log.read_text()
    log.unlink()
    full = _run(root, "--base", base, "--head", head, "--full", doc_tests=DOC_TESTS, fc_log=log)
    assert "模式：全量" in full.stdout and log.read_text().strip() == "run", log.read_text()


# ---- 参数化用例 ID 的改名（merge-check-id-renames，内部#385）----

def _param_file(values):
    return ("import pytest\n\n\n@pytest.mark.parametrize(\"x\", " + repr(list(values)) + ")\n"
            "def test_p(x):\n    assert x\n")


def _ids_case(repo, base_vals, head_vals):
    root, _ = repo
    (root / "tests" / "test_p.py").write_text(_param_file(base_vals))
    base = _commit(root, "base params")
    if head_vals is None:
        (root / "tests" / "test_p.py").unlink()
    else:
        (root / "tests" / "test_p.py").write_text(_param_file(head_vals))
    head = _commit(root, "head params")
    r = _run(root, "--base", base, "--head", head, "--no-cache")
    return r, r.stdout + r.stderr


def test_renamed_parametrized_ids_are_not_deletions(repo):
    r, out = _ids_case(repo, ["a1", "b1"], ["a2", "b2"])
    assert r.returncode == 0, out
    assert "删 0、增 0、改名 2" in out, out
    assert "tests/test_p.py::test_p[a1] → tests/test_p.py::test_p[a2]" in out, out


def test_fewer_deletions_than_additions_in_a_function_are_renames(repo):
    r, out = _ids_case(repo, ["a1"], ["a2", "b2"])
    assert r.returncode == 0 and "删 0、增 1、改名 1" in out, out


def test_more_deletions_than_additions_in_a_function_still_fail(repo):
    r, out = _ids_case(repo, ["a1", "b1"], ["a2"])
    assert r.returncode != 0 and "删 2、增 1、改名 0" in out, out
    assert "删  tests/test_p.py::test_p[a1]" in out, out


def test_a_removed_parametrized_function_still_fails(repo):
    r, out = _ids_case(repo, ["a1", "b1"], None)
    assert r.returncode != 0 and "删 2、增 0、改名 0" in out, out


def test_a_rename_across_functions_is_still_a_deletion(repo):
    root, base = repo
    (root / "tests" / "test_a.py").write_text("def test_uno():\n    assert True\n\n\ndef test_two():\n    assert True\n")
    head = _commit(root, "rename function")
    r = _run(root, "--base", base, "--head", head, "--no-cache")
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "改名 0" in out and "删  tests/test_a.py::test_one" in out, out


# ---- 用例跨文件搬家（split-fast-check-toolchain 1.1，内部#336）----

def _move_case(repo, base_files, head_files):
    """base / head 各写一组 tests/<名>.py（值为参数列表）；head 里没列的 base 文件删掉。"""
    root, _ = repo
    for name, vals in base_files.items():
        (root / "tests" / name).write_text(_param_file(vals))
    base = _commit(root, "base files")
    for name in base_files:
        if name not in head_files:
            (root / "tests" / name).unlink()
    for name, text in head_files.items():
        (root / "tests" / name).write_text(text if isinstance(text, str) else _param_file(text))
    head = _commit(root, "head files")
    r = _run(root, "--base", base, "--head", head, "--no-cache")
    return r, r.stdout + r.stderr


def test_ids_moved_to_another_file_are_not_deletions(repo):
    r, out = _move_case(repo, {"test_p.py": ["a1", "b1"]}, {"test_q.py": ["a1", "b1"]})
    assert r.returncode == 0, out
    assert "删 0、增 0、改名 0、搬家 2" in out, out
    assert "搬家  tests/test_p.py::test_p[a1] → tests/test_q.py::test_p[a1]" in out, out


def test_a_move_that_also_renames_the_function_is_a_deletion(repo):
    moved = _param_file(["a1"]).replace("def test_p(", "def test_r(")
    r, out = _move_case(repo, {"test_p.py": ["a1"]}, {"test_q.py": moved})
    assert r.returncode != 0 and "删 1、增 1、改名 0、搬家 0" in out, out


def test_each_added_id_takes_only_one_move(repo):
    r, out = _move_case(repo, {"test_p.py": ["a1"], "test_q.py": ["a1"]}, {"test_r.py": ["a1"]})
    assert r.returncode != 0 and "删 1、增 0、改名 0、搬家 1" in out, out
