"""`scripts/fast_check.sh` 的用例：RTL 名字与书写（模块名大小写、命名约定、书写风格、结构枚举、IP 级命名、综合指令属性）。

内部#336 从 tests/test_fast_check.py 按小节拆出，用例原样；夹具在 tests/fast_check_fixture.py。
"""
from fast_check_fixture import *  # noqa: F401,F403


# --- RTL 模块名必须全大写（repo-layout，本仓 内部#46 的 2.1） ----------------------
#
# 为什么值得有这道检查：2026-09-21 把 30 个模块名一次性改成大写之后，**没有任何
# 东西会让一个小写模块名失败** —— elaborate 过、综合过、仿真过、记录照常产生。
# 规范没有护栏就是建议，而下一个新写模块的人不会记得这一条。
# 它与本文件其余各项同一类：护栏本身，所以照 guardrail-scope 的口径要求
# 「成功路径也要说出覆盖了多少」。

@needs_iverilog
def test_a_lowercase_module_name_is_a_failure(tmp_path):
    """小写模块名当场 FAIL，报错指名文件、模块与应当改成的名字。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    # 夹具本身是合规的（模块名 FOO）；再塞一份小写的进去
    (tmp_path / "designs" / "foo" / "rtl" / "helper.v").write_text(
        "module foo(input wire i_a, output wire o_y);\n"
        "  assign o_y = i_a;\n"
        "endmodule\n")
    r = _run(script)
    assert r.returncode != 0, (
        f"rtl/ 里放了一个 module foo，护栏却退出 0：\n{r.stdout}\n{r.stderr}")
    out = r.stdout + r.stderr
    assert "helper.v:1" in out, f"报错没指名是哪个文件的哪一行：\n{out}"
    assert "模块名不是全大写：foo" in out, f"报错没指名是哪个模块：\n{out}"
    assert "应当改成 FOO" in out, f"报错没给出应当改成的名字：\n{out}"


@needs_iverilog
def test_the_module_name_check_counts_modules_not_files(tmp_path):
    """覆盖摘要里那一项报的是**模块数**，不是文件数。

    一个文件可以声明多个模块。报文件数会让「扫了 2 份文件」听起来像
    「查了 2 个模块」，而实际查的是 3 个 —— 从摘要上看不出差别，
    而这条检查唯一的「它真的跑了」的证据就是这个数（guardrail-scope）。
    """
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    # 一份文件里两个模块，都合规
    (tmp_path / "designs" / "foo" / "rtl" / "two.v").write_text(
        "module BAR(input wire i_a, output wire o_y);\n  assign o_y = i_a;\nendmodule\n"
        "module BAZ(input wire i_a, output wire o_y);\n  assign o_y = i_a;\nendmodule\n")
    _style_exempt(tmp_path, "designs/foo/rtl/two.v")       # 一个文件两个模块就是被测对象
    r = _run(script)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    out = r.stdout + r.stderr
    # 三个模块（FOO + BAR + BAZ）住在两份文件里
    assert "已执行  RTL 模块命名（3 个模块）" in out, (
        f"摘要没按模块数报（两份文件、三个模块）：\n{out}")


@needs_iverilog
def test_module_names_inside_comments_are_not_scanned(tmp_path):
    """注释里的 `module xxx` 不算声明 —— 与仿真逃生口那一项同一条理由：
    护栏一旦产生噪音，人就会给它加豁免，而豁免会长期存在。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "note.v").write_text(
        "/* 旧名字是\nmodule old_helper;\n已经改掉了 */\n"
        "// module another_old_one;\n"
        "module NOTE(input wire i_a, output wire o_y);\n"
        "  assign o_y = i_a;\n"
        "endmodule\n")
    _style_exempt(tmp_path, "designs/foo/rtl/note.v")      # 注释的形状就是被测对象
    r = _run(script)
    assert r.returncode == 0, (
        f"注释里的旧模块名被当成了声明：\n{r.stdout}\n{r.stderr}")


