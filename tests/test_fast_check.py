"""`scripts/fast_check.sh` 报告的通过必须是真的通过。

为什么值得有这个测试：这个脚本是 pre-push 钩子调的那一个，是**护栏本身**。
它误报的后果与别处不同 —— 别的地方错了是少一份数据，这里错了是「以为有防护」。
2026-09-09 修的两个缺陷都属于"报告的范围大于实际检查的范围"：

- 某个设计只要有一个组合 elaborate 失败，仍然照打 `ok ... (all param combos)`
  （退出码是对的，误导的是读日志的人）；
- `params.yaml` 里 `values` 写错键名或给成空列表时，组合展开产出空结果，
  循环拿空参数跑了一次 **iverilog 默认参数**，通过、打印「all param combos」、
  **退出码 0** —— 报告"全部组合已检查"，实际一个组合都没检查。

夹具是一个**独立的最小仓库**，不是本仓库：脚本按自身位置 `cd` 到仓库根，
拿真实设计当夹具就没法构造"坏掉的 params.yaml"这种输入。
"""
from fast_check_fixture import *  # noqa: F401,F403（夹具，内部#336）


@needs_iverilog
def test_all_combos_ok(tmp_path):
    """基线：全部组合都能 elaborate 时，报 ok 且退出码 0。"""
    r = _run(_fixture_repo(tmp_path, GOOD_PARAMS))
    assert r.returncode == 0, r.stdout
    assert "ok    elaborate FOO (all param combos)" in r.stdout


@needs_iverilog
def test_a_params_yaml_without_tops_is_a_failure(tmp_path):
    """缺 `tops:` 必须是 FAIL，**不得**回退到「以目录名为顶层」。

    这一条与 `test_no_combos_is_a_failure` 同形，防的也是同一类失效：
    脚本拿一个它其实没读懂的声明照常跑一次、照常打 ok、照常退出 0。
    区别只在触发方式 —— 那一条是 `values` 写错，这一条是整段声明还是旧形态。
    回退一旦存在，一份漏写 `tops:` 的 params.yaml 就会静默按目录名跑，
    而那正是最该报错的时刻。
    """
    for d in ("flow", "scripts", "cbb"):
        (tmp_path / d).mkdir()
    rtl = tmp_path / "designs" / "foo" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "foo.v").write_text(GOOD_RTL)
    # 旧形态：params: 直接挂在根下，没有 tops:
    (tmp_path / "designs" / "foo" / "params.yaml").write_text(GOOD_PARAMS)
    shutil.copy(SCRIPT, tmp_path / "scripts" / "fast_check.sh")
    # fast_check 读哪些文件由 flow/paths.py::rtl_candidates 决定（add-design-cbb-deps D3），
    # 夹具仓库要带上这一份 —— 拷的是本仓的真文件，不是替身。
    _copy_paths_py(tmp_path)
    r = _run(tmp_path / "scripts" / "fast_check.sh")
    assert r.returncode != 0, f"缺 tops: 却退出 0，护栏静默放行\n{r.stdout}"
    assert "tops" in r.stdout, (
        f"报错该点名缺的是 tops:，实际是：\n{r.stdout}")
    assert "all param combos" not in r.stdout, (
        "声明没读懂却报告全部组合已检查：\n" + r.stdout)


@needs_iverilog
def test_partial_failure_does_not_claim_all_combos_ok(tmp_path):
    """有组合失败时**不得**再打印那句 all param combos（回归：修复前会照常打印）。"""
    r = _run(_fixture_repo(tmp_path, GOOD_PARAMS, extra_rtl=BROKEN_RTL))
    assert r.returncode != 0, r.stdout
    assert "FAIL  elaborate FOO" in r.stdout
    assert "all param combos" not in r.stdout, (
        "某个设计有组合失败，却仍然报告它的全部组合都过了：\n" + r.stdout)


