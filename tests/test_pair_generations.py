"""两代配对：「零差异」这句话只能在它真成立时说出口。

`scripts/pair_generations.py` 的退出码被拿来当零差异类任务的判据（内部#59），
所以它最该挡住的是**假的 0**：配不上的组消失在计数里、同代重复测量不一致
却没人看见、每次必变的字段把真差异淹没。全部用合成记录，不跑任何工具。
"""
import json

import pytest
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import pair_generations as pg  # noqa: E402


def _rec(fp, design, params, cells=100, ts="2026-09-25T00:00:00", **extra):
    rec = {
        "experiment_id": f"{design}-{fp}-{json.dumps(params)}",
        "timestamp": ts,
        "git_commit": fp * 5,
        "flow": {"fingerprint": f"sha256:{fp}" + "0" * 56, "yosys": fp},
        "design": design,
        "params": params,
        "sim": {"passed": True, "vcd_path": f"/runs/{fp}/x.vcd"},
        "synth": {"cell_count": cells},
    }
    rec.update(extra)
    return rec


def _write(tmp_path, recs):
    p = tmp_path / "experiments.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return p


def _run(tmp_path, recs, *args, capsys):
    rc = pg.main(["--records", str(_write(tmp_path, recs)), *args])
    return rc, capsys.readouterr().out


