"""顶层端口组合依赖检查（io-comb-deps，内部#266；用户 2026-10-11 定 Q1–Q5）。

对被测顶层的一组参数，算出每个输出端口**组合**依赖哪些输入端口，与 LRS「接口组合依赖」表
逐项比对：实测有、表里没允许的一项判违规（白名单，Q2）。

分析（design D1）：yosys 展平后 `techmap` 拆成逐位门，时序单元与存储切断依赖，其余单元的
每个输出位依赖它的每个输入位。逐位是必要的：按字级单元算，一条载荷做按位与 / 或、下游只取
一位时，会把整条载荷都算进来（内部#266 verify 实测的门控空闲信号假违规）。组合环按强连通
分量合并后再算，结果对环也精确。

不计的输入（D2）：时钟端口、复位、`sta.static_ports` 匹配到的端口。
"""
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.synth.synth import _chparam_sets, _inc_flags  # noqa: E402

# 时序单元与存储：切断组合依赖。techmap 之后寄存器是 $_DFF*_ / $_SDFF*_ / $_DLATCH*_ 一类细粒度单元。
SEQ_PREFIX = ("$_DFF", "$_SDFF", "$_ALDFF", "$_DLATCH", "$_SR_", "$_FF_",
              "$dff", "$adff", "$sdff", "$aldff", "$dffsr", "$dlatch", "$adlatch", "$sr", "$ff",
              "$mem", "$check", "$assert", "$assume", "$cover", "$print", "$live", "$fair")

YOSYS_SCRIPT = """\
{reads}
{chparam}
hierarchy -check -top {top}
proc
flatten
opt_clean
memory
memory_map
opt_clean
techmap
opt_clean
write_json {out}
"""


def export_netlist(sources, top, params, workdir, incs=(), yosys=None):
    """跑 yosys 得到逐位网表（yosys JSON 的 dict）。脚本、日志与 JSON 留在 workdir。"""
    yosys = yosys or shutil.which("yosys")
    if yosys is None:
        raise RuntimeError("io_comb_deps：yosys 不在 PATH（先把 oss-cad-suite 加进 PATH）")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "netlist.json"
    script = YOSYS_SCRIPT.format(
        reads="\n".join(f"read_verilog {_inc_flags(incs)}{s}" for s in sources),
        chparam=f"chparam {_chparam_sets(params)} {top}" if params else "",
        top=top, out=out)
    (workdir / "iodeps.ys").write_text(script)
    proc = subprocess.run([yosys, "-q", "-l", str(workdir / "yosys.log"), "-s", str(workdir / "iodeps.ys")],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"io_comb_deps：yosys 失败（{workdir / 'yosys.log'}）：\n"
                           + (proc.stderr or proc.stdout)[-3000:])
    return json.loads(out.read_text())


def _module(netlist, top):
    try:
        return netlist["modules"][top]
    except KeyError:
        raise RuntimeError(f"io_comb_deps：网表里没有顶层 {top}") from None


def _excluded(name, exclude):
    return any(fnmatch.fnmatchcase(name, pat) for pat in exclude)


def _graph(mod):
    """{位: [它组合依赖的位]}；时序单元驱动的位与没人驱动的位不在表里。另返回 {位: (单元类型, src)}。"""
    drv, where = {}, {}
    for cell in mod["cells"].values():
        if cell["type"].startswith(SEQ_PREFIX):
            continue
        ins, outs = [], []
        for pin, bits in cell["connections"].items():
            dst = ins if cell["port_directions"].get(pin) == "input" else outs
            dst.extend(b for b in bits if isinstance(b, int))
        src = cell.get("attributes", {}).get("src", "")
        for b in outs:
            drv[b] = ins
            where[b] = (cell["type"], src)
    return drv, where