@needs_iverilog
@pytest.mark.parametrize("params_yaml, why", [
    ("params:\n  DAT_W:\n    valuez: [4, 8]\n", "values 键名写错"),
    ("params:\n  DAT_W:\n    values: []\n", "values 是空列表"),
])
def test_no_combos_is_a_failure(tmp_path, params_yaml, why):
    """展开不出组合必须是 FAIL —— 否则会拿 RTL 默认参数跑一次并报告全部通过。"""
    r = _run(_fixture_repo(tmp_path, params_yaml))
    assert r.returncode != 0, f"{why}: 退出码 0，护栏静默放行\n{r.stdout}"
    assert "FAIL  展开参数组合 foo" in r.stdout, r.stdout
    assert "all param combos" not in r.stdout, (
        f"{why}: 一个组合都没检查，却报告全部组合已检查\n{r.stdout}")


# --- 护栏必须说出自己实际覆盖了什么（guardrail-scope） -----------------------
#
# 下面这组用**桩 iverilog** 而不是 @needs_iverilog。测的是 fast_check.sh 的控制流
# 与报告口径，不是 iverilog 本身；桩既让这组测试在没装工具链的机器上也能跑，
# 也让"elaborate 失败"这种输入可以被确定性地构造出来。

# 见到某个特定源文件就失败，用来构造"部分组合失败"
STUB_FAILS_ON_BAD = """\
#!/bin/sh
for a in "$@"; do
  case "$a" in *bad.v) echo "stub: refusing bad.v" >&2; exit 1;; esac
done
""" + _STUB_VVP + "exit 0\n"


def _assert_harness_sane(script, stub):
    """夹具自检：确认这一轮 iverilog 的可见性确实是测试想要的那种。"""
    bindir = script.parent.parent / "stubbin"
    path = f"{bindir}:{_VENV_BIN}:/usr/bin:/bin:/usr/sbin:/sbin"
    found = shutil.which("iverilog", path=path)
    if stub is None:
        assert found is None, f"夹具失效：本应没有 iverilog，却找到 {found}"
        vfound = shutil.which("verilator", path=path)
        assert vfound is None, f"夹具失效：本应没有 verilator，却找到 {vfound}"
    else:
        assert found is not None, "夹具失效：桩 iverilog 没有生效"
    assert shutil.which("bash", path=path), "夹具失效：PATH 上没有 bash"
    assert shutil.which("python3", path=path), "夹具失效：PATH 上没有 python3"


