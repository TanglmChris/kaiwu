"""io-comb-deps：顶层端口组合依赖检查（内部#266，flow/check/io_comb_deps.py）。"""
import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIX = REPO_ROOT / "tests" / "fixtures" / "iodeps"
needs_yosys = pytest.mark.skipif(shutil.which("yosys") is None, reason="yosys 不在 PATH")


@pytest.fixture(scope="module")
def mini_netlist(tmp_path_factory):
    from flow.check import io_comb_deps as icd
    return icd.export_netlist([FIX / "iodeps_mini.v"], "IODEPS_MINI", {},
                              tmp_path_factory.mktemp("iodeps"))


@pytest.fixture(scope="module")
def mini_deps(mini_netlist):
    from flow.check import io_comb_deps as icd
    return icd.port_deps(mini_netlist, "IODEPS_MINI", exclude=["clk", "rst_n", "cfg_*"])


@needs_yosys
def test_analysis_passthrough_is_reported(mini_deps):
    assert mini_deps["o_y"] == {"i_a"}, mini_deps


@needs_yosys
def test_analysis_handshake_dependence_is_reported(mini_deps):
    assert mini_deps["o_rdy"] == {"i_vld"}, mini_deps


@needs_yosys
def test_analysis_is_bitwise(mini_deps):
    # 字级的异或单元会把 i_c 连进 o_p；逐位之后只剩 i_d
    assert mini_deps["o_p"] == {"i_d"}, mini_deps


@needs_yosys
def test_analysis_registered_output_has_no_deps(mini_deps):
    assert mini_deps["o_q"] == set(), mini_deps


@needs_yosys
def test_analysis_excluded_ports_are_not_counted(mini_deps):
    assert mini_deps["o_r"] == {"i_f"}, mini_deps          # 复位不计
    assert mini_deps["o_s"] == set(), mini_deps            # 静态端口不计


@needs_yosys
def test_analysis_one_path_names_cells_with_src(mini_netlist):
    from flow.check import io_comb_deps as icd
    steps = icd.one_path(mini_netlist, "IODEPS_MINI", "o_rdy", "i_vld")
    assert steps, "o_rdy ← i_vld 应当找得到一条路径"
    assert any("iodeps_mini.v:" in s for s in steps), steps
    assert icd.one_path(mini_netlist, "IODEPS_MINI", "o_q", "i_e") is None


# --- 1.2：LRS 表的写法、比对、配置清单 -----------------------------------------------

LRS_OK = """\
# 某设计 LRS

### 5.7 端口之间的组合依赖

| 输出 | 允许组合依赖的输入 | 性质 |
|---|---|---|
| `o_rdy` | 无 | — |
| `o_y` | `i_a` | 直通 |
| `m_*` | `s_*`（同名） | 直通 |
| `o_p` | `MODE` 取 2 / 3 时：`i_d`；`MODE` 取 1 时：无 | 条件 |

后面的正文。
"""

PORTS_IN = {"i_a", "i_d", "i_vld", "s_dat", "s_strb"}
PORTS_OUT = {"o_rdy", "o_y", "o_p", "m_dat", "m_strb"}


def _rows(text=LRS_OK):
    from flow.check import io_comb_deps as icd
    return icd.parse_table(text)


def test_table_rows_are_parsed():
    rows = _rows()
    assert [r.outputs for r in rows] == [["o_rdy"], ["o_y"], ["m_*"], ["o_p"]]
    assert rows[0].segments == [(None, [])]
    assert rows[3].segments == [(("MODE", (2, 3)), ["i_d"]), (("MODE", (1,)), [])]


@pytest.mark.parametrize("cell", [
    "`i_a` 与 M 侧的同名字段",          # 反引号之外还有文字
    "另加 `i_d`",
])
def test_table_bad_cell_is_an_error_with_line(cell):
    from flow.check import io_comb_deps as icd
    text = LRS_OK.replace("| `o_y` | `i_a` | 直通 |", f"| `o_y` | {cell} | 直通 |")
    with pytest.raises(icd.TableError) as e:
        icd.parse_table(text)
    assert "第 8 行" in str(e.value), str(e.value)


