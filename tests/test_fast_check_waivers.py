"""`scripts/fast_check.sh` 的用例：失败豁免（内部#254、内部#290）。

内部#336 从 tests/test_fast_check.py 按小节拆出，用例原样；夹具在 tests/fast_check_fixture.py。
"""
from fast_check_fixture import *  # noqa: F401,F403


# --- 失败豁免（内部#254，fast-check-waivers）---

def _add_directive(repo, name="foo"):
    """在 designs/foo/rtl/<name>.v 的 module 前加一个综合指令属性 —— 触发 directive 段。"""
    f = repo / "designs" / "foo" / "rtl" / f"{name}.v"
    if not f.exists():
        f.write_text(_good_rtl(name.upper()))
    f.write_text(f.read_text().replace("module ", "(* keep_hierarchy *)\nmodule ", 1))


WAIVER_FOO = """\
waivers:
  - check: directive
    files: designs/foo/rtl/foo.v
    issue: 246
    until: 改成 params.yaml 的 keep_hierarchy 之后
    count: 1
"""


def test_waiver_absent_directive_fails(tmp_path):
    """夹具自检：没有豁免时 directive 段失败，且失败的只有这一段。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    assert fails == ["FAIL  可综合 RTL 里有综合指令属性"], r.stdout


def test_waiver_covers_all_violations_exits_zero(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _write_waivers(tmp_path, WAIVER_FOO)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert "WAIVED  可综合 RTL 里有综合指令属性" in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[豁免 #246] designs/foo/rtl/foo.v:" in r.stdout, r.stdout
    assert "生效的豁免" in r.stdout and "designs/foo/rtl/foo.v" in r.stdout, r.stdout
    assert "未核 issue 状态" in r.stdout, "跳过联网查询却没说\n" + r.stdout


def test_waiver_partial_still_fails(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _add_directive(tmp_path, "foo2")
    _write_waivers(tmp_path, WAIVER_FOO)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    assert "FAIL  可综合 RTL 里有综合指令属性" in r.stdout, r.stdout
    assert "[豁免 #246] designs/foo/rtl/foo.v:" in r.stdout, r.stdout
    assert "\n[未豁免] designs/foo/rtl/foo2.v:" in r.stdout, r.stdout


def test_waiver_missing_field_fails(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _write_waivers(tmp_path, WAIVER_FOO.replace("    issue: 246\n", ""))
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    assert "FAIL  失败豁免" in r.stdout and "issue" in r.stdout, r.stdout


def _add_second_directive(repo):
    """同一文件再加一个综合指令（真实形态：挂着豁免的文件里又写进一条新违规，内部#330 的 1ac5b5e0）。"""
    f = repo / "designs" / "foo" / "rtl" / "foo.v"
    f.write_text(f.read_text().replace("    assign o_y = i_a;\n", "    (* keep *) wire extra_w;\n    assign extra_w = 1'b0;\n    assign o_y = i_a;\n", 1))


def test_waiver_fixture_has_two_violations_in_one_file(tmp_path):
    """夹具自检：加第二个指令后，directive 段对 foo.v 报两条违规（不是一条）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _add_second_directive(tmp_path)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    hits = [l for l in r.stdout.splitlines() if l.startswith("designs/foo/rtl/foo.v:") and "综合指令属性" in l]
    assert len(hits) == 2, r.stdout
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    assert fails == ["FAIL  可综合 RTL 里有综合指令属性"], r.stdout     # 只有 directive 段失败


def test_waiver_new_violation_in_waived_file_fails(tmp_path):
    """内部#330：豁免登记 1 条，同一文件本次 2 条 —— 多出来的是新违规，这一段失败，写出登记数与本次数。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _add_second_directive(tmp_path)
    _write_waivers(tmp_path, WAIVER_FOO)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    assert "FAIL  可综合 RTL 里有综合指令属性" in r.stdout, r.stdout
    assert "登记 1 条，本次 2 条" in r.stdout, r.stdout