# --- RTL 命名约定（rtl-structure-authority，2026-09-27 unify-rtl-naming） -------
#
# 为什么值得有这道检查：与「模块名全大写」同一个理由 —— `parameter WIDTH`、端口 `din`
# 照样 elaborate、综合、出数，没有任何东西会让它失败。用户 2026-09-27 要求「一定要
# 统一命名」，没有护栏的「一定要」只是建议。
# 只查能机械判定的条款（design.md 的 D9）：「个数用 _N」这类语义约定检查不猜。

@needs_iverilog
@pytest.mark.parametrize("decl, name, why", [
    ("module BAD1 #(parameter WIDTH = 4) (input wire [WIDTH-1:0] i_a, output wire o_y);\n"
     "  assign o_y = i_a[0];\nendmodule\n", "WIDTH", "DAT_W"),
    ("module BAD2 #(parameter DW = 4) (input wire [DW-1:0] i_a, output wire o_y);\n"
     "  assign o_y = i_a[0];\nendmodule\n", "DW", "_W 结尾"),
    ("module BAD3 #(parameter W = 4) (input wire [W-1:0] i_a, output wire o_y);\n"
     "  assign o_y = i_a[0];\nendmodule\n", "W", "单个字母"),
    ("module BAD4 (input wire x, output wire o_y);\n  assign o_y = x;\nendmodule\n",
     "x", "i_ 开头"),
    ("module BAD5 (input wire din, output wire o_y);\n  assign o_y = din;\nendmodule\n",
     "din", "i_ 开头"),
    ("module BAD6 (input wire i_valid, output wire o_y);\n  assign o_y = i_valid;\nendmodule\n",
     "i_valid", "valid → vld"),
    ("module BAD7 (input wire i_a, output wire o_data_pos);\n  assign o_data_pos = i_a;\nendmodule\n",
     "o_data_pos", "data → dat"),
    ("module BAD8 (input wire i_a, inout wire o_y);\n  assign o_y = i_a;\nendmodule\n",
     "o_y", "inout"),
    ("module BAD9 (input wire i_a, output wire o_y);\n  localparam SEGW = 2;\n"
     "  assign o_y = i_a;\nendmodule\n", "SEGW", "_W 结尾"),
])
def test_a_naming_violation_is_a_failure(tmp_path, decl, name, why):
    """每一类违规各自让这一项 FAIL，报错指名文件、模块、名字与违反的条款。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "bad_name.v").write_text(decl)
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"放了一个不合约定的 {name}，护栏却退出 0：\n{out}"
    assert "FAIL  RTL 命名约定" in out, f"不是命名约定这一项报的：\n{out}"
    assert "bad_name.v:" in out and f" {name}：" in out, f"报错没指名文件与名字：\n{out}"
    assert why in out, f"报错没说违反的是哪一条（期望含 {why!r}）：\n{out}"


@needs_iverilog
def test_a_params_yaml_key_is_checked_too(tmp_path):
    """params.yaml 的参数键就是 RTL 参数名，也是记录里 params 的键 —— 同一条约定。"""
    script = _fixture_repo(tmp_path, "params:\n  WIDTH:\n    values: [4]\n")
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "params.yaml 参数键 WIDTH" in out, f"params.yaml 的键没被查：\n{out}"


@needs_iverilog
def test_compliant_names_pass_and_are_counted(tmp_path):
    """合规时这一项通过，并报出查了多少模块 / 参数 / 端口（guardrail-scope）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "hs.v").write_text(
        "module HS #(parameter DAT_W = 4, parameter PIPE_STAGES = 0)\n"
        "  (input wire clk, input wire rst_n,\n"
        "   input wire i_vld, output wire o_rdy, input wire [DAT_W-1:0] i_dat,\n"
        "   output wire o_vld, input wire i_rdy, output wire [DAT_W-1:0] o_dat);\n"
        "  localparam CNT_W = $clog2(DAT_W + 1);\n"
        "  assign o_vld = i_vld;\n  assign o_rdy = i_rdy;\n  assign o_dat = i_dat;\n"
        "endmodule\n")
    r = _run(script)
    out = r.stdout + r.stderr
    assert "ok    RTL 命名约定" in out, f"合规的握手模块被判违规：\n{out}"
    # FOO: DAT_W + i_a/o_y；HS: DAT_W/PIPE_STAGES/CNT_W + 8 个端口；params.yaml: DAT_W
    assert "RTL 命名约定（2 个模块、5 个参数、10 个端口）" in out, (
        f"摘要的计数不对：\n{out}")


