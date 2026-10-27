"""`scripts/fast_check.sh` 的用例：设计文档（draw.io 图、review/、LRS / LLD、旧格式退役、接口分节、lld-restructure、内部#253、内部#226、内部#331）。

内部#336 从 tests/test_fast_check.py 按小节拆出，用例原样；夹具在 tests/fast_check_fixture.py。
"""
from fast_check_fixture import *  # noqa: F401,F403


# --- 设计根的 draw.io 图（内部#119 补充，integration-port-doc D4）----------------------------

@pytest.mark.parametrize("files, ok, needle", [
    (("arch.drawio", "arch.svg"), True, None),
    (("arch.svg",), False, "arch.svg"),
    (("arch.drawio", "arch.png"), False, "arch.png"),
])
def test_doc_takes_drawio_and_svg_with_source(tmp_path, files, ok, needle):
    """doc/ 收 .drawio 与由它导出的 .svg；.svg 没有同名 .drawio 失败；PNG 仍不收。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    doc = tmp_path / "designs" / "foo" / "doc"
    doc.mkdir()
    for f in files:
        (doc / f).write_text("<x/>\n")
    r = _run_with_path(script, stub=STUB_OK)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0, out
    else:
        assert r.returncode != 0, out
        assert needle in out, out


# --- 设计根的评审记录 review/（2026-10-15 闭源切换 1.1，内部#305）--------------------------

REVIEW_DOCS = ("a.md", "b.diff", "c.patch", "d.html", "e.svg", "e.drawio")


@pytest.mark.parametrize("extra, ok, needle", [
    ((), True, None),
    (("run.log",), False, "run.log"),
    (("x.json",), False, "x.json"),
    (("lone.svg",), False, "lone.svg"),
])
def test_review_takes_documents_only(tmp_path, extra, ok, needle):
    """review/ 下一次评审一个子目录，只收文档；日志、JSON 之类的证据不收，.svg 照旧要同名 .drawio。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    r1 = tmp_path / "designs" / "foo" / "review" / "r1"
    r1.mkdir(parents=True)
    for f in REVIEW_DOCS + extra:
        (r1 / f).write_text("<x/>\n")
    r = _run_with_path(script, stub=STUB_OK)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0, out
    else:
        assert r.returncode != 0, out
        assert needle in out, out
        if not needle.endswith(".svg"):
            assert "review/ 只收文档" in out, out


@needs_verilator
def test_the_real_repo_is_lint_clean_under_its_waivers():
    """本仓全部参数组合在 flow/lint/waivers.vlt 之下 lint 干净 —— 也就是 fast_check 本身的那一项。

    直接跑一个代表组合就够判定「豁免文件能被解析」：以 `// verilator` 开头的注释会被
    当成元指令、整份文件报 syntax error（2026-09-25 实撞）。全量由 fast_check 负责。
    """
    import subprocess as sp
    r = sp.run(["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME",
                # ADDER32 不流水时没有寄存器，clk / rst_n 不用 —— 正好要靠设计根 waivers.vlt 里的几条才干净
                # （开源拆分后换成 ADDER32，内部#305；全仓那份照样一起读，验它能被解析）
                "--top-module", "ADDER32", "-GPIPE_STAGES=0",
                str(REPO_ROOT / "flow" / "lint" / "waivers.vlt"),
                str(REPO_ROOT / "designs" / "adder32" / "waivers.vlt"),
                *map(str, sorted((REPO_ROOT / "designs" / "adder32" / "rtl").glob("*.v")))],
               capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# --- LRS / LLD（lrs-lld-docs）--------------------------------------------------------
# 专用设计（designs/）的文档是 LRS（需求）+ LLD（实现）+ verify，需求以加粗的 R.00X 定义，
# LLD 的追溯表覆盖全部 R。没有机械判据时，「有需求没人实现」「LLD 说实现了一条不存在的
# 需求」「漏了一整节」都不会让任何东西失败。通用构件（cbb/）只有精简 spec + verify。

DOC_CHECK = "LRS 与 LLD 的结构与需求追溯"


def test_well_formed_params_asserts_and_versions_pass(tmp_path):
    """内部#113：参数表列全、断言编号唯一且引用都有定义、版本表升序时通过。"""
    info = "| 版本 | 日期 | 改动 |\n|---|---|---|\n| v1.9 | x | x |\n| v1.10 | x | x |\n"
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO"), info=info),
                      lld=_good_lld(asserts=("A1", "A2"), text="见 A2。"))
    assert r.returncode == 0, out


@pytest.mark.parametrize("old, new", [
    ("## 术语与约定", "## 3. 术语"),
    ("## 文档信息", "## 0. 修订记录"),
])
def test_renamed_required_sections_pass(tmp_path, old, new):
    """内部#119（lrs-writing-rules D1、D2）：「术语」「修订记录」都算对应的必填节；旧名「术语与约定」仍算。"""
    lrs = _lrs(_good_spec("FOO"))
    assert old in lrs
    r, out = _doc_run(tmp_path, lrs=lrs.replace(old, new), lld=_good_lld())
    assert r.returncode == 0, out