def test_missing_tool_is_a_failure_not_a_skip(tmp_path):
    """M1: 工具缺失不得被当作通过——退出码必须非 0，且要说清怎么修、怎么显式降级。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _assert_harness_sane(script, None)
    r = _run_with_path(script, stub=None)
    assert r.returncode != 0, "iverilog 缺失却以 0 退出：护栏静默放行"
    assert "iverilog" in r.stdout, r.stdout
    assert "~/tools/env.sh" in r.stdout, "没有给出修复方式\n" + r.stdout
    assert "FAST_CHECK_ALLOW_MISSING_TOOLS=1" in r.stdout, "没有给出具名降级方式\n" + r.stdout
    assert "--no-verify" in r.stdout, "没有给出 git 自己的旁路\n" + r.stdout
    assert "verilator" in r.stdout, "verilator 缺失没有被点名 —— lint 一项静默没跑\n" + r.stdout


def _tools_env_file(tmp_path):
    """一份替身 ~/tools/env.sh：把放着桩 iverilog / verilator 的目录接到 PATH 前面。

    故意引用一个没定义的变量 —— 真的 env.sh 也可能这样，fast_check 开着 set -u，
    source 它不能把护栏自己炸掉。"""
    tooldir = tmp_path / "toolsbin"
    tooldir.mkdir()
    for name, body in (("iverilog", STUB_OK), ("verilator", "#!/bin/sh\nexit 0\n")):
        f = tooldir / name
        f.write_text(body)
        f.chmod(0o755)
    env_sh = tmp_path / "env.sh"
    env_sh.write_text(f': "${{FAST_CHECK_NO_SUCH_VAR_XYZ}}"\nexport PATH="{tooldir}:$PATH"\n')
    return env_sh


def test_tools_env_is_sourced_when_tools_are_missing(tmp_path):
    """内部#107：工具不在 PATH 时，fast_check 自己 source 工具链脚本再查，并说出来。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    script = _fixture_repo(repo, GOOD_PARAMS)
    _assert_harness_sane(script, None)
    env_sh = _tools_env_file(tmp_path)
    r = _run_with_path(script, stub=None, env_extra={"FAST_CHECK_TOOLS_ENV": str(env_sh)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert str(env_sh) in r.stdout, "补了 PATH 却没说从哪补的\n" + r.stdout


def test_tools_env_missing_still_fails(tmp_path):
    """内部#107：工具链脚本不存在时照旧失败（P-17 的口径不变），不因「试过补」而放行。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    r = _run_with_path(script, stub=None,
                       env_extra={"FAST_CHECK_TOOLS_ENV": str(tmp_path / "no_such_env.sh")})
    assert r.returncode != 0, r.stdout
    assert "iverilog 不在 PATH" in r.stdout, r.stdout


def test_worktree_without_venv_gets_symlink_to_main(tmp_path):
    """内部#108：worktree 里没有 .venv、主仓有时，fast_check 软链主仓的 .venv 并说出来。"""
    main = tmp_path / "main"
    main.mkdir()
    script = _fixture_repo(main, GOOD_PARAMS)
    (main / ".gitignore").write_text(".venv\n")
    _ensure_git(script)
    (main / ".venv").symlink_to(REPO_ROOT / ".venv")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "wt", str(wt))
    assert not (wt / ".venv").exists()
    r = _run_with_path(wt / "scripts" / "fast_check.sh", stub=STUB_OK)
    assert (wt / ".venv").is_symlink(), r.stdout + r.stderr
    assert (wt / ".venv").resolve() == (main / ".venv").resolve()
    assert not (wt / ".venv").readlink().is_absolute(), (wt / ".venv").readlink()  # 工作区改名后照样能用（用户 10-25）
    assert ".venv" in r.stdout and str(main) in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout + r.stderr


def test_named_downgrade_exits_zero_but_names_what_was_skipped(tmp_path):
    """M2: 显式降级可以退出 0，但摘要必须逐项列出没跑的检查。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _assert_harness_sane(script, None)
    r = _run_with_path(script, stub=None,
                       env_extra={"FAST_CHECK_ALLOW_MISSING_TOOLS": "1"})
    assert r.returncode == 0, r.stdout
    # 先断言 M2 声明的主行为：摘要里把没跑的那类检查列出来
    assert "未执行" in r.stdout, "降级运行没有在摘要里列出未执行的检查"
    assert "RTL elaborate" in r.stdout, r.stdout
    assert "RTL lint" in r.stdout, "lint 没跑却没列进未执行\n" + r.stdout
    assert "DEGRADED" in r.stdout, "降级运行没有被标明\n" + r.stdout


# --docs-only（merge-check-reuse 1.4，内部#379）：merge_check 只改文档时传它，只跳 RTL lint。
# 桩 verilator 必失败：不带开关时 lint 红；带开关时 lint 不跑，摘要列为未执行，elaborate 与端口表照跑。
VERILATOR_FAILS = "#!/bin/sh\necho '%Warning-UNUSED: stub' >&2\nexit 1\n"


def test_docs_only_skips_lint_but_still_elaborates(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    full = _run_with_path(script, stub=STUB_OK, verilator=VERILATOR_FAILS)
    assert full.returncode != 0 and "FAIL  lint FOO" in full.stdout, "夹具失效：不带开关时桩 verilator 应让 lint 红\n" + full.stdout
    r = _run_with_path(script, stub=STUB_OK, verilator=VERILATOR_FAILS, args=("--docs-only",))
    assert r.returncode == 0, r.stdout
    assert "未执行  RTL lint" in r.stdout and "--docs-only" in r.stdout, "lint 没跑却没列进未执行\n" + r.stdout
    assert "已执行  RTL elaborate FOO" in r.stdout, r.stdout
    assert "已执行  spec 端口表与 RTL 一致" in r.stdout, "端口表读的是文档，只改文档也要照跑\n" + r.stdout


def test_summary_is_printed_on_the_passing_path(tmp_path):
    """M3: 全绿时也必须打印覆盖摘要——成功路径才是没人细看的那条。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    r = _run_with_path(script, stub=STUB_OK)
    _assert_harness_sane(script, STUB_OK)
    assert r.returncode == 0, r.stdout
    assert "覆盖摘要" in r.stdout, "摘要缺失：护栏没有说出它这一轮检查了什么"
    assert "python compileall" in r.stdout, r.stdout
    assert "RTL elaborate" in r.stdout, r.stdout
    assert "未执行" not in r.stdout, "全绿运行的摘要里不该出现未执行项\n" + r.stdout


def test_leak_over_baseline_fails(tmp_path):
    """内部#365：开源路径里新写进 block 命中、超过基线时 fast_check 失败，只列文件与次数。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = script.parent.parent
    (root / "flow" / "export" / "manifest.yaml").write_text(
        "include:\n  - flow/**\nrules:\n  block:\n    - name: secret-name\n      pattern: '\\bsecret_ip\\b'\n  warn: []\n")
    (root / "flow" / "leaky.py").write_text("x = 'secret_ip'\n")
    r = _run_with_path(script, stub=STUB_OK)
    assert r.returncode == 1, r.stdout
    assert "FAIL  开源集合泄漏不增" in r.stdout and "超过基线 0" in r.stdout, r.stdout
    assert "flow/leaky.py 1" in r.stdout, r.stdout  # 夹具停在 main 上，merge-base 就是自己：按文件列命中
    assert "'secret_ip'" not in r.stdout


def test_partial_failure_still_fails_with_stub(tmp_path):
    """M4 回归: 部分组合失败时仍退出非 0，且不声称覆盖全部组合。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS, extra_rtl=BROKEN_RTL)
    r = _run_with_path(script, stub=STUB_FAILS_ON_BAD)
    _assert_harness_sane(script, STUB_FAILS_ON_BAD)
    assert r.returncode != 0, r.stdout
    # 只看 elaborate 那一行：lint 是另一项检查，它在这里合法地全过
    assert "ok    elaborate FOO (all param combos)" not in r.stdout, (
        "有组合失败却报告全部组合都过了\n" + r.stdout)


