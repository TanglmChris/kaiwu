"""网表 vs RTL 等价：综合产出的门级网表与它的 RTL 逐输出相同（本仓 内部#22）。

为什么值得有这一层：`run_equiv.py` 证的是 **RTL vs RTL**（拆分实现 ≡ 平坦参考）。
综合本身从来没人验过 —— yosys + ABC 把 RTL 映射成 ASAP7 单元之后，网表与 RTL
是不是同一个函数，一直是默认成立的。记录里的面积、时序、功耗全都量在网表上，
网表错了，那些数字就是另一个电路的数字，而流程不会报任何错。

怎么证：
- gate 侧：`read_liberty`（**不带** `-lib`）从合并库的 `function` / `ff` 描述建出
  单元的功能模型，读网表、解开保层级、展平。
- gold 侧：综合当时读的同一组 RTL（`flow.synth.synth.source_files`）+ 同一组参数。
- 两侧接成 `miter -equiv`（输出 `trigger`，两边不同时为 1），导出 AIGER，交给
  ABC 的 `dprove` 证 `trigger` 恒为 0。组合设计 `dprove` 自己退化成 CEC；
  时序设计它用 fraig + 信号对应（scorr）+ 归纳，**是完整证明，不是有界展开**。
  组合 miter 上 SAT 没结论时退到 BDD（`collapse`）再证一次 —— 计数类函数（popcount
  加权和的阈值）SAT 证不动、BDD 却很小，见 `_run_job`。
- 时序设计的初态：先 `async2sync`（AIGER 没有异步复位），再用 `sim -w` 拉一拍复位、
  把复位之后的状态写成初值 —— 两侧从同一个复位态出发。不能只把初值清零：ASAP7
  触发器的内部状态是反相的（`IQN`），清零等于 Q=1，一开拍两边就不同。
  不复位的寄存器复位后仍没有定值：gold 侧按 x 处理（`xprop`），gold 输出为 x 的位不比
  （`miter -ignore_gold_x`），见 `_seq`（内部#188）。
- gold 侧的 `x`（变量位段越界时 `$shiftx` 给的 x）在 `write_aiger` 前定成 0。这是
  **保守**的：证过了，说明网表等于「x 取 0」那一个合法实现，因而是 RTL 的合法细化；
  碰到可达的 x 只会假失败，不会放过真错误。

为什么不用 yosys 自己的 `sat -seq N`：它没有结构哈希，要把两个结构不同的除法器展开
N 拍硬比 —— 一个带除法器的地址流水设计最大那档 10 分钟没出结果、800 MB；同一条 `dprove` 0.8 s。

覆盖边界（不要高估）：证的是**这一份网表**与 RTL 等价，网表来自 `runs/<id>/synth/`
（search 胜出的那份，就是记录里测的那一份）。`runs/` 是 gitignored 的，清过就没有
网表可证 —— 那一条报「缺网表」，不算通过。

本文件**不在** `METRIC_MODULES` 里：它不产出任何记录字段，改它不换代。
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow import records as record_store  # noqa: E402
from flow.flow_fingerprint import generation_label, split_by_generation  # noqa: E402
from flow.paths import clock_port, clocks, equiv_enabled, load_design_config, run_dir  # noqa: E402
from flow.machine_lock import machine_lock  # noqa: E402

DEFAULT_LIBERTY = Path.home() / "pdk" / "asap7_merged" / "asap7sc7p5t_RVT_TT.lib"
RECORDS = None   # None = 全部设计根的记录文件（内部#422，flow/records.py）；给路径则只读那一个文件
FF_CELL = "DFF"          # ASAP7 全部时序单元名都含 DFF（DFFHQNx1、DFFASRHQNx1 ……）


def _chparam(params):
    return " ".join(f'-set {k} "{v}"' if isinstance(v, str) else f"-set {k} {v}"
                    for k, v in params.items())


_TAIL = """techmap; opt -fast
dffunmap
aigmap
setundef -zero
write_aiger -zinit {aig}
"""


def _seq(clock, reset):
    """时序设计的初态：AIGER 没有异步复位，先 async2sync；再拉一拍复位写回初值。

    `clock` 是一个端口名或端口名列表（多时钟，内部#186）：拉复位那一拍里每个时钟都打，否则只在
    第一个时钟上的寄存器有初值，另一个域从未定状态开始比。AIGER 本身只有一个隐式时钟，所有
    寄存器每步都走 —— 两侧按同一种方式建模，比的仍是同一个函数。"""
    if not clock:
        return ""
    clks = " ".join(f"-clock in_{c}" for c in ([clock] if isinstance(clock, str) else clock))
    # 不复位的寄存器（内部#188）：复位之后它们没有定值。两侧各取一个任意初值去比，第 0 拍就对不上（ASAP7 触发器
    # 存的是反相的 IQN，网表里的寄存器名也丢了，没法按名字把两侧的初值配成一样）。所以 gold 侧把它们当 x：
    # `xprop` 只改写 gold 侧（gate 侧单元名以 `$flatten\gate.` 开头，不选），x 以两路 0/1 信号显式传播；
    # miter 用 `-ignore_gold_x`，gold 输出为 x 的位不比。gate 侧不复位的寄存器初值仍是任意的（write_aiger
    # -zinit 给它们加自由输入）。证明的是「从复位出发，gold 有定义的每一位，网表对任意初值都相等」——
    # 网表是 RTL 的合法细化。`-assume-def-inputs`：端口输入都是 0/1（AIGER 只有两值），不加则 xprop 认为
    # 时钟可能是 x、跳过 gold 侧的全部触发器。xprop 的 x 传播是保守的（例如选择信号为 x 时不看两路是否相同），
    # 只会多出不比的位，不会把真错误判成等价。
    return f"""async2sync
