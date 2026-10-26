"""网表 vs RTL 等价：能证过真网表，也必须证不过坏网表。

`flow/equiv/netlist_equiv.py` 的失效方式和别的等价层一样 —— 「削弱了的证明与完整的
证明在输出上完全一样」。所以每条正例都配一条反例：同一份网表改掉一个单元、或拿
错一级流水的 RTL 去比，必须 FAILED。

网表由用例自己现综合（`runs/` 是 gitignored 的，不能当夹具）。两个设计各挑最小的一档：
- CBB_LZD DAT_W=16：纯组合、没有子模块 → 走整体证明；
- 夹具 KP_TOP（`tests/fixtures/rtl/kp/`）DAT_W=8 PIPE_STAGES=2：带触发器、保层级的子模块
  → 走分层证明。早先这两档是一个已删的组合设计与 ADDER32，2026-10-01 随设计根删除
  （trim-design-roots 的 D1 / D2）；CBB 不例化子模块，提供不了分层的形状，所以用夹具。
"""
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

pytestmark = [
    pytest.mark.flow,
    pytest.mark.skipif(
        not all(shutil.which(t) for t in ("yosys", "yosys-abc")) or not LIBERTY.is_file(),
        reason="yosys / yosys-abc / 合并 liberty 不齐"),
]

FROM_DATA = ("CBB_LZD", {"DAT_W": 16, "MSB_EN": 0, "SCHEME": 0})
ADDER = ("KP_TOP", {"DAT_W": 8, "PIPE_STAGES": 2})

KP_SRC = REPO_ROOT / "tests/fixtures/rtl/kp"
KP_YAML = """design_root: kp
tops:
  KP_TOP:
    sim: {clock_signal: clk}
    sta: {ideal_drive_ports: [rst_n]}
    synth: {keep_hierarchy: [KP_ADD, KP_FULL]}
    params:
      DAT_W: {type: enum, role: scale, values: [8]}
      PIPE_STAGES: {type: enum, role: microarch, values: [1, 2]}
"""


@pytest.fixture(autouse=True)
def _kp_repo(tmp_path_factory, monkeypatch):
    """夹具设计 KP_TOP 放进一个临时仓库，流程按顶层名找它时去那里找（真实设计照旧）。"""
    import flow.equiv.netlist_equiv as ne
    import flow.paths as fp
    import flow.synth.synth as sy

    repo = tmp_path_factory.mktemp("kp_repo")
    (repo / "designs/kp/rtl").mkdir(parents=True)
    for f in KP_SRC.glob("*.v"):
        shutil.copy(f, repo / "designs/kp/rtl")
    (repo / "designs/kp/params.yaml").write_text(KP_YAML)

    def pick(fn):
        """KP_TOP 去临时仓库找，其余顶层照旧。fn 先取原函数，免得替换之后自己调自己。"""
        def wrapped(d, *a, **k):
            if d != "KP_TOP":
                return fn(d, *a, **k)
            k.pop("repo_root", None)
            # 第二个位置参数是 repo_root 的那几个函数（include_dirs 之类）按名字传
            if fn.__name__ in ("include_dirs", "include_files", "resolve_design_root",
                               "keep_hierarchy_modules", "clock_port"):
                return fn(d, repo_root=repo)
            return fn(d, *a, repo_root=repo, **k)
        return wrapped

    monkeypatch.setattr(sy, "SOURCE_SET_CACHE", repo / "runs" / ".source_sets")
    for mod, name in ((sy, "resolve_design_root"), (sy, "validate_params"),
                      (sy, "keep_hierarchy_modules"), (sy, "include_dirs"),
                      (sy, "include_files"), (ne, "clock_port"), (ne, "clocks"),
                      (ne, "load_design_config"), (fp, "include_dirs")):
        monkeypatch.setattr(mod, name, pick(getattr(fp, name)))