@needs_iverilog
def test_field_rows_under_a_port_are_not_ports(tmp_path):
    """内部#119（lrs-writing-rules D4）：一个接口一张表，端口行下方向为空的字段行不参与端口比对。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    spec = _good_spec("FOO").replace(
        "| `i_a` | in | `DAT_W` | 输入 |\n",
        "| `i_a` | in | `DAT_W` | 输入 |\n| `.lo` |  | 2 | 低两位 |\n| `[3:2] hi` |  | 2 | 高两位 |\n")
    _write_docs(tmp_path / "designs" / "foo", "FOO", spec)
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert ".lo" not in out, out


def test_complete_lrs_and_lld_pass_and_are_counted(tmp_path):
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO"), reqs=("R.001", "R.002")),
                      lld=_good_lld(trace=("R.001", "R.002")))
    assert r.returncode == 0, out
    assert f"ok    {DOC_CHECK}" in out, out
    assert f"已执行  {DOC_CHECK}（1 个顶层，2 条需求" in out, out


@pytest.mark.parametrize("block, bad", [
    ("```\n┌──────┐\n│ CORE │──▶ out\n└──────┘\n```\n", True),
    ("```\nm_cmd_addr = {row, col}\n```\n", False),
])
def test_ascii_art_diagrams_in_lrs_code_blocks_fail(tmp_path, block, bad):
    """内部#126（lrs-writing-rules-2 D3）：LRS 代码块里的框线 / 箭头字符算字符画结构图，失败并点名行号；
    普通代码块与正文里的「→」不算。"""
    lrs = _lrs(_good_spec("FOO")).replace("## 概述\n\n不适用\n",
                                          "## 概述\n\n输入 → 输出。\n\n" + block)
    assert block in lrs
    r, out = _doc_run(tmp_path, lrs=lrs, lld=_good_lld())
    if bad:
        assert r.returncode != 0, out
        assert "字符画" in out and "lrs.FOO.md:" in out, out
    else:
        assert r.returncode == 0, out


@needs_iverilog
def test_excluded_param_combos_are_not_elaborated(tmp_path):
    """内部#138（param-exclude D4）：exclude 命中的组合不 elaborate / lint，摘要写明排除了几个。"""
    import yaml
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    pfile = tmp_path / "designs" / "foo" / "params.yaml"
    cfg = yaml.safe_load(pfile.read_text())
    decl = cfg["tops"]["FOO"]["params"]
    name = next(iter(decl))
    total = 1
    for d in decl.values():
        total *= len(d["values"])
    cfg["tops"]["FOO"]["exclude"] = [{name: decl[name]["values"][0]}]
    pfile.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    kept = total - total // len(decl[name]["values"])
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert f"RTL elaborate FOO（{kept} 个参数组合，exclude 排除 {total - kept} 个）" in out, out


def test_a_wrong_exclude_entry_fails_fast_check(tmp_path):
    """内部#138（param-exclude D2）：排除项写了没声明的参数，fast_check 失败并点名。"""
    import yaml
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    pfile = tmp_path / "designs" / "foo" / "params.yaml"
    cfg = yaml.safe_load(pfile.read_text())
    cfg["tops"]["FOO"]["exclude"] = [{"NO_SUCH": 1}]
    pfile.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    r = _run_with_path(script, stub=STUB_OK)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "NO_SUCH" in out, out


@needs_iverilog
@pytest.mark.parametrize("item, bad, named", [
    ({"ports": ["i_*"], "kind": "false_path", "by": "R.001"}, False, None),
    ({"ports": ["i_*"], "kind": "false_path", "by": "R.999"}, True, "R.999"),
    ({"ports": ["x_*"], "kind": "false_path", "by": "R.001"}, True, "x_*"),
])
def test_static_ports_must_be_backed_by_a_requirement_and_match_an_input(tmp_path, item, bad, named):
    """内部#154（sta-static-ports D4）：by 要是接口文档里定义的需求，模式要匹配到 RTL 输入端口。"""
    import yaml
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    pfile = tmp_path / "designs" / "foo" / "params.yaml"
    cfg = yaml.safe_load(pfile.read_text())
    cfg["tops"]["FOO"].setdefault("sta", {})["static_ports"] = [item]
    pfile.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    r = _run(script)
    out = r.stdout + r.stderr
    if bad:
        assert r.returncode != 0, out
        assert named in out, out
    else:
        assert r.returncode == 0, out


@pytest.mark.parametrize("figure, bad", [
    ("![框图](doc/top.svg)\n\n顶层由两块组成。\n", True),
    ("![框图](doc/top.svg)\n\n**图 1-1** 框图 —— 看上下游接口\n", False),
    ("```\n![不是图](doc/x.svg)\n```\n", False),
])
def test_lrs_figures_need_a_caption(tmp_path, figure, bad):
    """内部#137（spec-readability D1）：LRS 里每处图片引用之后的第一个非空行要是「**图 」开头的图注，
    否则失败并点名行号；代码块里的图片语法不算。"""
    lrs = _lrs(_good_spec("FOO")).replace("## 概述\n\n不适用\n", "## 概述\n\n" + figure)
    assert figure in lrs
    r, out = _doc_run(tmp_path, lrs=lrs, lld=_good_lld())
    if bad:
        assert r.returncode != 0, out
        assert "图注" in out and "lrs.FOO.md:" in out, out
    else:
        assert r.returncode == 0, out


