"""流程指纹：同一套流程算出同一个数，换掉任何一项都要变。

为什么值得有这个测试：指纹是"这两条记录能不能放在一起比"的唯一依据。
它错的两种方式不对称 —— **太细只会多分几代（噪音，看得见）；太粗会把不可比的
数据判成可比（假结论，看不见）**。所以这里逐项扰动六项事实里最容易被忽略的三个
配方常量，确认每一项都真的进了指纹。

liberty 只取内容、不取路径：换个位置放同一份库不该分代，而**换掉库的内容不改任何
commit** —— 那正是 `git_commit` 认不出流程代的根本原因（docs/data-credibility.md 的 D-2 就是
重新生成合并库那次）。
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import flow.flow_fingerprint as ff

TOOLS = ("yosys", "sta", "iverilog")
needs_tools = pytest.mark.skipif(
    any(shutil.which(t) is None for t in TOOLS),
    reason="需要 yosys / sta / iverilog 在 PATH 上（source ~/tools/env.sh）")

FACTS = ("yosys", "opensta", "sim", "liberty_sha256",
         "synth_recipe_sha256", "sta_recipe_sha256", "metrics_code_sha256",
         "corner_liberty_sha256", "cell_models_sha256", "design_recipe_sha256")
DESIGN = "CBB_LZD"    # 真实设计夹具（开源构件，内部#305）；指纹按设计算（fingerprint-per-design）


@pytest.fixture
def liberty(tmp_path):
    p = tmp_path / "a.lib"
    p.write_text("library (fake) { }\n")
    return p


# --- M1 ---------------------------------------------------------------------
@needs_tools
def test_fingerprint_is_deterministic(liberty):
    """纯函数：同一环境连算两次逐字相同（没有时间戳、没有随机数、没有路径）。"""
    a = ff.flow_fingerprint(liberty, design=DESIGN)
    b = ff.flow_fingerprint(liberty, design=DESIGN)
    assert a == b
    assert a["fingerprint"].startswith("sha256:")
    # 指纹里不得夹带路径 —— 换个目录放同一份库不该分代
    assert str(liberty) not in repr(a)


# --- M2 ---------------------------------------------------------------------
@needs_tools
def test_liberty_enters_by_content_not_by_path(tmp_path, liberty):
    other_content = tmp_path / "b.lib"
    other_content.write_text("library (fake) { /* 换了内容 */ }\n")
    same_content = tmp_path / "sub" / "a.lib"
    same_content.parent.mkdir()
    same_content.write_text(liberty.read_text())

    base = ff.flow_fingerprint(liberty, design=DESIGN)
    changed = ff.flow_fingerprint(other_content, design=DESIGN)
    moved = ff.flow_fingerprint(same_content, design=DESIGN)

    assert changed["liberty_sha256"] != base["liberty_sha256"]
    assert changed["fingerprint"] != base["fingerprint"]
    # 同样的内容换个路径：六项事实与指纹必须完全一样
    assert moved == base


# --- M3 ---------------------------------------------------------------------
@needs_tools
def test_each_recipe_constant_enters_the_fingerprint(tmp_path, liberty, monkeypatch):
    from flow.sta import run_sta as flow_sta
    from flow.synth import synth as flow_synth

    base = ff.flow_fingerprint(liberty, design=DESIGN)
    assert set(base) == set(FACTS) | {"fingerprint"}, "八项事实必须齐全"

    # (a) 综合脚本模板
    monkeypatch.setattr(flow_synth, "YOSYS_TEMPLATE",
                        flow_synth.YOSYS_TEMPLATE + "\n# 扰动\n")
    a = ff.flow_fingerprint(liberty, design=DESIGN)
    assert a["synth_recipe_sha256"] != base["synth_recipe_sha256"]
    assert a["fingerprint"] != base["fingerprint"]
    assert a["sta_recipe_sha256"] == base["sta_recipe_sha256"]
    monkeypatch.undo()

    # (b) abc 约束文件的内容（不是它的路径）
    constr = tmp_path / "abc.constr"
    constr.write_text(Path(flow_synth.ABC_CONSTR).read_text() + "set_load 0.7\n")
    monkeypatch.setattr(flow_synth, "ABC_CONSTR", constr)
    b = ff.flow_fingerprint(liberty, design=DESIGN)
    assert b["synth_recipe_sha256"] != base["synth_recipe_sha256"]
    assert b["fingerprint"] != base["fingerprint"]
    monkeypatch.undo()

    # (c) STA 脚本模板
    monkeypatch.setattr(flow_sta, "STA_TCL_TEMPLATE",
                        flow_sta.STA_TCL_TEMPLATE + "\n# 扰动\n")
    c = ff.flow_fingerprint(liberty, design=DESIGN)
    assert c["sta_recipe_sha256"] != base["sta_recipe_sha256"]
    assert c["fingerprint"] != base["fingerprint"]
    assert c["synth_recipe_sha256"] == base["synth_recipe_sha256"]
    monkeypatch.undo()

    # (d) 推导延时目标用的那组比例。fmax 是"在这组目标里能拿到的最好值"，
    #     换掉这组比例就换掉了这个量的定义 —— 两组不同比例带同一个指纹会把不可比
    #     的数据判成可比（本仓 内部#25 记的就是这个缺口）。进指纹的是比例而不是推出来
    #     的皮秒值：皮秒值是每个设计各自的，两个设计跑同一套流程必须同代。
    from flow.synth import search as flow_search

    monkeypatch.setattr(flow_search, "DELAY_TARGET_RATIOS", (1.0, 0.5))
    d = ff.flow_fingerprint(liberty, design=DESIGN)
    assert d["synth_recipe_sha256"] != base["synth_recipe_sha256"], \
        "ratios 换了而 synth_recipe_sha256 没变"
    assert d["fingerprint"] != base["fingerprint"]
    assert d["sta_recipe_sha256"] == base["sta_recipe_sha256"]
    monkeypatch.undo()

    assert ff.flow_fingerprint(liberty, design=DESIGN) == base, "撤销扰动后必须回到原值"


# --- M1（metrics_code_sha256）------------------------------------------------
# 只哈希交给工具的脚本是不够的：同一份工具输出，换一种解析方式就得到不同口径的
# 字段，而脚本一个字没变。内部#18 就是这么发生的 —— `_count_path_stages` 把所有
# path group 的 cell 行加在一起，`critical_path_stages` 虚高 2。那次是**碰巧**
# 顺带改了 tcl（加 `-sort_by_slack`）才切开了代；把 tcl 的改动撤回、只留 Python
# 侧的改动，`sta_recipe_sha256` 与修复前逐字相同（`d581f8c009b8`）。
PARSING_CHANGE = ("""\
    for line in Path(checks_rpt).read_text().splitlines():""", """\
    for line in reversed(Path(checks_rpt).read_text().splitlines()):""")


@pytest.fixture
def metric_module(tmp_path, monkeypatch):
    """把某个被覆盖模块复制到临时目录，让测试改它而不动仓库里的那一份。"""
    import flow.flow_fingerprint as ff

    src = ff.REPO_ROOT / "flow/sta/run_sta.py"
    copy = tmp_path / "run_sta.py"
    copy.write_text(src.read_text())
    patched = tuple(copy if m == "flow/sta/run_sta.py" else ff.REPO_ROOT / m
                    for m in ff.METRIC_MODULES)
    monkeypatch.setattr(ff, "METRIC_MODULES", ff.METRIC_MODULES)
    monkeypatch.setattr(ff, "_metric_module_paths", lambda: patched)
    return copy


@needs_tools
def test_changing_parsing_logic_changes_the_fingerprint(liberty, metric_module):
    base = ff.flow_fingerprint(liberty, design=DESIGN)
    old, new = PARSING_CHANGE
    text = metric_module.read_text()
    assert text.count(old) == 1, "夹具里那段解析代码不在了，换一段"
    metric_module.write_text(text.replace(old, new))

    changed = ff.flow_fingerprint(liberty, design=DESIGN)
    assert changed["metrics_code_sha256"] != base["metrics_code_sha256"]
    assert changed["fingerprint"] != base["fingerprint"]
    # 交给工具的脚本一个字没变 —— 这正是 内部#18 那个缺口的形状
    assert changed["sta_recipe_sha256"] == base["sta_recipe_sha256"]
    assert changed["synth_recipe_sha256"] == base["synth_recipe_sha256"]


@needs_tools
def test_comments_and_docstrings_do_not_change_the_fingerprint(liberty, metric_module):
    """文档修订不得产生流程代噪声 —— 否则人会开始无视代的边界。"""
    base = ff.flow_fingerprint(liberty, design=DESIGN)
    text = metric_module.read_text()
    metric_module.write_text(
        '"""换掉整个模块 docstring。"""\n'
        + text.split('"""', 2)[2].lstrip("\n")
        + "\n# 末尾加一行注释\n\n\n")

    assert ff.flow_fingerprint(liberty, design=DESIGN) == base, (
        "只改了 docstring、注释与空行，指纹不该变")