def _synth(tmp_path, design, params):
    from flow.synth.synth import run_synth
    return Path(run_synth(design, params, str(LIBERTY), out_dir=tmp_path)["netlist_path"])


def _prove(design, params, netlist):
    from flow.equiv.netlist_equiv import prove_netlist
    status, _, log = prove_netlist(design, params, netlist, str(LIBERTY))
    return status, log


def _mutate(netlist, tmp_path):
    """把网表里第一个二输入 XOR/XNOR/AND 换成另一种 —— 函数一定变，端口不变。"""
    text = netlist.read_text()
    swaps = {"XOR2xp5_ASAP7_75t_R": "XNOR2xp5_ASAP7_75t_R",
             "XNOR2xp5_ASAP7_75t_R": "XOR2xp5_ASAP7_75t_R",
             "AND2x2_ASAP7_75t_R": "OR2x2_ASAP7_75t_R",
             "OR2x2_ASAP7_75t_R": "AND2x2_ASAP7_75t_R",
             "NAND2xp5_ASAP7_75t_R": "NOR2xp33_ASAP7_75t_R",
             "NOR2xp33_ASAP7_75t_R": "NAND2xp5_ASAP7_75t_R"}
    m = re.search("|".join(swaps), text)
    assert m, "网表里没有可替换的单元 —— 反例构造不出来，这条用例就证明不了什么"
    bad = tmp_path / "bad_netlist.v"
    bad.write_text(text[:m.start()] + swaps[m.group(0)] + text[m.end():])
    return bad


def test_a_combinational_netlist_is_proved_and_a_mutated_one_is_not(tmp_path):
    design, params = FROM_DATA
    nl = _synth(tmp_path, design, params)
    status, log = _prove(design, params, nl)
    assert status == "PROVED", log
    assert "[整体]" in log, "纯组合、无子模块的网表应当走整体证明\n" + log

    status, log = _prove(design, params, _mutate(nl, tmp_path))
    assert status == "FAILED", "改掉一个单元的网表居然证过了 —— 这层证明是假的\n" + log


def test_a_pipelined_netlist_is_proved_compositionally(tmp_path):
    design, params = ADDER
    nl = _synth(tmp_path, design, params)
    status, log = _prove(design, params, nl)
    assert status == "PROVED", log
    assert "[顶层（子模块剪开）]" in log and "[子模块 " in log, (
        "带保层级子模块的网表应当走分层证明\n" + log)


def test_a_pipelined_netlist_fails_against_the_wrong_latency(tmp_path):
    """拿 PIPE_STAGES=1 的 RTL 去比 2 级的网表：差一拍，必须证不过。

    这条守的是时序那一半 —— 初态、复位、剪开之后的顶层寄存器。只有组合反例的话，
    「顶层寄存器被剪掉了、根本没比」这种失效照样全绿。
    """
    design, params = ADDER
    nl = _synth(tmp_path, design, params)
    status, log = _prove(design, dict(params, PIPE_STAGES=1), nl)
    assert status == "FAILED", "延迟差一拍的 RTL 居然与网表等价\n" + log


def test_a_mutated_submodule_is_caught(tmp_path):
    """分层证明里改坏的单元落在子模块里 —— 子模块那一步必须抓到它。"""
    design, params = ADDER
    nl = _synth(tmp_path, design, params)
    status, log = _prove(design, params, _mutate(nl, tmp_path))
    assert status == "FAILED", log


def _sat_gives_up(tmp_path):
    """一个假 ABC：组合 miter 上的纯 `dprove` 一律答「没结论」，其余原样转给真 ABC。

    某个闭源设计最大一档那种 SAT 真证不出来的 miter 要综合十几分钟，不能当夹具；用这个把
    「SAT 没结论」这一支稳定地逼出来，BDD 后备才有东西可测。
    """
    fake = tmp_path / "abc_sat_gives_up"
    fake.write_text(f"""#!{sys.executable}
import re, subprocess, sys
cmd = sys.argv[2]
aig = re.search(r"read_aiger (\\S+);", cmd).group(1)
latches = int(open(aig, "rb").readline().split()[3])
if "collapse" not in cmd and latches == 0:
    print("Networks are UNDECIDED.")
    sys.exit(0)
sys.exit(subprocess.run([{shutil.which("yosys-abc")!r}] + sys.argv[1:]).returncode)
""")
    fake.chmod(0o755)
    return str(fake)