dffunmap
opt_clean
sim {clks} -resetn in_{reset} -rstlen 1 -n 1 -w
xprop -assume-def-inputs c:* c:$flatten\\gate.* %d
"""


def _tie_cmds(design, tie):
    """参考口径（reference-ppa）：gold 侧把这些顶层输入接成常数，与参考网表比。值的位宽由调用方
    （flow/synth/reference.py）先核过 —— `connect -set` 对超出位宽的值静默截断。"""
    if not tie:
        return ""
    return (f"cd {design}\n" + "".join(f"delete -input w:{p}\nconnect -set {p} {v}\n" for p, v in tie.items())
            + "cd ..\n")


def _sides(design, params, netlist, liberty, srcs, gate_body, gold_body, renames=("", ""),
           ignore_gold_x=False, tie=None):
    """两侧读入、各自做完 body、stash，再接成 miter。body 里放各自的展平 / 剪开方式。

    gold 侧 `proc` 之后跑 `memory`：RTL 里的寄存器数组被推断成 `$mem`（行为模型的 SRAM），不映射成
    触发器就留到 `write_aiger` 报错（内部#188，一个行为模型 SRAM 实撞）；综合那边 `synth` 做的是同一件事。

    顶层两侧都先改名 NLEQ_TOP：chparam 之后 RTL 侧的顶层可能是派生名
    `$paramod$<hash>\\<顶层>`，按原名选会落空（ADDER32 实撞）。
    """
    return f"""
read_liberty -ignore_miss_func {liberty}
read_verilog {netlist}
hierarchy -check -top {design}
rename -top NLEQ_TOP
{renames[0]}{gate_body}rename -top gate
design -stash gate

read_verilog -sv {srcs}
chparam {_chparam(params)} {design}
hierarchy -check -top {design}
proc
memory
{_tie_cmds(design, tie)}rename -top NLEQ_TOP
{renames[1]}{gold_body}rename -top gold
design -stash gold

