"""功能验证结果的判定：缺失、无用例、跳过、失败、错误都不算通过（design-verify-collaboration，内部#80）。

为什么值得有这个测试：「零个用例全部通过」与「跳过了失败的那条」都会让一轮验证看起来
是绿的，而 cocotb 的 JUnit 报告里 skipped 不算 failure —— 只数 failure 的判定会把它们
当成通过。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.verify.judge import judge  # noqa: E402


def _xml(tmp_path, cases, name="results.xml"):
    body = "".join(f'<testcase name="{n}" classname="t">{extra}</testcase>' for n, extra in cases)
    p = tmp_path / name
    p.write_text(f'<testsuites><testsuite name="s">{body}</testsuite></testsuites>')
    return p


def test_all_passing_is_a_pass(tmp_path):
    ok, problems = judge([_xml(tmp_path, [("a", ""), ("b", "")])])
    assert ok and problems == []


def test_missing_file_fails(tmp_path):
    ok, problems = judge([tmp_path / "nope.xml"])
    assert not ok
    assert any("不存在" in p for p in problems), problems


def test_no_testcase_fails(tmp_path):
    ok, problems = judge([_xml(tmp_path, [])])
    assert not ok
    assert any("没有用例" in p for p in problems), problems


@pytest.mark.parametrize("tag", ["skipped", "failure", "error"])
def test_a_single_bad_testcase_fails_and_is_named(tmp_path, tag):
    ok, problems = judge([_xml(tmp_path, [("a", ""), ("bad_one", f'<{tag} message="m"/>')])])
    assert not ok
    assert any("bad_one" in p and tag in p for p in problems), problems


def test_no_result_files_at_all_fails():
    ok, problems = judge([])
    assert not ok
    assert problems