def test_table_condition_without_colon_is_accepted():
    text = LRS_OK.replace("| `o_y` | `i_a` | 直通 |", "| `o_y` | `MODE` 取 2 时 `i_a` | 直通 |")
    assert _rows(text)[1].segments == [(("MODE", (2,)), ["i_a"])]


def test_table_must_exist_exactly_once():
    from flow.check import io_comb_deps as icd
    with pytest.raises(icd.TableError, match="没有"):
        icd.parse_table("# 空 LRS\n")
    with pytest.raises(icd.TableError, match="两张"):
        icd.parse_table(LRS_OK + "\n" + LRS_OK)


def _compare(deps, params=None, text=LRS_OK):
    from flow.check import io_comb_deps as icd
    return icd.compare(deps, icd.parse_table(text), params or {"MODE": 2}, PORTS_IN, PORTS_OUT)


def test_compare_clean_pass():
    res = _compare({"o_rdy": set(), "o_y": {"i_a"}, "m_dat": {"s_dat"}, "o_p": {"i_d"}})
    assert res.violations == [] and res.errors == [] and res.absent == [], res


def test_compare_declared_but_absent_is_only_a_hint():
    # 按表里的一对模式算：o_y ← i_a 一次都没出现才提示；m_* ← s_* 有 m_dat ← s_dat 就算出现过
    res = _compare({"m_dat": {"s_dat"}, "o_p": {"i_d"}})
    assert res.violations == [] and res.errors == [], res
    assert ("o_y", "i_a") in res.absent and not any(o.startswith("m_") for o, _ in res.absent), res


def test_compare_extra_dependency_fails():
    res = _compare({"o_rdy": {"i_vld"}, "o_y": {"i_a"}})
    assert ("o_rdy", "i_vld") in res.violations


def test_compare_same_name_binding():
    res = _compare({"m_dat": {"s_dat", "s_strb"}})
    assert ("m_dat", "s_strb") in res.violations
    assert ("m_dat", "s_dat") not in res.violations


def test_compare_condition_follows_config():
    assert _compare({"o_p": {"i_d"}}, {"MODE": 2}).violations == []
    assert ("o_p", "i_d") in _compare({"o_p": {"i_d"}}, {"MODE": 1}).violations


def test_compare_unknown_port_in_table_is_an_error():
    text = LRS_OK.replace("`i_a`", "`i_zz`")
    assert any("i_zz" in e for e in _compare({}, text=text).errors)


# --- handshake-depth-contracts 1.1：对外的同口 valid / 载荷不得放行同口 ready（内部#286）-------

SAME_IN = {"s_cmd_rdy", "m_wdat_rdy", "s_rdat_rdy"}
SAME_OUT = {"s_cmd_vld", "s_cmd_addr", "m_wdat_vld", "m_wdat_dat", "m_rdat_rdy"}


def _same(rows_md):
    from flow.check import io_comb_deps as icd
    text = "| 输出 | 允许组合依赖的输入 | 性质 |\n|---|---|---|\n" + rows_md
    return icd.compare({}, icd.parse_table(text), {}, SAME_IN, SAME_OUT)


def test_same_interface_valid_on_ready_is_an_error():
    res = _same("| `s_cmd_vld` | `s_cmd_rdy` | — |\n")
    assert any("s_cmd_vld" in e and "s_cmd_rdy" in e and "第 3 行" in e for e in res.errors), res


def test_same_interface_wildcard_payload_expands():
    res = _same("| `m_wdat_*` | `m_wdat_rdy` | — |\n")
    hits = [e for e in res.errors if "同口" in e]
    assert any("m_wdat_vld" in e for e in hits) and any("m_wdat_dat" in e for e in hits), res


def test_same_interface_ready_on_ready_is_allowed():
    res = _same("| `m_rdat_rdy` | `s_rdat_rdy` | — |\n")
    assert not any("同口" in e for e in res.errors), res


