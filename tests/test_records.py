"""记录按设计根分文件（experiment-record「实验记录按设计根分文件存放」「历史记录按设计根搬迁且逐字节守恒」，内部#422）。

夹具按本仓记录的真实形态造：新记录带 `design_root`；早期记录没有这个字段（那时设计根名等于顶层名）；
同一个顶层可能前一段没有字段、后一段有字段且设计根换了名（本仓有两个已删的闭源顶层就是这样，
design.md F8；这里用假名）；原文件最后一行可能不带换行；行的键顺序和空白各不相同，搬迁不得重新序列化。
"""
import json

import pytest

from flow import records


def _line(design, eid, root=None, extra=""):
    # 故意不用 json.dumps 的默认空白：搬迁只认原始字节
    rec = '{"design":%s,"experiment_id":"%s"%s%s}' % (
        json.dumps(design), eid, (',"design_root":"%s"' % root) if root else "", extra)
    return rec


def _declare(repo, kind, root, top):
    d = repo / kind / root
    (d / "rtl").mkdir(parents=True)
    (d / "params.yaml").write_text(f"tops:\n  {top}: {{}}\n")
    (d / "rtl" / f"{top}.v").write_text(f"module {top}(); endmodule\n")


@pytest.fixture
def repo(tmp_path):
    _declare(tmp_path, "cbb", "cbb_fifo", "CBB_FIFO")
    _declare(tmp_path, "designs", "adder32", "ADDER32")
    (tmp_path / "results").mkdir()
    return tmp_path


LEGACY = [
    _line("adder32", "a1"),                                  # 老行：无字段，设计根 = design
    _line("CBB_FIFO", "f1", "cbb_fifo"),
    _line("old_pipe", "z1"),                       # 同一顶层前段无字段
    _line("adder32", "a2", extra=',  "params": {"W": 8}'),   # 空白与键序照原样
    _line("old_pipe", "z2", "merged_root"),       # 后段带字段，设计根已改名并删除
    _line("ADDER32", "A1", "adder32"),
    _line("old_pipe", "z3"),                       # 又一条无字段的，仍跟整组走
    _line("CBB_FIFO", "f2", "cbb_fifo"),
]


def _write_legacy(repo, lines, trailing_newline=False):
    data = "\n".join(lines) + ("\n" if trailing_newline else "")
    (repo / "results" / "experiments.jsonl").write_bytes(data.encode())


def _lines(path):
    return path.read_bytes().decode().splitlines()


def test_root_of_new_record_uses_design_root():
    assert records.root_of({"design": "CBB_FIFO", "design_root": "cbb_fifo"}) == "cbb_fifo"
    assert records.root_of({"design": "adder32"}) == "adder32"


def test_legacy_roots_keep_each_top_in_one_file():
    roots = records.legacy_roots([json.loads(l) for l in LEGACY])
    assert roots["old_pipe"] == "merged_root"   # 整组跟最后一条带字段的走
    assert roots["adder32"] == "adder32"                   # 一条都没有字段：取 design
    assert roots["ADDER32"] == "adder32"
    assert roots["CBB_FIFO"] == "cbb_fifo"


def test_log_path_resolves_declared_root(repo):
    assert records.log_path("CBB_FIFO", repo_root=repo) == repo / "results" / "cbb_fifo" / "experiments.jsonl"
    assert records.rel_log_path("ADDER32", repo_root=repo) == "results/adder32/experiments.jsonl"


def test_migrate_conserves_bytes_and_order(repo):
    _write_legacy(repo, LEGACY)        # 末行不带换行
    summary = records.migrate(repo_root=repo)
    assert not (repo / "results" / "experiments.jsonl").exists()
    files = records.record_files(repo_root=repo)
    assert [f.parent.name for f in files] == ["adder32", "cbb_fifo", "merged_root"]
    got = [l for f in files for l in _lines(f)]
    assert sorted(got) == sorted(LEGACY)                    # 不多不少、逐字节
    for f in files:                                         # 每个文件内保持原相对顺序
        idx = [LEGACY.index(l) for l in _lines(f)]
        assert idx == sorted(idx), f
    assert _lines(files[2]) == [LEGACY[2], LEGACY[4], LEGACY[6]]
    assert all(f.read_bytes().endswith(b"\n") for f in files)
    assert summary["lines"] == len(LEGACY) and summary["added"] == len(LEGACY)


def test_migrate_again_only_adds_new_lines(repo):
    _write_legacy(repo, LEGACY, trailing_newline=True)
    records.migrate(repo_root=repo)
    new = [_line("CBB_FIFO", "f3", "cbb_fifo"), _line("adder32", "a3")]
    _write_legacy(repo, LEGACY + new)                       # 合并又带回了旧文件，多两行
    summary = records.migrate(repo_root=repo)
    assert summary["added"] == 2 and summary["lines"] == len(LEGACY) + 2
    assert _lines(records.log_path("CBB_FIFO", repo_root=repo))[-1] == new[0]
    assert sum(len(_lines(f)) for f in records.record_files(repo_root=repo)) == len(LEGACY) + 2


