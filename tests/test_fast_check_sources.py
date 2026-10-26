"""`scripts/fast_check.sh` 的用例：源文件一致与设计根洁净（同名 RTL、黄金参考副本、只许有源、仿真专用构造）。

内部#336 从 tests/test_fast_check.py 按小节拆出，用例原样；夹具在 tests/fast_check_fixture.py。
"""
from fast_check_fixture import *  # noqa: F401,F403


# --- 同名 RTL 在不同设计根下必须逐字节相同 -------------------------------------
#
# 为什么值得有这个测试：设计根按 repo-layout 各自自带 rtl/，所以一个模块被两个
# 设计根同时需要时只能留一份拷贝（2026-09-14 的一个组合子块就是：
# 它是自己的顶层，同时又是它所属地址流水那份交叉比对 SV TB 的被测件）。
# 拷贝的失效方式是**漂移**，而漂移之后两个设计根测的是两个不同的电路，
# 记录里看不出来 —— 正是本仓库最怕的那种失效。

def _two_roots(tmp_path, second_rtl, tb_pair=None):
    """搭一个有两个设计根的夹具仓库，两边各有一个同名 RTL 文件。

    `tb_pair` 给定时，另外在两边的 `tb/` 下各放一份同名的 `ref_model.py`，
    内容分别是这个二元组的两项 —— 用来查黄金参考模型那一侧。
    """
    for d in ("flow", "scripts", "cbb"):
        (tmp_path / d).mkdir()
    for name in ("foo", "bar"):
        rtl = tmp_path / "designs" / name / "rtl"
        rtl.mkdir(parents=True)
        (rtl / f"{name}.v").write_text(
            _good_rtl(name.upper(), f"designs/{name}/lrs.{name.upper()}.md"))
        (tmp_path / "designs" / name / "params.yaml").write_text(
            _as_tops(GOOD_PARAMS, name.upper()))
        _write_docs(tmp_path / "designs" / name, name.upper(), _good_spec(name.upper()))
    (tmp_path / "designs" / "foo" / "rtl" / "shared.v").write_text(SHARED_RTL)
    (tmp_path / "designs" / "bar" / "rtl" / "shared.v").write_text(second_rtl)
    _style_exempt(tmp_path, "designs/foo/rtl/shared.v", "designs/bar/rtl/shared.v")
    if tb_pair is not None:
        for name, body in zip(("foo", "bar"), tb_pair):
            tb = tmp_path / "designs" / name / "tb"
            tb.mkdir(parents=True)
            (tb / "ref_model.py").write_text(body)
    shutil.copy(SCRIPT, tmp_path / "scripts" / "fast_check.sh")
    # fast_check 读哪些文件由 flow/paths.py::rtl_candidates 决定（add-design-cbb-deps D3），
    # 夹具仓库要带上这一份 —— 拷的是本仓的真文件，不是替身。
    _copy_paths_py(tmp_path)
    return tmp_path / "scripts" / "fast_check.sh"


SHARED_RTL = "module SHARED_HELPER;\n  wire w = 1'b0;\nendmodule\n"


@needs_iverilog
def test_diverged_copies_are_a_failure(tmp_path):
    """两份同名 RTL 内容不同时必须失败，并指出是哪两份。"""
    script = _two_roots(tmp_path, SHARED_RTL.replace("1'b0", "1'b1"))
    result = _run(script)
    assert result.returncode != 0, result.stdout
    assert "shared.v" in result.stdout
    # 两条路径都要点出来，否则拿着一个文件名还得自己去找另一份在哪
    assert "designs/foo/rtl/shared.v" in result.stdout
    assert "designs/bar/rtl/shared.v" in result.stdout


@needs_iverilog
def test_identical_copies_pass_and_are_named_in_the_summary(tmp_path):
    """逐字节相同时放行，且覆盖摘要里要说出检查了几组。

    只在失败时说明范围是不够的 —— 成功路径才是没人细看的那条
    （guardrail-scope 的同一条要求）。
    """
    script = _two_roots(tmp_path, SHARED_RTL)
    result = _run(script)
    assert result.returncode == 0, result.stdout
    assert "同名源文件一致性（1 组）" in result.stdout