@needs_tools
def test_shrinking_the_module_list_changes_the_fingerprint(liberty, monkeypatch):
    base = ff.flow_fingerprint(liberty, design=DESIGN)
    monkeypatch.setattr(ff, "METRIC_MODULES", ff.METRIC_MODULES[:-1])
    shrunk = ff.flow_fingerprint(liberty, design=DESIGN)
    assert shrunk["metrics_code_sha256"] != base["metrics_code_sha256"], (
        "清单被缩小是一次静默的覆盖面收缩，必须分代")
    assert shrunk["fingerprint"] != base["fingerprint"]


# --- 驱动仿真的那一层 ---------------------------------------------------------
#
# 为什么值得有这个测试：`sim` 那项记的是**仿真器**版本，但仿真是 cocotb 驱动
# iverilog 的（`flow/sim/run_sim.py` 的 `cocotb_tools.runner.get_runner`）。
# cocotb 决定激励时序、Timer/Clock 的行为、波形转储的边沿 → VCD 不同
# → `sim.total_toggles` 不同 → `sta.dynamic_power_w` 不同，而仿真器可执行文件
# 一个字节没变。这与 内部#25（解析代码不分代）是同一类缺口，见本仓 内部#27 的缺口 3。

@needs_tools
def test_driver_runtime_enters_the_fingerprint(liberty, monkeypatch):
    """只换 cocotb 版本、不换仿真器，指纹必须变。"""
    base = ff.flow_fingerprint(liberty, design=DESIGN)

    monkeypatch.setattr(ff, "_driver_version",
                        lambda: "9.9.9-not-a-real-version")
    moved = ff.flow_fingerprint(liberty, design=DESIGN)

    assert moved["fingerprint"] != base["fingerprint"], (
        "换掉驱动仿真的那一层能改变 VCD、从而改变动态功耗，指纹却没动"
    )
    # 仿真器本身没变 —— 变的只有驱动层
    assert "9.9.9-not-a-real-version" in moved["sim"]
    assert "icarus" in moved["sim"]


