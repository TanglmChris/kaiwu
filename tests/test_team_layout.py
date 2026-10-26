"""team/：组织章程与能力镜像（team-organization，kaiwu-org-model）。

- 五个镜像各有 README.md，六节标题齐全；
- team/ 下的文件按 flow/export/manifest.yaml 的 block 规则零命中（不改 manifest，
  直接用它的规则扫工作区里的 team/，因为镜像不得含 IP 专属内容，与开不开源无关）。
"""
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "flow" / "export"))
import leak_scan  # noqa: E402

TEAM = REPO_ROOT / "team"
MIRRORS = ["kaiwu-spec", "kaiwu-design", "kaiwu-verify", "kaiwu-review", "kaiwu-report"]
SECTIONS = ["职责", "输入与输出", "交接", "禁区", "技能与模板", "经验"]


def _headings(text):
    return {m.group(1).strip() for m in re.finditer(r"^##\s+(.+?)\s*$", text, re.M)}


@pytest.mark.parametrize("mirror", MIRRORS)
def test_mirror_has_all_sections(mirror):
    readme = TEAM / "roles" / mirror / "README.md"
    assert readme.is_file(), f"缺镜像 team/roles/{mirror}/README.md"
    missing = [s for s in SECTIONS if s not in _headings(readme.read_text(encoding="utf-8"))]
    assert not missing, f"team/roles/{mirror} 缺节：{missing}"


def test_charter_and_pull_flow_exist():
    for name in ("README.md", "pull-team.md"):
        assert (TEAM / name).is_file(), f"缺 team/{name}"


def test_team_has_no_closed_content():
    assert (TEAM / "roles").is_dir(), "缺 team/roles"
    if not (REPO_ROOT / leak_scan.MANIFEST).exists():   # 写法同 test_fail_record（内部#365）
        pytest.skip("没有 flow/export/manifest.yaml：白名单闭源，不在导出集合（open-export「导出结果自足」）")
    manifest = leak_scan.load_manifest(REPO_ROOT, None, REPO_ROOT / leak_scan.MANIFEST)
    block = [(name, rx) for level, name, rx in manifest["rules"] if level == "block"]
    hits = []
    for f in sorted(TEAM.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(REPO_ROOT).as_posix()
        hits += [f"{rel}:0 {name}" for name, rx in block if rx.search(rel)]
        for no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            hits += [f"{rel}:{no} {name}" for name, rx in block if rx.search(line)]
    assert not hits, "team/ 含闭源内容：\n" + "\n".join(hits)


# ---- 常备授权按能力分组声明（team-organization，kaiwu-org-model 1.2）----

CONFIG = REPO_ROOT / "keel" / "config.yaml"
GROUP_RE = re.compile(r"^\s*#\s*组：\s*(\S.*)$")


def _authorize_lines(text):
    """`authorize:` 块里的行：从 `authorize:` 下一行到下一个顶层键之前。"""
    lines = text.splitlines()
    start = lines.index("authorize:") + 1
    end = next((i for i in range(start, len(lines))
                if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")),
               len(lines))
    return lines[start:end]


def test_authorize_entries_are_grouped():
    if not CONFIG.exists():   # 写法同 test_fail_record（内部#365）
        pytest.skip("没有 keel/config.yaml：用户 10-20 定移出开源集合，不在导出集合（open-export「导出结果自足」）")
    group, orphans = None, []
    for line in _authorize_lines(CONFIG.read_text(encoding="utf-8")):
        m = GROUP_RE.match(line)
        if m:
            group = m.group(1)
        elif line.strip().startswith("- ") and group is None:
            orphans.append(line.strip()[2:])
    assert not orphans, f"authorize: 条目不在任何组下：{orphans}"