design -copy-from gold -as gold gold
design -copy-from gate -as gate gate
miter -equiv{" -ignore_gold_x" if ignore_gold_x else ""} -flatten gold gate miter
hierarchy -top miter
"""


def build_script(design, params, netlist, liberty, sources, aig, clock=None,
                 reset="rst_n", tie=None):
    """整体证明：两侧全部展平。`clock` 为 None 表示按组合设计处理。"""
    flat = "setattr -mod -unset keep_hierarchy\nflatten; opt_clean\n"
    srcs = _inc_flags(design) + " ".join(map(str, sources))
    return (_sides(design, params, netlist, liberty, srcs, flat, flat, ignore_gold_x=bool(clock), tie=tie)
            + _seq(clock, reset) + _TAIL.format(aig=aig))


# --- 分层证明 ---------------------------------------------------------------
#
# 整体证明对大设计太慢：一个 32 字压缩流水的 miter 有 22 万个与门，dprove
# 十分钟没结论。本仓的时序顶层都是「保了层级的纯组合 step + 顶层寄存器」，于是拆开证：
#   1. 每个子模块类型：网表 ≡ RTL，一拍组合 CEC；
#   2. 顶层：两侧都把子模块实例剪开（`expose -evert`）—— 实例输出变成两侧**共享**的
#      自由输入，实例输入变成要比较的输出 —— 只剩寄存器与连线，dprove 很便宜。
# 两步合起来是完整的：顶层证了「每一拍子模块的输入两侧相等」，1 证了「相等的输入
# 给出相等的输出」，按拍归纳即得整体等价。前提是实例按名字一一对应 —— 对不上时
# rename / miter 当场报错，落到 FAILED，不会静默放过。
#
# 子模块名：网表里是转义标识符 `\$paramod\...`（yosys id 带前导反斜杠），RTL 侧是
# 私有 id `$paramod\...`，两边的参数哈希相同。统一改名成 NLEQ_SUB_<i> 再比；
# 只改模块名不够，实例的类型也要 `chtype -map` 跟着改。

_MODULE_RE = re.compile(r"^module (\\\S+|\w+)", re.M)


def _submodules(text, design):
    """网表里顶层之外的模块：[(gate 侧 id, gold 侧 id, 模块体)]。"""
    heads = [(m.group(1), m.start()) for m in _MODULE_RE.finditer(text)]
    out = []
    for i, (name, pos) in enumerate(heads):
        if name == design:
            continue
        body = text[pos:heads[i + 1][1] if i + 1 < len(heads) else len(text)]
        gold = name[1:] if name.startswith("\\$") else name.lstrip("\\")
        out.append((name, gold, body))
    return out


def _renames(subs, side):
    idx = 0 if side == "gate" else 1
    return "".join(f"rename {s[idx]} NLEQ_SUB_{i}\nchtype -map {s[idx]} NLEQ_SUB_{i}\n"
                   for i, s in enumerate(subs))


def _inc_flags(design):
    """gold 侧 RTL 的参数片段 include 目录（内部#76），与综合同口径；没有片段时是空串。"""
    from flow.paths import include_dirs
    return "".join(f"-I{d} " for d in include_dirs(design))


def build_compositional(design, params, netlist, liberty, sources, subs, aig_dir,
                        clock=None, reset="rst_n"):
    """返回 [(标签, yosys 脚本, aig 路径)]：每个子模块一份组合证明，最后一份是顶层。"""
    srcs = _inc_flags(design) + " ".join(map(str, sources))
    ren = (_renames(subs, "gate"), _renames(subs, "gold"))
    jobs = []
    for i in range(len(subs)):
        aig = Path(aig_dir) / f"sub{i}.aig"
        body = (f"hierarchy -top NLEQ_SUB_{i}\n"
                "setattr -mod -unset keep_hierarchy\nflatten; opt_clean\n")
        jobs.append((f"子模块 {subs[i][1]}",
                     _sides(design, params, netlist, liberty, srcs, body, body, ren)
                     + _TAIL.format(aig=aig), aig))
    cut = ("setattr -mod -unset keep_hierarchy\n"
           "setattr -mod -set keep_hierarchy 1 NLEQ_SUB_*\n"
           "flatten\n"
           "expose -evert NLEQ_TOP/t:NLEQ_SUB_*\n"
           "hierarchy -top NLEQ_TOP\n")
    aig = Path(aig_dir) / "top.aig"
    jobs.append(("顶层（子模块剪开）",
                 _sides(design, params, netlist, liberty, srcs, cut, cut, ren, ignore_gold_x=bool(clock))
                 + _seq(clock, reset) + _TAIL.format(aig=aig), aig))
    return jobs