@needs_tools
def test_simulator_and_driver_move_the_fingerprint_independently(liberty,
                                                                 monkeypatch):
    """两层各自单独变化都要改指纹 —— 不能只有一层真的进了摘要。"""
    base = ff.flow_fingerprint(liberty, design=DESIGN)
    real = ff._tool_version

    def only_sim(argv):
        if argv[0] == "iverilog":
            return "Icarus Verilog version 0.0 (fake)"
        return real(argv)

    monkeypatch.setattr(ff, "_tool_version", only_sim)
    sim_moved = ff.flow_fingerprint(liberty, design=DESIGN)
    monkeypatch.undo()
    monkeypatch.setattr(ff, "_driver_version", lambda: "0.0.0")
    driver_moved = ff.flow_fingerprint(liberty, design=DESIGN)

    assert sim_moved["fingerprint"] != base["fingerprint"]
    assert driver_moved["fingerprint"] != base["fingerprint"]
    # 两层不能互相顶替：各自扰动得到的也必须是两个不同的指纹
    assert sim_moved["fingerprint"] != driver_moved["fingerprint"]


@needs_tools
def test_flow_section_has_exactly_nine_facts(liberty):
    """七项之外只加了 SS/FF 两角的库（add-ss-ff-corner-sta），没有别的。

    驱动层（cocotb）那次是把 `sim` 一项取全，不算新增；角的库不同 —— 它们是综合库之外
    另两份决定测量结果的输入，并进 `liberty_sha256` 会改变一个既有字段的含义（红线 2），
    所以是第八项。第九项是门级仿真读的单元模型（gate-level-activity）。再加事实同样是
    schema 的改动，要走 Full。
    """
    facts = ff.flow_fingerprint(liberty, design=DESIGN)
    assert set(facts) == {"fingerprint", *FACTS}


# --- 角的库：第八项事实 --------------------------------------------------------
#
# 为什么值得有这一组：SS/FF 两份合并库不在仓库里、换一个字节不改任何 commit，
# 而 `sta.corners` 的每个数都来自它们。只哈希 TT 那份，就会把换过 SS 库的两批记录
# 判成同一代 —— 太粗的指纹失效是看不见的。