def port_deps(netlist, top, exclude=()):
    """{输出端口: {组合依赖的输入端口}}。exclude 是不计的输入端口名或 fnmatch 模式。"""
    mod = _module(netlist, top)
    label, outs = {}, {}
    for name, port in mod["ports"].items():
        bits = [b for b in port["bits"] if isinstance(b, int)]
        if port["direction"] == "input":
            if not _excluded(name, exclude):
                for b in bits:
                    label[b] = name
        elif port["direction"] == "output":
            outs[name] = bits
    drv, _ = _graph(mod)

    # Tarjan（迭代）：强连通分量按逆拓扑序产出，产出时它能到达的分量都已算好
    index, low, comp_of, comp_set = {}, {}, {}, []
    stack, on_stack, counter = [], set(), 0
    for root in (b for bits in outs.values() for b in bits):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            succ = drv.get(v, ())
            recurse = False
            while i < len(succ):
                w = succ[i]
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                members = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp_of[w] = len(comp_set)
                    members.append(w)
                    if w == v:
                        break
                cid = len(comp_set)
                s = set()
                for w in members:
                    if w in label:
                        s.add(label[w])
                    for x in drv.get(w, ()):
                        if comp_of[x] != cid:
                            s |= comp_set[comp_of[x]]
                comp_set.append(frozenset(s))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return {name: set().union(*(comp_set[comp_of[b]] for b in bits)) if bits else set()
            for name, bits in outs.items()}


def one_path(netlist, top, out_port, in_port):
    """一条从输出端口到输入端口的组合路径：单元列表（输出侧在前），每项「类型 src」。找不到返回 None。"""
    mod = _module(netlist, top)
    target = {b for b in mod["ports"][in_port]["bits"] if isinstance(b, int)}
    start = [b for b in mod["ports"][out_port]["bits"] if isinstance(b, int)]
    drv, where = _graph(mod)
    prev = {b: None for b in start}
    queue = list(start)
    for b in queue:                     # 广度优先，queue 边走边长
        if b in target:
            steps = []
            while prev[b] is not None:
                b, cell = prev[b]
                steps.append(cell)
            return list(reversed(steps))
        for x in drv.get(b, ()):
            if x not in prev:
                typ, src = where[b]
                prev[x] = (b, f"{typ} {src.split('|')[-1]}")
                queue.append(x)
    return None


# --- LRS「接口组合依赖」表（design D3） ---------------------------------------------

class TableError(ValueError):
    """LRS 的接口组合依赖表找不到、不止一张，或写法不合 docs/spec-writing.md 的约定。"""


class ConfigError(ValueError):
    """params.yaml 的 iodeps_configs 写错。"""


class Row:
    def __init__(self, lineno, outputs, segments):
        self.lineno, self.outputs, self.segments = lineno, outputs, segments

    def __repr__(self):
        return f"Row({self.lineno}, {self.outputs}, {self.segments})"


_TICK = re.compile(r"`([^`]+)`")
_PAREN = re.compile(r"（[^（）]*）")
_COND = re.compile(r"^`(\w+)`\s*取\s*(\d+(?:\s*/\s*\d+)*)\s*时[：:]?\s*")
_SEP = re.compile(r"[、，,\s]+")
_PORT_PAT = re.compile(r"[A-Za-z_][\w*]*")


def _tokens(text, lineno, what):
    """反引号端口 / 通配列表；写成「无」返回空表。反引号之外还有别的文字就是写法错误。"""
    text = _PAREN.sub("", text).strip()
    toks = _TICK.findall(text)
    rest = _SEP.sub("", _TICK.sub("", text))
    if not toks and rest == "无":
        return []
    if rest or not toks:
        raise TableError(f"LRS 第 {lineno} 行：{what}「{text}」只能是反引号写的端口（可带 *），或者「无」")
    bad = [t for t in toks if not _PORT_PAT.fullmatch(t)]
    if bad:
        raise TableError(f"LRS 第 {lineno} 行：{bad} 不是端口名或通配")
    return toks


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_table(text):
    """找出唯一一张表头前两格为「输出」「允许组合依赖的输入」的表，返回 [Row]。"""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines)
              if ln.lstrip().startswith("|") and _cells(ln)[:2] == ["输出", "允许组合依赖的输入"]]
    if not starts:
        raise TableError("LRS 里没有接口组合依赖表（表头前两格是「输出」「允许组合依赖的输入」）")
    if len(starts) > 1:
        raise TableError(f"LRS 里有两张以上的接口组合依赖表（第 {', '.join(str(i + 1) for i in starts)} 行）")
    rows = []
    for i in range(starts[0] + 2, len(lines)):
        ln = lines[i]
        if not ln.lstrip().startswith("|"):
            break
        cells, lineno = _cells(ln), i + 1
        if len(cells) < 2:
            raise TableError(f"LRS 第 {lineno} 行：表行不到两格")
        outputs = _tokens(cells[0], lineno, "「输出」格")
        if not outputs:
            raise TableError(f"LRS 第 {lineno} 行：「输出」格不能是「无」")
        segments = []
        for seg in _PAREN.sub("", cells[1]).split("；"):     # 括号里的说明可以带「；」，先去掉再分段
            seg = seg.strip()
            if not seg:
                continue
            m = _COND.match(seg)
            cond = None
            if m:
                cond = (m.group(1), tuple(int(v) for v in re.split(r"\s*/\s*", m.group(2))))
                seg = seg[m.end():]
            segments.append((cond, _tokens(seg, lineno, "「允许组合依赖的输入」格的一段")))
        if not segments:
            raise TableError(f"LRS 第 {lineno} 行：「允许组合依赖的输入」格是空的，没有依赖要写「无」")
        rows.append(Row(lineno, outputs, segments))
    return rows


