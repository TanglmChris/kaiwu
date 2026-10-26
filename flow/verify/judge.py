"""判定一轮功能验证的 JUnit 结果（内部#80）。

以下任何一种都不算通过，逐条给出原因：
- 没有给任何结果文件；
- 结果文件不存在；
- 文件里一个 `testcase` 都没有；
- 任何 `testcase` 带 `skipped`、`failure` 或 `error`。

cocotb 的 JUnit 报告把 skipped 与 failure 分开记，只数 failure 的判定会把「跳过了
失败的那条」和「零个用例」都当成通过。契约在 openspec/specs/design-verify-collaboration。

    from flow.verify.judge import judge
    ok, problems = judge([build / "results.xml" for build in builds])
"""
import xml.etree.ElementTree as ET
from pathlib import Path

BAD_TAGS = ("skipped", "failure", "error")


def judge(paths):
    """返回 (是否通过, 不通过的原因列表)。"""
    paths = [Path(p) for p in paths]
    if not paths:
        return False, ["没有任何结果文件"]
    problems = []
    for path in paths:
        if not path.is_file():
            problems.append(f"{path}：结果文件不存在")
            continue
        try:
            cases = list(ET.parse(path).iter("testcase"))
        except ET.ParseError as e:
            problems.append(f"{path}：无法解析（{e}）")
            continue
        if not cases:
            problems.append(f"{path}：没有用例")
        for case in cases:
            for tag in BAD_TAGS:
                found = case.find(tag)
                if found is not None:
                    why = found.get("message") or (found.text or "").strip()
                    problems.append(f"{path}：{case.get('name')} {tag}" + (f"（{why}）" if why else ""))
                    break
    return not problems, problems
