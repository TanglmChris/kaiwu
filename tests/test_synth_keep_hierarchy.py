"""保住层级的模块表由设计声明、由流程施加 —— 以及为什么声明必须逐个命中。

为什么值得有这个文件：`(* keep_hierarchy *)` 是**综合指令**，2026-09-21 之前
写在 18 份 RTL 里（本仓 内部#46 的 2.2）。搬进流程之后，「哪些模块要保住层级」
从 RTL 里的一个属性变成 `params.yaml` 里的一行声明 —— 而声明会**打错**。

打错的代价是本仓最怕的那一类：yosys 对选择不到的模块**只打一句警告、退出码 0**
（实测 `Warning: Selection "X" did not match any module.`）。于是那一层静默地
不再被保住，综合照常完成、PPA 数字照常写进记录。`docs/pitfalls.md` 的 P-3 记着
没有 keep_hierarchy 时会发生什么：ABC 的 `&dch` 把 ripple / CLA / carry-select
三种手写结构收敛成同一个映射结果 —— **架构对比整条失效，而两边都不报错**。

所以本文件钉三件事：
  1. 声明了就真的施加（脚本里有 `setattr`，且在 `synth` 之前）；
  2. 声明里有一个名字没命中就**当场失败**，不是「声明的 ∩ 读进来的」；
  3. 没声明的顶层照常综合，流程不猜。
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

needs_yosys = pytest.mark.skipif(
    shutil.which("yosys") is None or not LIBERTY.is_file(),
    reason="需要 yosys 在 PATH 上与合并 liberty 在本机")

SRC = REPO_ROOT / "tests/fixtures/rtl/kh"
PARAMS = {"DAT_W": 8, "SCHEME": 0}

# 夹具是专门写的小设计（tests/fixtures/rtl/kh/：参数化、嵌套、按 SCHEME 选子模块），
# 早先用 ADDER32 的 RTL，2026-10-01 随设计根删除（trim-design-roots 的 D2）。这里测的是
# 「声明怎么被施加、施加错了会不会报出来」这套机制，不是保层级对某个设计的 PPA 影响（P-3）。
_YAML = """design_root: p
tops:
  KH_TOP:
    sim: {{clock_signal: null}}
    sta: {{ideal_drive_ports: []}}
{synth}    params:
      DAT_W: {{type: enum, role: scale, values: [8]}}
      SCHEME: {{type: enum, role: microarch, values: [0], labels: {{0: RIPPLE}}}}