def test_bdd_takes_over_when_sat_has_no_verdict_and_still_catches_a_mutant(tmp_path):
    """SAT 没结论时退到 BDD：好网表要证过，改坏一个单元的网表照样要证不过。

    只测正例的话，「后备把什么都判成等价」与「后备真的证了」输出一模一样。
    """
    from flow.equiv.netlist_equiv import prove_netlist
    design, params = ADDER
    nl = _synth(tmp_path, design, params)
    abc = _sat_gives_up(tmp_path)

    status, _, log = prove_netlist(design, params, nl, str(LIBERTY), abc=abc)
    assert status == "PROVED", log
    assert "BDD 后备" in log, "SAT 被逼成没结论，却没有走 BDD 后备\n" + log

    status, _, log = prove_netlist(design, params, _mutate(nl, tmp_path), str(LIBERTY), abc=abc)
    assert status == "FAILED", "BDD 后备把改坏的网表证过了\n" + log
    assert "BDD 后备" in log, log


# --- 内部#186 复位端口按 params.yaml、多时钟 --------------------------------------------------

def test_reset_comes_from_params_and_both_clocks_are_driven(tmp_path, fixture_designs):
    """EQV_TOP：复位叫 sys_rst_n（sim.reset_signal），两个时钟。不带 --reset 也要证得过 —— 以前写死
    rst_n，直接报「找不到复位端口」；两个时钟都要在拉复位那一拍里打，否则 clk_b 域的初态没定。"""
    nl = _synth(tmp_path / "s", "EQV_TOP", {"DAT_W": 8})
    status, log = _prove("EQV_TOP", {"DAT_W": 8}, nl)
    assert status == "PROVED", log
    status, _ = _prove("EQV_TOP", {"DAT_W": 8}, _mutate(nl, tmp_path))
    assert status == "FAILED"


def test_a_missing_reset_declaration_is_a_config_error_not_a_failed_proof(tmp_path, fixture_designs, monkeypatch):
    """复位端口对不上时报 CONFIG（缺配置），不报 FAILED —— 后者看上去像网表不等价。"""
    import flow.equiv.netlist_equiv as ne
    nl = _synth(tmp_path / "s", "EQV_TOP", {"DAT_W": 8})
    status, _, log = ne.prove_netlist("EQV_TOP", {"DAT_W": 8}, nl, str(LIBERTY), reset="rst_n")
    assert status == "CONFIG" and "rst_n" in log and "sim.reset_signal" in log


def test_an_inferred_memory_in_the_rtl_is_mapped_on_the_gold_side(tmp_path, fixture_designs):
    """RTL 里的寄存器数组 yosys 推断成 $mem；gold 侧不跑 memory 就留到 write_aiger 报错（内部#188，
    一个行为模型 SRAM 实撞）。综合那边 synth 会映射成触发器，gold 侧要做同样的事。"""
    nl = _synth(tmp_path / "s", "MEM_TOP", {"DAT_W": 8})
    status, log = _prove("MEM_TOP", {"DAT_W": 8}, nl)
    assert status == "PROVED", log[-2000:]


def test_a_mutated_netlist_with_unreset_storage_is_still_caught(tmp_path, fixture_designs):
    """内部#188：不复位的存储在 gold 侧按 x 处理、x 位不比。这条防的是「不比」变成「全都不比」：
    网表里改一个门，复位之后可观察到的位仍要对不上。"""
    nl = _synth(tmp_path / "s", "MEM_TOP", {"DAT_W": 8})
    status, log = _prove("MEM_TOP", {"DAT_W": 8}, _mutate(nl, tmp_path))
    assert status == "FAILED", log[-2000:]