def test_configs_unknown_param_fails_before_yosys():
    from flow.check import io_comb_deps as icd
    with pytest.raises(icd.ConfigError, match="NOPE"):
        icd.validate_configs("TOP", [{"name": "a", "DAT_W": 8}, {"name": "b", "NOPE": 1}],
                             {"DAT_W": 32, "MODE": 1})


def test_configs_names_unique_and_nonempty():
    from flow.check import io_comb_deps as icd
    with pytest.raises(icd.ConfigError, match="重复"):
        icd.validate_configs("TOP", [{"name": "a"}, {"name": "a"}], {})
    with pytest.raises(icd.ConfigError, match="iodeps_configs"):
        icd.validate_configs("TOP", None, {})


@needs_yosys
def test_configs_missing_list_fails_from_cli(capsys):
    from flow.check import io_comb_deps as icd
    assert icd.main(["--design", "CBB_LZD"]) != 0           # CBB_LZD 没有声明 iodeps_configs
    assert "iodeps_configs" in capsys.readouterr().err


# --- 1.3：专用设计的配置清单 -------------------------------------------------------------

def test_iodeps_configs_are_not_in_design_recipe(tmp_path):
    """端口组合依赖的配置清单只供检查用，不进设计配方（不换代）。
    原先在真实的大设计上验，开源拆分时改成在临时设计根上声明（内部#305）。"""
    from flow import flow_fingerprint as ff
    root = tmp_path / "designs" / "foo"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "foo.v").write_text("module FOO (input wire i_a, output wire o_y); assign o_y = i_a; endmodule\n")
    (root / "params.yaml").write_text(
        "design_root: foo\ntops:\n  FOO:\n    sim: {clock_signal: null}\n    sta: {ideal_drive_ports: []}\n"
        "    params: {}\n    iodeps_configs:\n      - {name: app, params: {}}\n")
    recipe = ff.design_recipe("FOO", repo_root=tmp_path)
    assert recipe, "夹具没解析出设计配方"
    assert "iodeps" not in json.dumps(recipe)


def test_doc_example_table_parses():
    """docs/spec-writing.md §3.2 的示例表必须是工具读得懂的写法（文档与工具不能各说各话）。"""
    from flow.check import io_comb_deps as icd
    rows = icd.parse_table((REPO_ROOT / "docs" / "spec-writing.md").read_text())
    assert [r.outputs for r in rows] == [["s_cmd_rdy"], ["m_wdat_*"], ["m_rdat_rdy"]]
    assert rows[2].segments == [(("M_RDAT_MODE", (1,)), ["s_rdat_rdy"]), (("M_RDAT_MODE", (2, 3)), [])]


def test_table_semicolon_inside_note_is_not_a_segment():
    """括号里的说明可以带「；」，不能被当成分段（1.3 用一张真实的大表实跑时撞到）。"""
    text = LRS_OK.replace("| `o_y` | `i_a` | 直通 |", "| `o_y` | `i_a`（说明一；说明二） | 直通 |")
    assert _rows(text)[1].segments == [(None, ["i_a"])]


# --- 外部耦合下的组合环（io-comb-loops 1.2，内部#281） ---------------------------------

LOOP_LRS = """\
| 输出 | 允许组合依赖的输入 |
|---|---|
| `m_c_*` | `s_c_*` |
| `s_c_rdy` | `m_c_rdy` |
| `m_r_rdy` | `m_r_flg`、`s_r_rdy` |
"""


def _loop_setup(decl, allowed=()):
    """白名单表把夹具的依赖全部允许，结果只由环检查决定。"""
    from flow.check import io_comb_deps as icd
    return dict(sources=[FIX / "iodeps_loop.v"], incs=[], rtl_params={}, exclude=["clk"],
                rows=icd.parse_table(LOOP_LRS), loops_decl=decl, loops_allowed=list(allowed))