def _star_re(pat):
    return re.compile("^" + re.escape(pat).replace(r"\*", "(.*)") + "$")


def _pair_allowed(out, inp, op, ip):
    """输出 / 输入两边各只有一个 * 时，两个 * 要匹配同一串（同名绑定）；否则各自按通配匹配。"""
    mo, mi = _star_re(op).match(out), _star_re(ip).match(inp)
    if not (mo and mi):
        return False
    if op.count("*") == 1 and ip.count("*") == 1:
        return mo.group(1) == mi.group(1)
    return True


class Result:
    def __init__(self):
        self.violations, self.absent, self.errors = [], [], []

    def __repr__(self):
        return f"Result(violations={self.violations}, absent={self.absent}, errors={self.errors})"


def compare(deps, rows, params, ports_in, ports_out):
    """实测 deps（{输出: {输入}}）与表比对（design D4）。params 用来取条件段里的参数值。"""
    res = Result()
    pairs = []
    for row in rows:
        for op in row.outputs:
            if not any(fnmatch.fnmatchcase(p, op) for p in ports_out):
                res.errors.append(f"LRS 第 {row.lineno} 行：输出 `{op}` 在顶层没有对应端口")
        for cond, inputs in row.segments:
            for ip in inputs:
                if not any(fnmatch.fnmatchcase(p, ip) for p in ports_in):
                    res.errors.append(f"LRS 第 {row.lineno} 行：输入 `{ip}` 在顶层没有对应端口")
            if cond is not None:
                name, values = cond
                if name not in params:
                    res.errors.append(f"LRS 第 {row.lineno} 行：条件参数 {name} 不是顶层参数")
                    continue
                if params[name] not in values:
                    continue
            pairs.extend((op, ip, row.lineno) for op in row.outputs for ip in inputs)
    # 对外的同口 valid / 载荷不许放行同口 ready（docs/spec-writing.md §3，内部#286）；ready ← ready 不管
    same = set()
    for op, ip, lineno in pairs:
        for o in sorted(ports_out):
            for i in sorted(ports_in):
                if (i.endswith("_rdy") and o != i and o.startswith(i[:-3]) and (o, i, lineno) not in same
                        and _pair_allowed(o, i, op, ip)):
                    same.add((o, i, lineno))
                    res.errors.append(f"LRS 第 {lineno} 行：同口 `{o}` 不许组合依赖同口 `{i}`"
                                      "（对外的 valid 与载荷不依赖 ready，docs/spec-writing.md §3）")
    seen = set()
    for out in sorted(deps):
        for inp in sorted(deps[out]):
            hit = [(op, ip) for op, ip, _ in pairs if _pair_allowed(out, inp, op, ip)]
            if hit:
                seen.update(hit)
            else:
                res.violations.append((out, inp))
    for op, ip, _ in pairs:
        if (op, ip) in seen:
            continue
        concrete = [(o, i) for o in sorted(ports_out) for i in sorted(ports_in)
                    if _pair_allowed(o, i, op, ip)]
        res.absent.extend(concrete or [(op, ip)])
        seen.add((op, ip))
    return res