def netlist_path(rec):
    return run_dir(rec["experiment_id"], "synth") / f"{rec['design']}_netlist.v"


def _ports(netlist_text, top):
    """网表顶层模块的输入端口名集合。"""
    m = re.search(rf"^module {re.escape(top)}\s*\(", netlist_text, re.M)
    body = netlist_text[m.end():] if m else ""
    head = body.split("endmodule", 1)[0]
    return set(re.findall(r"^\s*input\s+(?:\[[^\]]*\]\s*)?(\w+)\s*;", head, re.M))


def _run_job(label, script, aig, tmp, yosys, abc, may_be_wiring=False, timeout=None):
    """跑一份 yosys 脚本 + dprove。返回 (是否 PROVED, 日志)。

    `may_be_wiring`：分层证明的顶层剪掉子模块之后可以**只剩连线**（纯组合设计的顶层
    就是把端口接到子模块上），那时 miter 本来就是常数 —— 与门数为 0 是合法的。
    整体证明与子模块证明里必须有真实逻辑，那两处与门数为 0 就是 miter 搭坏了。
    """
    ys = Path(tmp) / (aig.stem + ".ys")
    ys.write_text(script)
    r = subprocess.run([yosys, "-q", "-s", str(ys)], capture_output=True, text=True)
    if r.returncode != 0:
        return "FAILED", f"[{label}] yosys 搭 miter 失败：\n" + r.stdout + r.stderr
    # AIGER 头 `aig M I L O A`：A 是与门数。miter 被化简成常数时 A=0，ABC 会秒回
    # 「等价」—— 那不是证明，是 miter 搭坏了（2026-09-25 实撞：`-ignore_gold_x`
    # 产生的 $eqx 经 techmap 之后把 trigger 化成了常 0）。
    header = aig.read_bytes().split(b"\n", 1)[0].split()
    if len(header) < 6 or (int(header[5]) == 0 and not may_be_wiring):
        return "FAILED", f"[{label}] miter 退化成常数（AIGER 头 {header!r}），不能当作证明"
    v, out = _abc(abc, f"read_aiger {aig}; dprove", tmp, timeout)
    if v != "UNDECIDED":
        return v, f"[{label}]（AIGER 头 {header!r}）\n{out}"
    if not _combinational(header):
        # 时序 miter 上 dprove 没结论 —— 换 PDR（IC3）再试一次（内部#188）。撞上的是一个 32 位 FIFO
        # FIFO_DEP_N=16 RST_EN=0：不复位的存储按 x 处理后状态位翻倍（1563 个锁存器），dprove 的归纳
        # 在第 16 帧撞上它自己的 60 s 单步上限；PDR 8 s 证完。PDR 也是完整证明（求出归纳不变量），
        # 不是有界展开；反例照旧报 `was asserted in frame N`，结论照旧由 `verdict` 判。
        v2, out2 = _abc(abc, f"read_aiger {aig}; pdr -T {int(timeout or 600)}", tmp, timeout)
        return v2, f"[{label}]（AIGER 头 {header!r}）\n{out}\n[{label}] dprove 没有结论，PDR 后备：\n{out2}"
    # 组合 miter 上 SAT 没证出来 —— 换 BDD 再试一次。
    # 撞上的是某个闭源设计的某一档配置：输出 `o_hit` 是四个 32 位
    # popcount 加权和的阈值，两侧的加法树被 ABC 重构得毫无对应，SAT 扫描找不到内部
    # 等价点（dprove 600 s、&cec 520 s、iprove 900 s 都没结论）。这类「计数的函数」
    # 的 BDD 却很小：`collapse` 建出全局 BDD，miter 等价时输出就是常 0，3.9 s。
    # 反过来 BDD 对除法器会指数爆炸（上面那个地址流水设计），所以只当后备，不当首选。
    # `collapse` 之后的 `strash; dprove` 读的是一个常数（等价）或一个小网络（反例），
    # 结论照旧由 `verdict` 判：BDD 只是换了把网络化简到底的办法，不另立判据。
    v2, out2 = _abc(abc, f"read_aiger {aig}; collapse; strash; dprove", tmp, timeout)
    return v2, f"[{label}]\n{out}\n[{label}] SAT 没有结论，BDD 后备：\n{out2}"


