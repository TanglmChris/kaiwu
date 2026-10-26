"""`scripts/fast_check.sh` 的用例：端口表（规划端口表、过渡端口表、spec 端口表与 RTL、cbb 依赖）。

内部#336 从 tests/test_fast_check.py 按小节拆出，用例原样；夹具在 tests/fast_check_fixture.py。
"""
from fast_check_fixture import *  # noqa: F401,F403


# --- 规划端口表（内部#112，flow-guard-feedback D3）---------------------------------------

def _planned_fixture(tmp_path, planned, formal_extra=()):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    table = ("\n### 规划\n\n| 规划信号 | 方向 | 位宽 | 含义 |\n|---|---|---|---|\n"
             + "".join(f"| `{n}` | in | 1 | 还没有 RTL |\n" for n in planned))
    _write_docs(tmp_path / "designs" / "foo", "FOO", _good_spec("FOO", formal_extra) + table)
    return script


@needs_verilator
@pytest.mark.parametrize("planned", [["s_new_vld"], ["i_a"]])
def test_planned_ports_do_not_take_part_in_the_comparison(tmp_path, planned):
    """内部#112：规划信号表不参与比对 —— 还没有 RTL 的新端口，或现有端口的规划形态（与正式表同名），都照样通过。"""
    r = _run(_planned_fixture(tmp_path, planned))
    assert r.returncode == 0, r.stdout + r.stderr


@needs_verilator
def test_an_rtl_port_left_only_in_the_planned_table_fails(tmp_path):
    """内部#112：RTL 顶层已有、却只写在规划信号表里的端口，失败并点名，提示移进正式表。"""
    if True:
        script = _fixture_repo(tmp_path, GOOD_PARAMS)
        (tmp_path / "designs" / "foo" / "rtl" / "foo.v").write_text(UNUSED_CLK_RTL)
        _style_exempt(tmp_path, "designs/foo/rtl/foo.v")
        (tmp_path / "flow" / "lint").mkdir(parents=True, exist_ok=True)
        (tmp_path / "flow" / "lint" / "waivers.vlt").write_text(CLK_WAIVER)
        table = ("\n### 规划\n\n| 规划信号 | 方向 | 位宽 | 含义 |\n|---|---|---|---|\n"
                 "| `clk` | in | 1 | x |\n")
        _write_docs(tmp_path / "designs" / "foo", "FOO", _good_spec("FOO") + table)
        needle = "clk"
    r = _run(script)
    assert r.returncode != 0, r.stdout
    assert "规划信号" in r.stderr + r.stdout and needle in r.stderr + r.stdout, r.stdout + r.stderr
    assert "移进正式端口表" in r.stderr + r.stdout, r.stdout + r.stderr


# --- 集成期的过渡端口表（内部#119，integration-port-doc D1–D3）-------------------------------

def _port_doc_fixture(tmp_path, track=None):
    """LRS 写最终接口（多一个还没实现的 s_future），过渡端口表写 RTL 现在的端口。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path / "designs" / "foo"
    (root / "params.yaml").write_text(_as_tops(GOOD_PARAMS, "FOO") + "    port_doc: doc/track.FOO.md\n")
    _write_docs(root, "FOO", _good_spec("FOO", ("s_future",)))
    if track is not None:
        (root / "doc").mkdir(exist_ok=True)
        (root / "doc" / "track.FOO.md").write_text("# 跟踪\n\n## 4. 过渡端口表\n\n" + track)
    return script


@needs_iverilog
def test_port_doc_is_compared_instead_of_the_lrs(tmp_path):
    """内部#119：声明了 port_doc 的顶层按跟踪文档比对端口，LRS 写的最终接口不参与；摘要写明用的哪份。"""
    r = _run(_port_doc_fixture(tmp_path, _good_spec("FOO")))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "FOO 按 doc/track.FOO.md" in r.stdout, out


@needs_iverilog
def test_port_doc_missing_fails(tmp_path):
    """内部#119：port_doc 指向的文件不存在时失败并点名。"""
    r = _run(_port_doc_fixture(tmp_path, None))
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "doc/track.FOO.md" in out, out


@needs_iverilog
def test_port_doc_mismatch_fails(tmp_path):
    """内部#119：跟踪文档的端口表与 RTL 不一致，照样失败并点名端口。"""
    track = "| 信号 | 方向 | 位宽 | 含义 |\n|---|---|---|---|\n| `i_a` | in | `DAT_W` | x |\n"
    r = _run(_port_doc_fixture(tmp_path, track))
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "RTL 有、文档无：o_y" in out, out



# --- spec 端口表与 RTL 一致（guardrail-scope 的「秒级护栏必须检查 spec 端口表
# 与 RTL 一致」）-----------------------------------------------------------------
#
# 设计内部改动不走 OpenSpec（内部#58），`spec.<顶层>.md` 是接口契约唯一的权威。
# 2026-09-27 首次全量比对，6 个顶层里已有 2 个的 spec 悄悄过时：
# 一个把 `32*LANE_NUM` 写成 512，另一个把
# `CNT_W` 写成 2 —— 之前没有任何东西失败。这里用真 iverilog：被测的正是
# 「从 elaborate 的 vvp 里读出的端口」这条路径。