def test_identical_generations_are_zero_diff(tmp_path, capsys):
    # 每次必变的字段（id / 时间 / commit / flow / *_path）不算差异
    recs = [_rec("aaaaaaaa", "ADDER32", {"W": 8}),
            _rec("bbbbbbbb", "ADDER32", {"W": 8})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert rc == 0, out
    assert "零差异" in out


def test_a_changed_value_is_reported_and_fails(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", {"W": 8}, cells=100),
            _rec("bbbbbbbb", "ADDER32", {"W": 8}, cells=101)]
    rc, out = _run(tmp_path, recs, "--base", "previous", "--head", "latest",
                   "--show", "1", capsys=capsys)
    assert rc == 1
    assert "synth.cell_count  1" in out and "100 → 101" in out


def test_unpaired_combos_are_named_not_just_counted(tmp_path, capsys):
    # D-22 的 120 = 117 + 3：配不上的必须点名，而且不能是 0 退出
    recs = [_rec("aaaaaaaa", "ADDER32", {"W": 8}),
            _rec("aaaaaaaa", "ADDER32", {"W": 16}),
            _rec("bbbbbbbb", "ADDER32", {"W": 8})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert rc == 1
    assert '只有 base 一侧有：\n#   ADDER32 {"W": 16}' in out


def test_design_case_is_normalised_for_pairing(tmp_path, capsys):
    # 2026-09-21 之前的记录是小写顶层名（内部#46）
    recs = [_rec("aaaaaaaa", "adder32", {"W": 8}),
            _rec("bbbbbbbb", "ADDER32", {"W": 8})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert "配上 1 组" in out
    # design 字段本身的大小写变化作为普通差异报出来 —— 它确实变了
    assert rc == 1 and "design  1" in out


def test_schema_growth_is_listed_but_not_a_difference(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", {"W": 8}),
            _rec("bbbbbbbb", "ADDER32", {"W": 8}, sta={"hold_slack_ns": 1.0})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert rc == 0, out
    assert "+ sta.hold_slack_ns" in out


def test_unstable_repeats_within_a_generation_fail(tmp_path, capsys):
    # 同代同组合两次测量不同 → 测量不确定，跨代「零差异」不作数
    recs = [_rec("aaaaaaaa", "ADDER32", {"W": 8}, cells=100),
            _rec("aaaaaaaa", "ADDER32", {"W": 8}, cells=99),
            _rec("bbbbbbbb", "ADDER32", {"W": 8}, cells=99)]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert rc == 1
    assert "值不一致 base 1" in out


def _rec_src(fp, cells, src):
    r = _rec(fp, "CBB_LZD", {"W": 8}, cells=cells)
    r["synth"]["sources_sha256"] = src
    return r


def test_repeats_that_changed_rtl_are_not_measurement_noise(tmp_path, capsys):
    """同代同组合两条记录的读入集合不同（中间改过 RTL，内部#334 实撞）：不是测量不稳，
    取最后一条比，单列「换过 RTL」；最后一条与 head 相同就零差异。"""
    recs = [_rec_src("aaaaaaaa", 100, "old"), _rec_src("aaaaaaaa", 90, "new"),
            _rec_src("bbbbbbbb", 90, "new")]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert rc == 0, out
    assert "换过 RTL" in out and "1 组" in out, out
    assert "测量不一致" not in out.split("# 结论")[0].split("换过 RTL")[0], out


def test_repeats_with_the_same_rtl_that_disagree_still_fail(tmp_path, capsys):
    """失败臂：读入集合相同、数却不同，照旧算测量不稳。"""
    recs = [_rec_src("aaaaaaaa", 100, "same"), _rec_src("aaaaaaaa", 90, "same"),
            _rec_src("bbbbbbbb", 90, "same")]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert rc == 1, out
    assert "重复测量不一致 1 处" in out, out


def test_ignore_drops_a_field(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", {"W": 8}, cells=100),
            _rec("bbbbbbbb", "ADDER32", {"W": 8}, cells=101)]
    rc, _ = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb",
                 "--ignore", "synth.cell_count", capsys=capsys)
    assert rc == 0


def test_an_ambiguous_prefix_is_refused(tmp_path, capsys):
    recs = [_rec("aaaa1111", "ADDER32", {"W": 8}),
            _rec("aaaa2222", "ADDER32", {"W": 8})]
    rc = pg.main(["--records", str(_write(tmp_path, recs)),
                  "--base", "aaaa", "--head", "latest"])
    assert rc == 2
    assert "命中 2 代" in capsys.readouterr().err


def test_list_names_what_moved_in_the_fingerprint(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", {"W": 8}),
            _rec("bbbbbbbb", "ADDER32", {"W": 8})]
    rc, out = _run(tmp_path, recs, "--list", capsys=capsys)
    assert rc == 0
    lines = out.strip().splitlines()
    assert len(lines) == 2 and "变：yosys" in lines[1]


# --- 参数改名分界（experiment-record 的「`params` 的键换过一次名」，unify-rtl-naming 3.3）----
#
# 改名不换代（指纹不含 RTL），所以两侧常常在**同一代**里：靠指纹切不开，只能按
# git_commit 的祖先关系切（--split-at）。映射必须显式给（--param-map），只作用于
# base 一侧 —— 工具不猜：换词不像大小写，自动合并会把两个碰巧同名的参数配到一起。

import os
import subprocess


def _git_repo(tmp_path):
    """两个提交的最小 git 仓：返回 (仓路径, 分界之前的提交, 分界提交)。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                    capture_output=True, text=True, env=env).stdout.strip()
    run("init", "-q")
    (repo / "f").write_text("1")
    run("add", "f"); run("commit", "-qm", "before")
    before = run("rev-parse", "HEAD")
    (repo / "f").write_text("2")
    run("commit", "-qam", "rename")
    return repo, before, run("rev-parse", "HEAD")


def _rec_at(commit, params, cells=100, fp="aaaaaaaa"):
    rec = _rec(fp, "ADDER32", params, cells=cells)
    rec["git_commit"] = commit
    return rec


def test_renamed_keys_do_not_pair_without_an_explicit_map(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", {"WIDTH": 8}),
            _rec("bbbbbbbb", "ADDER32", {"DAT_W": 8})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb", capsys=capsys)
    assert rc == 1
    assert '只有 base 一侧有：\n#   ADDER32 {"WIDTH": 8}' in out, out


def test_an_explicit_param_map_pairs_the_renamed_keys(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", {"WIDTH": 8, "PIPE_STAGES": 0}),
            _rec("bbbbbbbb", "ADDER32", {"DAT_W": 8, "PIPE_STAGES": 0})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb",
                   "--param-map", "WIDTH=DAT_W", capsys=capsys)
    assert rc == 0, out
    assert "配上 1 组" in out and "零差异" in out
    assert "WIDTH→DAT_W" in out, "输出没写明这次配对用了哪张映射表"


def test_a_mapped_pair_with_a_different_value_still_fails(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", {"WIDTH": 8}, cells=100),
            _rec("bbbbbbbb", "ADDER32", {"DAT_W": 8}, cells=101)]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb",
                   "--param-map", "WIDTH=DAT_W", capsys=capsys)
    assert rc == 1 and "synth.cell_count  1" in out


def test_split_at_cuts_one_generation_by_commit_ancestry(tmp_path, capsys):
    repo, before, split = _git_repo(tmp_path)
    recs = [_rec_at(before, {"WIDTH": 8}), _rec_at(before, {"WIDTH": 16}),
            _rec_at(split, {"DAT_W": 8}), _rec_at(split, {"DAT_W": 16})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "aaaa",
                   "--split-at", split, "--repo", str(repo),
                   "--param-map", "WIDTH=DAT_W", capsys=capsys)
    assert rc == 0, out
    assert "配上 2 组" in out
    assert "分界" in out and split[:8] in out, "输出没写明按哪个提交切的"


# --- 结构枚举的取值也换过一次（unify-rtl-naming 3.6，D15）-------------------------
#
# 2026-09-29 起 SCHEME 取整数：同一个电路，旧记录写 "CLA"、新记录写 1。键映射配不上
# 取值，取值映射同样只能显式给 —— 工具不按 labels 猜，那等于替历史记录断言编号。

_OLD = {"CARRY_STRUCT": "CLA", "PIPE_STAGES": 0}
_NEW = {"SCHEME": 1, "PIPE_STAGES": 0}


def test_a_key_map_alone_does_not_pair_a_renumbered_value(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", _OLD), _rec("bbbbbbbb", "ADDER32", _NEW)]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb",
                   "--param-map", "CARRY_STRUCT=SCHEME", capsys=capsys)
    assert rc == 1, out
    assert '只有 base 一侧有：\n#   ADDER32 {"PIPE_STAGES": 0, "SCHEME": "CLA"}' in out, out


def test_an_explicit_value_map_pairs_the_renumbered_value(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", _OLD), _rec("bbbbbbbb", "ADDER32", _NEW),
            # 没被映射的旧取值原样保留，不猜编号
            _rec("aaaaaaaa", "ADDER32", {"CARRY_STRUCT": "CSEL", "PIPE_STAGES": 0})]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb",
                   "--param-map", "CARRY_STRUCT=SCHEME",
                   "--value-map", "SCHEME:CLA=1", capsys=capsys)
    assert "配上 1 组" in out, out
    assert '"SCHEME": "CSEL"' in out, "未映射的旧取值被改写或丢掉了"
    assert "SCHEME:CLA→1" in out, "输出没写明这次配对用了哪张取值映射"
    assert rc == 1, "有一组只在 base 一侧，不该判零差异"


def test_a_value_map_that_pairs_everything_exits_zero(tmp_path, capsys):
    recs = [_rec("aaaaaaaa", "ADDER32", _OLD), _rec("bbbbbbbb", "ADDER32", _NEW)]
    rc, out = _run(tmp_path, recs, "--base", "aaaa", "--head", "bbbb",
                   "--param-map", "CARRY_STRUCT=SCHEME",
                   "--value-map", "SCHEME:CLA=1", capsys=capsys)
    assert rc == 0 and "零差异" in out, out


@pytest.mark.parametrize("bad", ["SCHEME=CLA=1", "SCHEME:CLA", ":CLA=1"])
def test_a_malformed_value_map_is_refused(tmp_path, capsys, bad):
    recs = [_rec("aaaaaaaa", "ADDER32", _OLD), _rec("bbbbbbbb", "ADDER32", _NEW)]
    rc = pg.main(["--records", str(_write(tmp_path, recs)), "--base", "aaaa",
                  "--head", "bbbb", "--value-map", bad])
    assert rc == 2 and "--value-map" in capsys.readouterr().err


def test_split_at_with_an_unknown_commit_is_refused(tmp_path, capsys):
    repo, before, split = _git_repo(tmp_path)
    recs = [_rec_at("0" * 40, {"WIDTH": 8}), _rec_at(split, {"DAT_W": 8})]
    rc = pg.main(["--records", str(_write(tmp_path, recs)), "--base", "aaaa",
                  "--head", "aaaa", "--split-at", split, "--repo", str(repo)])
    assert rc == 2
    assert "不在" in capsys.readouterr().err


def test_list_without_records_reads_every_design_root_file(tmp_path, monkeypatch, capsys):
    """内部#422：不给 --records 时读全部 results/<设计根>/experiments.jsonl。"""
    from flow import records
    monkeypatch.setattr(records, "REPO_ROOT", tmp_path)
    for root, rec in (("root_x", _rec("a", "DES_X", {"W": 8})), ("root_y", _rec("b", "DES_Y", {"W": 8}))):
        d = tmp_path / "results" / root
        d.mkdir(parents=True)
        _write(d, [rec])
    assert pg.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "DES_X" in out and "DES_Y" in out, out