@needs_yosys
@pytest.mark.parametrize("declared", [True, False])
def test_loops_run_config_reports_issue_264_shape(tmp_path, declared):
    from flow.check import io_comb_deps as icd
    decl = {"rdy_dependent": ["m_r_flg"]} if declared else {}
    r = icd.run_config("IODEPS_LOOP", _loop_setup(decl), "cfg", {}, tmp_path)
    assert "peer_loops" in r and "channel_loops" in r, r
    if declared:
        assert not r["passed"]
        assert [l["ports"] for l in r["peer_loops"]] == [["m_r_flg", "m_r_rdy"]], r["peer_loops"]
        text = icd._report(r, False)
        assert "组合环" in text and "m_r_flg" in text and "m_r_rdy" in text, text
    else:
        assert r["passed"], "没声明时按 AXI 基线：S → M 的组合直通与 m_r_rdy ← m_r_flg 都不成环"
        assert r["peer_loops"] == []
    saved = json.loads((tmp_path / "cfg" / "result.json").read_text())
    assert saved["peer_loops"] == json.loads(json.dumps(r["peer_loops"]))
    assert not r["violations"] and not r["loop_errors"], r


@needs_yosys
def test_loops_allowed_by_lrs_table_passes(tmp_path):
    from flow.check import io_comb_deps as icd
    r = icd.run_config("IODEPS_LOOP", _loop_setup({"rdy_dependent": ["m_r_flg"]}, [(9, ["m_r_*"])]),
                       "cfg", {}, tmp_path)
    assert r["passed"], r
    assert r["peer_loops"][0]["allowed"] == 9


@needs_yosys
def test_loops_undeclared_port_fails_the_config(tmp_path):
    from flow.check import io_comb_deps as icd
    setup = _loop_setup({})
    setup["exclude"] = []                                  # clk 不排除 → 它按前缀分不进组
    r = icd.run_config("IODEPS_LOOP", setup, "cfg", {}, tmp_path)
    assert not r["passed"]
    assert any("clk" in e for e in r["loop_errors"]), r


def test_loops_doc_example_allowed_table_parses():
    from flow.check import io_comb_loops as icl
    rows = icl.parse_allowed((REPO_ROOT / "docs" / "spec-writing.md").read_text())
    assert rows and all(p for _, p in rows), rows


# --- 内部#338 iodeps-coverage：配置清单覆盖条件段与开关的每个取值 -------------------------
# LRS_OK 的条件段是 MODE 取 2 / 3、取 1；RTL 默认 MODE=2。声明的参数照专用设计 params.yaml 的形态：
# 开关 *_EN 带 values，非开关的 NUM 带 values。

RTL = {"MODE": 2, "CHK_EN": 1, "PT_EN": 0, "NUM": 16}
DECL = {"CHK_EN": [1, 0], "PT_EN": [0], "NUM": [16, 2]}


def _cov(configs, decl=DECL):
    from flow.check import io_comb_deps as icd
    return icd.coverage(_rows(), configs, RTL, decl)


def test_coverage_names_the_uncovered_condition_value_with_its_line():
    errors, _ = _cov([("a", {"MODE": 1, "CHK_EN": 0}), ("b", {})])          # MODE 取到 1、2（默认），缺 3
    assert len(errors) == 1 and "第 10 行" in errors[0] and "`MODE` 取 3" in errors[0], errors


def test_coverage_counts_rtl_defaults():
    errors, _ = _cov([("a", {"MODE": 1}), ("b", {"MODE": 3, "CHK_EN": 0}), ("c", {})])   # 2 只靠 c 的 RTL 默认值取到
    assert errors == [], errors


def test_coverage_switch_missing_one_side_is_an_error():
    errors, _ = _cov([("a", {"MODE": 1}), ("b", {"MODE": 3}), ("c", {})])    # CHK_EN 从没取 0
    assert any("`CHK_EN` 取 0" in e for e in errors), errors
    assert not any("PT_EN" in e for e in errors), errors                      # 只许取 0 的开关只要求 0


def test_coverage_non_switch_gap_is_only_a_hint():
    errors, hints = _cov([("a", {"MODE": 1, "CHK_EN": 0}), ("b", {"MODE": 3}), ("c", {})])
    assert errors == [], errors
    assert any("`NUM` 取 2" in h for h in hints), hints