def _spec_rows(*rows, header="| 信号 | 方向 | 位宽 | 含义 |"):
    body = "\n".join(f"| `{n}` | {d} | `{w}` | x |" if header.startswith("| 信号")
                     else f"| {d} | `{n}` | `{w}` | x |" for n, d, w in rows)
    return f"# FOO\n\n## 接口\n\n{header}\n|---|---|---|---|\n{body}\n"


def _port_fixture(tmp_path, spec_text):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _write_docs(tmp_path / "designs" / "foo", "FOO", spec_text)
    return script


@needs_iverilog
def test_port_width_fixed_value_mismatches_one_combo(tmp_path):
    r, out = _port_run(_port_fixture(tmp_path, _spec_rows(("i_a", "in", "DAT_W"), ("o_y", "out", "4"))))
    assert PORT_FAIL in out, f"应报「{PORT_FAIL}」，实际输出：\n{out}"
    assert "FOO" in out and "o_y" in out and "DAT_W=8" in out, out
    assert r.returncode != 0


@needs_iverilog
def test_port_missing_from_spec_fails(tmp_path):
    r, out = _port_run(_port_fixture(tmp_path, _spec_rows(("i_a", "in", "DAT_W"))))
    assert PORT_FAIL in out, f"应报「{PORT_FAIL}」，实际输出：\n{out}"
    assert "RTL 有、文档无" in out and "o_y" in out, out
    assert r.returncode != 0


@needs_iverilog
def test_port_in_spec_but_not_in_rtl_fails(tmp_path):
    r, out = _port_run(_port_fixture(tmp_path, _spec_rows(
        ("i_a", "in", "DAT_W"), ("o_y", "out", "DAT_W"), ("o_z", "out", "1"))))
    assert PORT_FAIL in out, f"应报「{PORT_FAIL}」，实际输出：\n{out}"
    assert "文档有、RTL 无" in out and "o_z" in out, out
    assert r.returncode != 0


@needs_iverilog
def test_port_direction_reversed_fails(tmp_path):
    r, out = _port_run(_port_fixture(tmp_path, _spec_rows(("i_a", "in", "DAT_W"), ("o_y", "in", "DAT_W"))))
    assert PORT_FAIL in out, f"应报「{PORT_FAIL}」，实际输出：\n{out}"
    assert "方向" in out and "o_y" in out, out
    assert r.returncode != 0


@needs_iverilog
@pytest.mark.parametrize("width", ["同上", "NO_SUCH_PARAM"])
def test_port_width_that_cannot_be_evaluated_fails(tmp_path, width):
    r, out = _port_run(_port_fixture(tmp_path, _spec_rows(("i_a", "in", "DAT_W"), ("o_y", "out", width))))
    assert PORT_FAIL in out, f"应报「{PORT_FAIL}」，实际输出：\n{out}"
    assert "求不出值" in out and width in out, out
    assert r.returncode != 0


@needs_iverilog
def test_spec_file_missing_fails(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "lrs.FOO.md").unlink()
    r, out = _port_run(script)
    assert PORT_FAIL in out, f"应报「{PORT_FAIL}」，实际输出：\n{out}"
    assert "lrs.FOO.md" in out, out
    assert r.returncode != 0


@needs_iverilog
@pytest.mark.parametrize("header", ["| 信号 | 方向 | 位宽 | 含义 |", "| 方向 | 端口 | 宽度 | 说明 |"])
def test_port_table_all_consistent_passes_with_either_header(tmp_path, header):
    spec = _spec_rows(("i_a", "in", "DAT_W"), ("o_y", "out", "$clog2(DAT_W*DAT_W)*DAT_W/2"), header=header)
    # $clog2(W*W)*W/2：W=4 → 4*4/2=8？不对 —— 这里要等于 W：clog2(16)=4，4*4/2=8≠4。
    # 所以用一个恒等于 W 的写法来测求值器：(W+W)/2
    spec = _spec_rows(("i_a", "in", "DAT_W"), ("o_y", "out", "(DAT_W+DAT_W)/2"), header=header)
    r, out = _port_run(_port_fixture(tmp_path, spec))
    assert r.returncode == 0, out
    assert f"ok    {PORT_CHECK}" in out, out
    assert f"已执行  {PORT_CHECK}（1 个顶层，2 个参数组合）" in out, out