def _combinational(header):
    """AIGER 头 `aig M I L O A` 的 L（锁存器数）为 0。BDD 后备只对组合 miter 用。"""
    return int(header[3]) == 0


# 每一步 dprove / PDR 的墙钟上限（秒）。函数入口与命令行共用：参考口径（run_experiment._reference）调
# prove_netlist 时不传 timeout，默认 None 时 dprove 没有上限，一个大设计的一个点跑了 6.3 小时（内部#232）。
DEFAULT_TIMEOUT_S = 600


def _abc(abc, cmd, tmp, timeout):
    """跑一条 ABC 命令，读结论。返回 (PROVED|FAILED|UNDECIDED, 日志)。"""
    try:
        # cwd 放进临时目录：dprove 没证出来时会把 miter 转储成当前目录下的
        # cecmiter.aig —— 并行时几路抢写同一个文件，还会弄脏工作区（实撞）
        r = subprocess.run([abc, "-c", cmd], capture_output=True, text=True,
                           timeout=timeout, cwd=tmp)
    except subprocess.TimeoutExpired:
        return "UNDECIDED", f"`{cmd}` {timeout} s 内没有结论。这不是反例，也不是通过"
    out = r.stdout + r.stderr
    v = verdict(out)
    if v != "PROVED" and not re.search(r"not equivalent|(?<!UN)SATISFIABLE|was asserted in frame", out):
        v = "UNDECIDED"          # dprove 撞上自己的冲突上限：「Networks are UNDECIDED」
    return v, out


def prove_one(rec, liberty, yosys="yosys", abc="yosys-abc", reset=None, timeout=DEFAULT_TIMEOUT_S):
    """证一条记录的网表（`runs/<id>/synth/`）。返回 (状态, 耗时秒, 日志)。

    状态：PROVED / FAILED（反例，或流程没搭起来）/ UNDECIDED（限时内没结论）/ MISSING /
    CONFIG（时钟或复位端口的声明与网表对不上，内部#186 —— 不是网表不等价）。
    只有 PROVED 算通过。
    """
    nl = netlist_path(rec)
    if not nl.is_file():
        return "MISSING", 0.0, f"网表不在：{nl}（runs/ 被清过？）"
    return prove_netlist(rec["design"], rec["params"], nl, liberty, yosys, abc, reset,
                         timeout=timeout)


def reset_port(design):
    """低有效复位端口名：`params.yaml` 的 `tops:<顶层>:sim:reset_signal`，没声明取约定的 `rst_n`（内部#186）。"""
    return (load_design_config(design).get("sim") or {}).get("reset_signal") or "rst_n"


def clock_ports(design):
    """全部时钟端口：声明了 `sta.clocks` 取它的每个 `port`，否则 `sim.clock_signal`（纯组合为空）。"""
    ports = [c["port"] for c in clocks(design) if c.get("port")]
    if ports:
        return ports
    clk = clock_port(design)
    return [clk] if clk else []