# --- 配置清单（design D5） -----------------------------------------------------------

_PARAM_DECL = re.compile(r"\bparameter\s+(?:integer\s+)?(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)\s*=\s*([^,;)\n]+)")


_SIZED = re.compile(r"(?:\d+)?\s*'[sS]?([bBoOdDhH])\s*([0-9a-fA-F_]+)")
_BASE = {"b": 2, "o": 8, "d": 10, "h": 16}


def _verilog_int(text):
    """十进制或带位宽的字面量（`2'b10`）转整数；表达式等别的写法原样返回字符串。"""
    m = _SIZED.fullmatch(text)
    if m:
        return int(m.group(2).replace("_", ""), _BASE[m.group(1).lower()])
    try:
        return int(text.replace("_", ""), 10)
    except ValueError:
        return text


def rtl_parameters(sources, top):
    """顶层 RTL 模块的 {参数名: 默认值}（能转成整数的转整数，其余留原文）。"""
    decl = re.compile(rf"^\s*module\s+{re.escape(top)}\b", re.M)
    for src in sources:
        text = Path(src).read_text()
        m = decl.search(text)
        if not m:
            continue
        end = text.find("endmodule", m.end())
        body = re.sub(r"//[^\n]*", "", text[m.start():end if end != -1 else None])
        out = {}
        for name, val in _PARAM_DECL.findall(body):
            out[name] = _verilog_int(val.strip())
        return out
    raise ConfigError(f"读入集合里找不到 module {top}")


def validate_configs(top, configs, rtl_params):
    """校验 iodeps_configs；返回 [(name, {参数: 值})]。写错在跑 yosys 之前报出。"""
    if not isinstance(configs, list) or not configs:
        raise ConfigError(f"{top}：params.yaml 的 tops:{top}:iodeps_configs 要写成非空列表"
                          "（每项 {name, <顶层 RTL 参数>: 值}），发布前检查要按它跑")
    out, names, bad = [], set(), []
    for i, item in enumerate(configs):
        tag = f"{top}：iodeps_configs[{i}]"
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
            bad.append(f"{tag} 要写成带 name 的映射")
            continue
        name = item["name"]
        if name in names:
            bad.append(f"{tag} 的 name {name} 重复")
        names.add(name)
        params = {k: v for k, v in item.items() if k != "name"}
        unknown = sorted(k for k in params if k not in rtl_params)
        if unknown:
            bad.append(f"{tag}（{name}）的 {', '.join(unknown)} 不是顶层 RTL 的参数")
        out.append((name, params))
    if bad:
        raise ConfigError("\n".join(bad))
    return out


# --- 配置清单的覆盖（内部#338，iodeps-coverage） -------------------------------------------

def coverage(rows, configs, rtl_params, declared):
    """iodeps_configs 覆盖了哪些取值（用户 2026-10-19 定）。返回 (errors, hints)：
    - 甲：LRS 表每个条件段写到的（参数, 取值），没有一组配置取到 → error；
    - 乙：params.yaml 里名字以 _EN 结尾、声明了 values 的开关，没取到的取值 → error；其余声明参数 → hint。
    取值按有效值算：配置写了取配置值，没写取 RTL 默认值（同 run_config 比对条件段时的取法）。"""
    eff = [{**rtl_params, **params} for _, params in configs]
    taken = lambda name, v: any(e.get(name) == v for e in eff)  # noqa: E731
    errors, hints, seen = [], [], set()
    for row in rows:
        for cond, _ in row.segments:
            if cond is None or cond[0] not in rtl_params:      # 不是顶层参数：compare 已报错
                continue
            for v in cond[1]:
                if (cond[0], v) not in seen and not taken(cond[0], v):
                    errors.append(f"LRS 第 {row.lineno} 行：`{cond[0]}` 取 {v} 的条件段没有一组 iodeps_configs 取到")
                seen.add((cond[0], v))
    for name, values in sorted((declared or {}).items()):
        for v in values:
            if taken(name, v):
                continue
            msg = f"params.yaml：`{name}` 取 {v} 没有一组 iodeps_configs 取到"
            (errors if name.endswith("_EN") else hints).append(msg)
    return errors, hints


