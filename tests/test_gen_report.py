"""`scripts/gen_report.py` 的参数角色声明与前沿分组。

本文件守的是一件容易被当成"呈现细节"的事：**前沿在哪些点之间判支配**。
判错了不会报错、不会缺数字，只会产出一张看起来完全正常、但在回答同义反复的表
（本仓 内部#44）。所以判据不是"有没有前沿"，而是"前沿里的点做的活是不是一样多"。
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gen_report  # noqa: E402

def _all_tops():
    """全部设计根声明的全部被测顶层，{顶层名: 它的 params 段}。

    **有意直接读 yaml，不走 `flow.paths.load_params_spec`** —— 这些用例要验的
    正是「声明里写了什么」，用被测代码去读声明会让「读法错了」与「声明错了」
    互相掩盖。代价是这里要自己知道 `tops:` 的形状。
    """
    out = {}
    from flow.paths import tree_glob   # 专用设计树（flow.paths.DESIGN_TREES，内部#305）
    for params in (REPO_ROOT / p for p in tree_glob("*/params.yaml", kind="design", repo_root=REPO_ROOT)):
        doc = yaml.safe_load(params.read_text()) or {}
        for top, cfg in (doc.get("tops") or {}).items():
            assert top not in out, f"顶层名 {top!r} 在多个设计根下被声明"
            out[top] = (cfg or {}).get("params") or {}
    return out


DESIGNS = tuple(_all_tops())


def _spec(design):
    return _all_tops()[design]


def test_a_swept_parameter_without_a_role_is_an_error():
    """M1：漏声明必须报错，而且要指名是哪个设计的哪个参数。

    这条守的不是"有没有校验"，是**没有默认值**。默认成 microarch 会让一个
    规模旋钮静默地混进前沿，产出一张看起来正常的表 —— 与本仓 D-1（Annotated 0
    不报错）同形。报错信息里必须带设计名与参数名，否则五个设计根一起报错时
    没人知道该去改哪一份。
    """
    with pytest.raises(Exception) as e:
        gen_report.param_role("某设计", "WIDTH",
                              {"type": "enum", "values": [8, 16]})
    msg = str(e.value)
    assert "某设计" in msg and "WIDTH" in msg, (
        f"报错信息没指名设计与参数，五份 params.yaml 一起报错时读者不知道改哪份：{msg}")


def test_a_non_swept_parameter_needs_no_role():
    """M2：`sweep: false` 的参数不进前沿，要求它声明角色没有意义。

    这一条防的是把校验做得过宽。`LANE_W` / `TAG_W` / `CSEL_BLOCK` 这类参数
    只有一个取值或不参与叉乘，逼它们声明只会制造一堆没有信息的 `role:` 行。
    """
    assert gen_report.param_role(
        "某设计", "LANE_W",
        {"type": "enum", "sweep": False, "values": [10]}) is None


def test_an_unknown_role_is_an_error():
    """M3：只有两个合法取值，第三个要报错并列出合法值。"""
    with pytest.raises(Exception) as e:
        gen_report.param_role("某设计", "WIDTH",
                              {"type": "enum", "role": "既不是也不是",
                               "values": [8, 16]})
    msg = str(e.value)
    assert "microarch" in msg and "scale" in msg, (
        f"报错没列出合法取值，读者只知道自己写错了、不知道该写什么：{msg}")


@pytest.mark.parametrize("design", DESIGNS)
def test_every_swept_parameter_declares_a_role(design):
    """五个设计根的声明必须齐全 —— 否则 `make report` 对它直接报错。

    这条用真实的 `params.yaml`，不是夹具：漏了一份的后果是那个设计的报告
    生不出来，而那件事应当在测试里就被看见，不是在有人跑 `make report` 时。
    """
    missing = [
        name for name, spec in _spec(design).items()
        if spec.get("sweep", True) is not False and "role" not in spec
    ]
    assert not missing, f"{design} 的这些扫参维度没有声明 role：{missing}"


@pytest.mark.parametrize("design", DESIGNS)
def test_the_declared_roles_are_legal(design):
    """取值只能是那两个。写错了同样只会静默产出一张错表。"""
    for name, spec in _spec(design).items():
        if spec.get("sweep", True) is False:
            continue
        assert gen_report.param_role(design, name, spec) in ("microarch", "scale")


def test_the_role_reader_does_not_live_in_a_fingerprinted_module():
    """⚠️ 角色读取留在 `gen_report.py` 里。

    `gen_report.py` 被明确排除在指纹之外（`flow_fingerprint.py` 的 METRIC_MODULES
    注释「它们只读记录，不写」）。2026-10-04 起 `flow/paths.py` 也不按代码进指纹
    （内部#146，按解析后的设计配方进），挪过去不再换代，但角色是报告侧的读法，仍住在这里。

    这条查的是**那个排除仍然成立** —— 有人把 gen_report.py 加进 METRIC_MODULES
    的那天，这条会红。
    """
    from flow.flow_fingerprint import METRIC_MODULES
    assert "scripts/gen_report.py" not in METRIC_MODULES
    assert hasattr(gen_report, "param_role"), "param_role 不在 gen_report 里"


# --------------------------------------------------------------------------
# 前沿按规模维度分组（本仓 内部#44）
# --------------------------------------------------------------------------

FRONT_HEADING = "## 面积-延时 Pareto 前沿"


# 合成记录里的 `ADDER32` 只是标签（trim-design-roots 的 D3）：设计根已于 2026-10-01 删除，
# 这里给它一份与当时 params.yaml 同形的合成声明，好让只依赖「声明形状」的用例照旧成立。
_ADDER32_LIKE = {
    "DAT_W": {"type": "enum", "role": "scale", "values": [8, 16, 32, 64]},
    "SCHEME": {"type": "enum", "role": "microarch", "values": [0, 1, 2, 3, 4, 5],
               "labels": {0: "RIPPLE", 1: "CLA", 2: "CSEL", 3: "SKLANSKY",
                          4: "KOGGE_STONE", 5: "BRENT_KUNG"}},
    "PIPE_STAGES": {"type": "enum", "role": "microarch", "values": [0, 1, 2]},
    "CSEL_BLK_W": {"type": "enum", "sweep": False, "values": [4, 2, 8, 16]},
}


# `FIFO_LIKE` 同理：两个规模维度（位宽、深度）加两个微架构开关的声明形状。以前拿真实的
# 闭源构件当样本，开源拆分后改成合成声明（kaiwu-layout-decouple 3.1，内部#305）。
_FIFO_LIKE = {
    "DAT_W": {"type": "enum", "role": "scale", "values": [1, 32]},
    "DEP_N": {"type": "enum", "role": "scale", "values": [2, 4, 16]},
    "PT_EN": {"type": "enum", "role": "microarch", "values": [0, 1]},
    "RST_EN": {"type": "enum", "role": "microarch", "values": [0, 1]},
}
_LABELS = {"ADDER32": _ADDER32_LIKE, "FIFO_LIKE": _FIFO_LIKE}


@pytest.fixture(autouse=True)
def _adder32_is_a_label(monkeypatch):
    real = gen_report.load_params_spec
    monkeypatch.setattr(gen_report, "load_params_spec",
                        lambda d, *a, **k: _LABELS[d] if d in _LABELS else real(d, *a, **k))


def _render(design):
    """按真实 `params.yaml` 的声明造记录再渲染 —— **不读 jsonl**。

    2026-09-28 之前这里读的是真实的 `results/experiments.jsonl`。那让这几条测试
    钉在「当下有哪些记录」上：`unify-rtl-naming` 改了参数名之后，`params.yaml` 已是
    新键而记录还是旧键，按 scale 维度分组当场失效 —— 测试红了，被测行为却没变
    （下面那条 `test_a_design_with_no_scale_dimension_keeps_one_front` 的 docstring
    记过同一类失效）。现在：声明是真的（分组键、role 都来自真实 `params.yaml`），
    记录是合成的（全部声明取值的叉乘，含 `sweep: false` 的取值），组内的点
    面积递增、延时递减，所以都在前沿上。
    """
    import itertools
    spec = gen_report.load_params_spec(design)
    names = list(spec)
    recs = []
    for n, vals in enumerate(itertools.product(*(spec[k]["values"] for k in names))):
        recs.append(_synthetic(design, "sha256:declared", 10.0 + n, 100.0 / (n + 1),
                               **dict(zip(names, vals))))
    return gen_report.render(design, recs)


def _scale_key(design):
    """该顶层声明里 role 为 scale、且取值多于一个的参数名（唯一一个）。"""
    spec = gen_report.load_params_spec(design)
    keys = [k for k, v in spec.items()
            if v.get("role") == "scale" and len(v["values"]) > 1]
    assert len(keys) == 1, keys
    return keys[0]


def _front_sections(text):
    """返回 {前沿小标题: 该节的正文行}。标题按 `## 面积-延时 Pareto 前沿…` 匹配。"""
    out, cur = {}, None
    for ln in text.split("\n"):
        if ln.startswith(FRONT_HEADING):
            cur = ln
            out[cur] = []
        elif ln.startswith("## "):
            cur = None
        elif cur is not None:
            out[cur].append(ln)
    return out


def test_the_front_is_grouped_by_the_scale_dimension():
    """M1：`CBB_LZD` 的前沿必须按 `DAT_W` 分成五张表（早先是一个压缩流水按字数三张，2026-10-01 删除）。

    不分组时三行全是 `LANE_NUM=8` —— 256 位的 line 比 1024 位的少做四倍的活，
    它当然又小又快。那不是取舍，是同义反复（内部#44）。

    判据不是"有三张表"，而是**每张表里的点 `LANE_NUM` 都相同**：
    真正要防的是支配关系跨规模判，表的数目只是它的副产品。
    """
    sections = _front_sections(_render("CBB_LZD"))
    key = _scale_key("CBB_LZD")   # 位宽维度
    assert len(sections) == 5, (
        f"{key} 五档 = 五张表，实得 {len(sections)}：{list(sections)}")
    for heading, body in sections.items():
        assert key in heading, f"表头没写明这一组是哪个规模：{heading}"
        rows = [l for l in body if l.startswith("| ") and "---" not in l]
        col = [c.strip() for c in rows[0].split("|")].index(key)
        vals = {r.split("|")[col].strip() for r in rows[1:]}   # 跳过表头行
        assert len(vals) == 1, (
            f"同一张前沿表里出现了多个 {key} 取值 {vals} —— "
            f"支配关系跨规模判了，这正是 #44：{heading}")


def test_a_design_with_no_microarch_dimension_gets_no_front():
    """M2：`CBB_BIN2ONEHOT` 不该印前沿表（早先是一个组合地址子块，2026-10-01 删除）。

    它唯一的扫参维度 `DAT_W` 是 `scale`，分组之后每组只剩一个点。那样的"前沿"
    每张都是单行表 —— 印出来比不印更误导：它看起来像一个结论，实际上只是
    把每条记录各抄了一遍。
    """
    sections = _front_sections(_render("CBB_BIN2ONEHOT"))
    assert list(sections) == [FRONT_HEADING], (
        f"不该分组（分了每组只有一个点）：{list(sections)}")
    body = sections[FRONT_HEADING]
    # 查的是**没有表**，不是"整节消失"。标题留着，读者才找得到那句说明；
    # 整节静默消失与静默印错一样糟。
    assert not [l for l in body if l.startswith("| ")], (
        "没有任何微架构维度却印了前沿表 —— 每组只有一个点，"
        f"那张表看起来像结论，实际是把记录各抄一遍：{body}")
    assert "没有微架构维度" in "\n".join(body), (
        f"前沿不印了，但没说为什么：{body}")


def test_a_design_with_no_scale_dimension_keeps_one_front(monkeypatch):
    """M3：一个只有 microarch 维度的设计，前沿仍是一张表。

    分组不得波及本来就正确的设计。这条是分组改动的边界：它只在有 `scale`
    维度时才改变行为。

    ⚠️ **夹具是合成的，不是某个真设计。** 原来这条拿一个已删的解压流水当样本，
    因为它当时只声明了 `PIPE_STAGES`。2026-09-21 给它补了规模参数（内部#45 的 2.2）
    之后它有了 scale 维度，这条当场红 —— 而**在补声明的那一刻它还是绿的**，
    因为记录里还没有这个键（`scale_params()` 取的是「声明里有 ∩
    记录里出现过」）。也就是说它红得比根因晚了两个任务。
    换一个真设计解决不了：现在五个顶层**全都**有 scale 维度，再挑一个只是把同样的
    失效推到下一次有人给它补维度的时候。所以改成合成声明 + 合成记录。
    """
    spec = {"PIPE_STAGES": {"type": "enum", "role": "microarch", "values": [0, 1]}}
    monkeypatch.setattr(gen_report, "load_params_spec", lambda d, *a, **k: spec)
    recs = [
        _synthetic("ADDER32", None, 100.0, 1.0, PIPE_STAGES=0),
        _synthetic("ADDER32", None, 120.0, 0.8, PIPE_STAGES=1),
    ]
    sections = _front_sections(gen_report.render("ADDER32", recs))
    assert len(sections) == 1, f"没有 scale 维度却分了组：{list(sections)}"
    assert list(sections)[0] == FRONT_HEADING, (
        f"没有 scale 维度，标题不该带分组键：{list(sections)[0]}")
    rows = [l for l in sections[FRONT_HEADING] if l.startswith("| ") and "---" not in l]
    assert len(rows) - 1 == 2, (
        f"两个点都该在这唯一一张表里，实得 {len(rows) - 1} 行")


def test_grouping_does_not_empty_the_adder_front():
    """M5：`CBB_LZD` 分组后每组仍有多行，`FIFO_LIKE`（两个规模维度）是 2×3 = 6 张表。

    早先是 `ADDER32` 与一个地址流水设计（3×3 = 9 张），2026-10-01 删除。

    分组最容易出的错是**分组键取多了** —— 把 microarch 维度也算进去，
    于是每组只剩一个点，前沿全变成单行表而测试照样绿（每张表都"非空"）。
    所以这里查的是行数下界，不是表的存在。
    """
    adder = _front_sections(_render("CBB_LZD"))
    assert len(adder) == 5, f"位宽五档该有五张表：{list(adder)}"
    for heading, body in adder.items():
        rows = [l for l in body if l.startswith("| ") and "---" not in l]
        assert len(rows) - 1 >= 2, (
            f"{heading} 分组后只剩 {len(rows) - 1} 行 —— "
            "要么分组键把 microarch 维度也算进去了，要么记录不全")

    addr = _front_sections(_render("FIFO_LIKE"))
    assert len(addr) == 6, f"数据位宽两档 × 深度三档该有六张表：{list(addr)}"


# --- 任务 2.2：报告一顶层一份 + 读入集合不同的记录不同组 ----------------------

def _synthetic(design, digest, area, delay, **params):
    """一条够 render() 用的合成记录。digest 为 None 表示这一行没有 sources_sha256。"""
    synth = {"cell_count": 10, "area_um2": area, "critical_path_stages": 3,
             "critical_path_delay_ns": delay}
    if digest is not None:
        synth["sources_sha256"] = digest
    return {
        "experiment_id": f"{design}-" + "-".join(str(v) for v in params.values()) + "-deadbeef",
        "timestamp": "2026-09-20T00:00:00+00:00",
        "git_commit": "0" * 40,
        "flow": {"fingerprint": "sha256:same-generation-for-both"},
        "design": design,
        "params": params,
        "sim": {"passed": True, "cycles": 1, "total_toggles": 1},
        "synth": synth,
        "sta": {"clock_period_ns": 5.0, "slack_ns": 5.0 - delay,
                "fmax_mhz": 1000.0 / delay, "fmax_method": "analytic",
                "dynamic_power_w": 1e-6, "static_power_w": 1e-9},
        "ref_metrics": None,
    }


def test_the_report_file_is_named_after_the_top(tmp_path, monkeypatch, fixture_designs):
    """一个设计根挂两个顶层，报告就得是两份，文件名带顶层名。

    为什么值得有这条：收根之前根名等于顶层名，`REPORT.md` 这个名字不会撞；
    收根之后同一个根下可以有两个顶层（当时是一个压缩流水设计根下的压缩与解压，
    2026-10-02 起用夹具 `tests/fixtures/designs/shapes/` 的 SHAPE_COMB / SHAPE_REG1），
    两份报告写同一个文件名的话，后跑的那次**静默覆盖**先跑的那次 —— 没有任何工具会报错。
    """
    import json as _json

    log = tmp_path / "experiments.jsonl"
    log.write_text("\n".join(_json.dumps(r) for r in [
        _synthetic("SHAPE_REG1", None, 100.0, 1.0, DAT_W=8),
        _synthetic("SHAPE_REG1", None, 90.0, 1.2, DAT_W=8),
    ]) + "\n")
    # 写进临时设计根，不碰夹具那份 —— 这条用例第一次跑红时就往
    # 设计根里落了一个 REPORT.md，正是它要防的那种文件。
    root = tmp_path / "designs" / "shapes"
    root.mkdir(parents=True)
    monkeypatch.setattr(gen_report, "resolve_design_root", lambda d, r=None: root)

    out = gen_report.gen_report("SHAPE_REG1", log_path=log)
    assert out.name == "REPORT.SHAPE_REG1.md", (
        f"报告写到了 {out.name}，不是 REPORT.SHAPE_REG1.md —— "
        "同一个设计根下的第二个顶层会把第一个的报告覆盖掉")
    assert out.parent == root, f"写到了 {out.parent} —— 该在设计根下"


def test_records_that_read_different_sources_are_not_put_on_one_front():
    """同一代里 `synth.sources_sha256` 不同的记录不进同一张前沿表。

    为什么值得有这条：`flow` 指纹不含 RTL、也不含读入集合（它们是被测对象，
    不是流程），所以两条**指纹相同**的记录完全可能测的是两个不同的编译单元 ——
    本仓 内部#50 实测差到 2.5 倍。把它们放进同一条前沿，得到的取舍是假的，
    而报告上没有任何地方会提示这一点。
    """
    import json as _json

    # 顺序即 jsonl 的追加顺序。留哪一组与分代同一套规则：**最后一条所属的那组**。
    # 所以这里把要保留的 aaa 两条放在最后，被排除的 bbb 放在最前 ——
    # 那条恰好面积最小、延时最短，合进去必然落在前沿上，所以「有没有混进来」看得见。
    recs = [
        _synthetic("ADDER32", "sha256:bbb", 60.0, 0.5,
                   DAT_W=8, SCHEME="SKLANSKY", PIPE_STAGES=0, CSEL_BLK_W=4),
        _synthetic("ADDER32", "sha256:aaa", 100.0, 1.0,
                   DAT_W=8, SCHEME="RIPPLE", PIPE_STAGES=0, CSEL_BLK_W=4),
        _synthetic("ADDER32", "sha256:aaa", 120.0, 0.8,
                   DAT_W=8, SCHEME="CLA", PIPE_STAGES=0, CSEL_BLK_W=4),
    ]
    text = gen_report.render("ADDER32", recs)
    fronts = _front_sections(text)
    rows = "\n".join(l for body in fronts.values() for l in body)
    assert "SKLANSKY" not in rows, (
        "两条 sources_sha256 不同的记录进了同一张前沿表 —— "
        "指纹相同不代表读的是同一组源文件（本仓 #50）")
    assert "sources_sha256" in text or "读入" in text, (
        "被排除的记录必须在报告里说清楚，不能静默消失")
    _json  # noqa: F841


def test_an_unknown_source_set_is_not_lumped_in_with_a_known_one():
    """缺 `sources_sha256` 的历史记录与带摘要的新记录也不同组。

    1403 条历史行全部缺这个字段。把「未知」并进任何一个已知组，等于替它们
    断言「读的是同一组文件」，而那件事谁也不知道（experiment-record 的 MUST NOT）。
    反过来，两条都未知时**必须仍然同组** —— 否则历史记录会炸成一行一组，
    那不是谨慎，是把报告弄没了。
    """
    # 面积最小 —— 合进去的话它必然落在前沿上，所以「有没有混进来」看得见。
    # 取一个被支配的点当探针是没用的：它本来就不会出现在前沿表里。
    known = _synthetic("ADDER32", "sha256:aaa", 50.0, 1.5,
                       DAT_W=8, SCHEME="RIPPLE", PIPE_STAGES=0, CSEL_BLK_W=4)
    unknown_a = _synthetic("ADDER32", None, 120.0, 0.8,
                           DAT_W=8, SCHEME="CLA", PIPE_STAGES=0, CSEL_BLK_W=4)
    unknown_b = _synthetic("ADDER32", None, 90.0, 0.9,
                           DAT_W=8, SCHEME="SKLANSKY", PIPE_STAGES=0, CSEL_BLK_W=4)

    # 留最后一条所属的组 —— 这里是两条未知的那组。
    rows = "\n".join(l for body in _front_sections(
        gen_report.render("ADDER32", [known, unknown_a, unknown_b])).values()
        for l in body)
    assert "RIPPLE" not in rows, "未知与已知被并进了同一张前沿表"
    assert "CLA" in rows and "SKLANSKY" in rows, (
        "两条都未知的记录被拆开了 —— 历史记录会炸成一行一组")


# --- unify-rtl-naming 3.5：结构枚举显示成「编号 (名字)」（D14）-----------------------
#
# 2026-09-29 起结构枚举取整数，名字只在 params.yaml 的 labels 里。报告里光写 `1`
# 没人认得出是哪种结构，所以显示时补上名字；排序、分组、前沿判断仍按编号。

_LABELLED = {
    "SCHEME": {"type": "enum", "role": "microarch", "values": [0, 1, 2],
               "labels": {0: "RIPPLE", 1: "CLA", 2: "CSEL"}},
}


def test_labelled_scheme_is_shown_as_number_and_name(monkeypatch):
    monkeypatch.setattr(gen_report, "load_params_spec", lambda d, *a, **k: _LABELLED)
    recs = [
        _synthetic("ADDER32", None, 120.0, 0.8, SCHEME=1),   # 快但大
        _synthetic("ADDER32", None, 100.0, 1.0, SCHEME=0),   # 慢但小：两点都在前沿上
    ]
    text = gen_report.render("ADDER32", recs)
    full = [l for l in text.split("\n") if l.startswith("| 0 (RIPPLE) |") or l.startswith("| 1 (CLA) |")]
    front = "\n".join(l for body in _front_sections(text).values() for l in body)
    assert "| 1 (CLA) |" in front and "| 0 (RIPPLE) |" in front, front
    # 全量表与前沿表各一行；排序仍按编号：0 在 1 前面
    assert len(full) == 4, text
    assert full[0].startswith("| 0 (RIPPLE) |") and full[1].startswith("| 1 (CLA) |"), full


def test_values_without_a_label_are_shown_as_is(monkeypatch):
    """分界之前的字符串取值、labels 里没有的编号：原样显示，不报错。"""
    monkeypatch.setattr(gen_report, "load_params_spec", lambda d, *a, **k: _LABELLED)
    recs = [
        _synthetic("ADDER32", None, 120.0, 0.8, SCHEME="CLA"),
        _synthetic("ADDER32", None, 100.0, 1.0, SCHEME=7),
    ]
    text = gen_report.render("ADDER32", recs)
    assert "| CLA |" in text and "| 7 |" in text, text
    assert "(CLA)" not in text, "字符串取值不该再被补名字"


# --------------------------------------------------------------------------
# 三角（本仓 内部#61）：记录带 sta.corners 时报告要展示，且带 PVT
# --------------------------------------------------------------------------

CORNER_HEADING = "## SS / FF 两角"


def _corner_record(width, corners=True):
    rec = {
        "experiment_id": f"ADDER32-RIPPLE-{width}",
        "design": "ADDER32",
        "params": {"DAT_W": width, "SCHEME": "RIPPLE", "PIPE_STAGES": 2, "CSEL_BLK_W": 4},
        "flow": {"fingerprint": "sha256:" + "a" * 64},
        "synth": {"area_um2": 10.0 * width, "critical_path_delay_ns": 0.1 * width,
                  "sources_sha256": "sha256:" + "b" * 64},
        "sta": {"clock_period_ns": 5.0, "slack_ns": 5.0 - 0.1 * width, "fmax_mhz": 100.0,
                "dynamic_power_w": 1e-5, "static_power_w": 1e-8, "hold_slack_ns": 0.04},
    }
    if corners:
        rec["sta"]["corners"] = {
            "SS": {"pvt": {"voltage_v": 0.63, "temperature_c": 100.0},
                   "critical_path_delay_ns": 0.15 * width, "slack_ns": 5.0 - 0.15 * width,
                   "hold_slack_ns": 0.06, "static_power_w": 1.4e-7, "dynamic_power_w": 8e-6,
                   "fmax_mhz": 1.0, "fmax_method": "analytic"},
            "FF": {"pvt": {"voltage_v": 0.77, "temperature_c": 0.0},
                   "critical_path_delay_ns": 0.07 * width, "slack_ns": 5.0 - 0.07 * width,
                   "hold_slack_ns": 0.03125, "static_power_w": 9e-9, "dynamic_power_w": 1.3e-5,
                   "fmax_mhz": 2.0, "fmax_method": "analytic"},
        }
    return rec


def _section(text, heading):
    lines = text.split("\n")
    i = next(k for k, ln in enumerate(lines) if ln.startswith(heading))
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith("## "):
            break
        out.append(ln)
    return "\n".join(out)


def test_the_corner_section_shows_both_corners_with_their_pvt():
    text = gen_report.render("ADDER32", [_corner_record(8), _corner_record(16)])
    assert CORNER_HEADING in text, "记录带 sta.corners，报告里却没有角的表"
    sec = _section(text, CORNER_HEADING)
    # PVT 必须在：SS 漏电大是 100 °C 的缘故，不带温度会被读成「慢角漏电大」
    assert "0.63 V / 100 °C" in sec and "0.77 V / 0 °C" in sec
    assert "0.031250" in sec, "FF 的 hold 余量没进表"
    assert "1.400e-07" in sec, "SS 的静态功耗没进表"
    # 角的 fmax 是 analytic，与 TT 的 search 口径不同 —— 不进这张表，免得被并排排名
    assert "fmax" not in sec.split("\n|", 1)[1].split("\n")[0]


def test_records_without_corners_get_no_corner_section():
    text = gen_report.render("ADDER32", [_corner_record(8, corners=False)])
    assert CORNER_HEADING not in text


def test_a_record_without_corners_among_ones_with_them_shows_as_missing():
    text = gen_report.render("ADDER32", [_corner_record(8), _corner_record(16, corners=False)])
    sec = _section(text, CORNER_HEADING)
    # 列按参数名排序：改名（2026-09-28）之后 SCHEME 不再是第一列，所以按单元格找，不按行首
    rows = [ln for ln in sec.split("\n") if "| RIPPLE |" in ln]
    row8, row16 = (next(r for r in rows if f"| {w} |" in r) for w in (8, 16))
    assert gen_report.MISSING not in row8
    assert row16.endswith(" | ".join([gen_report.MISSING] * len(gen_report.CORNER_COLUMNS)) + " |")


# --- area-breakdown 1.2：每个配置一张面积拆分表（内部#174，design-report）---------------

def _with_breakdown(rec, memory=True):
    rec = json.loads(json.dumps(rec))
    rec["synth"]["area_breakdown"] = {
        "gate_unit": {"cell": "NAND2x1_ASAP7_75t_R", "area_um2": 0.08748},
        "sequential_area_um2": 40.0,
        "hierarchy": [
            {"path": "TOP", "level": 0, "module": "TOP", "instances": 1, "area_um2": 100.0,
             "cell_count": 900, "sequential_area_um2": 40.0},
            {"path": "TOP/BUF", "level": 1, "module": "BUF", "instances": 1, "area_um2": 70.0,
             "cell_count": 600, "sequential_area_um2": 35.0},
            {"path": "TOP/BUF/SRAM", "level": 2, "module": "SRAM", "instances": 2, "area_um2": 30.0,
             "cell_count": 200, "sequential_area_um2": 25.0},
            {"path": "TOP/BUF/(glue)", "level": 2, "module": None, "instances": 1, "area_um2": 40.0,
             "cell_count": 400, "sequential_area_um2": 10.0},
            {"path": "TOP/(glue)", "level": 1, "module": None, "instances": 1, "area_um2": 30.0,
             "cell_count": 300, "sequential_area_um2": 5.0},
        ],
        "memory_models": {"modules": ["SRAM"] if memory else [], "area_um2": 30.0 if memory else 0.0,
                          "sequential_area_um2": 25.0 if memory else 0.0},
    }
    return rec


def test_each_config_gets_an_area_breakdown_table():
    new = _with_breakdown(_synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8))
    old = _synthetic("FIFO_LIKE", "sha256:a", 50.0, 1.0, W=4)
    text = gen_report.render("FIFO_LIKE", [old, new])
    assert "## 面积拆分" in text
    sec = text.split("## 面积拆分", 1)[1]
    assert "| 层次 | 实例数 | 面积 µm² | 门数 | 单元数 | 时序面积 µm² | 组合面积 µm² | 占比 |" in sec
    # 门数 = 面积 ÷ 0.08748；组合 = 面积 − 时序；占比相对顶层
    assert "| TOP | 1 | 100.0 | 1,143 | 900 | 40.0 | 60.0 | 100.0% |" in sec
    assert "| 　　SRAM | 2 | 30.0 | 343 | 200 | 25.0 | 5.0 | 30.0% |" in sec
    assert "（本层胶合逻辑）" in sec
    assert "| 存储模型合计（SRAM） | — | 30.0 | 343 | — | 25.0 | 5.0 | 30.0% |" in sec
    assert "| **扣除存储模型后** | — | 70.0 | 800 | — | 15.0 | 55.0 | 70.0% |" in sec
    # 没有拆分的旧记录要说明，不能留空让人以为是 0
    assert "记录无面积拆分" in sec


def test_without_memory_models_there_is_no_deduction_row():
    rec = _with_breakdown(_synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8), memory=False)
    text = gen_report.render("FIFO_LIKE", [rec])
    assert "## 面积拆分" in text
    sec = text.split("## 面积拆分", 1)[1]
    assert "扣除存储模型后" not in sec and "存储模型合计" not in sec


def test_a_zero_cell_netlist_does_not_break_the_area_table():
    """零单元网表（CBB_ONEHOT2BIN DAT_W=2）顶层面积为 0：占比显示「—」，不除以 0。"""
    rec = _synthetic("FIFO_LIKE", "sha256:a", 0.0, 1.0, W=2)
    rec["synth"]["area_breakdown"] = {
        "gate_unit": {"cell": "NAND2x1_ASAP7_75t_R", "area_um2": 0.08748},
        "sequential_area_um2": 0.0,
        "hierarchy": [{"path": "TOP", "level": 0, "module": "TOP", "instances": 1, "area_um2": 0.0,
                       "cell_count": 0, "sequential_area_um2": 0.0}],
        "memory_models": {"modules": [], "area_um2": 0.0, "sequential_area_um2": 0.0},
    }
    sec = gen_report.render("FIFO_LIKE", [rec]).split("## 面积拆分", 1)[1]
    assert "| TOP | 1 | 0.0 | 0 | 0 | 0.0 | 0.0 | — |" in sec


# --- sta-scenarios：按场景的时序 ---------------------------------------------------

def _with_scenarios(rec, scen):
    rec["sta"]["scenarios"] = [
        {"name": n, "case": {"m": i}, "by": "R.021", "critical_path_delay_ns": d, "critical_path_stages": st,
         "fmax_mhz": 1000.0 / d, "fmax_method": "analytic", "slack_ns": 5.0 - d, "clocks": [],
         "corners": {"SS": {"critical_path_delay_ns": d * 1.5, "slack_ns": 5.0 - d * 1.5}}}
        for i, (n, d, st) in enumerate(scen)]
    return rec


def test_each_scenario_gets_its_own_columns():
    a = _with_scenarios(_synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8), [("case_a", 0.8, 20), ("case_b", 0.5, 12)])
    b = _with_scenarios(_synthetic("FIFO_LIKE", "sha256:a", 120.0, 2.0, W=16), [("case_a", 1.6, 30), ("case_b", 1.0, 18)])
    text = gen_report.render("FIFO_LIKE", [a, b])
    assert "## 按场景的时序" in text
    sec = text.split("## 按场景的时序", 1)[1].split("\n## ", 1)[0]
    assert "各场景最坏" in sec
    assert ("| W | 主 TT 延时 ns | case_a TT 延时 ns | case_a 级数 | case_a fmax MHz | case_a SS 延时 ns | case_a SS slack ns"
            " | case_b TT 延时 ns | case_b 级数 | case_b fmax MHz | case_b SS 延时 ns | case_b SS slack ns |") in sec
    assert "| 8 | 1.000000 | 0.800000 | 20 | 1250.0 | 1.200000 | 3.800000 | 0.500000 | 12 | 2000.0 | 0.750000 | 4.250000 |" in sec
    assert "| 16 | 2.000000 | 1.600000 | 30 | 625.0 |" in sec


@pytest.mark.parametrize("scen", [[], None])
def test_no_scenarios_no_section(scen):
    rec = _synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8)
    if scen is not None:
        rec["sta"]["scenarios"] = scen
    assert "按场景的时序" not in gen_report.render("FIFO_LIKE", [rec])


# --- reference-ppa：参考口径一节 ------------------------------------------------------

def _with_reference(rec, area, seq, fmax, stages, over):
    unit = {"cell": "NAND2x1_ASAP7_75t_R", "area_um2": 0.08748}
    top = {"path": "TOP", "level": 0, "module": "TOP", "instances": 1, "area_um2": rec["synth"]["area_um2"],
           "cell_count": 10, "sequential_area_um2": 40.0}
    rec["synth"]["area_breakdown"] = {"gate_unit": unit, "sequential_area_um2": 40.0, "hierarchy": [top],
                                      "memory_models": {"modules": [], "area_um2": 0.0, "sequential_area_um2": 0.0}}
    rec["reference"] = {
        "scenario": "case_a", "case": {"m": 1}, "delay_target_ps": None,
        "synth": {"cell_count": 5, "area_um2": area,
                  "area_breakdown": {"gate_unit": unit, "sequential_area_um2": seq, "hierarchy": [],
                                     "memory_models": {"modules": [], "area_um2": 0.0, "sequential_area_um2": 0.0}}},
        "sta": {"fmax_mhz": fmax, "critical_path_stages": stages, "critical_path_delay_ns": 1000.0 / fmax},
        "depth": {"stages": stages, "budget": 30, "over_budget_count": over}, "equiv": "PROVED"}
    return rec


def test_the_reference_section_lists_values_and_differences():
    rec = _with_reference(_synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8), 60.0, 30.0, 1250.0, 12, 0)
    text = gen_report.render("FIFO_LIKE", [rec])
    assert "## 参考口径" in text
    sec = text.split("## 参考口径", 1)[1].split("\n## ", 1)[0]
    assert "接成常数" in sec and "跨层次" in sec
    assert ("| W | 场景 | 等价 | 参考面积 µm² | 参考门数 | 参考时序面积 µm² | 参考 TT fmax MHz | 参考级数 | 超预算终点 "
            "| Δ面积 µm² | Δ时序面积 µm² | Δfmax MHz |") in sec
    # 门数 = 60 / 0.08748 = 686；Δ = 参考 − 正式：面积 60−100、时序 30−40、fmax 1250−1000
    assert "| 8 | case_a | 已证 | 60.0 | 686 | 30.0 | 1250.0 | 12 | 0 | -40.0 | -10.0 | 250.0 |" in sec


@pytest.mark.parametrize("ref", [None, "absent"])
def test_no_reference_no_section(ref):
    rec = _synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8)
    if ref is None:
        rec["reference"] = None
    assert "参考口径" not in gen_report.render("FIFO_LIKE", [rec])


def test_an_unproved_reference_is_listed_without_numbers():
    """内部#202 D10：reference.equiv 不是 PROVED 的配置只列场景与「未证等价（…），不报数」。"""
    rec = _synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8)
    rec["reference"] = {"scenario": "case_a", "case": {"m": 1}, "delay_target_ps": 100, "equiv": "UNDECIDED",
                        "equiv_log_path": "x.log"}
    text = gen_report.render("FIFO_LIKE", [rec])
    sec = text.split("## 参考口径", 1)[1].split("\n## ", 1)[0]
    assert "未证等价（UNDECIDED），不报数" in sec, sec
    assert "| case_a |" in sec, sec