ASYNC_FIFO_HEAD = """\
module AF #(parameter DAT_W = 8)
  (input wire wr_clk, input wire wr_rst_n, input wire i_wr_vld, output wire o_wr_rdy,
   input wire [DAT_W-1:0] i_wr_dat,
   input wire rd_clk, input wire rd_rst_n, output wire o_rd_vld, input wire i_rd_rdy,
   output wire [DAT_W-1:0] o_rd_dat);
  assign o_wr_rdy = 1'b1;
  assign o_rd_vld = i_wr_vld;
  assign o_rd_dat = i_wr_dat;
endmodule
"""


@needs_iverilog
def test_multi_clock_domain_clocks_and_resets_are_allowed(tmp_path):
    """多时钟构件的 `<域>_clk` / `<域>_rst_n` 输入与单时钟的 clk / rst_n 同样放行（D11）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "af.v").write_text(ASYNC_FIFO_HEAD)
    r = _run(script)
    out = r.stdout + r.stderr
    assert "ok    RTL 命名约定" in out, f"异步 FIFO 的 wr_clk / rd_rst_n 被判违规：\n{out}"


@needs_iverilog
@pytest.mark.parametrize("decl, name", [
    ("module BADC1 (input wire wr_clk, output wire rd_clk);\n  assign rd_clk = wr_clk;\nendmodule\n",
     "rd_clk"),
    ("module BADC2 (input wire wr_clock, output wire o_y);\n  assign o_y = wr_clock;\nendmodule\n",
     "wr_clock"),
    ("module BADC3 (input wire WR_clk, output wire o_y);\n  assign o_y = WR_clk;\nendmodule\n",
     "WR_clk"),
])
def test_clock_like_names_outside_the_pattern_still_fail(tmp_path, decl, name):
    """放行的只是「小写域名 + _clk / _rst_n 的输入」，别的像时钟的名字照样拦。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "badc.v").write_text(decl)
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and f" {name}：" in out, f"{name} 应当被拦下：\n{out}"


# --- RTL 书写风格（add-rtl-coding-style 1.1，D15、D16、D19）---------------------
#
# 能机械判定的十项。STYLE_OK 十项全合规；每个违规用例只在它上面改一处，
# 所以一条用例红了，就一定是那一项的判定在起作用。



def test_a_fully_compliant_file_passes_the_style_check(tmp_path):
    out, _ = _style_out(_style_repo(tmp_path, {"sty.v": STYLE_OK}))
    assert f"ok    {STYLE}" in out, out