# --- 黄金参考模型的复制件同样不许漂移 ------------------------------------------
#
# 为什么这一侧比 RTL 那一侧更要紧：RTL 漂移之后两个设计根测的是两个不同的电路，
# 至少 PPA 数字会对不上；**模型漂移连数字都不产生** —— 两个 TB 各自拿着一份
# 不同的期望值，各自全绿。没有任何下游指标会暴露它。
#
# 2026-09-14 引入：一个解压流水的 TB 需要压缩侧 TB 已经写过的那份独立
# Python 压缩器模型（`build_ref`），按 repo-layout 设计根要自包含，只能各存一份。

SHARED_MODEL = "def build_ref(line):\n    return 1, line\n"


@needs_iverilog
def test_diverged_tb_models_are_a_failure(tmp_path):
    """两份同名的 tb/ 模型内容不同时必须失败，并指出是哪两份。"""
    script = _two_roots(tmp_path, SHARED_RTL,
                        tb_pair=(SHARED_MODEL,
                                 SHARED_MODEL.replace("1, line", "0, line")))
    result = _run(script)
    assert result.returncode != 0, (
        "两份 tb/ 模型内容不同，fast_check 却退出 0")
    assert "ref_model.py" in result.stdout
    assert "designs/foo/tb/ref_model.py" in result.stdout
    assert "designs/bar/tb/ref_model.py" in result.stdout


@needs_iverilog
def test_identical_tb_models_are_counted_in_the_summary(tmp_path):
    """逐字节相同时放行，且组数把 tb/ 那一份也算进去。

    组数是这条检查唯一的"它真的跑了"的证据 —— 「没有同名文件」与「检查没跑
    起来」在输出上必须可区分（guardrail-scope 的同一条要求）。
    """
    script = _two_roots(tmp_path, SHARED_RTL,
                        tb_pair=(SHARED_MODEL, SHARED_MODEL))
    result = _run(script)
    assert result.returncode == 0, result.stdout
    assert "同名源文件一致性（2 组）" in result.stdout


# --- 设计根下只许有源（repo-layout / guardrail-scope） -------------------------
#
# 为什么值得有这个测试：`repo-layout` 的「单次原始产物 MUST NOT 写入设计根目录
# 内部」把判据的观察量都写死了 ——「MUST 以该目录下有没有新增文件为观察量，
# MUST NOT 以 git status 是否干净为观察量」—— 但在 2026-09-15 之前**没有任何
# 东西在执行它**。结果就是它预言的失效方式真的发生了：两个设计根的 tb/ 下各躺着
# 一份残留 results.xml，五个设计根下都有 __pycache__，全部被 .gitignore 挡住，
# `git ls-files designs/*/tb/` 一个都看不见。
#
# 所以这组用例的夹具**故意不建 git 仓库**：只要检查是拿 git 的视野做的，
# 它在这里就什么也发现不了。

