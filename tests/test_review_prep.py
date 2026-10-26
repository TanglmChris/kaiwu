"""评审开工的机械检查一键入口（内部#196，review-prep）。

纯函数用真实形态的夹具（名字是造出来的）：豁免增减照一次评审往返的形态造（5 条删除里 4 条是代码从
alu_old.v 搬到 alu_new.v、豁免跟着换了 -file）；告警行照 verilator 5.053 的输出格式写。
整体用例在本仓 HEAD 上对小 CBB 跑（真 verilator + 该提交自己的 fast_check），标 flow。
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

W = "designs/demo_alu/waivers.vlt"
OLD = {
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/alu_old.v" -match "*'s_pad_cnt'*\""""),
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/alu_old.v" -match "*Bits of function variable are not used: 'step'*\""""),
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/fifo_ctl.v" -match "*'blk_len'*\""""),
    (W, """lint_off -rule WIDTHTRUNC -file "*/alu_old.v" -match "*VAR 'CNT_MAX'*\""""),
    (W, """lint_off -rule WIDTHTRUNC -file "*/alu_old.v" -match "*VAR 'WORD_END'*\""""),
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/out_reg.v" -match "*'unchanged'*\""""),
}
NEW = {
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/alu_new.v" -match "*'s_pad_cnt'*\""""),
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/alu_new.v" -match "*Bits of function variable are not used: 'step'*\""""),
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/fifo_ctl.v" -match "*'blk_length'*\""""),
    (W, """lint_off -rule WIDTHTRUNC -file "*/alu_new.v" -match "*VAR 'CNT_MAX'*\""""),
    (W, """lint_off -rule WIDTHTRUNC -file "*/alu_new.v" -match "*VAR 'WORD_END'*\""""),
    (W, """lint_off -rule PINCONNECTEMPTY -file "*/pipe_cmd.v" -match "*'m_next_flag'\""""),
    (W, """lint_off -rule UNUSEDSIGNAL -file "*/out_reg.v" -match "*'unchanged'*\""""),
}

LINT_OUT = """\
%Warning-UNUSEDPARAM: designs/demo_alu/rtl/tbl_dec.v:10:16: Parameter is not used: 'TBL_DIR'
                      ... For warning description see https://verilator.org/warn/UNUSEDPARAM?v=5.053
                      ... Use "/* verilator lint_off UNUSEDPARAM */" and lint_on around source to disable this message.
%Warning-PINCONNECTEMPTY: designs/demo_alu/rtl/pipe_top.v:212:10: Cell pin connected by name with empty reference: 'm_next_flag'
%Warning-PINCONNECTEMPTY: designs/demo_alu/rtl/pipe_top.v:213:10: Cell pin connected by name with empty reference: 'm_head_flag'
%Warning-WIDTHTRUNC: designs/demo_alu/rtl/alu_new.v:48:31: Operator VAR 'WORD_END' expects 6 bits on the Initial value, but Initial value's CONST '32'h40' generates 32 bits.
%Error: Exiting due to 4 warning(s)
"""

LRS = """\
## 文档信息

| 版本 | 日期 | 改动 |
|---|---|---|
| v1.9 | 09-30 | 初稿 |
| v1.10 | 10-02 | 改 §5 |
| v1.37 | 10-05 | 收紧 R.003 |

## 正文

| v9.99 | 不是版本表的行也以 v 开头时只认格式 `| vX.Y |`，这里故意放一行更大的，测取最大值 |
"""


def test_waiver_diff_pairs_moves_across_files():
    import review_prep as rp
    d = rp.waiver_diff(OLD, NEW)
    assert len(d["moved"]) == 4, d["moved"]
    assert [l for _, l in d["added"]] == ["""lint_off -rule PINCONNECTEMPTY -file "*/pipe_cmd.v" -match "*'m_next_flag'\"""",
                                          """lint_off -rule UNUSEDSIGNAL -file "*/fifo_ctl.v" -match "*'blk_length'*\""""], d["added"]
    assert [l for _, l in d["removed"]] == ["""lint_off -rule UNUSEDSIGNAL -file "*/fifo_ctl.v" -match "*'blk_len'*\""""], d["removed"]
    assert len(NEW) - len(OLD) == len(d["added"]) - len(d["removed"]), "净增减与两份条数之差一致"


def test_lint_tally_counts_categories_not_continuations():
    import review_prep as rp
    assert rp.tally(LINT_OUT) == {"PINCONNECTEMPTY": 2, "UNUSEDPARAM": 1, "WIDTHTRUNC": 1}


def test_doc_version_takes_the_largest_table_version():
    import review_prep as rp
    assert rp.doc_version(LRS) == "v9.99"               # 所有 `| vX.Y |` 行首里最大的
    assert rp.doc_version(LRS.replace("| v9.99", "| x9.99")) == "v1.37"   # 按数值比：1.37 > 1.10 > 1.9
    assert rp.doc_version("# 没有版本表\n") is None


def test_unknown_rev_fails_with_2(tmp_path):
    r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "review_prep.py"), "--rev", "no-such-ref",
                        "--top", "CBB_LZD"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "no-such-ref" in r.stdout + r.stderr, r.stdout + r.stderr


@pytest.mark.flow
@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator 不在 PATH")
def test_table_on_a_real_commit_and_no_worktree_left(tmp_path):
    # 临时检出建在专属的 TMPDIR 下（at_ref 用 mkdtemp），只查这个目录：整机的 git worktree list 别的会话随时在变，
    # 前后比会被它们弄红（内部#359 合并检查实撞：另一个 worktree 的 HEAD 在两次 list 之间动了）
    tmp = (tmp_path / "t").resolve()
    tmp.mkdir()
    out = tmp_path / "table.md"
    # 跑的过程中看 TMPDIR：at_ref 跑完连 mkdtemp 那层也删（内部#397），只能在运行中证明检出建在这里
    p = subprocess.Popen([sys.executable, str(REPO_ROOT / "scripts" / "review_prep.py"), "--rev", "HEAD",
                          "--top", "CBB_LZD", "--prev", "HEAD", "--out", str(out)],
                         cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env=dict(os.environ, TMPDIR=str(tmp)))
    seen = False
    while p.poll() is None:
        seen = seen or any(tmp.glob("at_ref_*/wt"))
        time.sleep(0.05)
    log = p.stdout.read()
    assert p.returncode == 0, log
    table = out.read_text()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    assert head in table, table
    for row in ("| 被评提交 |", "| `spec.CBB_LZD.md` |", "| fast_check |", "| 无豁免 lint（默认参数） |",
                "| 无豁免 lint（", "| 豁免增减 |"):
        assert row in table, (row, table)
    assert "新增 0、删除 0、换文件 0" in table, table
    assert seen, "临时检出应建在给定的 TMPDIR 下"  # 失败臂：没建在这里，下面的检查就什么也没查
    assert list(tmp.iterdir()) == [], f"临时检出要删掉，连 at_ref_* 这层也不留（#397）：{list(tmp.iterdir())}"
    listed = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert str(tmp) not in listed, "git worktree list 里不能留下临时检出"