SWEEP_FALSE_PARAMS = """\
params:
  DAT_W:
    values: [4, 8]
  BLK_N:
    sweep: false
    values: [1, 2, 3]
"""


def test_sweep_false_values_are_still_elaborated(tmp_path):
    """`sweep: false` 只把参数挡在**实验**叉乘之外，不该把它挡在**检查**之外。

    两个展开器是分开的，且必须保持分开：
      - flow/paths.py::param_combos() 尊重 sweep: false —— scripts/sweep.py 用它，
        为的是不产生「参数标签不同、实际电路相同」的冗余记录；
      - scripts/fast_check.sh 自己内联展开，对全部 values 叉乘 —— 护栏要覆盖
        每一个**可被声明的**取值，否则 params.yaml 里写得出来的组合会没人 elaborate 过。

    这个测试锁住后者。把 fast_check 改成调用 param_combos()「保持一致」，
    看起来是消除重复，实际会让护栏覆盖面从全部 values 静默缩到 values[0] ——
    正是 issue 内部#9 曾经**以为**已经发生、而实际并未发生的那件事。
    """
    script = _fixture_repo(tmp_path, SWEEP_FALSE_PARAMS)
    r = _run_with_path(script, stub=STUB_OK)
    _assert_harness_sane(script, STUB_OK)
    assert r.returncode == 0, r.stdout
    # DAT_W(2) × BLK_N(3) = 6；若尊重 sweep: false 则只有 2
    assert "6 个参数组合" in r.stdout, (
        "护栏没有覆盖 sweep: false 参数的全部取值——覆盖面被缩窄了\n" + r.stdout)