def _root_with_extra(tmp_path, *relpaths):
    """搭一个最小仓库，并在设计根下放若干本不该存在的文件。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    for rel in relpaths:
        f = tmp_path / "designs" / "foo" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("stray\n")
    return script


def test_a_leftover_results_xml_is_a_failure(tmp_path):
    """设计根的 tb/ 下留着 results.xml 必须失败，并说清它该去哪一层。"""
    script = _root_with_extra(tmp_path, "tb/results.xml")
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode != 0, (
        "设计根里躺着上一次仿真的结果文件，护栏却退出 0\n" + r.stdout)
    assert "designs/foo/tb/results.xml" in r.stdout, r.stdout
    assert "runs/" in r.stdout, (
        "没有说清它应该落在哪一层，拿着报错还得回头读契约\n" + r.stdout)


def test_gitignore_does_not_excuse_a_stray_file(tmp_path):
    """被 .gitignore 挡住的产物同样是写进了设计根 —— 判据不许是 git 的视野。

    这一条正是 repo-layout 把观察量写死的原因：用 `git status` 去查，
    契约在被违反时照样通过。
    """
    script = _root_with_extra(tmp_path, "tb/results.xml")
    (tmp_path / ".gitignore").write_text("results.xml\n__pycache__/\n")
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode != 0, (
        ".gitignore 里写了一行，护栏就放行了 —— 判据用的是 git 的视野\n" + r.stdout)


def test_bytecode_cache_is_not_excused_either(tmp_path):
    """`__pycache__` 不是「单次原始产物」，但它同样是设计根下的新增文件。

    不给它开白名单：一旦开了，判据就从「目录里有没有别的东西」退化成
    「有没有**我认得的**别的东西」，而下一个漏进来的产物恰恰是没人认得的那个。
    """
    script = _root_with_extra(tmp_path, "tb/__pycache__/ref_model.cpython-311.pyc")
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode != 0, (
        "设计根下长出了 __pycache__，护栏却退出 0\n" + r.stdout)
    assert "__pycache__" in r.stdout, r.stdout


def test_clean_design_roots_pass_and_are_counted(tmp_path):
    """设计根干净时放行，且覆盖摘要要说出检查了几个设计根。

    组数是这条检查唯一的「它真的跑了」的证据 —— 「没有多余文件」与
    「检查根本没跑起来」在输出上必须可区分（guardrail-scope）。
    """
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode == 0, r.stdout
    assert "ok    设计根下只有源文件" in r.stdout, r.stdout
    assert "已执行  设计根洁净度（1 个设计根）" in r.stdout, (
        "覆盖摘要没有列出这一类检查\n" + r.stdout)


@pytest.mark.parametrize("name, ok", [("sim_waivers.vlt", True), ("other_waivers.vlt", False)])
def test_sim_waivers_is_a_design_root_source(tmp_path, name, ok):
    """内部#312：设计根的 sim_waivers.vlt（仿真构建专用豁免）算源文件；别的 .vlt 仍是多余文件（失败臂）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / name).write_text("`verilator_config\n")
    r = _run_with_path(script, stub=STUB_OK)
    assert (r.returncode == 0) is ok, r.stdout
    assert ("ok    设计根下只有源文件" in r.stdout) is ok, r.stdout
    if not ok:
        assert f"designs/foo/{name}" in r.stdout, r.stdout


def test_the_old_unnamed_doc_files_are_rejected_with_a_hint(tmp_path):
    """收根前的 `spec.md` 这种不带顶层名的文件名必须被拒，且报错要说清怎么改。

    这一条不是洁癖：一个根挂两个顶层时，`spec.md` **指谁不明确** ——
    留着它就会有人往里写第二个顶层的接口契约，而那份契约没有任何东西指向它。
    报错里带上改法（`spec.<top>.md`），否则读日志的人只知道被拒、不知道要干嘛。
    """
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "lrs.md").write_text("# lrs\n")
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode != 0, f"不带顶层名的 lrs.md 被放行了\n{r.stdout}"
    assert "lrs.<top>.md" in r.stdout, (
        f"报错没告诉人该改成什么：\n{r.stdout}")


def test_legitimate_source_shapes_are_not_flagged(tmp_path):
    """契约声明的那几种源不得被误伤 —— 含 doc/ 与 REPORT.md。

    误伤的代价不是「多报一次」：护栏一旦产生噪音，人就会给它加豁免，
    而豁免会长期存在。
    """
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path / "designs" / "foo"
    # 四类文档一个被测顶层一套，文件名带顶层名（2026-09-20 收根，本仓 内部#45）。
    # 夹具里顶层叫 FOO，所以是 spec.FOO.md 而不是 spec.md。
    # designs/ 下的专用设计：lrs / lld / verify（lrs-lld-docs）；lrs、lld 由 _fixture_repo 写好
    (root / "verify.FOO.md").write_text(_verify_md())
    (root / "REPORT.FOO.md").write_text("# report\n")
    (root / "tb").mkdir()
    (root / "tb" / "test_foo.py").write_text("def test_x(): pass\n")
    (root / "tb" / "tb_foo.sv").write_text("module tb_foo; endmodule\n")
    (root / "doc").mkdir()
    (root / "doc" / "upstream.html").write_text("<p>x</p>\n")
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode == 0, ("合法的源被当成了产物：\n" + r.stdout)