def _corner_libs(tmp_path, corners=("TT", "SS", "FF")):
    d = tmp_path / "merged"
    d.mkdir()
    for c in corners:
        (d / f"asap7sc7p5t_RVT_{c}.lib").write_text(f"library (fake_{c}) {{ }}\n")
    return d / "asap7sc7p5t_RVT_TT.lib"


@needs_tools
def test_a_corner_library_enters_as_its_own_fact(tmp_path):
    tt = _corner_libs(tmp_path)
    before = ff.flow_fingerprint(tt, design=DESIGN)
    assert set(before["corner_liberty_sha256"]) == {"SS", "FF"}

    (tt.parent / "asap7sc7p5t_RVT_SS.lib").write_text("library (fake_SS) { /* 换了 */ }\n")
    after = ff.flow_fingerprint(tt, design=DESIGN)
    assert after["fingerprint"] != before["fingerprint"]
    assert after["liberty_sha256"] == before["liberty_sha256"], (
        "换的是 SS 库，综合库那一项不该动 —— 它的含义只是综合用的那份")
    assert after["corner_liberty_sha256"]["SS"] != before["corner_liberty_sha256"]["SS"]
    assert after["corner_liberty_sha256"]["FF"] == before["corner_liberty_sha256"]["FF"]


@needs_tools
def test_a_liberty_that_is_not_a_tt_library_has_no_corners(liberty):
    """主库名推不出兄弟角（例如 `a.lib`）：那一项是空对象，不是报错。"""
    assert ff.flow_fingerprint(liberty, design=DESIGN)["corner_liberty_sha256"] == {}


def test_a_missing_sibling_corner_is_named_not_skipped(tmp_path):
    """名字对得上而文件不在 —— 配置错了，必须报出是哪一份，不能静默少测一角。"""
    tt = _corner_libs(tmp_path, corners=("TT", "FF"))
    with pytest.raises(FileNotFoundError, match="asap7sc7p5t_RVT_SS.lib"):
        ff.corner_liberties(tt)


# --- 驱动层的版本必须取自跑仿真的那个解释器，不是 PATH -------------------------
#
# 为什么值得有这个测试：2026-09-14 实测，本机有**两个** cocotb ——
# `~/tools/oss-cad-suite/bin/cocotb-config` 报 2.1.0.dev0+41564633，
# `.venv/bin/cocotb-config` 报 2.1.0。而 `~/tools/env.sh` 把 oss-cad-suite 排在前面，
# 于是「是否 source 过 env.sh」决定了指纹记哪一个 —— 而仿真自始至终用的是 venv
# 那个（run_sim.py 的 `from cocotb_tools.runner import get_runner` 由
# .venv/bin/python3 执行）。两代记录因此在同一台机器、同一个真正的驱动下
# 记了两个不同的版本串。
#
# 两个方向都坏：**假分代**（同一驱动换个 shell 就换一代）和**漏真分代**
# （换掉 venv 里的 cocotb，只要 oss-cad-suite 那个不动，指纹一个字不变）。
#
# `shutil.which` 那一套对 yosys / OpenSTA / iverilog 是对的 —— 它们就是被 PATH
# 解析后执行的那个二进制。对 cocotb 不对：它是被 **import** 的库，不是被执行的命令。

@needs_tools
def test_driver_version_does_not_depend_on_path(liberty, tmp_path, monkeypatch):
    """PATH 前面插一个报别的版本的 cocotb-config，指纹必须一动不动。"""
    baseline = ff.flow_fingerprint(liberty, design=DESIGN)

    shim = tmp_path / "bin"
    shim.mkdir()
    fake = shim / "cocotb-config"
    fake.write_text("#!/bin/sh\necho 9.9.9-from-PATH\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:{os.environ['PATH']}")

    with_path_shim = ff.flow_fingerprint(liberty, design=DESIGN)
    assert with_path_shim == baseline, (
        "驱动层的版本随 PATH 变了 —— 那记的就不是仿真实际 import 的那个 cocotb"
    )
    assert "9.9.9-from-PATH" not in with_path_shim["sim"]


