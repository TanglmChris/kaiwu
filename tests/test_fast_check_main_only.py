"""`scripts/fast_check.sh` 的用例：记录与报告只在白名单分支上提交，合并不丢行、不断 provenance。

内部#336 从 tests/test_fast_check.py 按小节拆出；内部#422 起由「只许 main」改为白名单（flow/record_branches.yaml），
记录按设计根分文件。夹具在 tests/fast_check_fixture.py。
"""
import json

from fast_check_fixture import *  # noqa: F401,F403


# --- parallel-worktree「秒级护栏必须机械检查记录与报告的来源」与 experiment-record「已提交记录的
# git_commit 必须是 HEAD 的祖先」（内部#422）--------------------------------------------------------
#
# 原来只许 main 的两条理由没变：分支被 rebase / squash 合入后记录的 git_commit 查不到；几个分支往同一个
# 文件末尾追加，手工解冲突最容易丢行改行。现在各 PM 的集成分支就是本 team 的 main，所以按白名单放行，
# 再用「git_commit 可达」与「历史行原样保留」两项把两条理由各自机械化。

SRC = "记录与报告的来源"
HIST = "记录历史行原样保留"
REACH = "记录的 git_commit 可达 HEAD"
MIGRATED = "旧单文件已搬迁"
REC = "results/foo/experiments.jsonl"


def _head(root):
    return _git(root, "rev-parse", "HEAD").strip()


def _rec_line(root, eid):
    """按真实形态造一条记录：git_commit 取写入时的 HEAD（run_experiment 就是这么取的）。"""
    return json.dumps({"design": "FOO", "design_root": "foo", "experiment_id": eid,
                       "git_commit": _head(root), "timestamp": f"2026-10-25T00:00:{eid[-2:]}"}) + "\n"


def _append_commit(root, rel, text, msg=None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text((p.read_text() if p.exists() else "") + text)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg or f"touch {rel}")


def _branch_fixture(tmp_path):
    """main 上已有一条记录与一个 cbb 根，停在非白名单分支 worktree-x 上。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = script.parent.parent
    bar = root / "cbb" / "bar"
    (bar / "rtl").mkdir(parents=True)
    (bar / "rtl" / "bar.v").write_text(_good_rtl("BAR", "cbb/bar/spec.BAR.md"))
    (bar / "params.yaml").write_text(_as_tops(GOOD_PARAMS, "BAR"))
    (bar / "spec.BAR.md").write_text(_good_spec("BAR"))
    _ensure_git(script)
    _append_commit(root, REC, _rec_line(root, "e01"), "main 上的正式记录")
    _git(root, "checkout", "-q", "-b", "worktree-x")
    return script, root


def _out(script):
    r = _run_with_path(script, stub=STUB_OK)
    return r, r.stdout + r.stderr


def test_branch_that_committed_a_new_record_fails(tmp_path):
    script, root = _branch_fixture(tmp_path)
    _append_commit(root, REC, _rec_line(root, "e02"))
    r, out = _out(script)
    assert f"FAIL  {SRC}" in out and REC in out, out
    assert r.returncode != 0, out


@pytest.mark.parametrize("rel", ["cbb/bar/REPORT.BAR.md", "designs/foo/REPORT.FOO.md"])
def test_branch_that_committed_a_report_fails(tmp_path, rel):
    script, root = _branch_fixture(tmp_path)
    _append_commit(root, rel, "# report\n")
    r, out = _out(script)
    assert f"FAIL  {SRC}" in out and rel in out, out
    assert r.returncode != 0, out


def test_branch_that_merged_the_integration_branch_passes(tmp_path):
    """组员把集成分支合进自己的分支：带进来的记录与报告在白名单分支里，不算违规。"""
    script, root = _branch_fixture(tmp_path)
    _git(root, "checkout", "-q", "-b", "cbb_open", "main")
    _append_commit(root, REC, _rec_line(root, "e03"), "集成分支上的正式记录")
    _append_commit(root, "cbb/bar/REPORT.BAR.md", "# report\n", "集成分支上的报告")
    _git(root, "checkout", "-q", "worktree-x")
    _git(root, "merge", "-q", "--no-edit", "cbb_open")
    r, out = _out(script)
    assert f"ok    {SRC}" in out, out
    assert r.returncode == 0, out


def test_whitelisted_branch_may_commit_records_and_reports(tmp_path):
    script, root = _branch_fixture(tmp_path)
    _git(root, "checkout", "-q", "-b", "cbb_open", "main")
    _append_commit(root, REC, _rec_line(root, "e04"))
    _append_commit(root, "cbb/bar/REPORT.BAR.md", "# report\n")
    r, out = _out(script)
    assert f"ok    {SRC}（当前分支 cbb_open 在白名单里）" in out, out
    assert f"已执行  {SRC}" in out, out
    assert r.returncode == 0, out


def _branch_fixture_with_report(tmp_path, report="cbb/bar/REPORT.BAR.md"):
    """同 _branch_fixture，但 main 上已经提交了一份报告，供分支删除。"""
    script, root = _branch_fixture(tmp_path)
    _git(root, "checkout", "-q", "main")
    _append_commit(root, report, "# report\n")
    _git(root, "checkout", "-q", "worktree-x")
    _git(root, "merge", "-q", "--ff-only", "main")
    return script, root


def _commit_removal(root, *rels):
    _git(root, "rm", "-rq", *rels)
    _git(root, "commit", "-qm", f"remove {' '.join(rels)}")


@pytest.mark.parametrize("report, removed", [
    ("cbb/bar/REPORT.BAR.md", ("cbb/bar",)),              # 整个设计根随报告一起删
    ("cbb/bar/REPORT.OLD.md", ("cbb/bar/REPORT.OLD.md",)),  # 根还在，tops: 里已没有 OLD
])
def test_deleting_a_report_whose_top_is_gone_passes_and_is_listed(tmp_path, report, removed):
    """内部#81：删除一份已没有顶层的报告不产生记录，不算违规，但要列出来。"""
    script, root = _branch_fixture_with_report(tmp_path, report)
    _commit_removal(root, *removed)
    r, out = _out(script)
    assert f"ok    {SRC}" in out, out
    assert f"放行  {report}" in out, f"放行的删除必须逐个列出，实际输出：\n{out}"
    assert r.returncode == 0, out