@pytest.mark.parametrize("where, bad", [
    ("SUB_A", True),
    ("文档信息", False),
])
def test_lld_references_to_undefined_requirements_fail(tmp_path, where, bad):
    """内部#140（spec-readability D2）：LLD 全文引用的 R 号都要在 LRS 有定义，失败点名编号与行号；
    只写在修订记录（文档信息）一节里的已删编号不报。"""
    lld = _good_lld()
    old = f"## {where}\n\n不适用\n"
    assert old in lld
    lld = lld.replace(old, f"## {where}\n\n原 R.015 已删除，见 R.001。\n")
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=lld)
    if bad:
        assert r.returncode != 0, out
        assert "R.015" in out and "lld.FOO.md:" in out, out
    else:
        assert r.returncode == 0, out


@pytest.mark.parametrize("kind, lrs_kw, lld_kw, named", [
    ("LRS 缺一节", {"skip": ("性能需求",)}, {}, "性能需求"),
    ("LLD 缺一节", {}, {"skip": ("DFX 实现",)}, "DFX"),
    ("LLD 缺概述", {}, {"skip": ("设计概述",)}, "概述"),
    ("模块划分表里的模块没有自己的节", {}, {"skip": ("SUB_A",)}, "SUB_A"),
    ("LRS 缺配置与应用场景", {"skip": ("配置与应用场景",)}, {}, "配置与应用场景"),
    ("LLD 缺设计断言", {}, {"skip": ("设计断言",)}, "设计断言"),
    ("重号", {"reqs": ("R.001", "R.003", "R.003")}, {"trace": ("R.001", "R.003")}, "R.003"),
    ("编号格式错", {"reqs": ("R.001", "R.1")}, {"trace": ("R.001",)}, "R.1"),
    ("没有需求", {"reqs": ()}, {"trace": ()}, "至少"),
    ("追溯漏一条", {"reqs": ("R.001", "R.005")}, {"trace": ("R.001",)}, "R.005"),
    ("追溯悬空", {"reqs": ("R.001",)}, {"trace": ("R.001", "R.009")}, "R.009"),
    ("没有追溯表", {}, {"trace": None}, "追溯表"),
    # flow-guard-feedback（内部#113）
    ("参数表漏列 params.yaml 的参数", {"params": ()}, {}, "DAT_W"),
    ("断言重号", {}, {"asserts": ("A1", "A2", "A2")}, "A2"),
    ("引用了不存在的断言", {}, {"asserts": ("A1",), "text": "见 A12。"}, "A12"),
    ("没有断言表却引用断言", {}, {"text": "见 A3。"}, "A3"),
    ("版本表乱序", {"info": "| 版本 | 日期 | 改动 |\n|---|---|---|\n| v1.14 | x | x |\n| v1.13 | x | x |\n"}, {}, "v1.13"),
])
def test_lrs_lld_structure_and_trace_failures_are_named(tmp_path, kind, lrs_kw, lld_kw, named):
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO"), **lrs_kw), lld=_good_lld(**lld_kw))
    assert f"FAIL  {DOC_CHECK}" in out, f"{kind} 应失败：\n{out}"
    assert named in out.split(f"FAIL  {DOC_CHECK}", 1)[1], f"{kind} 要点名 {named}：\n{out}"
    assert r.returncode != 0, out


def test_missing_lld_fails(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "lld.FOO.md").unlink()
    out = (r := _run_with_path(script, stub=STUB_OK)).stdout + r.stderr
    assert f"FAIL  {DOC_CHECK}" in out and "lld.FOO.md" in out, out
    assert r.returncode != 0


@pytest.mark.parametrize("where, name", [
    ("designs/foo", "spec.FOO.md"),
    ("designs/foo", "design.FOO.md"),
    ("cbb/bar", "design.BAR.md"),
    ("cbb/bar", "lld.BAR.md"),
])
def test_doc_kinds_follow_the_root_type(tmp_path, where, name):
    """designs/ 只认 lrs / lld / verify；cbb/ 只认 spec / verify（各加 REPORT）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path
    if where.startswith("cbb"):
        bar = root / "cbb" / "bar"
        (bar / "rtl").mkdir(parents=True)
        (bar / "rtl" / "bar.v").write_text(_good_rtl("BAR", "cbb/bar/spec.BAR.md"))
        (bar / "params.yaml").write_text(_as_tops(GOOD_PARAMS, "BAR"))
        (bar / "spec.BAR.md").write_text(_good_spec("BAR"))
    (root / where / name).write_text("# x\n")
    out = (r := _run_with_path(script, stub=STUB_OK)).stdout + r.stderr
    assert "FAIL  设计根下有非源文件" in out and f"{where}/{name}" in out, out
    assert r.returncode != 0


@needs_iverilog
def test_port_table_is_read_from_the_lrs(tmp_path):
    """RTL 加了端口而 LRS 没跟上 —— 端口表检查读的是 LRS（要真 iverilog 出 vvp）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "foo.v").write_text(GOOD_RTL.replace(
        "(input wire [DAT_W-1:0] i_a,", "(input wire [DAT_W-1:0] i_a, input wire i_b,"))
    out = (r := _run(script)).stdout + r.stderr
    assert "RTL 有、文档无：i_b" in out, out
    assert r.returncode != 0


