"""fast_check 同一份内容只检查一次（内部#382，budget-renew-fast-check-load 1.3）。

夹具沿用 tests/test_fast_check.py 的最小仓（真 fast_check.sh），另拷 flow/check/fc_cache.py；iverilog / verilator 是
放在仓外的桩，每调一次记一行到 STUB_LOG，用来看第二次是不是真的没跑检查。
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from fast_check_fixture import GOOD_PARAMS, REPO_ROOT, STUB_OK, _VENV_BIN, _ensure_git, _fixture_repo, _git

FC_CACHE = REPO_ROOT / "flow" / "check" / "fc_cache.py"
LOG_LINE = 'echo "$(basename "$0")" >> "$STUB_LOG"\n'
VERILATOR = "#!/bin/sh\n" + LOG_LINE + '[ -n "$STUB_FAIL" ] && [ -f "$STUB_FAIL" ] && { echo "%Warning-UNUSED: stub" >&2; exit 1; }\nexit 0\n'


@pytest.fixture
def fx(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    script = _fixture_repo(root, GOOD_PARAMS)
    (root / ".gitignore").write_text("__pycache__/\n")
    if FC_CACHE.exists():   # 没有它时 fast_check 照常全跑：红臂就是「第二次没复用」
        shutil.copy(FC_CACHE, root / "flow" / "check" / "fc_cache.py")
    _ensure_git(script)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in (("iverilog", STUB_OK.replace("#!/bin/sh\n", "#!/bin/sh\n" + LOG_LINE, 1)), ("verilator", VERILATOR)):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    log = tmp_path / "tools.log"
    env = dict(os.environ, PATH=f"{bindir}:{_VENV_BIN}:/usr/bin:/bin:/usr/sbin:/sbin", STUB_LOG=str(log),
               STUB_FAIL=str(tmp_path / "fail"))
    env.pop("FAST_CHECK_ALLOW_MISSING_TOOLS", None)
    env.pop("FAST_CHECK_NO_CACHE", None)
    return root, bindir, log, env, tmp_path


def _run(root, env, *args, **extra):
    return subprocess.run([str(root / "scripts" / "fast_check.sh"), *args], cwd=root, capture_output=True, text=True,
                          env=dict(env, **extra))


def _calls(log):
    return len(log.read_text().splitlines()) if log.exists() else 0


def _summary(out):
    return [l for l in out.splitlines() if l.startswith(("  已执行", "  未执行"))]


def test_second_run_reuses_and_runs_no_tools(fx):
    root, _, log, env, _ = fx
    first = _run(root, env)
    assert first.returncode == 0 and "复用" not in first.stdout, first.stdout
    n = _calls(log)
    assert n > 0, "夹具失效：第一次没调桩工具"
    again = _run(root, env)
    assert again.returncode == 0, again.stdout
    assert "复用" in again.stdout and "覆盖摘要" in again.stdout, again.stdout
    assert _summary(again.stdout) == _summary(first.stdout), "复用打印的覆盖摘要与当时不同"
    assert _calls(log) == n, "复用时不该再调 iverilog / verilator"


def test_another_worktree_reuses_it_too(fx):
    root, _, log, env, tmp = fx
    assert _run(root, env).returncode == 0
    n = _calls(log)
    wt = tmp / "wt2"
    _git(root, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    r = subprocess.run([str(wt / "scripts" / "fast_check.sh")], cwd=wt, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "复用" in r.stdout and _calls(log) == n, r.stdout


@pytest.mark.parametrize("case", ["dirty", "ignored-stray", "degraded", "no-cache", "tool-changed"])
def test_not_reused_when_inputs_differ_or_tree_is_not_clean(fx, case):
    root, bindir, log, env, _ = fx
    assert _run(root, env).returncode == 0
    n = _calls(log)
    args, extra = [], {}
    if case == "dirty":
        (root / "designs" / "foo" / "lrs.FOO.md").write_text((root / "designs" / "foo" / "lrs.FOO.md").read_text() + "\n")
    elif case == "ignored-stray":
        d = root / "designs" / "foo" / "rtl" / "__pycache__"
        d.mkdir()
        (d / "x.pyc").write_text("x")
    elif case == "degraded":
        extra["FAST_CHECK_ALLOW_MISSING_TOOLS"] = "1"
    elif case == "no-cache":
        args.append("--no-cache")
    elif case == "tool-changed":
        (bindir / "verilator").write_text(VERILATOR + "# 升级了\n")
    r = _run(root, env, *args, **extra)
    assert "复用" not in r.stdout, f"{case}：不该复用\n" + r.stdout
    assert _calls(log) > n, f"{case}：应当真的跑了检查"


def test_a_failed_run_is_not_recorded(fx):
    root, _, log, env, tmp = fx
    (tmp / "fail").write_text("1")
    assert _run(root, env).returncode != 0, "夹具失效：桩 verilator 应让 lint 失败"
    (tmp / "fail").unlink()
    n = _calls(log)
    r = _run(root, env)
    assert r.returncode == 0 and "复用" not in r.stdout and _calls(log) > n, "失败那次被记下来了\n" + r.stdout
    assert "复用" in _run(root, env).stdout


def test_docs_only_and_full_are_kept_apart(fx):
    root, _, log, env, _ = fx
    assert _run(root, env).returncode == 0
    n = _calls(log)
    r = _run(root, env, "--docs-only")
    assert r.returncode == 0 and "复用" not in r.stdout and _calls(log) > n, r.stdout
    assert "复用" in _run(root, env, "--docs-only").stdout


# --- 记录与报告这一项不走缓存（内部#432）------------------------------------------------
# 缓存键是 HEAD 树与 merge-base，而「记录与报告的来源」看的是当前分支名与 HEAD 提交本身：白名单分支
# 推过的同一棵树，快进进一个不在白名单里的分支，复用那次通过就等于跳过了这一项。

SRC = "记录与报告的来源"
REC = "results/foo/experiments.jsonl"


def _commit_record(root, eid):
    """按真实形态加一条记录并提交：git_commit 取写入时的 HEAD（run_experiment 就是这么取的）。"""
    head = _git(root, "rev-parse", "HEAD").strip()
    p = root / REC
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text((p.read_text() if p.exists() else "") + json.dumps(
        {"design": "FOO", "design_root": "foo", "experiment_id": eid, "git_commit": head,
         "timestamp": f"2026-10-26T00:00:{eid[-2:]}"}) + "\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", f"记录 {eid}")


def test_a_reused_pass_still_reports_the_current_branch(fx):
    root, _, log, env, _ = fx
    first = _run(root, env)
    assert first.returncode == 0 and f"当前分支 main" in first.stdout, first.stdout
    _git(root, "checkout", "-q", "-b", "worktree-y")
    again = _run(root, env)
    assert again.returncode == 0 and "复用" in again.stdout, again.stdout
    assert "worktree-y" in again.stdout and "当前分支 main" not in again.stdout, again.stdout


def test_a_reused_pass_does_not_hide_a_squash_that_breaks_provenance(fx):
    """内部#432 的风险臂：键只有树与 merge-base，不看提交历史。cbb_open 上先改一处、再按那个提交写一条记录，
    通过并记下；把它 squash 成 main 上的一个提交（同一棵树、同一个 merge-base）放到另一个分支上，
    记录的 git_commit 已不可达 HEAD —— 复用那次通过就放过了 provenance 断链。"""
    root, _, log, env, _ = fx
    _git(root, "checkout", "-q", "-b", "cbb_open")
    note = root / "designs" / "foo" / "lrs.FOO.md"
    note.write_text(note.read_text() + "\n")
    _git(root, "commit", "-qam", "改一处")
    _commit_record(root, "e01")
    assert _run(root, env).returncode == 0
    tree = _git(root, "rev-parse", "HEAD^{tree}").strip()
    squashed = _git(root, "commit-tree", tree, "-p", "main", "-m", "squash").strip()
    _git(root, "checkout", "-q", "-b", "worktree-z", squashed)
    r = _run(root, env)
    out = r.stdout + r.stderr
    assert "复用" in out, "夹具失效：同一棵树、同一个 merge-base 应命中缓存\n" + out
    assert "FAIL  记录的 git_commit 可达 HEAD" in out, out
    assert r.returncode != 0, out