# --- 可综合 RTL 里不许有仿真专用构造 -------------------------------------------
#
# 为什么值得有这个测试：`$random` / `$fwrite` / `#n` 延时 / `initial` 块进了
# 可综合 RTL，会让**仿真看到的电路与综合出的电路当场分家，而两边都不报错** ——
# 仿真照常全绿，综合照常出网表，只是两者测的不是同一个东西。这是本仓库的头号
# 失效模式（「跑通了但数字不可信」）在 RTL 层的形态。
#
# 本仓 RTL 目前对全部待扫模式实测干净（design.md 的 F4），所以这是一道**防回归**
# 的护栏 —— 它的红必须靠稻草人造出来，不是靠现存违规。口径借鉴
# MoonshotAI/nano-kpu 的 harness/audit.py（R1 扫描）。

ESCAPE_RTL = """\
module LEAKY (input wire clk, output reg [7:0] o_y);
  initial o_y = 8'h00;
  always @(posedge clk) begin
    o_y <= $random;
    #1 o_y <= o_y + 1;
  end
endmodule
"""

# 同样的字样，但全在注释与字符串字面量里 —— 这不是违规。
COMMENTED_RTL = """\
// 这个模块**不许**用 $random，也不许有 initial 块或 #1 延时。
/* $fwrite / $readmemh / $dumpvars 同理，见 docs/pitfalls.md */
module TIDY (input wire [3:0] i_a, output wire [3:0] o_y);
  // initial 块只该出现在 tb/ 里
  assign o_y = i_a;                  // $urandom 也是
endmodule
"""


def test_simulation_only_constructs_in_rtl_are_a_failure(tmp_path):
    """可综合 RTL 里出现 $random / initial / #n 必须失败，并给出文件与行号。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "leaky.v").write_text(ESCAPE_RTL)
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode != 0, (
        "可综合 RTL 里有 $random/initial/#n，护栏却退出 0 —— "
        "仿真与综合口径会当场分家，而两边都不报错\n" + r.stdout)
    assert "designs/foo/rtl/leaky.v" in r.stdout, r.stdout
    assert "$random" in r.stdout, "没有指出命中的是哪个构造\n" + r.stdout
    assert "initial" in r.stdout, r.stdout
    # 行号：$random 在第 4 行
    assert ":4" in r.stdout, "没有给出行号，拿着报错还得自己找\n" + r.stdout


def test_the_same_words_in_comments_are_not_a_violation(tmp_path):
    """注释与字符串字面量里的字样不算 —— 否则护栏会变成噪音，而噪音会逼出豁免。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "tidy.v").write_text(COMMENTED_RTL)
    _style_exempt(tmp_path, "designs/foo/rtl/tidy.v")      # 中文注释本身就是被测对象
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode == 0, (
        "注释里写着 $random / initial 就被判违规了：\n" + r.stdout)


def test_testbenches_are_not_scanned(tmp_path):
    """只扫 rtl/。tb/ 里 initial、#n、$dumpvars 全都是正当的。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    tb = tmp_path / "designs" / "foo" / "tb"
    tb.mkdir()
    (tb / "tb_foo.sv").write_text(
        "module tb_foo;\n  initial begin\n    $dumpfile(\"x.vcd\");\n"
        "    #10 $finish;\n  end\nendmodule\n")
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode == 0, (
        "TB 里正当的 initial/#n/$dumpfile 被当成了违规：\n" + r.stdout)


def test_clean_rtl_passes_and_the_file_count_is_reported(tmp_path):
    """全干净时放行，且覆盖摘要要说出扫了几个 RTL 文件。

    文件数是这条检查唯一的「它真的跑了」的证据 —— 「没有违规」与
    「检查根本没跑起来」在输出上必须可区分（guardrail-scope）。
    """
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode == 0, r.stdout
    assert "已执行  RTL 仿真逃生口（1 个 RTL 文件）" in r.stdout, (
        "覆盖摘要没有列出这一类检查与扫描过的文件数\n" + r.stdout)