# ---- 旧文档格式已退役（内部#134，retire-legacy-docs）----
# designs/ 下的 spec / design 由 lrs / lld 取代；过渡清单 flow/lint/doc_legacy.txt 随之取消。

def _legacy_root(tmp_path):
    """designs/foo 仍用旧文档：spec + design，没有 lrs / lld。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path / "designs" / "foo"
    (root / "lrs.FOO.md").unlink()
    (root / "lld.FOO.md").unlink()
    (root / "spec.FOO.md").write_text(_good_spec("FOO"))
    (root / "design.FOO.md").write_text("# design\n")
    (root / "rtl" / "foo.v").write_text(_good_rtl("FOO", "designs/foo/spec.FOO.md"))
    return script


@pytest.mark.parametrize("listed", [False, True])
def test_old_spec_design_docs_fail_even_if_listed(tmp_path, listed):
    """内部#134：designs/ 下的 spec / design 一律失败；登记在已删除的过渡清单里也不再豁免。"""
    script = _legacy_root(tmp_path)
    if listed:
        (tmp_path / "flow" / "lint").mkdir(parents=True, exist_ok=True)
        (tmp_path / "flow" / "lint" / "doc_legacy.txt").write_text("# 过渡\ndesigns/foo\n")
    out = (r := _run_with_path(script, stub=STUB_OK)).stdout + r.stderr
    assert r.returncode != 0, out
    assert "spec.FOO.md" in out and "lrs.FOO.md" in out, out
    assert "旧格式" in out, out


# ---- 接口按类型分节，端口表分写在几张表里（lrs-section-revise 1.3）----
# 只读第一张表时，分表之后后面几张表里的端口根本不会被比 —— 而它们照样「看起来写了」。

def _two_tables(first, second):
    hdr = "| 信号 | 方向 | 位宽 | 含义 |\n|---|---|---|---|\n"
    row = lambda n, d, w: f"| `{n}` | {d} | `{w}` | x |\n"
    return ("# FOO\n\n## 接口\n\n### 时钟与复位\n\n不适用\n\n### 数据输入\n\n" + hdr
            + "".join(row(*r) for r in first) + "\n协议说明。\n\n### 数据输出\n\n" + hdr
            + "".join(row(*r) for r in second))


@needs_iverilog
@pytest.mark.parametrize("first, second, ok, named", [
    ([("i_a", "in", "DAT_W")], [("o_y", "out", "DAT_W")], True, None),
    ([("i_a", "in", "DAT_W")], [("o_y", "out", "DAT_W+1")], False, "o_y 位宽"),
    ([("i_a", "in", "DAT_W"), ("o_y", "out", "DAT_W")], [("o_y", "out", "DAT_W")], False, "o_y 写了不止一行"),
])
def test_port_tables_split_by_interface_type_are_merged(tmp_path, first, second, ok, named):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _write_docs(tmp_path / "designs" / "foo", "FOO", _two_tables(first, second))
    r, out = _port_run(script)
    if ok:
        assert f"ok    {PORT_CHECK}" in out, out
    else:
        assert PORT_FAIL in out and named in out, out
        assert r.returncode != 0


PARAM_CHK_RTL = GOOD_RTL.replace("endmodule\n", """\
`ifdef CBB_PARAM_CHK_ON
generate
    if(DAT_W == 8) begin : GEN_DAT_W_CHK
        $error("FOO: DAT_W 8 is illegal");
    end
endgenerate
`endif
endmodule
""")


@needs_iverilog
def test_rtl_param_checks_are_on(tmp_path):
    """RTL 自带的参数检查（`ifdef CBB_PARAM_CHK_ON 里的 $error）必须生效：params.yaml 声明出
    一个 RTL 判为非法的组合，fast_check 就失败。内部#165：流程从没定义过这个宏，一组非法的
    参数组合一路 elaborate 通过、进了扫参。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "foo.v").write_text(PARAM_CHK_RTL)
    r = _run(script)
    assert r.returncode != 0, r.stdout
    assert "FAIL  elaborate FOO DAT_W=8" in r.stdout
    assert "FAIL  elaborate FOO DAT_W=4" not in r.stdout


@needs_iverilog
@pytest.mark.parametrize("item, named", [
    ({"name": "a", "case": {"i_a": 3}, "by": "R.001"}, None),
    ({"name": "a", "case": {"i_a": 3}, "by": "R.999"}, "R.999"),
    ({"name": "a", "case": {"x_b": 0}, "by": "R.001"}, "x_b"),
    ({"name": "a", "case": {"i_a": 16}, "by": "R.001"}, "超出位宽"),
])
def test_depth_scenarios_must_be_backed_by_a_requirement_and_fix_inputs(tmp_path, item, named):
    """内部#189：验收场景的定值同样要由接口文档里定义的需求担保，端口要是 RTL 输入、值不超位宽（i_a 4 位）。"""
    import yaml
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    pfile = tmp_path / "designs" / "foo" / "params.yaml"
    cfg = yaml.safe_load(pfile.read_text())
    cfg["tops"]["FOO"].setdefault("sta", {})["scenarios"] = [item]
    pfile.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    r = _run(script)
    out = r.stdout + r.stderr
    if named:
        assert r.returncode != 0, out
        assert named in out, out
    else:
        assert r.returncode == 0, out