@pytest.mark.parametrize("old, new, item", [
    ("    dat_r[DAT_W-1:0] <= i_a;", "\tdat_r[DAT_W-1:0] <= i_a;", "tab"),
    ("// Purpose : style fixture", "// Purpose : 中文", "非 ASCII"),
    ("// Spec    : designs/foo/lrs.FOO.md\n", "", "头注释"),
    ("// Module  : STY\n", "// Module  : STX\n", "头注释"),
    ("// Spec    : designs/foo/lrs.FOO.md", "// Spec    : designs/foo/spec.NONE.md", "头注释"),
    ("endmodule\n", "endmodule\nmodule STY2;\nendmodule\n", "一个文件一个模块"),
    ("    case(st_r)", "    casex(st_r)", "casex / casez"),
    ("    case(st_r)", "    casez(st_r)", "casex / casez"),
    ("        default: begin\n            st_pre = 2'd0;\n        end\n", "", "case 缺 default"),
    ("        2'd0: begin\n            st_pre = 2'd1;\n",
     "        2'd0: begin\n            case(i_a[0])\n                1'b0: begin\n                    st_pre = 2'd1;\n"
     "                end\n            endcase\n", "case 缺 default"),
    ("    {dat_1ff} <= dat_r;", "    cnt <= dat_r;", "寄存器后缀"),
    ("    {dat_1ff} <= dat_r;", "    {dat_1ff, b} <= dat_r;", "寄存器后缀"),
    ("always@(posedge clk) begin : BLK_DAT", "always@(posedge clk) begin", "always 块名"),
    ("always@(*) begin : BLK_ST_PRE", "always@(*) begin : ST_PRE", "always 块名"),
    ("begin : BLK_FOR", "begin : FOR_REV", "always 块名"),
    ("begin : GEN_WIDE", "begin : WIDE", "generate 块名"),
    ("begin : GEN_FOR", "begin : FOR_SUM", "generate 块名"),
    ("U_STY_IDLE_CBB_LZD", "U_CBB_LZD_2", "例化名"),
    ("U_STY_IDLE_CBB_LZD", "U_STY_IDLE_LZD", "例化名"),
    # rtl-style-four-rules（内部#101）：书写约定的四条 MUST
    ("//---- signal declaration\n", "//---- signal declaration\n\x60default_nettype none\n", "default_nettype"),
    ("integer          bi;", "integer          bi;\nwire             tie = 1'b0;", "定义带赋值"),
    ("integer          bi;", "integer          bi;\nreg  [1:0]       ini_r = 2'd0;", "定义带赋值"),
    ("integer          bi;", "integer          bi;\nlocalparam integer LP_N = 2;", "localparam integer"),
    ("begin : GEN_FOR\n", "begin : GEN_FOR\n        localparam LP_I = gi;\n", "generate 内 localparam"),
])
def test_each_style_item_fails_on_its_own(tmp_path, old, new, item):
    assert old in STYLE_OK, old
    out, block = _style_out(_style_repo(tmp_path, {"sty.v": STYLE_OK.replace(old, new, 1)}))
    assert f"FAIL  {STYLE}" in out, out
    assert f"designs/foo/rtl/sty.v:" in block and f"[{item}]" in block, block


def test_default_nettype_in_a_comment_does_not_count(tmp_path):
    """内部#101：注释里提到 \x60default_nettype 不算违规（剥掉注释再匹配）。"""
    out, _ = _style_out(_style_repo(tmp_path, {"sty.v": STYLE_OK.replace(
        "//---- signal declaration\n", "//---- signal declaration (no \x60default_nettype here)\n")}))
    assert f"ok    {STYLE}" in out, out


def test_spec_path_may_carry_section_numbers(tmp_path):
    """私有子模块没有自己的规格，Spec 写上层规格的路径加章节号（一个大设计的缓冲子模块下的五个子模块）。"""
    out, _ = _style_out(_style_repo(tmp_path, {"sty.v": STYLE_OK.replace(
        "// Spec    : designs/foo/lrs.FOO.md", "// Spec    : designs/foo/lrs.FOO.md (6.2, 7.5)")}))
    assert f"ok    {STYLE}" in out, out


def test_file_name_must_match_the_module(tmp_path):
    out, block = _style_out(_style_repo(tmp_path, {"other.v": STYLE_OK.replace(
        "// File    : sty.v", "// File    : other.v")}))
    assert "designs/foo/rtl/other.v:" in block and "[一个文件一个模块]" in block and "sty.v" in block, block


def test_legacy_files_are_exempt_but_must_still_be_violating(tmp_path):
    bad = STYLE_OK.replace("    case(st_r)", "    casez(st_r)")
    out, _ = _style_out(_style_repo(tmp_path, {"sty.v": bad},
                                    legacy="# 旧文件\ndesigns/foo/rtl/sty.v\n"))
    assert f"ok    {STYLE}" in out and "豁免 1 个" in out, out