@needs_tools
def test_driver_version_is_the_installed_package(liberty):
    """记的就是 venv 里装的那个包的版本。"""
    import importlib.metadata
    # 用 endswith 而不是 in：oss-cad-suite 那个报 2.1.0.dev0+41564633，
    # 而 "cocotb 2.1.0" 是它的**前缀**——子串判断会把错的那个也放过去。
    sim = ff.flow_fingerprint(liberty, design=DESIGN)["sim"]
    assert sim.endswith(f"+ cocotb {importlib.metadata.version('cocotb')}"), sim


# --- 单元模型：第九项事实（gate-level-activity，内部#65）--------------------------
#
# 功耗来自门级仿真的 VCD，门级仿真读的是 PDK 附带的单元 Verilog 模型。它们不在仓库里，
# 换一份不改任何 commit —— 与 liberty 同理，要按内容进指纹。

@needs_tools
def test_cell_models_enter_the_fingerprint_by_content(liberty, tmp_path, monkeypatch):
    models = [tmp_path / "asap7sc7p5t_AO_RVT_TT_1.v", tmp_path / "asap7sc7p5t_OA_RVT_TT_1.v"]
    for m in models:
        m.write_text(f"module {m.stem}; endmodule\n")
    monkeypatch.setattr(ff, "_cell_model_files", lambda: models)
    before = ff.flow_fingerprint(liberty, design=DESIGN)
    models[1].write_text("module changed; endmodule\n")
    after = ff.flow_fingerprint(liberty, design=DESIGN)
    assert after["cell_models_sha256"] != before["cell_models_sha256"]
    assert after["fingerprint"] != before["fingerprint"]
    assert after["liberty_sha256"] == before["liberty_sha256"]


def test_gate_sim_is_a_metric_module():
    assert "flow/sim/gate_sim.py" in ff.METRIC_MODULES


# --- fingerprint-per-design（内部#146）---------------------------------------------

def _two_design_repo(root, a_sta=None):
    """两个设计根，各一个顶层；a_sta 给出时写进 A 的 sta 段。"""
    import yaml
    for name, top, sta in (("a", "A", a_sta), ("b", "B", None)):
        cfg = {"sim": {"clock_signal": "clk"}, "params": {"W": {"values": [8]}}}
        if sta:
            cfg["sta"] = sta
        (root / "cbb" / name).mkdir(parents=True, exist_ok=True)
        (root / "cbb" / name / "params.yaml").write_text(yaml.safe_dump({"tops": {top: cfg}}))
    return root


def test_changing_one_designs_flow_config_moves_only_its_recipe(tmp_path):
    """内部#146：A 的时钟与保层级声明变了，只有 A 的设计配方变，B 的不变。"""
    root = _two_design_repo(tmp_path / "r1")
    a0, b0 = (ff.design_recipe_sha256(t, repo_root=root) for t in ("A", "B"))
    root2 = _two_design_repo(tmp_path / "r2", a_sta={
        "clocks": [{"name": "clk", "port": "clk", "period_ns": 5},
                   {"name": "cg", "port": "cg_clk", "period_ns": 5}],
        "clock_groups": [["clk", "cg"]]})
    a1, b1 = (ff.design_recipe_sha256(t, repo_root=root2) for t in ("A", "B"))
    assert a1 != a0
    assert b1 == b0


def test_paths_py_is_not_hashed_as_code():
    """内部#146 D2：paths.py 对测量的影响按解析后的值进指纹，不再按代码哈希。"""
    assert "flow/paths.py" not in ff.METRIC_MODULES


def test_computing_a_fingerprint_without_a_design_is_refused(liberty):
    """内部#146 D3：不给设计当场 TypeError，不退回不含设计配方的指纹。"""
    with pytest.raises(TypeError):
        ff.flow_fingerprint(liberty)


@needs_tools
def test_two_designs_differ_only_in_the_design_recipe(liberty):
    """内部#146：同一环境下两个设计的指纹不同，差别只在设计配方这一项。"""
    a = ff.flow_fingerprint(liberty, design="ADDER32")      # 带时钟与复位
    b = ff.flow_fingerprint(liberty, design="CBB_BIN2ONEHOT")   # 纯组合：clock_signal 为 null
    diff = {k for k in a if a[k] != b[k]}
    assert diff == {"design_recipe_sha256", "fingerprint"}, diff


def test_the_design_recipe_carries_static_ports():
    """内部#154（sta-static-ports D3）：正式 STA 读的 static_ports 进设计配方。"""
    assert ff.design_recipe("CBB_LZD")["static_ports"] == []