# --- 护栏自身在 bash 3.2 上跑得起来，且夭折不会被报成通过 ---
# 这两条**故意不加** `@needs_iverilog`：它们要防的失效正是「在 bash 4 的机器上
# 开发、在 bash 3.2 的机器上跑，而上面那批用例因为 iverilog 不在 PATH 全被跳过」。

def test_the_script_does_not_use_bash_4_associative_arrays():
    """`declare -A` 在 macOS 自带的 bash 3.2 上不存在。

    2026-09-20 引入的逐顶层统计用了关联数组。它在 3.2 上的表现不是当场报错
    退出，而是打一句 `declare: -A: invalid option` 接着跑，到下一行
    `${top_fail[$top]}` 把顶层名当算术展开、撞上 set -u 才夭折 —— 只打了第一条
    检查，**退出码 0**。2026-09-24 在 mac mini 上实测到这一幕。

    源码扫描比行为用例更适合守这一条：行为用例要有 iverilog 才跑，而这个缺陷
    恰恰只在"有 iverilog"的机器上才现形，两个条件在同一台机器上凑齐才被看见。

    整行注释不算 —— 修复本身就要在注释里写明为什么不能用它，与 RTL 那几项
    源码扫描同口径（`test_a_directive_named_only_in_a_comment_is_not_a_violation`）。
    """
    code = [ln for ln in SCRIPT.read_text().splitlines()
            if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code if "declare -A" in ln], (
        "fast_check.sh 用了关联数组，macOS 自带的 bash 3.2 跑不了它 ——"
        "逐顶层统计请用平行的下标数组加线性查找，见 `_top_slot`")


def test_a_premature_abort_cannot_report_success(tmp_path):
    """脚本中途夭折时，退出码必须不是 0。

    bash 不保证把夭折传出来：实测 bash 3.2 在 `while ... done <<< "$str"` 里
    撞上 set -u 的未绑定变量，脚本只打了第一条检查就结束，**退出码是 0**。
    对一个 pre-push 护栏来说这是最坏的一种失效 —— 不是"少查了一项"，是
    "以为有防护"，而且它与「一切正常」在退出码上一模一样。

    这里往哨兵之后、第一项 RTL 检查之前注入一条必然夭折的语句，复现的就是
    实测那一幕的形状。不需要 iverilog：夭折发生在 elaborate 之前。
    """
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    src = script.read_text()
    marker = "# --- RTL: elaborate（iverilog）+ lint（verilator），每个参数组合各跑一次 ---\n"
    assert marker in src, "脚本结构变了，注入点要跟着改"
    script.write_text(src.replace(
        marker, ': "${__fast_check_no_such_var__}"\n' + marker, 1))
    r = _run(script)
    assert r.returncode != 0, (
        f"脚本中途夭折却退出 0：\n{r.stdout}\n{r.stderr}")
    assert "没跑到末尾" in r.stderr, (
        f"夭折没被点名，读日志的人只会看到半截输出：\n{r.stdout}\n{r.stderr}")
    assert "覆盖摘要" not in r.stdout, (
        f"没跑完却印出了覆盖摘要：\n{r.stdout}")


# --- RTL lint（verilator --lint-only -Wall，豁免在 flow/lint/waivers.vlt）---------------

UNUSED_CLK_AND_EXTRA_RTL = """\
module FOO #(parameter DAT_W = 4) (input wire clk, input wire i_extra,
                               input wire [DAT_W-1:0] i_a, output wire [DAT_W-1:0] o_y);
  assign o_y = i_a;
endmodule
"""


def _lint_fixture(tmp_path, rtl, waivers=None):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "foo.v").write_text(rtl)
    _style_exempt(tmp_path, "designs/foo/rtl/foo.v")       # lint 告警的形状就是被测对象
    # 这些 RTL 比 GOOD_RTL 多几个 1 位输入，spec 端口表跟着写全
    extra = [n for n in ("clk", "extra") if f"input wire {n}" in rtl]
    _write_docs(tmp_path / "designs" / "foo", "FOO", _good_spec("FOO", extra))
    if waivers is not None:
        (tmp_path / "flow" / "lint").mkdir(parents=True, exist_ok=True)
        (tmp_path / "flow" / "lint" / "waivers.vlt").write_text(waivers)
    return script


