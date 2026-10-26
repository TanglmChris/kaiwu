"""综合出的网表必须满足 liberty 自己的电学约束。

为什么值得有这个测试：`max_capacitance` 在 liberty 里只是一个**声明**，没有任何
工具会因为超标而报错。OpenSTA 照常用查找表外插算出一个延时、给出看上去正常的
slack。一个 `INVx1` 驱动 436 个负载时，它一个 cell 就占掉整条关键路径的一半以上 ——
此时 `critical_path_delay_ns` 度量的是"这个流程不插缓冲"，不是"这个电路有多深"。
2026-09-09 就是这么翻的车：一个压缩流水设计的关键路径 12.3168 ns 里，两个超标 5 倍
的 cell 占了 10.28 ns。

`electrical_violations()` 用**独立的正则**扫 liberty 与网表，不复用 `synth.py` 的
任何函数 —— 用被测流程自己的代码去验证它，测不出流程本身的偏差。
"""
import functools
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

# 一个只为触发大扇出而生的最小设计：内部算出来的一根 sel 要驱动 256 个 mux 的
# 选择端。选择信号**必须是内部信号**而不是顶层输入端口 —— 端口没有驱动单元，
# 也就没有"哪个 cell 扛不住"这回事；真实形态（zc 那个 436 扇出的 INVx1）
# 也是内部单元。不插缓冲时综合器会让一个最小单元硬扛 256 个负载。
FANOUT_FIXTURE = """\
module fanout_hog (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [7:0]   c,
    input  wire [255:0] a,
    input  wire [255:0] b,
    output wire [255:0] y
);
    wire s = ^c;
    assign y = s ? a : b;
endmodule
"""


@functools.lru_cache(maxsize=1)
def _liberty_cells(path):
    """{cell 名: (max_capacitance, {输入引脚: capacitance})}，独立正则实现。"""
    text = Path(path).read_text()
    cells = {}
    # 顶层 cell 块之间切分；每个块里找 max_capacitance 与 direction:input 的引脚
    for m in re.finditer(r"^  cell \(([A-Za-z0-9_]+)\) \{", text, re.M):
        name = m.group(1)
        start = m.end()
        nxt = text.find("\n  cell (", start)
        body = text[start:nxt if nxt != -1 else len(text)]
        maxcap = None
        mc = re.search(r"max_capacitance\s*:\s*([0-9.eE+-]+)\s*;", body)
        if mc:
            maxcap = float(mc.group(1))
        pins = {}
        for pm in re.finditer(r"\n    pin \(([A-Za-z0-9_]+)\) \{", body):
            pstart = pm.end()
            pnxt = body.find("\n    pin (", pstart)
            pbody = body[pstart:pnxt if pnxt != -1 else len(body)]
            if re.search(r"direction\s*:\s*input\s*;", pbody):
                cm = re.search(r"\n\s+capacitance\s*:\s*([0-9.eE+-]+)\s*;", pbody)
                if cm:
                    pins[pm.group(1)] = float(cm.group(1))
        cells[name] = (maxcap, pins)
    return cells


def electrical_violations(netlist_path, liberty_path=LIBERTY):
    """返回 [(实例名, cell 型号, 负载, max_capacitance), ...]，为空表示没有超标。

    负载 = 这条网上所有输入引脚的 capacitance 之和（本地流没有连线电容）。
    """
    lib = _liberty_cells(str(liberty_path))
    text = Path(netlist_path).read_text()

    # 网表里的实例：  <cell> <inst> ( .PIN(net), ... );
    inst_re = re.compile(
        r"\n\s*\\?([A-Za-z0-9_$\\.]+)\s+(\\?[A-Za-z0-9_$\\.\[\]]+)\s*\(([^;]*?)\);",
        re.S)
    conn_re = re.compile(r"\.([A-Za-z0-9_]+)\(([^)]*)\)")

    load_on_net = {}     # net -> 累计输入引脚电容
    driver_of_net = {}   # net -> (实例名, cell 名)
    for m in inst_re.finditer(text):
        cell, inst, body = m.group(1), m.group(2), m.group(3)
        if cell not in lib:
            continue
        _maxcap, in_pins = lib[cell]
        for pin, net in conn_re.findall(body):
            net = net.strip()
            if not net:
                continue
            if pin in in_pins:
                load_on_net[net] = load_on_net.get(net, 0.0) + in_pins[pin]
            else:
                driver_of_net[net] = (inst, cell)

    out = []
    for net, (inst, cell) in driver_of_net.items():
        maxcap = lib[cell][0]
        load = load_on_net.get(net, 0.0)
        if maxcap is not None and load > maxcap:
            out.append((inst, cell, load, maxcap))
    return sorted(out, key=lambda r: -r[2])


