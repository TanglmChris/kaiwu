"""自检型 SV TB 的分层回归：读设计根 `tb/regress.<顶层>.yaml`，展开、去重、在一个任务池里跑（内部#83 的 A、B）。

    .venv/bin/python3 flow/verify/regress.py --design <顶层> --tier inner      # 内循环
    .venv/bin/python3 flow/verify/regress.py --design <顶层> --tier full -j 4  # 全量：验证侧在发布之后跑（内部#149）
    .venv/bin/python3 flow/verify/regress.py --design <顶层> --tier full --list
    .venv/bin/python3 flow/verify/regress.py --design <顶层> --tier full --sim icarus   # 交叉核对

清单（YAML）：
- `tb`：TB 文件，相对清单所在目录；`top`：仿真顶层模块名；`dut`：被测顶层（取 RTL 闭包，可省）；
- `done` / `pass`：判据正则 —— 输出里最后一行匹配 `done` 的行必须匹配 `pass`；
- `sets`：命名的参数组，每组是若干 {参数: 值} 的列表；
- `groups`：每组 `tiers`（`inner` / `full` 的子集）与 `params`（参数名 → 取值列表，取值写 `$<set>`
  就把那个参数组整组展开），组内取笛卡尔积；
- `runtime`（可省）：运行期参数名，以 `+NAME=值` 传给仿真，不进编译键 —— 编译键相同的作业共用一次编译。

仿真器（`--sim`）默认 Verilator（`verilator --binary --timing`，结构参数 `-G`），可选 Icarus
（`iverilog -P` + `vvp`）。一个大设计的子模块全量两者结论行逐条相同，Verilator 约快 6 倍（内部#83 的 D）；
TB 写法上两点差异：随机数要自己播种（Verilator 的 `$urandom(seed)` 不给后续调用播种）；
Verilator 的 `$finish` 之后同一块里的语句照样执行。

去重键是**补齐 TB 默认值之后**的完整参数（默认值从 TB 的 `parameter` 声明里读）：一组省略 `LANES`、
另一组写 `LANES=2` 而默认值就是 2 时，两者是同一个作业。全部作业进一个线程池，按上次实测时长降序提交
（没有实测的排最前，免得新作业成为尾巴），时长按仿真器分开记在 `runs/regress/<名>/durations.<仿真器>.json`。

并行度默认 4：同机各会话的重活加起来不超过 6（`docs/toolchain.md`「CPU 预算」，内部#359）；`make regress` 外面排队拿 `cpu-heavy`。
不进 `METRIC_MODULES`，不产生实验记录。
"""
import argparse
import itertools
import json
import math
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.disk import KEEP_BUILDS, prune_old, require_free

TIERS = ("inner", "full")
SIMS = ("verilator", "icarus")


def load_manifest(path):
    path = Path(path)
    m = yaml.safe_load(path.read_text()) or {}
    for k in ("tb", "top", "done", "pass"):
        if k not in m:
            raise ValueError(f"{path} 缺 `{k}`")
    m["_path"] = path
    m["_tb"] = path.parent / m["tb"]
    return m


def _split_top_level(text):
    """按不在括号里的逗号切开。"""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def tb_defaults(tb_path):
    """TB 里 `parameter` 声明的 {名字: 默认值文本}。去掉注释后按语句读，一条语句可声明多个。"""
    text = re.sub(r"//[^\n]*", "", Path(tb_path).read_text())
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = {}
    for stmt in re.findall(r"\bparameter\b(.*?);", text, flags=re.S):
        for item in _split_top_level(stmt):
            if "=" not in item:
                continue
            lhs, rhs = item.split("=", 1)
            name = lhs.split()[-1]
            out[name] = rhs.strip()
    return out


def job_key(params):
    return ",".join(f"{k}={params[k]}" for k in sorted(params))


def _axis_values(m, values):
    out = []
    for v in values:
        if isinstance(v, str) and v.startswith("$"):
            name = v[1:]
            if name not in (m.get("sets") or {}):
                raise ValueError(f"清单引用了不存在的参数组 {v}")
            out.extend(m["sets"][name])
        else:
            out.append(v)
    return out