def _declared_values(cfg):
    """params.yaml 里 tops:<顶层>:params: 各参数声明的 values（只收带 values 的）。"""
    return {k: list(v["values"]) for k, v in (cfg.get("params") or {}).items()
            if isinstance(v, dict) and v.get("values")}


# --- 按设计跑（design D2、D6） -------------------------------------------------------

def interface_doc(root, top):
    """写「接口组合依赖」表的接口文档：`lrs.<顶层>.md`；没有 LRS 的通用构件用精简规格 `spec.<顶层>.md`（内部#415）。
    两者都有时以 LRS 为准；都没有时返回 LRS 的路径，读的时候报找不到文件。"""
    lrs = Path(root) / f"lrs.{top}.md"
    spec = Path(root) / f"spec.{top}.md"
    return spec if not lrs.is_file() and spec.is_file() else lrs


def design_setup(design):
    """读入集合、include、接口文档路径（setup["lrs"]，见 interface_doc）、不计的输入模式、配置清单。"""
    from flow import paths
    from flow.synth.synth import source_files
    cfg = paths.load_design_config(design)
    sources = source_files(design)
    rtl_params = rtl_parameters(sources, design)
    configs = validate_configs(design, cfg.get("iodeps_configs"), rtl_params)
    exclude = [c["port"] for c in paths.clocks(design)]
    exclude.append((cfg.get("sim") or {}).get("reset_signal") or "rst_n")
    for item in paths.static_ports(design):
        exclude.extend(item["ports"])
    lrs = interface_doc(paths.resolve_design_root(design), design)
    return dict(sources=sources, incs=paths.include_dirs(design), rtl_params=rtl_params,
                configs=configs, exclude=exclude, lrs=lrs, loops_decl=cfg.get("iodeps_loops") or {},
                declared=_declared_values(cfg))


