"""外部耦合下的顶层组合环（io-comb-loops，内部#281）：端口归组、AXI 基线 + 显式声明的外部模型、SCC、LRS 允许表。

全部用合成的端口依赖，不跑 yosys；接到真网表上的用例在 tests/test_io_comb_deps.py。
"""
import pytest

from flow.check import io_comb_loops as icl

# 一个两侧的小顶层：S 侧 cmd / rdat，M 侧 cmd / wdat / rdat，外加一个中断与一个静态配置
PORTS = {
    "s_cmd_vld": "input", "s_cmd_dat": "input", "s_cmd_rdy": "output",
    "s_rdat_vld": "output", "s_rdat_dat": "output", "s_rdat_rdy": "input",
    "m_cmd_vld": "output", "m_cmd_dat": "output", "m_cmd_rdy": "input",
    "m_wdat_vld": "output", "m_wdat_rdy": "input",
    "m_rdat_vld": "input", "m_rdat_flg": "input", "m_rdat_rdy": "output",
    "alarm": "output", "cfg_en": "input", "clk": "input",
}
EXCLUDE = ["clk", "cfg_*"]


def _check(deps, rdy_dependent=(), decl=None, allowed=()):
    decl = dict(decl if decl is not None else {"no_peer": ["alarm"]})
    if rdy_dependent:
        decl["rdy_dependent"] = list(rdy_dependent)
    return icl.check(deps, PORTS, decl, EXCLUDE, list(allowed))


def test_issue_264_shape_needs_declaration():
    """内部#264：m_rdat_rdy 组合依赖对端的 flg，真实对端的 flg 又随我们的 rdy 变。声明 flg 后成环；不声明按 AXI 不成环。"""
    deps = {"m_rdat_rdy": {"m_rdat_flg"}}
    assert _check(deps)["passed"], "没声明时按 AXI，对方的数据不随本方 rdy 变"
    r = _check(deps, ["m_rdat_flg"])
    assert not r["passed"]
    assert r["peer_loops"][0]["ports"] == ["m_rdat_flg", "m_rdat_rdy"]
    assert r["peer_loops"][0]["internal"] == [("m_rdat_flg", "m_rdat_rdy")]
    assert r["peer_loops"][0]["allowed"] is None
    assert r["channel_loops"][0]["ports"] == ["m_rdat_flg", "m_rdat_rdy"]


def test_cross_channel_loop_fails_by_peer_but_not_by_channel():
    """m_cmd_vld 组合依赖 m_wdat_rdy：对方整体时对端的 wdat rdy 可依赖我们的 cmd vld → 成环；按通道不成环。"""
    r = _check({"m_cmd_vld": {"m_wdat_rdy"}})
    assert not r["passed"]
    assert r["peer_loops"][0]["ports"] == ["m_cmd_vld", "m_wdat_rdy"]
    assert r["channel_loops"] == [], "按通道时 m_cmd 与 m_wdat 不该互连"


def test_pass_through_is_not_a_loop():
    """S 进、M 出的组合直通（vld / 数据往前、rdy 往回）：按 AXI 两端的 vld 都不随 rdy 变，不成环。

    这是全连模型的误报来源：main 上 10 组都因旁路直通报出 51 个端口的大环（内部#281）。"""
    deps = {"m_cmd_dat": {"s_cmd_dat"}, "m_cmd_vld": {"s_cmd_vld"}, "s_cmd_rdy": {"m_cmd_rdy"}}
    r = _check(deps)
    assert r["passed"], r
    assert r["peer_loops"] == [] and r["channel_loops"] == []


def test_same_channel_handshake():
    """m_rdat_rdy 依赖 m_rdat_vld：AXI 下合法（rdy 可依赖 vld）；对端声明 vld 随 rdy 变时才成环。"""
    deps = {"m_rdat_rdy": {"m_rdat_vld"}}
    assert _check(deps)["passed"]
    assert not _check(deps, ["m_rdat_vld"])["passed"]


@pytest.mark.parametrize("pats,ok", [
    (["m_rdat_flg", "m_rdat_rdy"], True),
    (["m_rdat_*"], True),                               # 一个通配盖住环上全部端口
    (["m_rdat_flg"], False),                            # 少一个端口
    (["m_rdat_flg", "m_rdat_rdy", "m_cmd_rdy"], False),  # 多一个端口
])
def test_allowed_table_must_match_exactly(pats, ok):
    r = _check({"m_rdat_rdy": {"m_rdat_flg"}}, ["m_rdat_flg"], allowed=[(12, pats)])
    assert r["passed"] is ok
    assert (r["peer_loops"][0]["allowed"] == 12) is ok


def test_undeclared_ports_are_all_reported():
    with pytest.raises(icl.GroupError) as e:
        _check({}, decl={})
    assert "alarm" in str(e.value)
    ports = dict(PORTS, dfx_raw="output")
    with pytest.raises(icl.GroupError) as e:
        icl.check({}, ports, {}, EXCLUDE, [])
    assert "alarm" in str(e.value) and "dfx_raw" in str(e.value), "要一次全部报出"


def test_declared_peer_groups_ports_together():
    """peers 声明的端口自成一个对方；它的握手也按 AXI 基线连。"""
    ports = dict(PORTS, csr_req_vld="output", csr_req_rdy="input")
    decl = {"peers": {"csr": ["csr_*"]}, "no_peer": ["alarm"]}
    r = icl.check({"csr_req_vld": {"csr_req_rdy"}}, ports, decl, EXCLUDE, [])
    assert not r["passed"]
    assert r["peer_loops"][0]["ports"] == ["csr_req_rdy", "csr_req_vld"]
    r = icl.check({"csr_req_vld": {"csr_req_rdy"}}, ports, {"no_peer": ["alarm", "csr_*"]}, EXCLUDE, [])
    assert r["passed"]


def test_excluded_ports_need_no_declaration():
    r = _check({})
    assert r["passed"] and r["peer_loops"] == []


def test_bad_declaration_shape():
    with pytest.raises(icl.GroupError, match="peers"):
        _check({}, decl={"peer": {}})
    with pytest.raises(icl.GroupError, match="rdy_dependent"):
        _check({}, ["m_rdat_nosuch"])


def test_parse_allowed_table():
    text = """\
| 环上端口 | 理由 |
|---|---|
| `m_rdat_rdy`、`m_rdat_vld` | 写法示例 |
| `s_*` | 通配 |

| 别的表 | x |
|---|---|
| `m_cmd_vld` | 不读 |
"""
    assert icl.parse_allowed(text) == [(3, ["m_rdat_rdy", "m_rdat_vld"]), (4, ["s_*"])]
    assert icl.parse_allowed("没有表\n") == []
    with pytest.raises(icl.GroupError, match="第 3 行"):
        icl.parse_allowed("| 环上端口 |\n|---|\n| `a` 和 `b` |\n")