def prove_netlist(design, params, nl, liberty, yosys="yosys", abc="yosys-abc",
                  reset=None, rtl_sources=None, timeout=DEFAULT_TIMEOUT_S, tie=None):
    """证一份网表 ≡ 该顶层在这组参数下的 RTL。返回 (PROVED|FAILED, 耗时秒, 日志)。

    `tie`（{输入端口: 常数}，参考口径，reference-ppa）：gold 侧先把这些输入接成常数，网表里已没有这些端口。
    参考网表用 `-hieropt` 综合，子模块可能被特化、改名，分层证明的「实例按名字一一对应」不成立，一律整体证明。

    `rtl_sources` 只给测试留：默认取综合当时读的那一组（`source_files`）。
    """
    from flow.synth.synth import source_files

    text = Path(nl).read_text()
    clock = None
    reset = reset or reset_port(design)
    if FF_CELL in text:
        clock = clock_ports(design)
        inputs = _ports(text, design)
        # 不猜：端口认错了，sim 会从一个随便的状态开始比，假失败假通过都可能
        missing = [p for p in clock + [reset] if p not in inputs]
        if not clock or missing:
            return "CONFIG", 0.0, (f"网表有触发器，但找不到时钟/复位端口 {missing or ['（没有声明时钟）']}"
                                   "（时钟来自 params.yaml 的 sta.clocks / sim.clock_signal，复位来自 sim.reset_signal，"
                                   "没声明取 rst_n；--reset 可临时覆盖）")
    sources = rtl_sources if rtl_sources is not None else source_files(design)
    subs = _submodules(text, design)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        # 子模块里有触发器时剪开就不成立（剪开假设子模块是纯函数），退回整体证明
        if subs and not tie and not any(FF_CELL in body for _, _, body in subs):
            jobs = build_compositional(design, params, nl, liberty, sources, subs, tmp,
                                       clock, reset)
        else:
            aig = Path(tmp) / "miter.aig"
            jobs = [("整体", build_script(design, params, nl, liberty, sources, aig,
                                          clock, reset, tie=tie), aig)]
        logs = []
        for label, script, aig in jobs:
            status, log = _run_job(label, script, aig, tmp, yosys, abc,
                                   may_be_wiring=(aig.name == "top.aig"), timeout=timeout)
            logs.append(log)
            if status != "PROVED":
                return status, time.monotonic() - t0, "\n".join(logs)
    return "PROVED", time.monotonic() - t0, "\n".join(logs)


def verdict(abc_out):
    """读 `dprove` 的结论。时序走 `Networks are (not) equivalent`；没有锁存器时它退化成
    CEC，结论写成 `UNSATISFIABLE`（miter 输出不可能为 1 = 等价）/ `SATISFIABLE`。
    PDR 后备（内部#188）写 `Property proved` / `Output 0 ... was asserted in frame N`。

    两种说法都认，别的一律不算通过 —— 「不等价」与「没证出来」都不是 PROVED。
    """
    if ("Networks are equivalent" in abc_out or "Property proved" in abc_out
            or re.search(r"\bUNSATISFIABLE\b", abc_out)):
        return "PROVED"
    return "FAILED"


# 选中的记录全部按 equiv: false 跳过时的退出码（内部#333）。不用 0：脚本链里 0 会被读成「证过了」。
EXIT_ALL_SKIPPED = 3


def drop_undeclared(recs):
    """去掉声明了 `equiv: false` 的设计的记录（equiv-optional D4，内部#232）。返回 (保留的, 跳过的设计名)。"""
    skipped = sorted({r["design"] for r in recs if not equiv_enabled(r["design"])})
    return [r for r in recs if r["design"] not in skipped], skipped


