"""按提交比一个模块：gold（改前提交）≡ gate（改后提交或工作区）（内部#339，add-rev-equiv）。

    .venv/bin/python3 flow/equiv/rev_equiv.py --design <顶层> --top <模块> \\
        --gold-ref <提交>^ --gate-ref <提交>
    make -f flow/Makefile revequiv DESIGN=<顶层> TOP=<模块> GOLD=<提交>^ GATE=<提交>

两级判定（design D3）：
- text：两侧各自读入、定参、展开、映射存储，去掉源位置属性、隐藏内部网名后写 RTLIL，逐字相同即等价。
  证的是「规整后的网表一模一样」，含时序与复位逻辑。只改注释、空白、内部网名的提交在这一级就判完。
- induct：text 不同（或 `--mode induct`、或 `--gate-top` 改了模块名）时，`async2sync` 后
  `equiv_make` + `equiv_simple` + `equiv_induct`，未证数为 0 才判等价。证的是从匹配状态出发的时序等价；
  异步复位按同步处理，不证上电初值。寄存器重编码等状态对不上的改动可能证不出（报未证并列出未证信号，不误报等价）。

自检（design D4）：每次都做负对照 —— 包一层把 gate 第一个输出端口的最低位取反，用 equiv_simple 必须判不等；
归纳路径先证 gold ≡ gold。任一自检不过退出 3：那说明这个方法对这个模块不可信，不给结论。

退出码（design D5）：0 等价；1 不等或未证；2 用法 / 工具错误；3 自检失败。

源集合（design D2）：`git archive <提交> designs cbb flow` 解到临时目录，用**那个提交自己的**
`flow/paths.py::rtl_candidates` 取源，所以搬过目录的两个提交也能比。`--gate-ref WORKTREE`（默认）
取当前工作区（含未提交改动）。

不在 METRIC_MODULES，不写记录，不碰 flow/equiv/proved.json（design D7）。与 `make sigeq`（仿真签名）互补，
见 team/roles/kaiwu-design/README.md「改动的等价证据分三级」的 ②。
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = "WORKTREE"
EXIT_EQUIV, EXIT_DIFF, EXIT_USAGE, EXIT_SELFCHECK = 0, 1, 2, 3
NEG_FLIP = 1   # 负对照翻转掩码；测试把它桩成 0 来验证「负对照失效即退出 3」

SCOPE = {
    "text": "规整后网表逐字相同（含时序与复位逻辑）",
    "induct": "从匹配状态出发 {seq} 拍归纳的时序等价；异步复位按同步处理，不证上电初值",
}


class UsageError(Exception):
    pass


def _git(repo, *args, **kw):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, **kw)


def export(repo, ref, dst):
    """ref 的 designs / cbb / flow 导出到 dst；WORKTREE 表示当前工作区（未提交的改动也算）。"""
    dst.mkdir(parents=True)
    if ref == WORKTREE:
        r = _git(repo, "ls-files", "-z", "-co", "--exclude-standard", "--", "designs", "cbb", "flow")
        if r.returncode != 0:
            raise UsageError(f"{repo} 不是 git 仓库：{r.stderr.decode().strip()}")
        for f in filter(None, r.stdout.decode().split("\0")):
            p = repo / f
            if p.is_file():
                (dst / f).parent.mkdir(parents=True, exist_ok=True)
                (dst / f).write_bytes(p.read_bytes())
        return
    if _git(repo, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}").returncode != 0:
        raise UsageError(f"提交 {ref} 不存在")
    paths = [p for p in ("designs", "cbb", "flow")
             if _git(repo, "cat-file", "-e", f"{ref}:{p}").returncode == 0]
    tar = _git(repo, "archive", ref, *paths)
    if tar.returncode != 0:
        raise UsageError(f"导出 {ref} 失败：{tar.stderr.decode().strip()}")
    subprocess.run(["tar", "-x", "-C", str(dst)], input=tar.stdout, check=True)


def sources(design, tree):
    """用 tree 里那个提交自己的 flow/paths.py 取 design 的源文件集合（子进程，免得混进本仓的版本）。"""
    code = ("import json, sys; from flow.paths import rtl_candidates; "
            "print(json.dumps([str(p) for p in rtl_candidates(sys.argv[1], repo_root=__import__('pathlib').Path('.').resolve())]))")
    r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); " + code, design],
                       cwd=tree, capture_output=True, text=True)
    if r.returncode != 0:
        raise UsageError(f"在 {tree.name} 里找不到顶层 {design} 的源文件：{r.stderr.strip().splitlines()[-1:]}")
    srcs = json.loads(r.stdout)
    if not srcs:
        raise UsageError(f"{tree.name} 里顶层 {design} 没有 RTL 源文件")
    return srcs


def _chparam(module, params):
    return ("chparam " + " ".join(f"-set {k} {v}" for k, v in params.items()) + f" {module}; ") if params else ""


def _prep(srcs, module, params, name):
    """读入、定参、展开到一个扁平模块，改名为 name。"""
    script = ("read_verilog -sv " + " ".join(srcs) + "; " + _chparam(module, params)
              + f"hierarchy -check -top {module}; setattr -mod -unset keep_hierarchy; proc; flatten; "
              + "memory -nomap; memory_map; opt_clean -purge; ")
    return script + f"rename {module} {name}; "


def _yosys(script, log):
    r = subprocess.run(["yosys", "-q", "-l", str(log), "-p", script], capture_output=True, text=True)
    return r.returncode, log.read_text() if log.exists() else r.stdout + r.stderr


def text_dump(srcs, module, params, out, work):
    """写法规整后的 RTLIL：去掉模块与网 / 单元上的 src 属性，内部网名一律隐藏、重新编号（只留端口名）。"""
    rc, log = _yosys(_prep(srcs, module, params, "M") + "opt -purge; attrmap -remove src; attrmap -modattr -remove src; "
                     "rename -hide w:*; rename -enumerate; opt_clean -purge; " + f"write_rtlil {out}",
                     work / (out.name + ".log"))
    if rc != 0:
        raise UsageError(f"yosys 读入 {module} 失败（{out.name}）：\n{log[-2000:]}")
    return out.read_text()


def ports(srcs, module, params, work):
    j = work / "ports.json"
    rc, log = _yosys("read_verilog -sv " + " ".join(srcs) + "; " + _chparam(module, params)
                     + f"hierarchy -top {module}; proc; write_json -noscopeinfo {j}", work / "ports.log")
    if rc != 0:
        raise UsageError(f"yosys 读 {module} 的端口失败：\n{log[-2000:]}")
    return json.loads(j.read_text())["modules"][module]["ports"]


def negative_wrapper(srcs, module, params, work):
    """负对照：包一层，第一个输出端口与 NEG_FLIP 异或（默认翻转最低位）。"""
    ps = ports(srcs, module, params, work)
    outs = [n for n, p in ps.items() if p["direction"] == "output"]
    if not outs:
        raise UsageError(f"{module} 没有输出端口，做不了负对照")
    flip = outs[0]
    decl, conn = [], []
    for n, p in ps.items():
        w = len(p["bits"])
        decl.append(f"{p['direction']} wire {f'[{w - 1}:0] ' if w > 1 else ''}{n}")
        conn.append(f".{n}({n + '_neg_i' if n == flip else n})")
    w = len(ps[flip]["bits"])
    pov = ("#(" + ", ".join(f".{k}({v})" for k, v in params.items()) + ") ") if params else ""
    p = work / "neg.v"
    p.write_text(f"module NEG_{module} ({', '.join(decl)});\n"
                 f"  wire {f'[{w - 1}:0] ' if w > 1 else ''}{flip}_neg_i;\n"
                 f"  {module} {pov}U_NEG_{module} ({', '.join(conn)});\n"
                 f"  assign {flip} = {flip}_neg_i ^ {w}'d{NEG_FLIP};\nendmodule\n")
    return str(p), f"NEG_{module}", flip


def induct(gold, gate, seq, work, tag, simple_only=False):
    """gold / gate 各为 (源, 模块, 参数)。equiv_make + equiv_simple [+ equiv_induct]；返回 (证明了, 未证数, 日志)。"""
    (gs, gm, gp), (ts, tm, tp) = gold, gate
    script = (_prep(gs, gm, gp, "gold") + "design -stash gold; "
              + _prep(ts, tm, tp, "gate") + "design -stash gate; "
              "design -copy-from gold -as gold gold; design -copy-from gate -as gate gate; "
              "async2sync; equiv_make gold gate eq; hierarchy -top eq; "
              f"equiv_simple -seq {seq}; " + ("" if simple_only else f"equiv_induct -seq {seq}; ") + "equiv_status")
    rc, log = _yosys(script, work / f"induct_{tag}.log")
    m = re.search(r"Found (\d+) \$equiv cells.*?Of those cells (\d+) are proven and (\d+) are unproven", log, re.S)
    if rc != 0 or not m:
        return False, None, log
    return int(m.group(3)) == 0, int(m.group(3)), log


def _unproven(log, limit=20):
    names = re.findall(r"Unproven \$equiv \S+: (\S+) (\S+)", log)
    return [f"{a} / {b}" for a, b in names[:limit]]


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design", required=True, help="被测顶层（只用来定位源文件集合）")
    ap.add_argument("--top", required=True, help="要比的模块名（顶层或任何子模块）")
    ap.add_argument("--gold-ref", required=True, help="改前的提交")
    ap.add_argument("--gate-ref", default=WORKTREE, help="改后的提交；默认 WORKTREE（当前工作区，含未提交改动）")
    ap.add_argument("--gate-top", help="改后的模块名（模块改了名时用，直接走归纳）")
    ap.add_argument("-p", "--param", action="append", default=[], metavar="NAME=VALUE", help="两侧同样 chparam，可重复")
    ap.add_argument("--seq", type=int, default=8, help="equiv_simple / equiv_induct 的拍数（默认 8）")
    ap.add_argument("--mode", choices=("auto", "text", "induct"), default="auto")
    ap.add_argument("--repo", default=".", help="仓库目录（默认当前目录）")
    ap.add_argument("--keep", action="store_true", help="保留工作目录（打印路径），便于看 yosys 日志")
    return ap.parse_args(argv)


def run(a):
    repo = Path(a.repo).resolve()
    params = {}
    for kv in a.param:
        if "=" not in kv:
            raise UsageError(f"-p {kv} 要写成 NAME=VALUE")
        k, v = kv.split("=", 1)
        params[k] = v
    gate_top = a.gate_top or a.top
    with tempfile.TemporaryDirectory(prefix="rev_equiv_") as td:
        work = Path(tempfile.mkdtemp(prefix="rev_equiv_keep_")) if a.keep else Path(td)
        if a.keep:
            print(f"work: {work}")
        export(repo, a.gold_ref, work / "gold")
        export(repo, a.gate_ref, work / "gate")
        gs, ts = sources(a.design, work / "gold"), sources(a.design, work / "gate")
        print(f"gold {a.gold_ref}：{len(gs)} 个源文件；gate {a.gate_ref}：{len(ts)} 个源文件；模块 {a.top}"
              + (f" → {gate_top}" if gate_top != a.top else "") + (f"；参数 {params}" if params else ""))
        level = None
        if a.mode in ("auto", "text") and gate_top == a.top:
            same = text_dump(gs, a.top, params, work / "gold.il", work) == \
                text_dump(ts, a.top, params, work / "gate.il", work)
            print(f"text: {'相同' if same else '不同'}（写法规整后的 RTLIL 逐字比）")
            if same:
                level = "text"
            elif a.mode == "text":
                print("结论 DIFF(text)：规整后的网表不同；要判时序等价用 --mode induct")
                return EXIT_DIFF
        if level is None:
            ok, un, log = induct((gs, a.top, params), (gs, a.top, params), a.seq, work, "self")
            print(f"self: gold ≡ gold {'证明' if ok else f'未证 {un}'}")
            if not ok:
                print(log[-3000:])
                print("结论 SELFCHECK FAIL：归纳证不出 gold ≡ gold，这个方法对该模块不可信，不给结论")
                return EXIT_SELFCHECK
            ok, un, log = induct((gs, a.top, params), (ts, gate_top, params), a.seq, work, "main")
            if not ok:
                print(f"induct: 未证 {un}" if un is not None else "induct: yosys 没有给出 equiv_status")
                miss = _unproven(log)
                if miss:
                    print("  未证的信号（gold / gate，前 20 个；状态对不上时先看这些）：")
                    for m in miss:
                        print(f"    {m}")
                elif un is None:
                    print(log[-3000:])
                print(f"结论 NOT EQUIV(induct, seq={a.seq})：不等或未证")
                return EXIT_DIFF
            level = "induct"
        # 负对照：两级都用 equiv_simple（翻转那一位证不出来就够，省掉归纳）。不比规整文本：包装层展开后
        # 单元编号本来就会变，文本「不同」不说明任何事 —— 掩码为 0、gate 原样时它照样不同，负对照就空了。
        neg, neg_top, flip = negative_wrapper(ts, gate_top, params, work)
        nok, nun, _ = induct((gs, a.top, params), (ts + [neg], neg_top, {}), a.seq, work, "neg",
                             simple_only=True)
        print(f"neg: 翻转 {flip}[0] 后 " + ("仍判等价 —— 判据失效" if nok else f"判不等（equiv_simple 未证 {nun}）"))
        if nok:
            print("结论 SELFCHECK FAIL：负对照没被抓到，不给结论")
            return EXIT_SELFCHECK
        tag = "EQUIV(text)" if level == "text" else f"EQUIV(induct, seq={a.seq})"
        print(f"结论 {tag}：{SCOPE[level].format(seq=a.seq)}")
        return EXIT_EQUIV


def main(argv=None):
    a = parse(argv)
    try:
        return run(a)
    except UsageError as e:
        print(f"rev_equiv: {e}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
