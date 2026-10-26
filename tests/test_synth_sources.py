"""综合读入哪些源文件 —— 以及为什么这件事必须是确定的。

为什么值得有这个测试：`flow/synth/synth.py` 原来 glob 整个 `rtl/` 目录，
全读进来再靠 `synth -top` 里的 `hierarchy` 把没用到的模块删掉。删是删干净了 ——
yosys 日志明确写着 `Removing unused module`，产出的网表里只有一个模块，
端口表逐字相同 —— 但**删得掉不等于没影响**。

实测（2026-09-20，本仓 内部#50）：一个不例化任何子模块的组合设计，
它的单元数随 `rtl/` 里有几份文件在 **13 / 33 / 36 / 15** 之间变化，最大 2.5 倍。
固定读入集合连跑三次逐字节相同，所以这是**确定性的偏差，不是运行间随机**。
确定性比随机更坏：随机会被察觉，确定性的偏差会被当成真实差异记进
`results/experiments.jsonl`，而记录里没有任何字段能看出读入集合变过。

本文件钉两件事：
  1. 读入集合是该顶层的**依赖闭包**，于是同一个顶层放在文件数不同的目录里
     综合出来的结果**相同**；
  2. 读入集合进记录（`synth.sources_sha256`），成为一条可见的自变量。
"""
import hashlib
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

# 夹具改用仓里保留的 cbb 构件（trim-design-roots 的 D2；早先用一个已删的组合设计）：
# CBB_LZD 全文一处例化都没有，依赖闭包就是它自己；另外三个开源 RTL 文件当「从不被例化的模块」（内部#305）。
SRC = REPO_ROOT / "cbb"
TOP_FILE = SRC / "cbb_lzd/rtl/cbb_lzd.v"
NOISE = [SRC / "cbb_bin2onehot/rtl/cbb_bin2onehot.v",
         SRC / "cbb_onehot2bin/rtl/cbb_onehot2bin.v",
         REPO_ROOT / "designs/adder32/rtl/full_adder.v"]
PARAMS = {"DAT_W": 16, "MSB_EN": 0, "SCHEME": 0}
YAML = """design_root: p
tops:
  CBB_LZD:
    sim: {clock_signal: null}
    sta: {ideal_drive_ports: []}
    params:
      DAT_W: {type: enum, values: [16]}
      MSB_EN: {type: enum, values: [0]}
      SCHEME: {type: enum, values: [0], labels: {0: CLA}}
"""


def _repo(tmp_path, name, noise):
    """搭一个临时仓库：顶层 + `noise` 里那些**从不被例化**的模块。"""
    d = tmp_path / name
    (d / "designs/p/rtl").mkdir(parents=True)
    shutil.copy(TOP_FILE, d / "designs/p/rtl")
    for f in noise:
        shutil.copy(f, d / "designs/p/rtl")
    (d / "designs/p/params.yaml").write_text(YAML)
    return d


def _synth(repo, tmp_out, monkeypatch):
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
    return sy.run_synth("CBB_LZD", PARAMS, LIBERTY, out_dir=tmp_out)


@needs_yosys
def test_unrelated_files_in_the_rtl_dir_do_not_change_the_result(tmp_path, monkeypatch):
    """同一个顶层，两个文件数不同的目录，综合结果必须相同。

    这是 内部#50 的核心判据（2026-09-20 实测那个组合设计的单元数随目录里的文件数
    在 13 / 33 / 36 / 15 之间变）。CBB_LZD 的依赖闭包只有它自己，所以「只有它」与
    「它 + 3 个从不被例化的模块」必须给出同一个电路。
    """
    lean = _synth(_repo(tmp_path, "lean", []), tmp_path / "o1", monkeypatch)
    fat = _synth(_repo(tmp_path, "fat", NOISE), tmp_path / "o2", monkeypatch)
    assert lean["cell_count"] == fat["cell_count"], (
        f"{lean['cell_count']} != {fat['cell_count']} —— 同一个顶层，"
        f"只因为 rtl/ 里多了 3 个从不被例化的模块，综合结果就不同（本仓 #50）")
    assert lean["area_um2"] == fat["area_um2"]