def _synth_fixture(tmp_path):
    """用 flow/synth/synth.py 里那条 abc 命令综合 fanout 夹具，返回网表路径。

    abc 那一行从 `synth.py` 自己的模板里取，所以流程改了这个测试会跟着改 ——
    这是刻意的耦合：测试要验的就是"流程有没有要求缓冲"。
    """
    from flow.synth import synth as flow_synth

    src = tmp_path / "fanout_hog.v"
    src.write_text(FANOUT_FIXTURE)
    nl = tmp_path / "nl.v"
    # delay_opt="" —— 这个夹具验的是"流程有没有要求缓冲"，与延时目标无关，
    # 所以取不加压的那一档（也就是本参数存在之前的那条命令行）。
    abc_line = [l for l in flow_synth.YOSYS_TEMPLATE.splitlines()
                if l.startswith("abc ")][0].format(
        liberty=LIBERTY, abc_constr=flow_synth.ABC_CONSTR, delay_opt="")
    ys = tmp_path / "s.ys"
    ys.write_text("\n".join([
        f"read_verilog {src}",
        "synth -top fanout_hog",
        f"dfflibmap -liberty {LIBERTY}",
        abc_line,
        "opt_clean",
        "rename -top fanout_hog",
        f"write_verilog {nl}",
    ]))
    subprocess.run(["yosys", "-s", str(ys)], capture_output=True, check=True)
    return nl


@pytest.mark.skipif(not LIBERTY.is_file(), reason="合并 liberty 不在本机")
def test_flow_asks_abc_for_buffering(tmp_path):
    """流程必须给 abc 传 -constr —— 不传就完全没有 buffer/upsize/dnsize。"""
    from flow.synth import synth as flow_synth

    abc_lines = [l for l in flow_synth.YOSYS_TEMPLATE.splitlines()
                 if l.startswith("abc ")]
    assert len(abc_lines) == 1, "synth.py 的模板里应该正好有一条 abc 命令"
    assert "-constr" in abc_lines[0], (
        "flow/synth/synth.py 的 abc 命令没有 -constr。yosys 只有在给了 -constr 时"
        "才会在默认脚本末尾接上 buffer; upsize; dnsize —— 不给就完全没有缓冲插入"
        "和驱动强度优化（见 `yosys -h abc` 的两套默认脚本）。")

    constr = Path(flow_synth.ABC_CONSTR)
    assert constr.is_file(), f"约束文件不存在: {constr}"
    body = constr.read_text()
    # 只认行首的指令，不要匹配到注释里的同名词
    cell = re.search(r"^set_driving_cell\s+(\S+)", body, re.M)
    assert cell, "约束文件里缺 set_driving_cell"
    assert re.search(r"^set_load\s+[0-9.]+", body, re.M), "约束文件里缺 set_load"
    assert cell.group(1) in _liberty_cells(str(LIBERTY)), (
        f"set_driving_cell 指定的 {cell.group(1)} 不在 liberty 里 —— "
        f"换 PDK 时必须同时改 {constr}")


@pytest.mark.flow
@pytest.mark.skipif(not LIBERTY.is_file() or __import__("shutil").which("yosys") is None,
                    reason="合并 liberty 或 yosys 不在本机（#193）")
def test_high_fanout_net_is_buffered(tmp_path):
    """一根线驱动 256 个 mux 选择端时，综合结果不得有 cell 超过自己的 max_capacitance。"""
    nl = _synth_fixture(tmp_path)
    bad = electrical_violations(nl)
    assert not bad, (
        "网表里有 cell 的负载超过它自己的 max_capacitance（liberty 只声明不强制，"
        "任何工具都不会因此报错，但 STA 会外插出一个巨大且看似正常的延时）：\n"
        + "\n".join(f"  {inst} ({cell}): 负载 {load:.1f} fF > max {mx:.1f} fF"
                    for inst, cell, load, mx in bad[:10]))


if __name__ == "__main__":
    # 也可以直接查一份真实网表：
    #   python tests/test_synth_electrical.py runs/<id>/synth/<top>_netlist.v
    target = Path(sys.argv[1])
    found = electrical_violations(target)
    if found:
        print(f"{target}: {len(found)} 个 cell 负载超标（按超标量排序，前 10）：")
        for inst, cell, load, mx in found[:10]:
            print(f"  {inst} ({cell}): {load:.1f} fF > max {mx:.1f} fF  ({load/mx:.1f}x)")
        sys.exit(1)
    print(f"{target}: 所有 cell 的负载都在 max_capacitance 之内")