def test_a_legacy_entry_that_is_already_compliant_fails(tmp_path):
    out, block = _style_out(_style_repo(tmp_path, {"sty.v": STYLE_OK},
                                        legacy="designs/foo/rtl/sty.v\n"))
    assert "designs/foo/rtl/sty.v" in block and "已合规" in block, block


def test_a_legacy_entry_that_does_not_exist_fails(tmp_path):
    out, block = _style_out(_style_repo(tmp_path, {"sty.v": STYLE_OK},
                                        legacy="designs/foo/rtl/gone.v\n"))
    assert "designs/foo/rtl/gone.v" in block and "不存在" in block, block


def test_frozen_goldens_are_not_style_checked(tmp_path):
    script = _style_repo(tmp_path, {"sty.v": STYLE_OK})
    frozen = tmp_path / "flow" / "equiv" / "frozen" / "foo"
    frozen.mkdir(parents=True)
    (frozen / "old.v").write_text("module OLD;\n\twire x;\nendmodule\n")
    out, _ = _style_out(script)
    assert "frozen" not in out.split(f"{STYLE}", 1)[1].split("\n\n", 1)[0], out


# --- 结构枚举取整数、每个编号都有名字（unify-rtl-naming 1.3，D12、D14）-------------
#
# 结构枚举（SCHEME / *_SCHEME）取整数，名字只在 params.yaml 的 labels 里给人读。
# 写错一个数字比写错一个名字更难看出来，所以编号与名字的对应要能机械核对。

ENUM = "RTL 结构枚举"


def _enum_rtl(tmp_path, decl):
    (tmp_path / "designs" / "foo" / "rtl" / "en.v").write_text(
        f"module EN #(parameter {decl}) (input wire i_a, output wire o_y);\n"
        "    assign o_y = i_a;\nendmodule\n")


@pytest.mark.parametrize("decl, name", [
    ('SCHEME = "CLA"', "SCHEME"),
    ('CPA_SCHEME = "KS"', "CPA_SCHEME"),
])
def test_string_structure_enum_fails(tmp_path, decl, name):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _enum_rtl(tmp_path, decl)
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and f"FAIL  {ENUM}" in out, out
    assert "designs/foo/rtl/en.v" in out and f"模块 EN 的 {name}" in out and "要取整数" in out, out