def expand(m, tier, defaults=None):
    """返回 (去重后的作业列表, 去重前的作业数)。作业是 {参数: 值文本}，已补齐 TB 默认值。"""
    if tier not in TIERS:
        raise ValueError(f"tier 只能是 {TIERS}")
    defaults = tb_defaults(m["_tb"]) if defaults is None else defaults
    runtime = set(m.get("runtime") or [])
    jobs, seen, raw = [], set(), 0
    for g in m.get("groups") or []:
        if tier not in g.get("tiers", ()):
            continue
        axes = [_axis_values(m, vals) for vals in (g.get("params") or {}).values()]
        names = list((g.get("params") or {}).keys())
        for combo in itertools.product(*axes):
            raw += 1
            given = {}
            for name, v in zip(names, combo):
                given.update({str(k): vv for k, vv in v.items()} if isinstance(v, dict) else {name: v})
            unknown = sorted(set(given) - set(defaults) - runtime)
            if unknown:
                raise ValueError(f"组 {g.get('name')} 用了 TB 里没有的参数 {unknown}（{m['_tb'].name}）")
            params = {**defaults, **{k: str(v) for k, v in given.items()}}
            key = job_key(params)
            if key not in seen:
                seen.add(key)
                jobs.append(params)
    return jobs, raw


def order(jobs, durations):
    """按上次实测时长降序；没有实测的当作无穷大，排最前。同时长保持原序。"""
    return sorted(jobs, key=lambda j: -durations.get(job_key(j), math.inf))