def test_coverage_is_judged_on_the_whole_list_even_with_config_subset(tmp_path, monkeypatch, capsys):
    """--config 只跑一组时，覆盖仍按整份清单算；有缺口就以非 0 退出，即使跑的那组 PASS。"""
    from flow.check import io_comb_deps as icd
    lrs = tmp_path / "lrs.TOP.md"
    lrs.write_text(LRS_OK)
    setup = dict(configs=[("a", {"MODE": 1}), ("b", {"MODE": 3}), ("c", {})], rtl_params=RTL, declared=DECL,
                 lrs=lrs, exclude=[], loops_decl={})
    monkeypatch.setattr(icd, "design_setup", lambda design: dict(setup))
    ran = []

    def fake_run(design, s, name, params, outdir, deps_only=False, keep_netlist=False):
        ran.append(name)
        return dict(name=name, params=params, deps={}, violations=[], absent=[], errors=[],
                    peer_loops=[], channel_loops=[], loop_errors=[], passed=True)
    monkeypatch.setattr(icd, "run_config", fake_run)
    monkeypatch.setattr(icd, "_report", lambda r, deps_only: f"== {r['name']} PASS")
    rc = icd.main(["--design", "TOP", "--config", "a", "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert ran == ["a"], ran
    assert rc != 0, out
    assert "`CHK_EN` 取 0" in out and "覆盖缺口 1" in out, out


# --- 通用构件只有精简规格（内部#415，io-comb-deps「LRS 必须用固定写法声明接口组合依赖」）-------------------
# cbb/ 下的构件按 flow/templates/cbb-root/ 只写 spec.<顶层>.md，不写 LRS；表的写法相同，只换读哪份文档。

def test_interface_doc_falls_back_to_the_cbb_spec(tmp_path):
    from flow.check import io_comb_deps as icd
    (tmp_path / "spec.TOP.md").write_text("# TOP\n")
    assert icd.interface_doc(tmp_path, "TOP") == tmp_path / "spec.TOP.md"


def test_interface_doc_prefers_the_lrs(tmp_path):
    from flow.check import io_comb_deps as icd
    (tmp_path / "spec.TOP.md").write_text("# TOP\n")
    (tmp_path / "lrs.TOP.md").write_text("# TOP\n")
    assert icd.interface_doc(tmp_path, "TOP") == tmp_path / "lrs.TOP.md"


def test_interface_doc_without_either_points_at_the_lrs(tmp_path):
    from flow.check import io_comb_deps as icd
    assert icd.interface_doc(tmp_path, "TOP") == tmp_path / "lrs.TOP.md"


def _spec_only_setup(tmp_path, monkeypatch, text):
    from flow.check import io_comb_deps as icd
    (tmp_path / "spec.TOP.md").write_text(text)
    setup = dict(configs=[("a", {"MODE": 1, "CHK_EN": 0}), ("b", {"MODE": 3}), ("c", {})], rtl_params=RTL,
                 declared=DECL, lrs=icd.interface_doc(tmp_path, "TOP"), exclude=[], loops_decl={})
    monkeypatch.setattr(icd, "design_setup", lambda design: dict(setup))
    monkeypatch.setattr(icd, "run_config", lambda design, s, name, params, outdir, deps_only=False, keep_netlist=False:
                        dict(name=name, params=params, deps={}, violations=[], absent=[], errors=[],
                             peer_loops=[], channel_loops=[], loop_errors=[], passed=True))
    monkeypatch.setattr(icd, "_report", lambda r, deps_only: f"== {r['name']} PASS")
    return icd


def test_the_table_is_read_from_the_cbb_spec(tmp_path, monkeypatch, capsys):
    icd = _spec_only_setup(tmp_path, monkeypatch, "# TOP\n\n## 接口组合依赖\n\n" + LRS_OK)
    rc = icd.main(["--design", "TOP", "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert "覆盖检查（#338）：缺口 0" in out, out
    assert rc == 0, out


def test_a_cbb_spec_without_the_table_names_the_file(tmp_path, monkeypatch, capsys):
    icd = _spec_only_setup(tmp_path, monkeypatch, "# TOP\n\n## 功能\n\n没有表。\n")
    rc = icd.main(["--design", "TOP", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 2, err
    assert "spec.TOP.md" in err and "接口组合依赖表" in err, err