def test_deleting_the_report_of_a_live_top_still_fails(tmp_path):
    script, root = _branch_fixture_with_report(tmp_path)
    _commit_removal(root, "cbb/bar/REPORT.BAR.md")
    r, out = _out(script)
    assert f"FAIL  {SRC}" in out and "cbb/bar/REPORT.BAR.md" in out, out
    assert r.returncode != 0, out


def test_renaming_a_report_is_caught_by_its_new_path(tmp_path):
    """放行删除之后，改名不能变成漏洞：改名按「删旧 + 增新」判，新路径照拦。"""
    script, root = _branch_fixture_with_report(tmp_path)
    _git(root, "mv", "cbb/bar/REPORT.BAR.md", "cbb/bar/REPORT.BAZ.md")
    _git(root, "commit", "-qm", "rename report")
    r, out = _out(script)
    assert f"FAIL  {SRC}" in out and "cbb/bar/REPORT.BAZ.md" in out, out
    assert r.returncode != 0, out


def test_uncommitted_dev_records_on_a_branch_pass(tmp_path):
    script, root = _branch_fixture(tmp_path)
    (root / REC).write_text((root / REC).read_text() + _rec_line(root, "e05"))
    r, out = _out(script)
    assert r.returncode == 0, out
    assert f"ok    {SRC}" in out and f"已执行  {SRC}" in out, out