@needs_yosys
def test_the_source_set_is_the_dependency_closure_not_the_directory(tmp_path, monkeypatch):
    """读入集合必须是依赖闭包 —— 判据是 `synth.sources_sha256` 两边相同。

    只比 cell_count 不够：两个不同的读入集合**碰巧**给出同样的单元数是可能的
    （13/33/36/15 那串数字里 13 就出现过两次）。摘要相同才证明读的真是同一组文件。
    """
    lean = _synth(_repo(tmp_path, "lean2", []), tmp_path / "o3", monkeypatch)
    fat = _synth(_repo(tmp_path, "fat2", NOISE), tmp_path / "o4", monkeypatch)
    assert lean["sources_sha256"] == fat["sources_sha256"], (
        "两边读入的源文件集合不同 —— 闭包没算对")


@needs_yosys
def test_the_closure_excludes_a_module_that_is_never_instantiated(tmp_path, monkeypatch):
    """闭包只含顶层与它例化的模块，不含目录里从不被例化的文件。

    内部#50 的那个真实实例（一个已删设计根里躺着一个没人例化的 RTL 文件）
    随设计根于 2026-10-01 删除，这里用夹具复现同一个形状。
    """
    import flow.paths as fp
    import flow.synth.synth as sy

    d = tmp_path / "r"
    (d / "designs/q/rtl").mkdir(parents=True)
    (d / "designs/q/rtl/top_q.v").write_text(
        "module TOP_Q (input wire i_a, output wire o_y);\n"
        "    SUB_Q U_TOP_Q_SUB_Q (.i_a(i_a), .o_y(o_y));\nendmodule\n")
    (d / "designs/q/rtl/sub_q.v").write_text(
        "module SUB_Q (input wire i_a, output wire o_y);\n    assign o_y = ~i_a;\nendmodule\n")
    (d / "designs/q/rtl/orphan_q.v").write_text(
        "module ORPHAN_Q (input wire i_a, output wire o_y);\n    assign o_y = i_a;\nendmodule\n")
    (d / "designs/q/params.yaml").write_text(
        "design_root: q\ntops:\n  TOP_Q:\n    sim: {clock_signal: null}\n    params: {}\n")
    monkeypatch.setattr(sy, "SOURCE_SET_CACHE", d / "runs" / ".source_sets")
    monkeypatch.setattr(sy, "resolve_design_root",
                        lambda x: fp.resolve_design_root(x, repo_root=d))
    got = {p.name for p in sy.source_files("TOP_Q")}
    assert got == {"top_q.v", "sub_q.v"}, f"闭包解出来是 {sorted(got)}"


def test_the_digest_does_not_depend_on_the_order_the_files_are_given():
    """摘要与给出顺序无关 —— 否则它会把「换了个排序」报成「换了一组文件」。"""
    from flow.synth.synth import sources_digest

    a = [TOP_FILE, NOISE[0]]
    assert sources_digest(a) == sources_digest(list(reversed(a)))


def test_the_digest_covers_content_not_just_names(tmp_path):
    """内容变了摘要必须变 —— 只哈希文件名的话，改 RTL 就看不出来了。"""
    from flow.synth.synth import sources_digest

    f = tmp_path / "m.v"
    f.write_text("module m(); endmodule\n")
    before = sources_digest([f])
    f.write_text("module m(); wire w; endmodule\n")
    assert sources_digest([f]) != before


# --- 读入集合跨进 cbb/ 依赖（add-design-cbb-deps）----------------------------------
#
# 被测顶层在 params.yaml 声明 `deps:` 之后，候选文件 = 本根 + 依赖根的 rtl/*.v，
# 读入集合仍按「全部声明取值下的存活闭包」取。这里钉住三件只有 yosys 求过闭包
# 才能判断的事：依赖根里没被例化的文件不进来；声明了没用上 / 用了没声明都报错；
# 缓存随依赖文件的内容失效。

needs_yosys_only = pytest.mark.skipif(shutil.which("yosys") is None,
                                      reason="需要 yosys 在 PATH 上")

_IP_YAML = """design_root: ip
tops:
  IP:
    sim: {{clock_signal: null}}
    params:
      W: {{type: enum, values: [4]}}
{deps}"""
_CBB_YAML = """design_root: {root}
tops:
  {top}:
    sim: {{clock_signal: null}}
    params:
      W: {{type: enum, values: [4]}}
"""
_IP_RTL = """module IP #(parameter W = 4) (input wire [W-1:0] a, output wire [W-1:0] y);
  CBB_A #(.W(W)) U_IP_CBB_A (.a(a), .y(y));
endmodule
"""
_CBB_A_RTL = """module CBB_A #(parameter W = 4) (input wire [W-1:0] a, output wire [W-1:0] y);
  assign y = ~a;
endmodule
"""
# 例化 CBB_A_HELPER 的版本：用来验证缓存随依赖文件内容失效
_CBB_A_RTL_WITH_HELPER = """module CBB_A #(parameter W = 4) (input wire [W-1:0] a, output wire [W-1:0] y);
  CBB_A_HELPER #(.W(W)) U_CBB_A_HELPER (.a(a), .y(y));
endmodule
"""
_CBB_A_HELPER_RTL = """module CBB_A_HELPER #(parameter W = 4) (input wire [W-1:0] a, output wire [W-1:0] y);
  assign y = a;
endmodule
"""


