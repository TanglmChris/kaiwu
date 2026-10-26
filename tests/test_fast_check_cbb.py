"""`scripts/fast_check.sh` 的用例：本地 CBB 副本、通用验证项表、位复制计数。

内部#336 从 tests/test_fast_check.py 按小节拆出，用例原样；夹具在 tests/fast_check_fixture.py。
"""
from fast_check_fixture import *  # noqa: F401,F403


# --- 本地 CBB 副本（local-cbb-naming，内部#246 / 内部#258） ------------------------------
#
# 设计根里拷进来、加后缀隔离的共享 CBB 副本用小写文件名与模块名，例化名写
# `U_<共享 CBB 名>[_<功能>]`。哪些文件是副本只认 `flow/lint/local_cbb.txt`：
# 顶层 `cbb_foo_bar.v` 也可能形如 `cbb_*_<后缀>`，按名字模式推断会把它误放行。

LOCAL_LIST = "flow/lint/local_cbb.txt"
LOCAL_COPY = "designs/foo/rtl/cbb_lzd_foo.v"
CASE_FAIL = "FAIL  RTL 模块名"
STYLE_LOCAL = (STYLE_OK.replace("CBB_LZD #(", "cbb_lzd_foo #(", 1)
               .replace("U_STY_IDLE_CBB_LZD", "U_CBB_LZD_IDLE", 1))


def _local_repo(tmp_path, listed=(LOCAL_COPY,), copy_mod="cbb_lzd_foo", sty=STYLE_LOCAL,
                extra=None):
    files = {"sty.v": sty, "cbb_lzd_foo.v": _good_rtl(mod=copy_mod)}
    script = _style_repo(tmp_path, files)
    for rel, text in (extra or {}).items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    if listed is not None:
        (tmp_path / LOCAL_LIST).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / LOCAL_LIST).write_text("# 本地 CBB 副本\n" + "".join(p + "\n" for p in listed))
    return script


def test_local_cbb_copy_with_lowercase_name_passes(tmp_path):
    r = _run(_local_repo(tmp_path))
    out = r.stdout + r.stderr
    assert f"ok    {STYLE}" in out, f"名单内的副本与 U_CBB_LZD_IDLE 例化应当通过（{LOCAL_LIST}）：\n{out}"
    assert CASE_FAIL not in out, f"名单内的小写副本不应报模块名（{LOCAL_LIST}）：\n{out}"


@pytest.mark.parametrize("kwargs, want", [
    # 不在名单里：即使形如 cbb_*_<后缀> 也按全大写报
    (dict(listed=None), "模块名不是全大写：cbb_lzd_foo"),
    # 名单失效：路径不存在 / 不在设计根的 rtl/ 下
    (dict(listed=(LOCAL_COPY, "designs/foo/rtl/cbb_gone_foo.v")), f"{LOCAL_LIST}:3"),
    (dict(listed=("designs/foo/cbb_lzd_foo.v",), extra={"designs/foo/cbb_lzd_foo.v": "// x\n"}),
     f"{LOCAL_LIST}:2"),
    # 副本声明的模块名与文件名不一致
    (dict(copy_mod="cbb_lzd_foo_x"), "本地 CBB 模块名必须是 cbb_lzd_foo"),
])
def test_local_cbb_list_and_module_name_failures(tmp_path, kwargs, want):
    r = _run(_local_repo(tmp_path, **kwargs))
    out = r.stdout + r.stderr
    # 不看退出码：夹具的 sty.v 本来就过不了 lint（例化口没接全），退出码恒非 0；判据只看报错文字
    assert want in out, f"报错里没有 {want}（{LOCAL_LIST}）：\n{out}"


# 名单也可以随设计根走（kaiwu-layout-decouple D5，内部#305）：`<设计根>/local_cbb.txt` 与全仓名单取并集，
# 只能列本根 rtl/ 下的文件；它是设计根的源文件，洁净度检查不得拦它。
ROOT_LIST = "designs/foo/local_cbb.txt"


def test_root_local_cbb_list_is_honoured_and_counts_as_source(tmp_path):
    script = _local_repo(tmp_path, listed=None)
    (tmp_path / ROOT_LIST).write_text("# 本根的本地 CBB 副本\n" + LOCAL_COPY + "\n")
    r = _run(script)
    out = r.stdout + r.stderr
    assert f"ok    {STYLE}" in out, f"设计根名单里的副本应当通过（{ROOT_LIST}）：\n{out}"
    assert CASE_FAIL not in out, out
    assert "ok    设计根下只有源文件" in out, out


def test_root_local_cbb_list_may_not_reach_into_another_root(tmp_path):
    other = "designs/bar/rtl/cbb_lzd_bar.v"
    script = _local_repo(tmp_path, listed=None, extra={other: "// x\n"})
    (tmp_path / ROOT_LIST).write_text(LOCAL_COPY + "\n" + other + "\n")
    out = (lambda r: r.stdout + r.stderr)(_run(script))
    assert f"{ROOT_LIST}:2" in out and "本设计根" in out, out


@pytest.mark.parametrize("inst", [
    "U_CBB_LZD_IDLE_FOO",     # 带隔离后缀
    "U_STY_IDLE_CBB_LZD",     # 按普通 D7 写
    "U_cbb_lzd_idle",         # 不是全大写
])
def test_local_cbb_instance_name_failures(tmp_path, inst):
    sty = STYLE_LOCAL.replace("U_CBB_LZD_IDLE", inst, 1)
    out, block = _style_out(_local_repo(tmp_path, sty=sty))
    assert f"FAIL  {STYLE}" in out, f"本地副本例化名 {inst} 应当失败（{LOCAL_LIST}）：\n{out}"
    assert "[例化名]" in block and inst in block, block