@needs_verilator
def test_an_unwaived_lint_warning_is_a_failure(tmp_path):
    """elaborate 能过、lint 不过的 RTL 必须 FAIL，并点名是哪个组合、哪条 warning。"""
    r = _run(_lint_fixture(tmp_path, UNUSED_CLK_RTL))
    assert r.returncode != 0, "有未豁免的 lint warning 却以 0 退出\n" + r.stdout
    assert "FAIL  lint FOO DAT_W=4" in r.stdout, r.stdout
    assert "UNUSEDSIGNAL" in r.stdout and "'clk'" in r.stdout, r.stdout
    assert "ok    elaborate FOO" in r.stdout, "elaborate 与 lint 应当分开判\n" + r.stdout
    assert "ok    lint FOO" not in r.stdout, r.stdout


@needs_verilator
def test_a_waiver_silences_exactly_what_it_names(tmp_path):
    """豁免只放过它点名的那一条：同一文件、同一规则、换一个信号，照样 FAIL。"""
    r = _run(_lint_fixture(tmp_path, UNUSED_CLK_RTL, CLK_WAIVER))
    assert r.returncode == 0, r.stdout
    assert "ok    lint FOO (all param combos)" in r.stdout, r.stdout
    assert "豁免 1 条" in r.stdout, "摘要没写豁免了几条\n" + r.stdout

    other = tmp_path / "b"
    other.mkdir()
    r = _run(_lint_fixture(other, UNUSED_CLK_AND_EXTRA_RTL, CLK_WAIVER))
    assert r.returncode != 0, "豁免了 clk，extra 却也被放过了\n" + r.stdout
    assert "'i_extra'" in r.stdout and "'clk'" not in r.stdout, r.stdout


@needs_verilator
def test_a_design_root_carries_its_own_waivers(tmp_path):
    """内部#109：设计根顶层的 waivers.vlt 与 flow/lint/waivers.vlt 一起生效，算进摘要，洁净度不报它。"""
    script = _lint_fixture(tmp_path, UNUSED_CLK_RTL)
    (tmp_path / "designs" / "foo" / "waivers.vlt").write_text(CLK_WAIVER)
    r = _run(script)
    assert r.returncode == 0, r.stdout
    assert "ok    lint FOO (all param combos)" in r.stdout, r.stdout
    assert "豁免 1 条" in r.stdout, "设计根的豁免没算进摘要\n" + r.stdout
    assert "不该存在的东西" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert "ok    lint 豁免没有过时" in r.stdout, r.stdout


STALE_SIGNAL_WAIVER = CLK_WAIVER + 'lint_off -rule UNUSEDSIGNAL -file "*/foo.v" -match "*\'gone_sig\'*"\n'
STALE_FILE_WAIVER = CLK_WAIVER + 'lint_off -rule UNUSEDSIGNAL -file "*/no_such.v" -match "*\'clk\'"\n'


@needs_verilator
@pytest.mark.parametrize("waivers, needle", [
    (STALE_SIGNAL_WAIVER, "gone_sig"),
    (STALE_FILE_WAIVER, "no_such.v"),
])
def test_a_stale_waiver_fails_naming_its_line(tmp_path, waivers, needle):
    """内部#109：豁免的信号不在文件里、或 -file 匹配不到文件，都是过时豁免，失败并点名文件与行号。"""
    script = _lint_fixture(tmp_path, UNUSED_CLK_RTL)
    (tmp_path / "designs" / "foo" / "waivers.vlt").write_text(waivers)
    r = _run(script)
    assert r.returncode != 0, "过时豁免却以 0 退出\n" + r.stdout
    assert "FAIL  lint 豁免过时" in r.stdout, r.stdout
    assert "designs/foo/waivers.vlt:3" in r.stdout and needle in r.stdout, r.stdout


# --- 设计根可解析（flow-batch-2026-10 的 1.1，内部#74）--------------------------------
#
# 护栏自己按 params.yaml 遍历设计根，看不到「会让流程解析报错」的根：2026-09-28
# 一个只放规格的根让内循环 5 → 62 个失败，护栏却报通过。这一项用流程自己的入口建索引。