def run_config(design, setup, name, params, outdir, deps_only=False, keep_netlist=False):
    """跑一组配置，返回结果 dict；违规每项带一条路径。"""
    work = Path(outdir) / name
    netlist = export_netlist(setup["sources"], design, params, work, incs=setup["incs"])
    if not keep_netlist:
        (work / "netlist.json").unlink(missing_ok=True)      # 大设计的逐位网表上 GB，算完就删
    mod = _module(netlist, design)
    ports_in = {n for n, p in mod["ports"].items() if p["direction"] == "input"}
    ports_out = {n for n, p in mod["ports"].items() if p["direction"] == "output"}
    deps = port_deps(netlist, design, setup["exclude"])
    out = dict(name=name, params=params, deps={k: sorted(v) for k, v in sorted(deps.items()) if v})
    if not deps_only:
        eff = {k: v for k, v in setup["rtl_params"].items()}
        eff.update(params)
        res = compare(deps, setup["rows"], eff, ports_in, ports_out)
        # 外部耦合下的组合环（io-comb-loops，内部#281）：在同一份依赖上补外部模型找环
        from flow.check import io_comb_loops
        ports = {n: p["direction"] for n, p in mod["ports"].items()}
        try:
            loops = io_comb_loops.check(deps, ports, setup.get("loops_decl"), setup["exclude"],
                                        setup.get("loops_allowed", []))
            loop_errors = []
        except io_comb_loops.GroupError as e:
            loops, loop_errors = dict(peer_loops=[], channel_loops=[], loop_notes=[], passed=False), [str(e)]
        out.update(violations=[dict(output=o, input=i, path=one_path(netlist, design, o, i))
                               for o, i in res.violations],
                   absent=res.absent, errors=res.errors,
                   peer_loops=loops["peer_loops"], channel_loops=loops["channel_loops"], loop_errors=loop_errors,
                   loop_notes=loops.get("loop_notes", []),
                   passed=not res.violations and not res.errors and loops["passed"])
    (work / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def _report(r, deps_only):
    lines = []
    if deps_only:
        lines.append(f"== {r['name']}：输出 ← 组合依赖的输入")
        lines += [f"   {o} ← {', '.join(i)}" for o, i in r["deps"].items()]
        return "\n".join(lines)
    lines.append(f"== {r['name']}：{'PASS' if r['passed'] else 'FAIL'}"
                 f"（违规 {len(r['violations'])}，写法错误 {len(r['errors'])}，声明未出现 {len(r['absent'])}）")
    lines += [f"   写法错误：{e}" for e in r["errors"]]
    for v in r["violations"]:
        lines.append(f"   违规：{v['output']} ← {v['input']}（LRS 表没有允许）")
        for step in (v["path"] or [])[:12]:
            lines.append(f"       {step}")
    lines += [f"   提示：表里允许 {o} ← {i}，本组实测没有" for o, i in r["absent"]]
    bad = [l for l in r["peer_loops"] if l["allowed"] is None]
    lines.append(f"   外部耦合下的组合环（io-comb-loops）：按对方整体 {len(r['peer_loops'])} 个"
                 f"（未允许 {len(bad)}），按通道 {len(r['channel_loops'])} 个（参考）")
    lines += [f"   环检查出错：{e}" for e in r["loop_errors"]]
    lines += [f"   环检查提示：{n}" for n in r.get("loop_notes", [])]
    for l in r["peer_loops"]:
        tag = "未允许" if l["allowed"] is None else f"LRS 第 {l['allowed']} 行允许"
        lines.append(f"   组合环（{tag}）：{'、'.join(l['ports'])}")
        lines += [f"       内部 {o} ← {i}" for i, o in l["internal"][:20]]
    for l in r["channel_loops"]:
        lines.append(f"   参考·按通道的组合环：{'、'.join(l['ports'])}")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser(description="顶层端口组合依赖检查（io-comb-deps，#266）")
    ap.add_argument("--design", required=True)
    ap.add_argument("--config", action="append", help="只跑这几组（iodeps_configs 的 name），默认全部")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", help="产物目录，默认 runs/iodeps/<顶层>")
    ap.add_argument("--deps-only", action="store_true", help="只列实测依赖，不与 LRS 比对")
    ap.add_argument("--keep-netlist", action="store_true", help="保留逐位网表 JSON（默认算完就删）")
    a = ap.parse_args(argv)
    try:
        setup = design_setup(a.design)
        if not a.deps_only:
            from flow.check import io_comb_loops
            lrs_text = setup["lrs"].read_text()
            try:
                setup["rows"] = parse_table(lrs_text)
                setup["loops_allowed"] = io_comb_loops.parse_allowed(lrs_text)
            except (TableError, io_comb_loops.GroupError) as e:
                raise TableError(f"{setup['lrs'].name}：{e}") from e
    except (ConfigError, TableError, FileNotFoundError, RuntimeError, ValueError) as e:
        print(f"io_comb_deps：{e}", file=sys.stderr)
        return 2
    configs = setup["configs"]
    cov_errors = []
    if not a.deps_only:
        # 覆盖按整份清单算，与 --config 只跑哪几组无关（内部#338）
        cov_errors, cov_hints = coverage(setup["rows"], configs, setup["rtl_params"], setup.get("declared"))
        print(f"覆盖检查（#338）：缺口 {len(cov_errors)}，提示 {len(cov_hints)}")
        for e in cov_errors:
            print(f"   FAIL  {e}")
        for h in cov_hints:
            print(f"   提示  {h}")
    if a.config:
        unknown = sorted(set(a.config) - {n for n, _ in configs})
        if unknown:
            print(f"io_comb_deps：iodeps_configs 里没有 {unknown}", file=sys.stderr)
            return 2
        configs = [(n, p) for n, p in configs if n in a.config]
    outdir = Path(a.out) if a.out else REPO_ROOT / "runs" / "iodeps" / a.design
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        results = list(ex.map(lambda c: run_config(a.design, setup, c[0], c[1], outdir,
                                                   a.deps_only, a.keep_netlist), configs))
    for r in results:
        print(_report(r, a.deps_only))
    if a.deps_only:
        return 0
    failed = [r["name"] for r in results if not r["passed"]]
    print(f"\n汇总：{len(results)} 组，PASS {len(results) - len(failed)}，FAIL {len(failed)}"
          + (f"（{', '.join(failed)}）" if failed else "") + f"；覆盖缺口 {len(cov_errors)}")
    return 1 if failed or cov_errors else 0


if __name__ == "__main__":
    sys.exit(main())