@needs_iverilog
@pytest.mark.parametrize("conn, bad", [("i_a", None), ("i_gone", "i_gone")])
def test_sva_bind_names_must_exist_in_the_bound_module(tmp_path, conn, bad):
    """内部#194：bind 连接里的名字在被绑模块里不存在时，Verilator 静默接成隐式线、断言失效 —— fast_check 要点名报错。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    tb = tmp_path / "designs" / "foo" / "tb"
    tb.mkdir(exist_ok=True)
    (tb / "sva_foo.sv").write_text(
        "module SVA_FOO (input wire a);\nendmodule\n\n"
        f"// 注释里提到 i_gone 不算\nbind FOO SVA_FOO u_sva (\n    .a({conn})\n);\n")
    r = _run(script)
    out = r.stdout + r.stderr
    if bad:
        assert r.returncode != 0, out
        assert "sva_foo.sv" in out and bad in out and "SVA bind" in out, out
    else:
        assert r.returncode == 0, out
        assert "SVA bind 连接的名字都在被绑模块里（1 条 bind" in out, out


@needs_iverilog
def test_sva_bind_can_be_checked_against_the_design_ref(tmp_path, monkeypatch):
    """内部#211：验证分支的工作区是旧 RTL，bind 已跟到被测提交的新信号名。给 SVA_BIND_DESIGN_REF=<被测提交>
    时被绑模块按那个提交的 RTL 核（过），不给时按工作区核（点名失败）。"""
    tree = "designs"
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _ensure_git(script)
    rtl = tmp_path / tree / "foo" / "rtl" / "foo.v"
    old = rtl.read_text()
    rtl.write_text(old.replace("    assign o_y = i_a;", "    wire i_new;\n    assign o_y = i_a;"))
    _git(tmp_path, "commit", "-qam", "design R006")
    ref = _git(tmp_path, "rev-parse", "HEAD").strip()
    _git(tmp_path, "reset", "-q", "--hard", "HEAD~1")
    tb = tmp_path / tree / "foo" / "tb"
    tb.mkdir(exist_ok=True)
    (tb / "sva_foo.sv").write_text("module SVA_FOO (input wire a);\nendmodule\n\nbind FOO SVA_FOO u_sva (.a(i_new));\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "tb follows R006")
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "i_new" in out, out
    monkeypatch.setenv("SVA_BIND_DESIGN_REF", ref)
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert f"被绑 RTL 按 {ref}" in out, out


@needs_iverilog
@pytest.mark.parametrize("points, ok, named", [
    ([{"name": "p8", "DAT_W": 8}], True, None),
    ([{"name": "p8", "DAT_W": 16}], False, "16"),
    (None, False, "8"),
])
def test_sweep_points_and_cross_false_in_fast_check(tmp_path, points, ok, named):
    """内部#214：cross: false 的 DAT_W 在叉乘里只取 4，8 只经 sweep_points 出现；摘要写明含几个点。
    点的取值不在 values 里、cross: false 的取值没有任何点覆盖，都要点名失败。"""
    import yaml
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    pfile = tmp_path / "designs" / "foo" / "params.yaml"
    cfg = yaml.safe_load(pfile.read_text())
    top = cfg["tops"]["FOO"]
    top["params"]["DAT_W"]["cross"] = False
    if points is not None:
        top["sweep_points"] = points
    pfile.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    r = _run(script)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0, out
        assert "RTL elaborate FOO（2 个参数组合，含 sweep_points 1 个）" in out, out
    else:
        assert r.returncode != 0, out
        assert "FAIL  展开参数组合" in out and named in out, out


# --- 内部#203 lld-restructure：LLD 按模块组织 ---------------------------------------------

def test_lld_without_the_old_four_sections_passes(tmp_path):
    """旧的必填节（参数化实现、功能设计、综合与 PPA 预期、子模块详述）不再要求（D1）。"""
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=_good_lld())
    assert r.returncode == 0, out
    for old in ("参数化实现", "功能设计", "综合与 PPA 预期", "子模块详述"):
        assert old not in out, out


@pytest.mark.parametrize("old_structure", [False, True])
def test_deadlock_analysis_is_written_once(tmp_path, old_structure):
    """标题含「死锁」的节至多一个（D3）；还带旧「子模块详述」节的 LLD 只提示（过渡）。"""
    lld = _good_lld() + "\n## 死锁与冒险\n\n不适用\n\n### SUB_A 的死锁\n\n不适用\n"
    if old_structure:
        lld += "\n## 子模块详述\n\n不适用\n"
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=lld)
    assert "死锁与冒险" in out and "SUB_A 的死锁" in out, out
    if old_structure:
        assert r.returncode == 0 and "提示" in out, out
    else:
        assert r.returncode != 0 and f"FAIL  {DOC_CHECK}" in out, out


def test_the_lld_template_passes_the_doc_check(tmp_path):
    """按新模板（flow/templates/design-root/lld.md）原样放进设计根，文档检查通过（内部#203）。"""
    lld = (REPO_ROOT / "flow" / "templates" / "design-root" / "lld.md").read_text()
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO"), reqs=("R.001", "R.002")), lld=lld)
    assert r.returncode == 0, out
    assert "提示" not in out, out