RESOLVE = "设计根可解析"


def test_a_root_with_rtl_but_no_params_fails_the_resolution_check(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    bad = tmp_path / "designs" / "forgot" / "rtl"
    bad.mkdir(parents=True)
    (bad / "forgot.v").write_text("module FORGOT; endmodule\n")
    out = (r := _run(script)).stdout + r.stderr
    assert r.returncode != 0 and f"FAIL  {RESOLVE}" in out, out
    assert "forgot" in out.split(f"FAIL  {RESOLVE}", 1)[1].split("\n\n", 1)[0], out


def test_a_spec_only_root_passes_and_is_counted(tmp_path):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    later = tmp_path / "designs" / "later"
    later.mkdir()
    (later / "spec.LATER.md").write_text("# LATER\n")
    out = (r := _run(script)).stdout + r.stderr
    assert f"ok    {RESOLVE}" in out and "其中 1 个规格先行" in out, out


def _spec_only_root(tmp_path, names):
    """规格先行根：没有 params.yaml 与 rtl/，只放 names 里的文档（doc/ 下的照放）。"""
    later = tmp_path / "designs" / "later"
    for name in names:
        (later / name).parent.mkdir(parents=True, exist_ok=True)
        (later / name).write_text("# LATER\n")


@needs_iverilog
def test_a_spec_only_root_may_hold_its_lrs_and_lld(tmp_path):
    """内部#391：repo-layout「设计根可以先只有规格」允许 lrs / lld 先进仓；以前「设计根下只有源文件」按 params.yaml
    的 tops: 放行文档，规格先行根没有 params.yaml，于是 lrs / lld 全被拒。这里看整体退出码，不只看可解析一项。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _spec_only_root(tmp_path, ["lrs.LATER.md", "lld.LATER.md", "doc/track.LATER.md"])
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ok    设计根下只有源文件" in out and "其中 1 个规格先行" in out, out


@needs_iverilog
def test_a_spec_only_root_with_two_top_names_is_refused(tmp_path):
    """顶层名无从对 params.yaml 核时，同一根内的文档顶层名必须一致：拼错一份就拒掉（内部#391）。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    _spec_only_root(tmp_path, ["lrs.LATER.md", "lld.LATR.md"])
    r = _run(script)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "FAIL  设计根下有非源文件" in out, out
    assert "lld.LATR.md" in out and "lrs.LATER.md" in out and "顶层名不一致" in out, out


# --- 参数片段：rtl/inc/ 自动成为 include 目录（flow-batch-2026-10 的 1.2，内部#76）---------

INC_RTL = _good_rtl().replace(
    "module FOO #(parameter DAT_W = 4)",
    'module FOO #(parameter DAT_W = 4\n`include "foo_param.vh"\n)').replace(
    "assign o_y = i_a;", "assign o_y = i_a ^ {DAT_W{SHIFT[0]}};")


def _inc_repo(tmp_path, fragment="    ,parameter SHIFT = 1\n"):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    (tmp_path / "designs" / "foo" / "rtl" / "foo.v").write_text(INC_RTL)
    inc = tmp_path / "designs" / "foo" / "rtl" / "inc"
    inc.mkdir()
    (inc / "foo_param.vh").write_text(fragment)
    return script


@needs_iverilog
def test_a_parameter_fragment_is_found_by_elaborate_and_lint(tmp_path):
    r = _run(_inc_repo(tmp_path))
    assert "ok    elaborate FOO (all param combos)" in r.stdout, r.stdout
    assert "ok    lint FOO (all param combos)" in r.stdout, r.stdout


def test_a_fragment_with_a_tab_fails_the_style_check(tmp_path):
    out = (r := _run(_inc_repo(tmp_path, "\t,parameter SHIFT = 1\n"))).stdout
    assert f"FAIL  {STYLE}" in out and "rtl/inc/foo_param.vh" in out and "[tab]" in out, out
