"""项目自己的 skill 在 Claude 与 Codex 两端是同一份、命令示例守 CPU 预算（内部#373）。

openspec-* 由 keel 生成，两端各一份、各自刷新，不在这里管；项目自己写的 skill 只维护
`.claude/skills/<名>/`，`.agents/skills/<名>` 是指向它的符号链接，Codex 从那里发现。
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE = REPO_ROOT / ".claude" / "skills"
AGENTS = REPO_ROOT / ".agents" / "skills"
# 全机重活合计 ≤ 6，单个任务默认 4（team/README.md「CPU」、flow/budget.py，内部#359）
MAX_JOBS = 4


def _project_skills():
    return sorted(p.name for p in CLAUDE.iterdir() if p.is_dir() and not p.name.startswith("openspec-"))


def test_there_is_a_project_skill_to_check():
    assert _project_skills(), "夹具失效：.claude/skills 下没有项目自己的 skill"


@pytest.mark.parametrize("name", _project_skills())
def test_codex_entry_is_a_link_to_the_claude_skill(name):
    entry = AGENTS / name
    assert entry.is_symlink(), f".agents/skills/{name} 不存在或不是符号链接：Codex 找不到它，或两端各维护一份"
    assert entry.resolve() == (CLAUDE / name).resolve(), f".agents/skills/{name} 没指向 .claude/skills/{name}"
    assert (entry / "SKILL.md").is_file()


@pytest.mark.parametrize("name", _project_skills())
def test_command_examples_stay_within_the_cpu_budget(name):
    text = (CLAUDE / name / "SKILL.md").read_text(encoding="utf-8")
    over = [(m.group(0), int(m.group(2))) for m in re.finditer(r"(-j|-n|JOBS=|KAIWU_JOBS=)\s*(\d+)\b", text)
            if int(m.group(2)) > MAX_JOBS]
    assert not over, f"{name} 的命令示例并发超过 {MAX_JOBS}：{over}"
    assert "-n auto" not in text, f"{name} 用了 -n auto（#359）"