def load_durations(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _sources(m):
    if not m.get("dut"):
        return [], []
    from flow.paths import include_dirs
    from flow.synth.synth import source_files
    return [str(s) for s in source_files(m["dut"])], [str(d) for d in include_dirs(m["dut"])]


def _build_cmd(sim, top, compile_params, incs, tb, sources, target):
    """编译命令与编译产物（可执行的那个文件）。"""
    if sim == "icarus":
        cmd = ["iverilog", "-g2012", "-s", top, "-o", str(target)]
        cmd += [f"-P{top}.{k}={v}" for k, v in compile_params.items()]
        return cmd + [f"-I{d}" for d in incs] + [str(tb)] + sources, target
    # -j 1：编译与仿真共用同一个线程池的并行度，不再各自开线程
    cmd = ["verilator", "--binary", "--timing", "-j", "1", "--Mdir", str(target), "--top-module", top,
           "-Wno-fatal", "-Wno-lint", "-Wno-style"]
    cmd += [f"-G{k}={v}" for k, v in compile_params.items()]
    return cmd + [f"-I{d}" for d in incs] + [str(tb)] + sources, target / f"V{top}"


def run(manifest_path, tier, jobs_n=4, out_dir=None, durations_path=None, timeout=600, sim="verilator",
        sources=None, incs=None):
    """跑一层。返回 (退出码, 结果列表)；结果是 {params, ok, info, seconds}。

    `sources` / `incs` 给了就用它们代替清单 `dut` 的 RTL 闭包（flow/verify/sigeq.py 用来换成某个提交导出的 RTL，内部#224）。"""
    if sim not in SIMS:
        raise ValueError(f"sim 只能是 {SIMS}")
    m = load_manifest(manifest_path)
    name = m.get("dut") or Path(manifest_path).stem
    base = REPO_ROOT / "runs" / "regress" / name
    # 磁盘护栏（内部#173）：开跑前查剩余空间；每次回归留一份构建，只留最近 KEEP_BUILDS 份（含本次）
    require_free(what="回归")
    if out_dir is None:
        prune_old(base, keep=KEEP_BUILDS - 1)
    out_dir = Path(out_dir) if out_dir else base / time.strftime("%Y%m%d-%H%M%S")
    durations_path = Path(durations_path) if durations_path else base / f"durations.{sim}.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    durations = load_durations(durations_path)
    jobs, raw = expand(m, tier)
    jobs = order(jobs, durations)
    if sources is None:
        sources, incs = _sources(m)
    sources, incs = [str(x) for x in sources], [str(x) for x in (incs or [])]
    runtime = set(m.get("runtime") or [])
    done_re, pass_re = re.compile(m["done"]), re.compile(m["pass"])
    top = m["top"]

    builds, builds_lock = {}, threading.Lock()

    def build(params):
        ckey = job_key({k: v for k, v in params.items() if k not in runtime})
        with builds_lock:
            if ckey not in builds:
                builds[ckey] = {"lock": threading.Lock(), "n": len(builds), "exe": None,
                                "err": None, "done": False}
            b = builds[ckey]
        with b["lock"]:
            if not b["done"]:
                target = out_dir / (f"b{b['n']}.vvp" if sim == "icarus" else f"b{b['n']}")
                cmd, b["exe"] = _build_cmd(sim, top, {k: v for k, v in params.items() if k not in runtime},
                                           incs, m["_tb"], sources, target)
                r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
                if r.returncode != 0 or not b["exe"].is_file():
                    b["err"] = "编译失败：" + (r.stderr or r.stdout)[-400:]
                b["done"] = True
        return b

    def one(params):
        t0 = time.monotonic()
        b = build(params)
        if b["err"]:
            return {"params": params, "ok": False, "info": b["err"], "seconds": time.monotonic() - t0}
        plus = [f"+{k}={v}" for k, v in params.items() if k in runtime]
        try:
            exe = ["vvp", "-n", str(b["exe"])] if sim == "icarus" else [str(b["exe"])]
            r = subprocess.run([*exe, *plus], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=timeout)
            out = r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return {"params": params, "ok": False, "info": f"超时（{timeout} s）",
                    "seconds": time.monotonic() - t0}
        done = [ln for ln in out.splitlines() if done_re.search(ln)]
        if not done:
            info, ok = "没有匹配 done 的结论行（DONE）：" + out[-400:], False
        else:
            info, ok = done[-1], bool(pass_re.search(done[-1]))
        return {"params": params, "ok": ok, "info": info, "seconds": time.monotonic() - t0}

    print(f"# regress {name} {tier}（{sim}）：去重前 {raw}、去重后 {len(jobs)} 个作业，并行度 {jobs_n}，"
          f"产物 {out_dir}", flush=True)
    t0 = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=jobs_n) as pool:
        futs = [pool.submit(one, j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            results.append(r)
            print(f"[{i}/{len(jobs)}] {'ok  ' if r['ok'] else 'FAIL'} {job_key(r['params'])} "
                  f"({r['seconds']:.1f} s)" + ("" if r["ok"] else f"\n    {r['info']}"), flush=True)
    bad = sum(not r["ok"] for r in results)
    durations.update({job_key(r["params"]): round(r["seconds"], 3) for r in results})
    durations_path.parent.mkdir(parents=True, exist_ok=True)
    durations_path.write_text(json.dumps(durations, indent=0, sort_keys=True))
    print(f"# regress 结束：通过 {len(results) - bad}/{len(results)}，编译 {len(builds)} 次，"
          f"用时 {time.monotonic() - t0:.1f} s", flush=True)
    return (1 if bad else 0), results


def manifest_for(design):
    from flow.paths import resolve_design_root
    return resolve_design_root(design) / "tb" / f"regress.{design}.yaml"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design", help="被测顶层；清单取其设计根的 tb/regress.<顶层>.yaml")
    ap.add_argument("--manifest", help="直接给清单路径")
    ap.add_argument("--tier", choices=TIERS, default="inner")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--sim", choices=SIMS, default="verilator", help="仿真器（默认 verilator）")
    ap.add_argument("--timeout", type=float, default=600, help="每个作业的仿真超时（秒）")
    ap.add_argument("--list", action="store_true", help="只列作业（每组展开数、去重前后），不跑")
    a = ap.parse_args(argv)
    if not (a.design or a.manifest):
        ap.error("要给 --design 或 --manifest")
    path = Path(a.manifest) if a.manifest else manifest_for(a.design)
    if a.list:
        m = load_manifest(path)
        defaults = tb_defaults(m["_tb"])
        for g in m.get("groups") or []:
            if a.tier in g.get("tiers", ()):
                one = {**m, "groups": [g]}
                print(f"{g.get('name')}: {expand(one, a.tier, defaults)[1]}")
        jobs, raw = expand(m, a.tier, defaults)
        print(f"# {a.tier}：去重前 {raw}，去重后 {len(jobs)}")
        return 0
    rc, _ = run(path, a.tier, a.jobs, timeout=a.timeout, sim=a.sim)
    return rc


if __name__ == "__main__":
    sys.exit(main())