def test_load_reads_all_files_including_retired_roots(repo):
    _write_legacy(repo, LEGACY)
    records.migrate(repo_root=repo)
    zc = records.load("old_pipe", repo_root=repo)
    assert [r["experiment_id"] for r in zc] == ["z1", "z2", "z3"]
    assert len(records.load(repo_root=repo)) == len(LEGACY)
    one = records.load(repo_root=repo, path=records.log_path("CBB_FIFO", repo_root=repo))
    assert [r["experiment_id"] for r in one] == ["f1", "f2"]


def test_failed_self_check_keeps_legacy(repo, monkeypatch):
    _write_legacy(repo, LEGACY)
    real = records._write_file

    def lossy(path, lines):                                  # 人为让一个目标文件少一行
        real(path, lines[:-1] if path.parent.name == "cbb_fifo" else lines)

    monkeypatch.setattr(records, "_write_file", lossy)
    with pytest.raises(records.MigrationError):
        records.migrate(repo_root=repo)
    assert (repo / "results" / "experiments.jsonl").exists()


def test_dry_run_writes_nothing(repo):
    _write_legacy(repo, LEGACY)
    summary = records.migrate(repo_root=repo, dry_run=True)
    assert summary["roots"] == {"adder32": 3, "cbb_fifo": 2, "merged_root": 3}
    assert records.record_files(repo_root=repo) == []
    assert (repo / "results" / "experiments.jsonl").exists()


def test_load_merges_files_by_timestamp_keeping_file_order(repo):
    """多文件按 timestamp 归并、各文件内部不重排（design.md F9）：同一文件里相邻时间戳倒序（并行扫参）照原样。"""
    a = repo / "results" / "adder32" / "experiments.jsonl"
    f = repo / "results" / "cbb_fifo" / "experiments.jsonl"
    a.parent.mkdir(); f.parent.mkdir()
    a.write_text('{"design":"ADDER32","experiment_id":"a1","timestamp":"T1"}\n'
                 '{"design":"ADDER32","experiment_id":"a3","timestamp":"T3"}\n')
    f.write_text('{"design":"CBB_FIFO","experiment_id":"f2","timestamp":"T2"}\n'
                 '{"design":"CBB_FIFO","experiment_id":"f5","timestamp":"T5"}\n'
                 '{"design":"CBB_FIFO","experiment_id":"f4","timestamp":"T4"}\n')
    assert [r["experiment_id"] for r in records.load(repo_root=repo)] == ["a1", "f2", "a3", "f5", "f4"]


def test_redirect_points_run_experiment_at_one_file_and_restores(repo, tmp_path):
    from scripts import run_experiment as rx
    saved = (rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS, rx._worktree_status)
    target = records.log_path("CBB_FIFO", repo_root=repo)
    with records.redirect(rx, target, repo_root=repo):
        assert rx.EXPERIMENTS_LOG == target
        assert rx.LOG_PATH_IN_STATUS == "results/cbb_fifo/experiments.jsonl"
        rx._assert_clean_worktree("?? results/cbb_fifo/experiments.jsonl\n")     # 本设计根的文件不算脏
        with pytest.raises(RuntimeError):
            rx._assert_clean_worktree("?? results/adder32/experiments.jsonl\n")  # 别的设计根的算
    assert (rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS, rx._worktree_status) == saved


def test_redirect_status_lists_untracked_file_not_its_new_dir(tmp_path):
    """新设计根的第一条记录写完，默认 porcelain 只报 `?? results/<根>/`，守卫会在第二个组合上自锁。"""
    import subprocess
    from scripts import run_experiment as rx
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    target = tmp_path / "results" / "cbb_new" / "experiments.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n")
    with records.redirect(rx, target, repo_root=tmp_path):
        st = rx._worktree_status()
        assert st.strip() == "?? results/cbb_new/experiments.jsonl", st
        rx._assert_clean_worktree(st)


def test_load_falls_back_to_legacy_only_before_migration(repo):
    _write_legacy(repo, LEGACY)
    assert records.source_files(repo_root=repo) == [repo / "results" / "experiments.jsonl"]
    assert len(records.load(repo_root=repo)) == len(LEGACY)
    records.migrate(repo_root=repo)
    _write_legacy(repo, LEGACY)                     # 合并带回旧文件：不叠加，避免重复计数
    assert records.source_files(repo_root=repo) == records.record_files(repo_root=repo)
    assert len(records.load(repo_root=repo)) == len(LEGACY)