def select_records(design=None, generation="latest", ids=None, records=RECORDS):
    recs = record_store.load(path=records)
    if ids:
        want = set(ids)
        return [r for r in recs if r["experiment_id"] in want], "按 experiment_id"
    if design:
        # 先按设计过滤再分代：指纹按设计算（内部#146），各设计的「最新一代」不是同一代。先在全仓取最新一代
        # 再过滤，只有恰好是全仓最新的那个设计选得中，其余都「一条都没选中」（内部#188 时实撞）
        recs = [r for r in recs if r["design"].upper() == design.upper()]
    gens = list(split_by_generation(recs).items())
    if not gens:
        return [], "（无记录）"
    if generation == "latest":
        key = gens[-1][0]
    else:
        hits = [k for k, _ in gens
                if k[0] == "flow" and k[1].split(":")[-1].startswith(generation)]
        if len(hits) != 1:
            raise SystemExit(f"指纹前缀 {generation!r} 命中 {len(hits)} 代，要恰好 1 代")
        key = hits[0]
    chosen = dict(gens)[key]
    # 同一组合被测多次时只证最后一条（与 score.latest_per_params 同一口径）
    last = {}
    for r in chosen:
        last[(r["design"], json.dumps(r["params"], sort_keys=True))] = r
    return list(last.values()), generation_label(key)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", help="只证这个被测顶层")
    ap.add_argument("--generation", default="latest", help="latest 或指纹前缀")
    ap.add_argument("--id", action="append", dest="ids", help="只证这条记录，可重复")
    ap.add_argument("--liberty", default=str(DEFAULT_LIBERTY))
    ap.add_argument("--reset", default=None,
                    help="低有效复位端口名，覆盖 params.yaml 的 sim.reset_signal（没声明时取 rst_n）")
    ap.add_argument("--yosys", default="yosys")
    ap.add_argument("--abc", default="yosys-abc")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                    help="每一步 dprove 的墙钟上限（秒，默认 600）。超时报 UNDECIDED —— 不是通过")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="同时证几条（默认 1）。与 sweep / run_equiv 同一条理由：不按 CPU 数推")
    a = ap.parse_args(argv)

    recs, scope = select_records(a.design, a.generation, a.ids)
    recs, skipped = drop_undeclared(recs)
    if skipped:
        print(f"# 按设计声明跳过（params.yaml 的 equiv: false）：{', '.join(skipped)}", flush=True)
    n = len(recs)
    print(f"# netlist-equiv: {scope}，{n} 条记录"
          + (f"，只看 {a.design}" if a.design else "")
          + f"，并行度 {a.jobs}", flush=True)
    if n == 0:
        if skipped:
            # 选中了，但全部是声明不做等价的设计（内部#333）：单独的结论与退出码，不和「选错 id」混成同一个 1
            print("# 结论 SKIPPED：选中的记录全部按 params.yaml 的 equiv: false 跳过 —— 不是通过，也不是选错", flush=True)
            return EXIT_ALL_SKIPPED
        print("# 一条都没选中 —— 不能当作通过", flush=True)
        return 1

    counts = {"PROVED": 0, "FAILED": 0, "UNDECIDED": 0, "MISSING": 0, "CONFIG": 0}
    t0 = time.monotonic()
    # 全机互斥（内部#223）：大设计单进程约 7.5 GB，两个 worktree 同时证会把 16 GB 的机器压垮；本进程内仍按 -j 并行
    with machine_lock("equiv", f"netlist_equiv {scope} {a.design or ''} -j {a.jobs}"), \
            ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futs = {pool.submit(prove_one, r, a.liberty, a.yosys, a.abc, a.reset, a.timeout): (i, r)
                for i, r in enumerate(recs, 1)}
        for fut in as_completed(futs):
            i, r = futs[fut]
            status, dt, log = fut.result()
            counts[status] += 1
            print(f"[{i}/{n}] {status:9s} {r['experiment_id']}  ({dt:.1f} s)", flush=True)
            if status != "PROVED":
                print("    " + "\n    ".join(log.strip().splitlines()[-6:]), flush=True)
    print(f"# netlist-equiv 结束: 证了 {counts['PROVED']}/{n}，失败 {counts['FAILED']}，"
          f"未判定 {counts['UNDECIDED']}，缺网表 {counts['MISSING']}，缺配置 {counts['CONFIG']}，"
          f"用时 {time.monotonic() - t0:.1f} s", flush=True)
    return 0 if counts["PROVED"] == n else 1


if __name__ == "__main__":
    sys.exit(main())