# --- 内部#203 lld-restructure 1.2：param / ppa / timing 三份文档 ----------------------------

def _three_docs(root, top="FOO", skip=()):
    for kind in ("param", "ppa", "timing"):
        if kind not in skip:
            (root / f"{kind}.{top}.md").write_text(
                (REPO_ROOT / "flow" / "templates" / "design-root" / f"{kind}.md").read_text())


@pytest.mark.parametrize("old_structure, skip, ok", [
    (False, (), True),
    (False, ("timing",), False),
    (True, ("timing",), True),
])
def test_param_ppa_timing_docs_must_exist(tmp_path, old_structure, skip, ok):
    """D4：设计根要有 param / ppa / timing 三份文档（模板原样即可）；还是旧结构的 LLD 缺了只提示。"""
    lld = _good_lld() + ("\n## 子模块详述\n\n不适用\n" if old_structure else "")
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path / "designs" / "foo"
    (root / "lld.FOO.md").write_text(lld)
    for kind in ("param", "ppa", "timing"):
        (root / f"{kind}.FOO.md").unlink()
    _three_docs(root, skip=skip)
    r = _run_with_path(script, stub=STUB_OK)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0, out
        if skip:
            assert "提示" in out and "timing.FOO.md" in out, out
    else:
        assert r.returncode != 0 and "timing.FOO.md" in out, out


# --- 内部#203 lld-restructure 1.4：S1 / S2 / S5 句子检查；内部#221 起致命 -------------------------------

SENT_LINE = re.compile(r"^\s*\S*(lrs|lld)\.FOO\.md:\d+: S\d ", re.M)


def test_sentence_rules_fail_with_file_and_line(tmp_path):
    """S1（R 条文 > 80 字、LLD 条目 > 200 字）、S2（R 条文分号 ≥ 2）、S5（术语表「不用」列的词出现在正文）
    每处一行、以 路径:行号: 开头（失败豁免认得出）；内部#221 起 rc 非 0。"""
    long_r = "上游发来的写命令" * 12                       # 96 字
    lrs = _lrs(_good_spec("FOO"), reqs=("R.001", "R.002", "R.003"))
    lrs = lrs.replace("- **R.001** 需求 R.001", f"- **R.001** {long_r}")
    lrs = lrs.replace("- **R.002** 需求 R.002", "- **R.002** 读时返回数据；写时收下数据；空闲时拉高 idle。")
    lrs = lrs.replace("- **R.003** 需求 R.003", "- **R.003** 前级发来的命令按序处理。")
    old = "## 术语与约定\n\n不适用\n"
    assert old in lrs and f"- **R.001** {long_r}" in lrs
    lrs = lrs.replace(old, "## 术语与约定\n\n| 用 | 不用 | 指什么 |\n|---|---|---|\n| 上游 | 前级 | 发命令的一方 |\n")
    lld = _good_lld(trace=("R.001", "R.002", "R.003"), text="- " + "SUB_A 把命令存进缓冲再送出" * 15)
    r, out = _doc_run(tmp_path, lrs=lrs, lld=lld)
    assert r.returncode != 0, out
    lines = [m.group(0) for m in SENT_LINE.finditer(out)]
    assert any("lrs.FOO.md:" in ln and "S1" in ln for ln in lines), out
    assert any("S2" in ln for ln in lines), out
    assert any("lld.FOO.md:" in ln and "S1" in ln for ln in lines), out
    assert re.search(r"lrs\.FOO\.md:\d+: S5 .*前级", out), out


def test_sentence_rules_are_hints_with_file_and_line(tmp_path):
    """内部#221（用户 2026-10-19 定）：S1 / S2 / S5 转为致命之后，S9 仍只作提示 —— 出「提示」行、点名文件与行号，rc 为 0。
    用例名沿用 内部#203 的「只作提示」用例，用例 ID 不删（合并检查要求）。"""
    lrs = _lrs(_good_spec("FOO")).replace("需求 R.001", "读数据在有限拍内返回")
    assert "读数据在有限拍内返回" in lrs
    r, out = _doc_run(tmp_path, lrs=lrs, lld=_good_lld())
    assert r.returncode == 0, out
    assert re.search(r"提示.*S9 上界写数字.*1 处.*lrs\.FOO\.md:\d+（有限）", out), out
    assert not SENT_LINE.search(out), out          # 没有任何一条致命的句子违规行

def test_s5_ignores_link_targets(tmp_path):
    """S5 不看链接目标：`![图](doc/layout_slot.svg)` 里的 slot 是文件名，不是正文用词（spec 10-05 反映的误报）。"""
    lrs = _lrs(_good_spec("FOO"))
    old = "## 术语与约定\n\n不适用\n"
    assert old in lrs
    lrs = lrs.replace(old, "## 术语与约定\n\n| 用 | 不用 | 指什么 |\n|---|---|---|\n| 表项 | slot | 一项 |\n\n"
                      "![版面](doc/layout_slot.svg)\n\n**图 3-1** 版面\n\n见 [版面](doc/layout_slot.svg)。\n")
    r, out = _doc_run(tmp_path, lrs=lrs, lld=_good_lld())
    assert r.returncode == 0, out
    assert "S5" not in out, out