def test_integer_structure_enum_passes(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _enum_rtl(tmp_path, "SCHEME = 2")
    out = (r := _run(script)).stdout + r.stderr
    assert f"ok    {ENUM}" in out, out


def test_frozen_string_scheme_is_not_scanned(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    frozen = tmp_path / "flow" / "equiv" / "frozen" / "foo"
    frozen.mkdir(parents=True)
    (frozen / "old.v").write_text('module OLD #(parameter SCHEME = "CLA") (); endmodule\n')
    out = (r := _run(script)).stdout + r.stderr
    assert f"ok    {ENUM}" in out, out


@pytest.mark.parametrize("labels, why", [
    (None, "缺 labels"),
    ("{0: RIPPLE, 1: CLA}", "缺名字的编号 [2]"),
    ("{0: RIPPLE, 1: CLA, 2: CSEL, 3: KS}", "多出的编号 [3]"),
    ("{0: RIPPLE, 1: CLA, 2: CLA}", "名字重复 CLA"),
    ("{0: RIPPLE, 1: cla, 2: CSEL}", "名字要大写 cla"),
])
def test_scheme_labels_must_match_values(tmp_path, labels, why):
    params = GOOD_PARAMS + "  SCHEME:\n    values: [0, 1, 2]\n"
    if labels is not None:
        params += f"    labels: {labels}\n"
    out = (r := _run(_fixture_repo(tmp_path, params))).stdout + r.stderr
    assert r.returncode != 0 and f"FAIL  {ENUM}" in out, out
    assert "designs/foo/params.yaml" in out and "FOO 的 SCHEME" in out and why in out, out


def test_scheme_labels_that_match_pass(tmp_path):
    params = GOOD_PARAMS + "  SCHEME:\n    values: [0, 1, 2]\n    labels: {0: RIPPLE, 1: CLA, 2: CSEL}\n"
    out = (r := _run(_fixture_repo(tmp_path, params))).stdout + r.stderr
    assert f"ok    {ENUM}" in out, out


# --- IP 设计根按 IP 级约定命名（unify-rtl-naming 1.4，D17–D19，内部#77）---------------
#
# IP 子模块与 PPA 实验顶层同在 designs/ 下，按目录分不开，所以由设计根
# params.yaml 顶层的 `role: ip` 声明。声明了的根里通道口用 s_ / m_（前缀按通道、
# 不按方向），边带口不加前缀；没声明的根照旧要求 i_ / o_。

IP_HEAD = """\
module IPM #(
     parameter SUB_FIFO_DEPTH = 4
    ,parameter S_CMD_MODE     = 2'b00
) (
     input  wire       clk
    ,input  wire       s_cmd_vld
    ,output wire       s_cmd_rdy
    ,input  wire [3:0] s_cmd_addr
    ,output wire       m_cmd_vld
    ,input  wire       m_cmd_rdy
    ,input  wire [1:0] cfg_mode
);
    assign s_cmd_rdy = m_cmd_rdy;
    assign m_cmd_vld = s_cmd_vld;
endmodule
"""


def _ip_repo(tmp_path, rtl, role="ip"):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    pfile = tmp_path / "designs" / "foo" / "params.yaml"
    if role is not None:
        pfile.write_text(f"role: {role}\n" + pfile.read_text())
    (tmp_path / "designs" / "foo" / "rtl" / "ipm.v").write_text(rtl)
    return script


def test_ip_root_allows_channel_and_sideband_ports(tmp_path):
    """声明 role: ip 的根里，s_ / m_ 两个方向都放行，边带口不加前缀。"""
    r = _run(_ip_repo(tmp_path, IP_HEAD))
    out = r.stdout + r.stderr
    assert "ok    RTL 命名约定" in out, f"IP 的 s_ / m_ / 边带口被判违规：\n{out}"
    assert "按 IP 级约定 2 个模块" in out, out


@pytest.mark.parametrize("old, new, name", [
    ("s_cmd_rdy", "i_cmd_rdy", "i_cmd_rdy"),                      # 输出口用了 i_
    ("s_cmd_vld", "s_cmd_valid", "s_cmd_valid"),                  # 禁用词
    ("input  wire [1:0] cfg_mode", "inout  wire [1:0] cfg_mode", "cfg_mode"),
])
def test_ip_root_still_checks_direction_banned_words_and_inout(tmp_path, old, new, name):
    """IP 放宽的只是前缀：i_ / o_ 用了就要与方向一致，禁用词与 inout 照查。"""
    r = _run(_ip_repo(tmp_path, IP_HEAD.replace(old, new)))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and f" {name}：" in out, f"{name} 应当被拦下：\n{out}"


def test_channel_prefix_without_ip_declaration_fails(tmp_path):
    """没有 role: ip 的根，s_cmd_addr 照旧要求 i_。"""
    r = _run(_ip_repo(tmp_path, IP_HEAD, role=None))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and " s_cmd_addr：input 端口要以 i_ 开头" in out, out


def test_misspelled_role_fails(tmp_path):
    r = _run(_ip_repo(tmp_path, IP_HEAD, role="IP"))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "role" in out and "只许取 ip" in out, out


def test_function_inputs_are_not_module_ports(tmp_path):
    """function 的 input 不是模块端口（一个 ECC 构件里的 f_h_col(dat_w) 曾被误报）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "fn.v").write_text("""\
module FN #(parameter DAT_W = 4) (input wire [DAT_W-1:0] i_a, output wire [DAT_W-1:0] o_y);
    function integer f_x;
        input integer dat_w;
        begin
            f_x = dat_w + 1;
        end
    endfunction
    assign o_y = i_a + f_x(DAT_W);
endmodule
""")
    r = _run(script)
    out = r.stdout + r.stderr
    assert "ok    RTL 命名约定" in out, f"function 的输入被当成端口：\n{out}"


@needs_iverilog
def test_frozen_goldens_are_not_scanned(tmp_path):
    """flow/equiv/frozen/ 下的冻结件不适用书写约定，检查不许扫它。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    frozen = tmp_path / "flow" / "equiv" / "frozen" / "foo"
    frozen.mkdir(parents=True)
    (frozen / "old.v").write_text(
        "module old_one #(parameter WIDTH = 4) (input wire din, output wire dout);\n"
        "  assign dout = din;\nendmodule\n")
    r = _run(script)
    out = r.stdout + r.stderr
    assert "ok    RTL 命名约定" in out, f"冻结件被扫了：\n{out}"


# --- RTL 里不许有综合指令属性（rtl-structure-authority，本仓 内部#46 的 2.2） -----
#
# 为什么值得有这道检查：`(* keep_hierarchy *)` 2026-09-21 从 18 份 RTL 搬进了
# 综合流程（声明在 params.yaml）。搬完之后**没有任何东西**会让一个漏网的属性
# 失败 —— 它照样 elaborate、照样综合、照样出数。而这一条比「模块名大写」更险：
# 属性留在 RTL 里时，同一个意图有两个来源，两边漂移了也不会有人发现。
#
# 扫的是一个**明确的三名单**（design.md 的 D10）。加名字的判据是「它是给综合
# 工具的指令，不是电路描述」。代价不对称：多扫两个从未用过的名字成本是两行，
# 漏扫一个的代价是护栏在该响的时候不响。

@needs_iverilog
def test_a_synthesis_directive_in_rtl_is_a_failure(tmp_path):
    """综合指令属性当场 FAIL，报错指名文件、行号、属性，并说该去哪声明。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "keepme.v").write_text(
        "(* keep_hierarchy *)\n"
        "module KEEPME(input wire i_a, output wire o_y);\n"
        "  assign o_y = i_a;\n"
        "endmodule\n")
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode != 0, (
        f"rtl/ 里放了一个 (* keep_hierarchy *)，护栏却退出 0：\n{out}")
    assert "keepme.v:1" in out, f"报错没指名文件与行号：\n{out}"
    assert "keep_hierarchy" in out, f"报错没指名是哪个属性：\n{out}"
    assert "params.yaml" in out, (
        f"报错没说这个意图该去哪声明，读日志的人只知道被拒：\n{out}")


@needs_iverilog
def test_the_directive_scan_counts_the_files_it_read(tmp_path):
    """覆盖摘要报**扫过的 RTL 文件数** —— 「没有违规」与「没扫」必须可区分。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "two.v").write_text(
        "module BAR(input wire i_a, output wire o_y);\n  assign o_y = i_a;\nendmodule\n")
    _style_exempt(tmp_path, "designs/foo/rtl/two.v")       # 文件数才是被测对象
    r = _run(script)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "已执行  RTL 无综合指令（2 个 RTL 文件）" in r.stdout, (
        f"摘要没列出这一项与扫过的文件数：\n{r.stdout}")


@needs_iverilog
def test_a_directive_named_only_in_a_comment_is_not_a_violation(tmp_path):
    """注释里提到属性名不算 —— 搬家那段历史就写在 `prefix_node.v` 的注释里，
    而护栏一旦产生噪音，人就会给它加豁免，豁免会长期存在。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "note.v").write_text(
        "// 这个模块要保住层级；声明在 ../params.yaml。\n"
        "// 2026-09-08 实测：没有 (* keep_hierarchy *) 时 ABC 会跨边界重构。\n"
        "/* dont_touch 与 keep 同理，都属于综合指令 */\n"
        "module NOTE(input wire i_a, output wire o_y);\n"
        "  assign o_y = i_a;\n"
        "endmodule\n")
    _style_exempt(tmp_path, "designs/foo/rtl/note.v")      # 注释的形状就是被测对象
    r = _run(script)
    assert r.returncode == 0, (
        f"注释里提到属性名就被判违规了：\n{r.stdout}\n{r.stderr}")