def test_uppercase_copy_suffix_does_not_relax_d7(tmp_path):
    """被例化模块名以大写后缀（如 `_FOO`）结尾时，例化名仍要以完整模块名结尾（rtl-r4-07）。"""
    sty = STYLE_OK.replace("CBB_LZD #(", "CBB_LZD_FOO #(", 1)
    out, block = _style_out(_local_repo(tmp_path, listed=(), sty=sty))
    assert f"FAIL  {STYLE}" in out, f"U_STY_IDLE_CBB_LZD 例化 CBB_LZD_FOO 应当失败（{LOCAL_LIST}）：\n{out}"
    assert "[例化名]" in block and "U_STY_IDLE_CBB_LZD" in block, block


@pytest.mark.parametrize("text,bad", [
    ("对端在握手之前可以改 valid 与全部载荷。", True),
    ("上游握手前可撤回 valid。", True),
    ("对端握手前会改 flg（例外，出处：#264）。", False),
    ("valid 拉高后保持到握手，握手后下一拍才可改。", False),
])
def test_handshake_exception_needs_source(tmp_path, text, bad):
    """内部#284 的 H1：「握手前可以改 / 撤回」一类写法要标「例外」并注出处（docs/spec-writing.md §3）；
    handshake-depth-contracts（内部#286，用户 10-13）由提示转致命，违规行不缩进、以 路径:行号: 开头，可登记豁免。"""
    r, out = _doc_run(tmp_path, lrs=_lrs(_good_spec("FOO")), lld=_good_lld(text=text))
    assert (r.returncode != 0) is bad, out
    assert ("H1 握手规则例外" in out) is bad, out
    if bad:
        assert "\ndesigns/foo/lld.FOO.md:" in out, out


def test_handshake_exception_can_be_waived(tmp_path):
    lld = _good_lld(text="上游握手前可撤回 valid。")
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "lld.FOO.md").write_text(lld)
    _write_waivers(tmp_path, "waivers:\n  - check: doc\n    files: designs/foo/lld.FOO.md\n"
                             "    issue: 285\n    until: spec 删掉这句之后\n    count: 1\n")
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[豁免 #285] designs/foo/lld.FOO.md:" in r.stdout, r.stdout


# --- 通用验证项表（handshake-depth-contracts D2，内部#286）---



@pytest.mark.parametrize("kind,verify,needle", [
    ("missing", _verify_md(table=False), "没有「通用规范」表"),
    ("short", _verify_md(rows=COMMON_ROWS[:-1]), "功能不依赖打拍配置"),
    ("empty", _verify_md(cover=""), "覆盖格是空的"),
])
def test_common_verify_table_required(tmp_path, kind, verify, needle):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "verify.FOO.md").write_text(verify)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    assert "\ndesigns/foo/verify.FOO.md: " in r.stdout and needle in r.stdout, r.stdout


def test_common_verify_table_ok_and_waivable(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "verify.FOO.md").write_text(_verify_md())
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode == 0, r.stdout + r.stderr
    (tmp_path / "designs" / "foo" / "verify.FOO.md").write_text(_verify_md(table=False))
    _write_waivers(tmp_path, "waivers:\n  - check: doc\n    files: designs/foo/verify.FOO.md\n"
                             "    issue: 289\n    until: 补表之后\n    count: 1\n")
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[豁免 #289] designs/foo/verify.FOO.md:" in r.stdout, r.stdout


# --- 位复制计数与被测顶层的参数检查块（handshake-depth-contracts D5、D6，内部#286）---

@pytest.mark.parametrize("expr,flagged", [
    ("{(DAT_W-1){1'b0}}", False),
    ("{DAT_W{1'b0}}", False),
    ("{DAT_W-1{1'b0}}", True),
    ("{DAT_W/2{1'b0}}", True),
])
def test_replication_count_needs_parens(tmp_path, expr, flagged):
    sty = STYLE_OK.replace("assign o_y = sum;", f"assign o_y = sum ^ {{1'b0,{expr}}};", 1)
    out, block = _style_out(_style_repo(tmp_path, {"sty.v": sty}))
    assert (f"FAIL  {STYLE}" in out) is flagged, out
    if flagged:
        assert "[位复制计数]" in block and "designs/foo/rtl/sty.v:" in block, block


def test_param_check_block_required_on_top(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    f = tmp_path / "designs" / "foo" / "rtl" / "foo.v"
    f.write_text(f.read_text().replace("`ifdef CBB_PARAM_CHK_ON\n`endif\n", ""))
    out, block = _style_out(script)
    assert f"FAIL  {STYLE}" in out, out
    assert "[参数检查块]" in block and "FOO" in block and "designs/foo/rtl/foo.v" in block, block


def test_param_check_block_not_required_on_submodule(tmp_path):
    sub = _good_rtl("FOO_SUB").replace("`ifdef CBB_PARAM_CHK_ON\n`endif\n", "")
    out, _ = _style_out(_style_repo(tmp_path, {"foo_sub.v": sub}))
    assert f"ok    {STYLE}" in out, out