def test_a_skipped_equivalence_is_reported_with_numbers():
    """equiv-optional D3（内部#232）：设计声明不做等价时 reference.equiv = SKIPPED，照常列数，「等价」列写「未经等价验证」。"""
    rec = _with_reference(_synthetic("FIFO_LIKE", "sha256:a", 100.0, 1.0, W=8), 60.0, 30.0, 1250.0, 12, 0)
    rec["reference"]["equiv"] = "SKIPPED"
    sec = gen_report.render("FIFO_LIKE", [rec]).split("## 参考口径", 1)[1].split("\n## ", 1)[0]
    assert "| 8 | case_a | 未经等价验证 | 60.0 | 686 |" in sec, sec
    assert "不报数" not in sec, sec


def test_default_reads_design_root_file_and_header_names_it(tmp_path, monkeypatch, fixture_designs):
    """内部#422：不给 log_path 时从全部设计根的记录文件读；报告头写本设计根的记录文件，不再写 results/experiments.jsonl。"""
    import json as _json
    from flow import records
    monkeypatch.setattr(records, "REPO_ROOT", tmp_path)
    f = tmp_path / "results" / "shapes" / "experiments.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(_json.dumps(_synthetic("SHAPE_REG1", None, 100.0, 1.0, DAT_W=8)) + "\n")
    root = tmp_path / "designs" / "shapes"
    root.mkdir(parents=True)
    monkeypatch.setattr(gen_report, "resolve_design_root", lambda d, r=None: root)
    text = gen_report.gen_report("SHAPE_REG1").read_text()
    assert "从 `results/shapes/experiments.jsonl` 生成" in text, text[:300]
    assert "results/experiments.jsonl" not in text
    assert "尚无实验数据" not in text