def test_assertion_else_in_generate_is_not_a_generate_else(tmp_path):
    """内部#234：generate 里 assert / assume / cover property (...) else 是断言的失败动作，不查块名。"""
    src = STYLE_OK.replace(
        "        assign sum[gi] = dat_1ff[gi] ^ rev_r[gi];\n",
        "        assign sum[gi] = dat_1ff[gi] ^ rev_r[gi];\n"
        "        A60_SUM: assert property (@(posedge clk) (sum[gi] == (dat_1ff[gi] ^ rev_r[gi])))\n"
        "            else $error(\"sum mismatch\");\n"
        "        C60_SUM: cover property (@(posedge clk) sum[gi]) else $error(\"x\");\n", 1)
    assert "A60_SUM" in src
    out, _ = _style_out(_style_repo(tmp_path, {"sty.v": src}))
    assert f"ok    {STYLE}" in out, out


def test_unnamed_generate_else_still_fails(tmp_path):
    """内部#234 的失败臂：真正的 generate else 不带 GEN_ 块名照报。"""
    old = "end else begin : GEN_NARROW"
    assert old in STYLE_OK
    out, block = _style_out(_style_repo(tmp_path, {"sty.v": STYLE_OK.replace(old, "end else begin", 1)}))
    assert f"FAIL  {STYLE}" in out, out
    assert "[generate 块名]" in block and "else" in block, block


@pytest.mark.parametrize("item", [
    "1. " + "SUB_A 把命令存进缓冲再送出" * 15,
    "| 写缓冲 | " + "SUB_A 把命令存进缓冲再送出" * 15 + " | R.001 |",
])
def test_s1_counts_numbered_items_and_table_cells(tmp_path, item):
    """内部#238：S1 的 LLD 条目含编号列表项与表格单元格（r9 实例：编号项 227 字、A59 格 223 字都漏报）。"""
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=_good_lld(text=item))
    assert r.returncode != 0, out
    assert re.search(r"lld\.FOO\.md:\d+: S1 句长（LLD 条目", out), out


def test_s1_short_table_cells_are_not_hinted(tmp_path):
    """内部#238 的反面：短单元格与分隔行不报。"""
    lld = _good_lld(text="| 项 | 说明 |\n|---|---|\n| 写缓冲 | SUB_A 把命令存进缓冲 |")
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=lld)
    assert r.returncode == 0, out
    assert "S1 句长（LLD 条目" not in out, out


def _lld_with_small_module(header):
    """模块划分一节在模块表后再加一张表，第一格表头为 header，列一个没有自己节的 MEM_SRAM。"""
    lld = _good_lld()
    old = "| `SUB_A` | x |\n"
    assert old in lld
    return lld.replace(old, old + f"\n| {header} | 所在模块 | 功能 | 用到的 CBB |\n|---|---|---|---|\n"
                       "| `MEM_SRAM` | `SUB_A` | 元数据存储 | 无 |\n", 1)


def test_small_module_table_rows_need_no_section(tmp_path):
    """内部#239（lld-small-modules D1/D2）：表头第一格为「小模块」的表里的模块不要求有节。"""
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=_lld_with_small_module("小模块"))
    assert r.returncode == 0, out
    assert "MEM_SRAM" not in out, out


def test_small_module_in_ordinary_table_still_needs_a_section(tmp_path):
    """失败臂：同一行写在表头为「模块」的表里，没有节照报。"""
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=_lld_with_small_module("模块"))
    assert r.returncode != 0, out
    assert "模块划分表里的 MEM_SRAM 没有自己的节" in out, out


# --- 内部#253：上界、延时、深度、次数要写数字或参数公式，「有限 / 尽快」一类只作提示（用户 2026-10-19 定，内部#221）---

@pytest.mark.parametrize("req,hinted", [
    ("读数据在有限拍内返回", True),
    ("命令尽快送出", True),
    ("读数据在 BUF_NUM × (BURST_LEN + 1) 拍内返回", False),
])
def test_vague_bound_words_are_hinted(tmp_path, req, hinted):
    lrs = _lrs(_good_spec("FOO")).replace("需求 R.001", req)
    r, out = _doc_run(tmp_path, lrs=lrs, lld=_good_lld())
    assert r.returncode == 0, out                     # S9 不致命（内部#221，用户 2026-10-19 定）
    assert ("S9 上界写数字" in out) is hinted, out
    if hinted:
        assert re.search(r"提示.*S9 上界写数字.*lrs\.FOO\.md:\d+", out), out


def test_vague_bound_words_in_revision_record_are_not_hinted(tmp_path):
    info = "| 版本 | 日期 | 改动 |\n|---|---|---|\n| v1.1 | x | R.001 改成有限拍内返回之外的写法 |\n"
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO"), info=info), lld=_good_lld())
    assert "S9 上界写数字" not in out, out


# --- 内部#226 ①③：LLD 图也要图注；文档信息表的版本号 = 修订记录最后一行 ---