def test_latest_generation_is_taken_per_design(tmp_path):
    """指纹按设计算（内部#146）：--design A 要取 A 自己的最新一代，不是全仓最新一代（那一代里可能没有 A）。"""
    import json as _json
    import flow.equiv.netlist_equiv as ne
    rows = [{"experiment_id": f"{d}-{i}", "design": d, "params": {"W": i},
             "flow": {"fingerprint": fp}}
            for d, fp, i in [("A", "sha256:aaa1", 1), ("A", "sha256:aaa2", 1), ("B", "sha256:bbb1", 1)]]
    log = tmp_path / "e.jsonl"
    log.write_text("".join(_json.dumps(r) + "\n" for r in rows))
    got, _ = ne.select_records(design="A", records=log)
    assert [r["experiment_id"] for r in got] == ["A-1"] and got[0]["flow"]["fingerprint"] == "sha256:aaa2"
    got, _ = ne.select_records(design="B", records=log)
    assert [r["flow"]["fingerprint"] for r in got] == ["sha256:bbb1"]


def _dprove_gives_up(tmp_path):
    """一个假 ABC：时序 miter 上的 `dprove` 一律答「没结论」，其余（pdr）原样转给真 ABC。"""
    fake = tmp_path / "abc_dprove_gives_up"
    fake.write_text(f"""#!{sys.executable}
import re, subprocess, sys
cmd = sys.argv[2]
aig = re.search(r"read_aiger (\\S+);", cmd).group(1)
latches = int(open(aig, "rb").readline().split()[3])
if "dprove" in cmd and latches > 0:
    print("Networks are UNDECIDED.")
    sys.exit(0)
sys.exit(subprocess.run([{shutil.which("yosys-abc")!r}] + sys.argv[1:]).returncode)
""")
    fake.chmod(0o755)
    return str(fake)


def test_pdr_takes_over_when_dprove_has_no_verdict_and_still_catches_a_mutant(tmp_path, fixture_designs):
    """内部#188：时序 miter 上 dprove 没结论时退到 PDR。好网表要证过，改坏一个单元的网表照样证不过。"""
    import flow.equiv.netlist_equiv as ne
    nl = _synth(tmp_path / "s", "MEM_TOP", {"DAT_W": 8})
    abc = _dprove_gives_up(tmp_path)
    status, _, log = ne.prove_netlist("MEM_TOP", {"DAT_W": 8}, nl, str(LIBERTY), abc=abc)
    assert status == "PROVED", log[-2000:]
    assert "PDR 后备" in log, log[-2000:]
    status, _, log = ne.prove_netlist("MEM_TOP", {"DAT_W": 8}, _mutate(nl, tmp_path), str(LIBERTY), abc=abc)
    assert status == "FAILED" and "PDR 后备" in log, log[-2000:]


# --- 内部#333：全部按 equiv: false 声明跳过，与「一条都没选中」分开 ----------------------

def test_all_records_skipped_by_declaration_is_its_own_verdict(fixture_designs, monkeypatch, capsys):
    """夹具设计 noequiv_root 的 NOEQ_TOP 声明了 equiv: false（原来用的是闭源设计，内部#365）。"""
    from flow.equiv import netlist_equiv as ne
    monkeypatch.setattr(ne, "select_records",
                        lambda *a, **k: ([{"design": "NOEQ_TOP", "experiment_id": "x"}], "测试"))
    assert ne.main(["--design", "NOEQ_TOP"]) == ne.EXIT_ALL_SKIPPED
    assert "SKIPPED" in capsys.readouterr().out
    monkeypatch.setattr(ne, "select_records", lambda *a, **k: ([], "测试"))
    assert ne.main(["--design", "NOPE"]) == 1, "真的一条都没选中，仍是 1"