def _dep_repo(tmp_path, deps=("CBB_A",)):
    """designs/ip（IP 例化 CBB_A）+ cbb/cbb_a（CBB_A + 未被例化的 CBB_A_HELPER）+ cbb/cbb_b。"""
    ip = tmp_path / "designs/ip"
    (ip / "rtl").mkdir(parents=True)
    (ip / "rtl/ip.v").write_text(_IP_RTL)
    (ip / "params.yaml").write_text(_IP_YAML.format(
        deps=f"    deps: [{', '.join(deps)}]\n" if deps else ""))
    a = tmp_path / "cbb/cbb_a"
    (a / "rtl").mkdir(parents=True)
    (a / "rtl/cbb_a.v").write_text(_CBB_A_RTL)
    (a / "rtl/cbb_a_helper.v").write_text(_CBB_A_HELPER_RTL)
    (a / "params.yaml").write_text(_CBB_YAML.format(root="cbb_a", top="CBB_A"))
    b = tmp_path / "cbb/cbb_b"
    (b / "rtl").mkdir(parents=True)
    (b / "rtl/cbb_b.v").write_text(
        "module CBB_B (input wire a, output wire y); assign y = a; endmodule\n")
    (b / "params.yaml").write_text(_CBB_YAML.format(root="cbb_b", top="CBB_B"))
    return tmp_path


def _sources(repo, monkeypatch):
    import flow.paths as fp
    import flow.synth.synth as sy
    monkeypatch.setattr(sy, "SOURCE_SET_CACHE", Path(repo) / "runs" / ".source_sets")
    monkeypatch.setattr(sy, "resolve_design_root",
                        lambda x: fp.resolve_design_root(x, repo_root=repo))
    return sy.source_files("IP")


@needs_yosys_only
def test_deps_bring_in_the_instantiated_cbb_files_only(tmp_path, monkeypatch):
    repo = _dep_repo(tmp_path)
    got = [p.relative_to(repo).as_posix() for p in _sources(repo, monkeypatch)]
    assert got == ["cbb/cbb_a/rtl/cbb_a.v", "designs/ip/rtl/ip.v"], got


@needs_yosys_only
def test_deps_declared_but_never_instantiated_is_an_error(tmp_path, monkeypatch):
    repo = _dep_repo(tmp_path, deps=("CBB_A", "CBB_B"))
    with pytest.raises(RuntimeError, match="CBB_B"):
        _sources(repo, monkeypatch)


@needs_yosys_only
def test_deps_missing_for_an_instantiated_cbb_is_an_error_that_names_deps(
        tmp_path, monkeypatch):
    repo = _dep_repo(tmp_path, deps=())
    with pytest.raises(RuntimeError, match="deps"):
        _sources(repo, monkeypatch)


@needs_yosys_only
def test_deps_content_change_invalidates_the_cached_source_set(tmp_path, monkeypatch):
    """改依赖文件的内容，缓存必须失效 —— 否则读入集合停在旧的闭包上。"""
    from flow.synth.synth import sources_digest

    repo = _dep_repo(tmp_path)
    before = _sources(repo, monkeypatch)
    (repo / "cbb/cbb_a/rtl/cbb_a.v").write_text(_CBB_A_RTL_WITH_HELPER)
    after = _sources(repo, monkeypatch)
    assert "cbb_a_helper.v" in {p.name for p in after}, (
        "CBB_A 改成例化 CBB_A_HELPER 之后读入集合没变 —— 缓存没随依赖文件失效")
    assert sources_digest(after) != sources_digest(before)


@needs_yosys_only
def test_deps_cache_that_is_not_json_is_a_miss(tmp_path, monkeypatch):
    """内部#57：并发读者可能读到写了一半的缓存。坏缓存当未命中，不抛错。"""
    repo = _dep_repo(tmp_path)
    want = _sources(repo, monkeypatch)
    (repo / "runs/.source_sets/IP.json").write_text("")
    assert _sources(repo, monkeypatch) == want