@pytest.mark.parametrize("caption,bad", [("", True), ("**图 4-1** 模块框图 —— 看连线", False)])
def test_lld_figure_needs_caption(tmp_path, caption, bad):
    text = "![框图](doc/a.svg)\n" + (caption + "\n" if caption else "\n正文。\n")
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=_good_lld(text=text))
    assert (r.returncode != 0) is bad, out
    if bad:
        assert "\ndesigns/foo/lld.FOO.md:" in out and "的图没有图注" in out, out


INFO_VER = "\n| 项 | 内容 |\n|---|---|\n| 版本 | {info} |\n\n| 版本 | 日期 | 改动 |\n|---|---|---|\n| v1.1 | x | x |\n| v1.2 | x | x |\n"


@pytest.mark.parametrize("info,bad", [("v1.2", False), ("v1.1", True)])
def test_doc_info_version_matches_last_revision(tmp_path, info, bad):
    lld = _good_lld().replace("## 文档信息\n\n不适用\n", "## 文档信息\n" + INFO_VER.format(info=info))
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=lld)
    assert (r.returncode != 0) is bad, out
    if bad:
        assert "\ndesigns/foo/lld.FOO.md" in out and "v1.1" in out and "v1.2" in out, out


# --- 内部#331：句子提示不看修订记录；「对应 LRS / LLD」一行的版本号；LLD 里的名字与 RTL 对照 ---

LONG_ITEM = "SUB_A 把命令存进缓冲再送出" * 15


@pytest.mark.parametrize("where, hinted", [("revision", False), ("body", True)])
def test_s1_skips_the_revision_record(tmp_path, where, hinted):
    """修订记录里的长行不报 S1（LLD 常驻的 4 条提示全是历史修订行）；同一行写在正文里照报（失败臂）。"""
    rev = f"| 版本 | 日期 | 改动 |\n|---|---|---|\n| v1.0 | x | {LONG_ITEM} |\n"
    lld = _good_lld(text="- " + LONG_ITEM if where == "body" else "")
    lld = lld.replace("## 文档信息\n\n不适用\n", "## 文档信息\n\n" + rev)
    assert rev in lld
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=lld)
    assert (r.returncode != 0) is hinted, out
    assert ("S1 句长（LLD 条目" in out) is hinted, out


def _versioned_docs(tmp_path, said):
    """LRS 与 LLD 当前都是 v1.2；param.FOO.md 的文档信息表写「对应 LRS / LLD」为 said。"""
    rev = "| 版本 | 日期 | 改动 |\n|---|---|---|\n| v1.1 | x | x |\n| v1.2 | x | x |\n"
    lrs = _lrs(_good_spec("FOO"), info=rev)
    lld = _good_lld().replace("## 文档信息\n\n不适用\n", "## 文档信息\n\n" + rev)
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path / "designs" / "foo"
    (root / "lrs.FOO.md").write_text(lrs)
    (root / "lld.FOO.md").write_text(lld)
    (root / "param.FOO.md").write_text(
        f"# FOO 参数化实现\n\n## 0. 文档信息\n\n| 项 | 内容 |\n|---|---|\n| 对应 LRS / LLD | {said} |\n"
        "| 版本 | v1.0 |\n\n| 版本 | 日期 | 改动 |\n|---|---|---|\n| v1.0 | x | x |\n\n## 1. 参数与结构\n\n不适用\n")
    r = _run_with_path(script, stub=STUB_OK)
    return r, r.stdout + r.stderr


def test_stale_version_line_is_hinted(tmp_path):
    r, out = _versioned_docs(tmp_path, "`lrs.FOO.md` v1.1 / `lld.FOO.md` v1.2")
    assert r.returncode == 0, out
    hit = [ln for ln in out.splitlines() if "#331" in ln and "param.FOO.md" in ln]
    assert len(hit) == 1 and "lrs.FOO.md v1.1" in hit[0] and "v1.2" in hit[0], out


def test_current_version_line_is_not_hinted(tmp_path):
    r, out = _versioned_docs(tmp_path, "`lrs.FOO.md` v1.2 / `lld.FOO.md` v1.2")
    assert r.returncode == 0, out
    assert "对应 lrs" not in out and "对应 lld" not in out, out


def test_lld_names_missing_from_rtl_are_hinted(tmp_path):
    """LLD 反引号里的 U_* / *_r 在 RTL 里找不到才提示；找得到的、带通配的、修订记录里的不报。"""
    lld = _good_lld(text="`U_FOO_KEEP` 存 `hold_r`；`U_FOO_GONE` 已改名；`advance_*_r` 是一组。")
    lld = lld.replace("## 文档信息\n\n不适用\n", "## 文档信息\n\n| 版本 | 日期 | 改动 |\n|---|---|---|\n"
                      "| v1.0 | x | 删 `U_FOO_OLD` |\n")
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path / "designs" / "foo"
    (root / "lld.FOO.md").write_text(lld)
    rtl = root / "rtl" / "foo.v"
    rtl.write_text(rtl.read_text().replace("    assign o_y = i_a;\n",
                                           "    assign o_y = i_a;   // U_FOO_KEEP hold_r\n"))
    r = _run_with_path(script, stub=STUB_OK)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    hit = [ln for ln in out.splitlines() if "rtl/*.v 里找不到" in ln]
    assert len(hit) == 1 and "U_FOO_GONE" in hit[0] and "lld.FOO.md:" in hit[0], out