"""


def _repo(tmp_path, name, keep=None):
    """搭一个临时仓库，`keep` 给定时在该顶层下声明保层级模块表。"""
    d = tmp_path / name
    (d / "designs/p/rtl").mkdir(parents=True)
    for f in SRC.glob("*.v"):
        shutil.copy(f, d / "designs/p/rtl")
    synth = ""
    if keep is not None:
        mods = "".join(f"        - {m}\n" for m in keep)
        synth = f"    synth:\n      keep_hierarchy:\n{mods}"
    (d / "designs/p/params.yaml").write_text(_YAML.format(synth=synth))
    return d


def _synth(repo, out, monkeypatch):
    import flow.paths as fp
    import flow.synth.synth as sy
    # 缓存也要跟着换到夹具仓库里：否则夹具冒名的顶层会覆盖真仓库
    # runs/.source_sets/ 里同名的那份，下一次真用到时白算一遍（ADDER32 约 25 s），
    # 在 pytest -n 下还会与读它的 worker 撞车。
    monkeypatch.setattr(sy, "SOURCE_SET_CACHE", Path(repo) / "runs" / ".source_sets")
    monkeypatch.setattr(sy, "resolve_design_root",
                        lambda x: fp.resolve_design_root(x, repo_root=repo))
    monkeypatch.setattr(sy, "validate_params",
                        lambda x, p: fp.validate_params(x, p, repo_root=repo))
    monkeypatch.setattr(sy, "keep_hierarchy_modules",
                        lambda x: fp.keep_hierarchy_modules(x, repo_root=repo))
    return sy.run_synth("KH_TOP", PARAMS, LIBERTY, out_dir=out)


def _script(out):
    return (Path(out) / "synth.ys").read_text()


@needs_yosys
def test_the_declared_modules_are_kept_by_the_flow_not_by_the_rtl(tmp_path, monkeypatch):
    """M1: 声明了就施加，且**排在 `hierarchy` 之后、`synth` 之前**。

    顺序不是风格问题，是对错问题（2026-09-21 实测）：`hierarchy` 把参数化模块
    换成 `$paramod…` 派生副本并删掉原来那个泛型模块，所以在它**之前**
    `setattr` 挂的属性会跟着一起没掉 —— 10 个模块里只有无参数的那个幸存。
    挂在 `synth` 之后则是 ABC 已经优化完了。两种错法都不报错、都照常出数。
    """
    out = tmp_path / "o1"
    _synth(_repo(tmp_path, "kept", ["KH_CORE", "KH_RIPPLE"]), out, monkeypatch)
    script = _script(out)
    assert "setattr -mod -set keep_hierarchy 1" in script, (
        f"声明了保层级模块，脚本里却没有 setattr：\n{script}")
    # 含式模式：派生副本叫 `$paramod$<hash>\<名字>` 或 `$paramod\<名字>\WIDTH=…`
    assert "*KH_CORE*" in script and "*KH_RIPPLE*" in script, (
        f"施加用的不是含式模式，派生副本会漏掉：\n{script}")
    i_h = script.index("hierarchy -check -top")
    i_s = script.index("setattr -mod -set keep_hierarchy")
    i_y = script.index("\nsynth")
    assert i_h < i_s < i_y, (
        f"顺序不对（hierarchy {i_h} / setattr {i_s} / synth {i_y}）：\n{script}")
    assert "select -clear" in script, (
        "施加完没有清选择集 —— 后面的 dfflibmap/abc 会只对最后选中的东西生效")


@needs_yosys
def test_the_attribute_really_lands_on_the_parameterized_copies(tmp_path, monkeypatch):
    """M1: 属性必须落在**派生副本**上，不是落在被 hierarchy 删掉的泛型模块上。

    这一条是上一条的实质面：脚本里有 `setattr` 不等于属性真的挂上了。
    2026-09-21 就踩过 —— `setattr` 排在 `hierarchy` 之前时脚本看起来完全正常，
    而 `ADDER32` 那 10 个模块里只有无参数的 `PREFIX_NODE` 带上了属性，
    另外 9 个在派生时全丢了。差别只有加 `-flatten` 才看得出来
    （647 vs 650 cells），而产线不加 `-flatten`，所以它不会以任何方式暴露。
    """
    import re
    import subprocess

    out = tmp_path / "o5"
    _synth(_repo(tmp_path, "landed", ["KH_CORE", "KH_RIPPLE", "KH_FULL"]),
           out, monkeypatch)
    script = _script(out)
    # 截到 setattr 那一行为止，换成「列出带这个属性的模块」
    head = script[:script.index("select -clear")]
    probe = tmp_path / "probe.ys"
    probe.write_text(head + "select -list =A:keep_hierarchy\n")
    r = subprocess.run([shutil.which("yosys"), "-s", str(probe)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    marked = {m for m in re.findall(r"\$paramod[^\s/]*\\([A-Z0-9_]+)", r.stdout)}
    marked |= {ln.strip() for ln in r.stdout.splitlines()
               if re.fullmatch(r"[A-Z][A-Z0-9_]*", ln.strip())}
    assert "KH_CORE" in marked, (
        f"参数化模块 KH_CORE 没带上属性 —— 派生副本漏标了。带上的是 {sorted(marked)}")


@needs_yosys
def test_a_declared_module_that_is_not_in_the_design_fails_the_run(tmp_path, monkeypatch):
    """M3: 声明里有一个名字没命中，综合必须**当场失败**并指名是哪一个。

    判据不能是「yosys 报了警告」：它只警告、退出 0。判据是流程自己拿存活模块
    集合比对之后抛错。不这么做的话，一个拼错的模块名会让那一层静默地不再被
    保住 —— 而 P-3 记着那意味着架构对比整条失效。
    """
    with pytest.raises(Exception) as e:
        _synth(_repo(tmp_path, "typo", ["KH_CORE", "KH_RIPPLLE"]),
               tmp_path / "o2", monkeypatch)
    msg = str(e.value)
    assert "KH_RIPPLLE" in msg, f"报错没指名是哪个模块没命中：{msg}"
    assert "KH_CORE" not in msg or "KH_RIPPLLE" in msg


@needs_yosys
def test_a_declared_module_outside_this_tops_closure_also_fails(tmp_path, monkeypatch):
    """M3: 名字拼对了但不在**这个顶层的依赖闭包**里，同样失败。

    这一条是「按顶层声明而不是按设计根声明」那个决定的判据（design.md 的 D1）。
    按根声明时这种情形是常态（同根的两个顶层闭包不相交），流程就只能接受
    「声明的 ∩ 读进来的」—— 而那恰好让上一条用例里的拼写错误也被放行。
    """
    with pytest.raises(Exception) as e:
        # KH_CLA 在 rtl/ 里，但 SCHEME=0（RIPPLE）这一组的闭包里没有它
        _synth(_repo(tmp_path, "outside", ["KH_CORE", "KH_CLA"]),
               tmp_path / "o3", monkeypatch)
    assert "KH_CLA" in str(e.value), str(e.value)


@needs_yosys
def test_a_top_without_the_declaration_synthesizes_with_no_setattr(tmp_path, monkeypatch):
    """M4: 没声明的顶层照常综合，脚本里不出现 setattr。

    流程 MUST NOT 猜哪些模块像 building block（`flow-parameterization`：
    流程代码不内嵌任何具体设计的名字）。
    """
    out = tmp_path / "o4"
    r = _synth(_repo(tmp_path, "bare", None), out, monkeypatch)
    assert "keep_hierarchy" not in _script(out), _script(out)
    assert r["cell_count"] > 0


def test_the_declaration_is_read_per_top_not_per_design_root(tmp_path):
    """声明挂在顶层之下，读法与 `sim:` / `sta:` 同形（design.md 的 D1）。

    早先用一个已删设计根的两个顶层（2026-10-01 删除），这里用夹具。
    """
    from flow.paths import keep_hierarchy_modules

    root = tmp_path / "designs" / "two"
    (root / "rtl").mkdir(parents=True)
    (root / "params.yaml").write_text("""design_root: two
tops:
  TOP_A:
    sim: {clock_signal: null}
    synth: {keep_hierarchy: [SUB_A]}
    params: {}
  TOP_B:
    sim: {clock_signal: null}
    synth: {keep_hierarchy: [SUB_B]}
    params: {}
  TOP_C:
    sim: {clock_signal: null}
    params: {}
""")
    for m in ("TOP_A", "TOP_B", "TOP_C"):
        (root / "rtl" / f"{m.lower()}.v").write_text(f"module {m}; endmodule\n")
    # 同一个根下的两个顶层各有各的表，互不相干；没声明的顶层表为空
    assert keep_hierarchy_modules("TOP_A", repo_root=tmp_path) == ["SUB_A"]
    assert keep_hierarchy_modules("TOP_B", repo_root=tmp_path) == ["SUB_B"]
    assert keep_hierarchy_modules("TOP_C", repo_root=tmp_path) == []