@needs_iverilog
def test_clog2_in_width_is_evaluated(tmp_path):
    rtl = tmp_path / "designs" / "foo" / "rtl"
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (rtl / "foo.v").write_text(
        "module FOO #(parameter DAT_W = 4) (input wire [DAT_W-1:0] i_a, output wire [$clog2(DAT_W)-1:0] o_y);\n"
        "  assign o_y = i_a[$clog2(DAT_W)-1:0];\nendmodule\n")
    _write_docs(tmp_path / "designs" / "foo", "FOO",
                _spec_rows(("i_a", "in", "DAT_W"), ("o_y", "out", "$clog2(DAT_W)")))
    r, out = _port_run(script)
    assert f"ok    {PORT_CHECK}" in out, out


# --- 设计根声明对 cbb 构件的依赖（add-design-cbb-deps）------------------------------
#
# IP 在 designs/ 下，例化的构件在 cbb/ 下。fast_check 以前只读设计根自己的 rtl/*.v，
# IP 一例化构件就 elaborate 失败；现在按 params.yaml 的 deps 与综合同口径读入。

FOO_USES_BAR = """\
module FOO #(parameter DAT_W = 4) (input wire [DAT_W-1:0] i_a, output wire [DAT_W-1:0] o_y);
  CBB_BAR #(.DAT_W(DAT_W)) U_FOO_CBB_BAR (.i_a(i_a), .o_y(o_y));
endmodule
"""


def _cbb_root(root, name, top, rtl):
    d = root / "cbb" / name
    (d / "rtl").mkdir(parents=True)
    (d / "rtl" / f"{name}.v").write_text(rtl)
    (d / "params.yaml").write_text(_as_tops(GOOD_PARAMS, top))
    (d / f"spec.{top}.md").write_text(_good_spec(top))
    return d


def _deps_fixture(tmp_path, deps, bar_rtl=None):
    """designs/foo 的 FOO 例化 cbb/cbb_bar 的 CBB_BAR；`deps` 写进 FOO 的声明。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS + (f"deps: [{', '.join(deps)}]\n"
                                                     if deps else ""))
    root = script.parent.parent
    (root / "designs" / "foo" / "rtl" / "foo.v").write_text(FOO_USES_BAR)
    _style_exempt(root, "designs/foo/rtl/foo.v")           # 例化关系才是被测对象
    _cbb_root(root, "cbb_bar", "CBB_BAR",
              bar_rtl or _good_rtl("CBB_BAR", "cbb/cbb_bar/spec.CBB_BAR.md"))
    return script, root


@needs_iverilog
def test_deps_let_an_ip_elaborate_and_lint_a_cbb_module(tmp_path):
    script, _ = _deps_fixture(tmp_path, ["CBB_BAR"])
    r = _run(script)
    assert r.returncode == 0, r.stdout
    assert "ok    elaborate FOO (all param combos)" in r.stdout
    assert "ok    lint FOO (all param combos)" in r.stdout


@needs_iverilog
def test_deps_missing_is_a_failure_naming_the_module(tmp_path):
    script, _ = _deps_fixture(tmp_path, [])
    r = _run(script)
    assert r.returncode != 0
    assert "FAIL  elaborate FOO" in r.stdout
    assert "CBB_BAR" in r.stdout, r.stdout


@needs_iverilog
def test_candidates_match_the_flow_for_transitive_and_misspelled_deps(tmp_path):
    """fast_check 与流程用同一张候选表：传递依赖读得进来，拼错的 deps 报的是同一句错。"""
    # CBB_BAR 自己例化 CBB_BAZ，只有 CBB_BAR 声明了 deps: [CBB_BAZ]
    script, root = _deps_fixture(tmp_path, ["CBB_BAR"], bar_rtl="""\
module CBB_BAR #(parameter DAT_W = 4) (input wire [DAT_W-1:0] i_a, output wire [DAT_W-1:0] o_y);
  CBB_BAZ #(.DAT_W(DAT_W)) U_CBB_BAR_CBB_BAZ (.i_a(i_a), .o_y(o_y));
endmodule
""")
    (root / "cbb" / "cbb_bar" / "params.yaml").write_text(
        _as_tops(GOOD_PARAMS + "deps: [CBB_BAZ]\n", "CBB_BAR"))
    _cbb_root(root, "cbb_baz", "CBB_BAZ", _good_rtl("CBB_BAZ", "cbb/cbb_baz/spec.CBB_BAZ.md"))
    _style_exempt(root, "cbb/cbb_bar/rtl/cbb_bar.v")
    r = _run(script)
    assert r.returncode == 0 and "ok    elaborate FOO (all param combos)" in r.stdout, (
        "传递依赖没被 fast_check 读进来 —— 它用的 candidates 与流程不同：\n" + r.stdout)

    (root / "designs" / "foo" / "params.yaml").write_text(
        _as_tops(GOOD_PARAMS + "deps: [CBB_BRA]\n", "FOO"))
    r = _run(script)
    assert r.returncode != 0
    assert "不是任何设计根声明的顶层" in r.stdout and "CBB_BRA" in r.stdout, (
        "拼错的 deps 没按 rtl_candidates 的报错失败 —— candidates 口径不同：\n" + r.stdout)