def test_waiver_count_above_actual_fails_asking_to_lower_it(tmp_path):
    """登记 2 条，本次只剩 1 条 —— 余量会藏住以后的新违规，要求把 count 改成 1。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _write_waivers(tmp_path, WAIVER_FOO.replace("count: 1", "count: 2"))
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    assert "登记 2 条，本次 1 条" in r.stdout and "count 改成 1" in r.stdout, r.stdout


@pytest.mark.parametrize("count", [None, "0", "两条"])
def test_waiver_count_is_required_and_positive(tmp_path, count):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    body = WAIVER_FOO.replace("    count: 1\n", "" if count is None else f"    count: {count}\n")
    _write_waivers(tmp_path, body)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    assert "FAIL  失败豁免文件有误" in r.stdout and "count" in r.stdout, r.stdout


def test_waiver_stale_when_violation_fixed(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _write_waivers(tmp_path, WAIVER_FOO)
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0, r.stdout
    assert "FAIL  失败豁免过时" in r.stdout and "designs/foo/rtl/foo.v" in r.stdout, r.stdout


@pytest.mark.parametrize("gh_state,expect", [("closed", "note  豁免挂的 #246 已关，修复还没进本分支"),
                                              (None, "未核 issue 状态（查不到：#246）")])
def test_waiver_issue_state(tmp_path, gh_state, expect):
    """豁免还在放行违规而 issue 已关 → 只提示、不拦（内部#291：修复交付即关、还没进 main 时不能卡住基于 main 的分支）；
    查不到（没有 gh）→ 只提示。用桩 gh，不联网。豁免不再放行任何违规时仍判过时，见 test_waiver_stale_when_violation_fixed。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _write_waivers(tmp_path, WAIVER_FOO)
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    if gh_state:
        gh = bindir / "gh"
        gh.write_text(f"#!/bin/sh\necho {gh_state}\n")
        gh.chmod(0o755)
    r = _run_with_path(script, stub=STUB_OK)
    assert expect in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout
    assert "FAIL  失败豁免过时" not in r.stdout, r.stdout


def test_waiver_issue_lookup_uses_this_repos_remote(tmp_path):
    """内部#329：核 issue 状态不写死仓名，用 gh 的 {owner}/{repo} 占位符按当前仓的远端解析（导出到公开仓后查它自己）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _add_directive(tmp_path)
    _write_waivers(tmp_path, WAIVER_FOO)
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = tmp_path / "gh_argv.txt"
    gh = bindir / "gh"
    gh.write_text(f'#!/bin/sh\necho "$@" >> {argv_log}\necho open\n')
    gh.chmod(0o755)
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode == 0, r.stdout
    called = argv_log.read_text()
    assert "repos/{owner}/{repo}/issues/246" in called, called
    assert "TanglmChris" not in called, called


def _verilator_with_version(tmp_path, version):
    """一个报指定版本号的桩 verilator；真去 lint 就失败，用来证明低版本时 lint 确实没跑。"""
    vdir = tmp_path / f"vl_{version}"
    vdir.mkdir()
    v = vdir / "verilator"
    v.write_text(
        "#!/bin/sh\n"
        f'[ "$1" = --version ] && {{ echo "Verilator {version} 2024-01-01 rev v{version}"; exit 0; }}\n'
        "echo 'stub: lint ran' >&2\nexit 1\n")
    v.chmod(0o755)
    return vdir


@pytest.mark.parametrize("version,ok", [("5.020", False), ("5.036", True), ("5.053", True)])
def test_verilator_below_minimum_is_environment_fail_not_lint_fail(tmp_path, version, ok):
    """内部#260：verilator 低于最低版本时报一行「环境」FAIL、lint 记未执行，不跑出 lint FAIL；达标照常 lint。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    vdir = _verilator_with_version(tmp_path, version)
    bindir = script.parent.parent / "stubbin"
    path = f"{vdir}:{bindir}:{_VENV_BIN}:/usr/bin:/bin:/usr/sbin:/sbin"
    r = _run_with_path(script, stub=STUB_OK, env_extra={"PATH": path})
    assert shutil.which("verilator", path=path) == str(vdir / "verilator"), "夹具失效：桩 verilator 没排在最前"
    if ok:
        # 达标时 lint 真的跑了：桩在 lint 时退出 1，所以应当看到 lint 失败而不是环境失败
        assert "FAIL  环境" not in r.stdout, r.stdout
        assert "lint" in r.stdout and r.returncode != 0, "达标版本却没跑 lint\n" + r.stdout
    else:
        assert r.returncode != 0, r.stdout
        assert f"FAIL  环境：verilator {version} < 5.036" in r.stdout, r.stdout
        assert "未执行  RTL lint（环境不合格" in r.stdout, r.stdout
        assert "stub: lint ran" not in r.stdout + r.stderr, "环境不合格却照跑了 lint\n" + r.stdout


# --- 内部#290：doc 段旧有违规也能按文件豁免 ---

def test_doc_legacy_violation_can_be_waived(tmp_path):
    """缺必填节一类的旧有 doc 违规打成不缩进、路径打头的行，登记豁免后 WAIVED（内部#290）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    lld = tmp_path / "designs" / "foo" / "lld.FOO.md"
    lld.write_text(lld.read_text().replace("## 设计断言", "## 别的节"))
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode != 0 and "\ndesigns/foo/lld.FOO.md 缺必填节" in r.stdout, r.stdout
    _write_waivers(tmp_path, "waivers:\n  - check: doc\n    files: designs/foo/lld.FOO.md\n"
                             "    issue: 290\n    until: 补节之后\n    count: 1\n")
    r = _run_with_path(script, stub=STUB_OK, env_extra=_NO_NET)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[豁免 #290] designs/foo/lld.FOO.md 缺必填节" in r.stdout, r.stdout