def test_migration_on_a_non_whitelisted_branch_passes(tmp_path):
    """历史搬迁只搬不增：删旧单文件、行原样进设计根文件，两项都过（本 change 自己就是这样提交的）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = script.parent.parent
    _ensure_git(script)
    lines = _rec_line(root, "e06") + _rec_line(root, "e07")
    _append_commit(root, "results/experiments.jsonl", lines, "搬迁前的旧单文件")
    _git(root, "checkout", "-q", "-b", "worktree-migrate")
    _git(root, "rm", "-q", "results/experiments.jsonl")
    _append_commit(root, REC, lines, "搬迁")
    r, out = _out(script)
    for item in (SRC, HIST, MIGRATED):
        assert f"ok    {item}" in out, out
    assert r.returncode == 0, out


def test_legacy_file_left_in_the_tree_fails(tmp_path):
    script, root = _branch_fixture(tmp_path)
    _git(root, "checkout", "-q", "main")
    _append_commit(root, "results/experiments.jsonl", _rec_line(root, "e08"))
    r, out = _out(script)
    assert f"FAIL  {MIGRATED}" in out and "flow.records migrate" in out, out
    assert r.returncode != 0, out


def test_merge_that_drops_a_history_line_fails(tmp_path):
    """手工解冲突删掉了父提交已有的一行：历史行检查拦下（红线 2）。"""
    script, root = _branch_fixture(tmp_path)
    _git(root, "checkout", "-q", "main")
    _append_commit(root, REC, _rec_line(root, "e09"))
    (root / REC).write_text((root / REC).read_text().splitlines(keepends=True)[1])   # 只留第二行
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "丢了一行")
    r, out = _out(script)
    assert f"FAIL  {HIST}" in out and REC in out, out
    assert r.returncode != 0, out


def _integration_with_record(tmp_path):
    script, root = _branch_fixture(tmp_path)
    _git(root, "checkout", "-q", "-b", "cbb_open", "main")
    _append_commit(root, "docs/notes.txt", "x\n", "集成分支上的代码提交")
    _append_commit(root, REC, _rec_line(root, "e10"), "在上面那个提交上跑出的记录")
    _git(root, "checkout", "-q", "main")
    _append_commit(root, "docs/main.txt", "y\n", "main 同时往前走了")
    return script, root


def test_squash_into_main_breaks_reachability(tmp_path):
    script, root = _integration_with_record(tmp_path)
    _git(root, "merge", "-q", "--squash", "cbb_open")
    _git(root, "commit", "-qm", "squash")
    _git(root, "branch", "-q", "-D", "cbb_open")      # 集成分支删掉后，那个提交只剩悬空对象
    r, out = _out(script)
    assert f"FAIL  {REACH}" in out and REC in out, out
    assert r.returncode != 0, out


def test_merge_into_main_keeps_reachability(tmp_path):
    script, root = _integration_with_record(tmp_path)
    _git(root, "merge", "-q", "--no-edit", "cbb_open")
    r, out = _out(script)
    for item in (SRC, HIST, REACH, MIGRATED):
        assert f"ok    {item}" in out, out
    assert r.returncode == 0, out


def test_missing_whitelist_fails(tmp_path):
    script, root = _branch_fixture(tmp_path)
    (root / "flow" / "record_branches.yaml").unlink()
    r, out = _out(script)
    assert f"FAIL  {SRC}" in out and "record_branches.yaml" in out, out
    assert r.returncode != 0, out


def test_without_a_main_branch_the_check_fails(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _ensure_git(script, branch="trunk")
    r, out = _out(script)
    assert r.returncode != 0, out
    assert f"FAIL  {SRC}" in out and "main" in out, out


def test_outside_a_git_repo_the_check_is_listed_as_not_run(tmp_path):
    """不在 git 仓库里（如 Download ZIP 解压的公开仓）：记为未执行，不判失败，也不算已执行（内部#443，用户 2026-10-26 定）。

    不走 _run_with_path（它会 git init），直接跑。没有 main 分支仍判失败，见上一条。"""
    import os
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    bindir = tmp_path / "stubbin"
    bindir.mkdir()
    for tool, body in (("iverilog", STUB_OK), ("verilator", "#!/bin/sh\nexit 0\n")):
        (bindir / tool).write_text(body)
        (bindir / tool).chmod(0o755)
    # GIT_CEILING_DIRECTORIES 挡住向上找 .git —— tmp 目录在某个 git 仓里时也不越界
    env = dict(os.environ, PATH=f"{bindir}:{_VENV_BIN}:/usr/bin:/bin:/usr/sbin:/sbin",
               GIT_CEILING_DIRECTORIES=str(tmp_path.parent))
    r = subprocess.run([str(script)], capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    assert f"FAIL  {SRC}" not in out, out
    assert f"  未执行  {SRC}（不在 git 仓库里" in out, out
    assert f"已执行  {SRC}" not in out, out
    assert r.returncode == 0, out
