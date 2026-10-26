"""Sweep every parameter combination declared in a design's params.yaml
and print a results table.

    python scripts/sweep.py --design CBB_LZD --liberty <path>
    python scripts/sweep.py --design CBB_LZD --liberty <path> --skip-existing
    python scripts/sweep.py --design CBB_LZD --liberty <path> --skip-existing-generation

两个跳过开关的口径不同，**不要合并**，见 sweep() 的 docstring。
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.disk import require_free
from flow.flow_fingerprint import flow_fingerprint
from flow.paths import load_design_config, load_params_spec, run_dir
from flow.param_exclude import ExcludeError, point_params, sweep_combos
from flow import records
from scripts import run_experiment as rx
from scripts import score
from scripts.run_experiment import run_experiment


class SweepError(Exception):
    """这一轮**根本不该这么跑** —— 不是某次测量失败。

    与测量失败分开的理由：测量失败是被测对象的事实（某个组合综合不过），
    调度层的错是「我以为在跑 A，实际在跑 B」，后者不该被当成一条实验结果的属性。
    """


class SweepFailures(RuntimeError):
    """这一轮跑完了，但有组合测量失败（内部#85）。`rows` 是写成了的那些记录，按声明顺序。

    单个组合失败是被测对象的事实，不拖住整轮：其余组合照跑，结尾逐条列出失败的组合，
    再以它退出（非 0）。与 SweepError 不同 —— 那是「这一轮根本不该这么跑」，立刻停。
    """

    def __init__(self, failures, rows):
        self.failures, self.rows = failures, rows
        super().__init__(f"{len(failures)} 个组合失败：" + "；".join(
            f"[{i}] {p}：{why}" for i, p, why in failures))


def _first_line(exc):
    text = str(exc).strip() or type(exc).__name__
    return f"{type(exc).__name__}: {text.splitlines()[0]}"


def combo_key(params):
    return tuple(sorted(params.items()))


def existing_combos(design, log_path=None, fingerprint=None, sources=None):
    """记录中已有的参数组合。

    `fingerprint` 给了就多一维匹配：只算 `flow.fingerprint` 等于它的那些记录，
    即「**本代**已有的」。不给就是「任何一代跑过的」。两种口径各服务一个开关，
    见 sweep()。

    `sources` 给了再多一维：只算 `synth.sources_sha256` 等于它的记录，即「用
    **同一份 RTL** 跑过的」。没有这个字段的记录（2026-09-20 之前）一律不算。
    两个开关都给它：指纹不含 RTL，改了 RTL 不换代，不按它匹配的话改了 RTL 之后
    的重跑会把最该重跑的那批恰好跳过（docs/data-credibility.md 的 D-14）。

    两种口径都**只看记录在不在，不看 `sim.passed`** —— 一条 `passed: false` 的
    记录也是这一代对这个组合的测量结果，RTL 没改，重跑它不会变成 true。
    这条口径要出现在覆盖摘要里，否则读者会以为跳过的都是成功的。
    """
    out = set()
    # log_path 为 None 时读全部设计根的记录文件（内部#422）：顶层换过设计根时，旧根文件里的记录照样算
    for rec in records.load(design, path=log_path):
        if fingerprint is not None:
            if (rec.get("flow") or {}).get("fingerprint") != fingerprint:
                continue
        if sources is not None:
            if (rec.get("synth") or {}).get("sources_sha256") != sources:
                continue
        out.add(combo_key(rec.get("params") or {}))
    return out


def _short(fingerprint):
    return (fingerprint or "").split(":")[-1][:8]


_BOTH_SWITCHES = (
    "--skip-existing 与 --skip-existing-generation 不能同时给。\n"
    "  两者判定「已有」的口径不同，输出却长得一样（都是「跳过 N 条」），"
    "差别只在 N 按什么算出来。让其中一个静默压过另一个，产出的是一个不会报错的误解。\n"
    "  --skip-existing            匹配 (design, params, synth.sources_sha256) —— "
    "任何一代、用同一份 RTL 跑过就算已有；用于续跑中断的**同一轮**扫参\n"
    "  --skip-existing-generation 匹配 (design, params, flow.fingerprint, "
    "synth.sources_sha256) —— 本代、用同一份 RTL 跑过才算已有；用于**换代重跑**的断点续跑\n"
    "  选一个。")


def current_sources_sha256(design):
    """当前 RTL 的读入集合摘要，与记录的 `synth.sources_sha256` 同一个函数算出。

    不另写哈希逻辑：两份会漂移，漂移的方向要么是「永远配不上」（白跑），要么是
    「永远配得上」（改了 RTL 照样跳过 —— 正是这一维要消灭的失效）。
    读入集合要 yosys 探测（有缓存）；只在开了跳过开关时才调它。
    """
    from flow.synth.synth import read_set_digest, source_files
    return read_set_digest(design, source_files(design))


def _warm_source_set_cache(design):
    """并行开跑之前，先**串行**把读入集合的缓存算出来。

    `flow/synth/synth.py` 的 `runs/.source_sets/<design>.json` 是跨实验共享的，
    写法是 `write_text`（先截断再写）。并行时多个 worker 同时算同一个设计，
    就会有人读到写了一半的那份，当场 `JSONDecodeError` —— 这个失效在串行下
    永远不会出现，所以只能在这里挡。算一次之后每个 worker 只读、不写。

    ⚠️ **不能**改 `synth.py` 去做原子写：它在 `METRIC_MODULES` 里，改一个字就
    换代，而换代会让这一轮跑出来的记录与上一代不可自动配对。
    """
    from flow.synth.synth import source_files
    source_files(design)


# 功耗算完之后 VCD 不再被读（内部#172，用户 2026-10-05 定）：大设计的 VCD 每个组合最多约 9 GB，
# 全扫一遍 50–60 GB，10-05 写满过磁盘。删在这里而不是 run_experiment：后者在 METRIC_MODULES 里，
# 改它全仓换代，而删 VCD 不改任何测量值。只删成功的组合，失败的留着排查；单条 make exp 由 scripts/exp.py 同样删（内部#222）。
# 删掉之后 `make sta RUN=<id>` 找不到 VCD 会报错（不会静默退回无活动率的估算，红线 5）。
VCD_STAGES = ("sim", "sim_gate")


def prune_vcd(experiment_id):
    """删掉一次实验在 runs/<id>/{sim,sim_gate}/ 下的 *.vcd，返回删掉的字节数。"""
    freed = 0
    for stage in VCD_STAGES:
        for f in run_dir(experiment_id, stage).glob("*.vcd"):
            freed += f.stat().st_size
            f.unlink()
    return freed


def _run_one(design, params, liberty, sim, period_ns, keep_vcd=False):
    """跑一个组合，连带记下墙钟。返回 (记录, 秒)。成功且没要求保留时删掉它的 VCD（内部#172）。"""
    # 每个组合开跑前查剩余空间（内部#173）：并行时组合是一开始就全部提交的，只在整轮开头查一次挡不住中途写满。
    # 空间不够的组合按测量失败记下，结尾列出，清理后用 SKIP_EXISTING=1 续跑。
    require_free(what="一个组合")
    t0 = time.monotonic()
    rec = run_experiment(design, params, liberty, sim=sim, period_ns=period_ns)
    if not keep_vcd:
        prune_vcd(rec["experiment_id"])
    return rec, time.monotonic() - t0


def sweep(design, liberty, sim="icarus", period_ns=5.0, skip_existing=False,
          skip_existing_generation=False, log_path=None, jobs=1, keep_vcd=False, points=None):
    """跑一个设计声明的全部参数组合，返回本轮跑出来的记录（口径见 _sweep 的 docstring）。

    记录追加到 `log_path`，不给时是本设计根的记录文件 `results/<设计根>/experiments.jsonl`（内部#422）。
    run_experiment.py 在 METRIC_MODULES 里，不改它：这一轮期间用 records.redirect 换它的写入目标，跑完复原。
    """
    log_path = Path(log_path) if log_path is not None else records.log_path(design)
    with records.redirect(rx, log_path):
        return _sweep(design, liberty, sim, period_ns, skip_existing, skip_existing_generation,
                      log_path, jobs, keep_vcd, points)


def _sweep(design, liberty, sim, period_ns, skip_existing, skip_existing_generation,
           log_path, jobs, keep_vcd, points):
    """跑一个设计声明的全部参数组合，返回本轮跑出来的记录。

    两个跳过开关都是显式的，默认都关闭 —— 「我就是想重测一遍」不该变成意外行为。

    `skip_existing` 按参数组合与 RTL 摘要（`synth.sources_sha256`）匹配，**不含流程
    版本**：任何一代、用同一份 RTL 跑过就算已有。它服务的场景是「同一轮扫参跑到
    一半断了，接着跑」。

    `skip_existing_generation` 再多匹配一维流程指纹，只跳过**本代**、同一份 RTL
    已有的。它服务的场景是「改了 METRIC_MODULES 里的文件，全量重跑，跑到一半
    断了」—— 在那个场景里 `skip_existing` 开了等于一条都不补。

    两个开关都按 RTL 摘要匹配：流程指纹不含 RTL，改了 RTL 不换代，只按参数（与
    指纹）匹配的话，改了 RTL 之后的重跑会把最该重跑的那批恰好跳过，覆盖摘要照报
    「已有 N 条」（docs/data-credibility.md 的 D-14，2026-09-16 实撞）。

    `jobs > 1` 时各组合并行跑。并行**不改变任何测量值**：测量路径上没有墙钟依赖
    （全仓唯一的 `time` 用处是记录的 `timestamp`，cocotb 的 `Timer` 是仿真时间），
    每次实验的产物按带 uuid 的 `experiment_id` 分目录，记录追加走 O_APPEND
    （单条最长 1677 字节，一次 write 写完，Linux 上对常规文件是原子的）。
    用线程而不是进程：三个工具都是子进程，等它们的时候 GIL 是放开的。
    并行前会先串行暖一次读入集合缓存，理由见 `_warm_source_set_cache`。

    本代的指纹是**开跑前现算**的，不取「记录里最后一条属于哪一代」：换代之后
    第一次跑时，记录里最后一条还属于上一代，那种取法会把整代判成已有，一条不跑
    且以 0 退出 —— 这个开关能犯的最严重的错误，且完全静默。
    """
    if skip_existing and skip_existing_generation:
        raise SweepError(_BOTH_SWITCHES)

    current_fp = None
    current_src = None
    if skip_existing or skip_existing_generation:
        current_src = current_sources_sha256(design)
    if skip_existing_generation:
        current_fp = flow_fingerprint(liberty, sim=sim, design=design)["fingerprint"]
        done = existing_combos(design, log_path, fingerprint=current_fp,
                               sources=current_src)
        key_desc = (f"(design, params, flow.fingerprint, synth.sources_sha256)，"
                    f"本代 {_short(current_fp)}、RTL {_short(current_src)}"
                    " —— 只看记录在不在，不看 sim.passed")
        scope = "本代同一份 RTL "
    elif skip_existing:
        done = existing_combos(design, log_path, sources=current_src)
        key_desc = (f"(design, params, synth.sources_sha256)，RTL {_short(current_src)}"
                    " —— 不含流程版本，任何一代用同一份 RTL 跑过就算已有；"
                    "只看记录在不在，不看 sim.passed")
        scope = "同一份 RTL "
    else:
        done = set()
        key_desc = "无（全部重跑）"
        scope = "记录中"

    # params.yaml 的 exclude 声明的非法组合不展开（内部#138，param-exclude）；声明了 sweep_points 就只跑点表（内部#214）
    cfg = load_design_config(design)
    combos, n_excl, n_pts = sweep_combos(design, cfg)
    if points:      # POINTS="a b"（内部#332）：只跑点表里点名的这几项，参数原样取自 params.yaml
        combos = [point_params(design, name, cfg) for name in points]
    n = len(combos)
    have = len(done & {combo_key(c) for c in combos})
    excl = (f"（按 POINTS 只跑 {'、'.join(points)}）" if points
            else f"（按 sweep_points 跑 {n_pts} 个点）" if n_pts
            else f"（params.yaml exclude 排除 {n_excl} 个）" if n_excl else "")
    print(f"# sweep {design}: 共 {n} 个组合{excl}，已有 {have} 条，本轮要跑 {n - have} 条")
    print(f"#   跳过口径: {key_desc}")
    print(f"#   并行度 {jobs}" + ("（串行）" if jobs == 1 else ""))

    def _check_fp(rec):
        _check_src(rec)
        if current_fp is None:
            return
        got = (rec.get("flow") or {}).get("fingerprint")
        if got != current_fp:
            # 往下跑的后果：新一代**永远**差着被跳过的那些条，而没有任何迹象。
            raise SweepError(
                f"过滤依据的指纹与刚写出来的记录对不上，这一轮补的不属于"
                f"它以为的那一代：\n  开跑前算的 {current_fp}\n"
                f"  记录里写的 {got}\n"
                "（合并 liberty 被换了？工具被换了？METRIC_MODULES 里的文件"
                "在跑的过程中被改了？）")

    def _check_src(rec):
        if current_src is None:
            return
        got = (rec.get("synth") or {}).get("sources_sha256")
        if got != current_src:
            # 往下跑的后果：这一轮补上的记录属于另一份电路，而「已有」按开跑前的
            # 那份 RTL 数 —— 跳过与补跑对的不是同一个东西。
            raise SweepError(
                f"跳过依据的 RTL 摘要与刚写出来的记录对不上，RTL 在扫参过程中被改了？\n"
                f"  开跑前算的 {current_src}\n  记录里写的 {got}")

    # 序号是**组合序号**、含被跳过的：被杀之后要能直接从日志读出跑到哪了，
    # 而「本轮第 3 条」在开了跳过开关时要读者自己做减法。
    todo = []
    for i, params in enumerate(combos, 1):
        if combo_key(params) in done:
            print(f"[{i}/{n}] {design} {params} 已有记录，跳过")
        else:
            todo.append((i, params))

    indexed = []          # (组合序号, 记录) —— 最后按序号还原成声明顺序
    failures = []         # (组合序号, 参数, 原因首行) —— 单个组合失败不停整轮（内部#85）
    ran = 0
    try:
        if jobs == 1:
            for i, params in todo:
                print(f"[{i}/{n}] {design} {params}", flush=True)
                try:
                    rec, _ = _run_one(design, params, liberty, sim, period_ns, keep_vcd)
                except Exception as e:      # 测量失败：记下，接着跑
                    failures.append((i, params, _first_line(e)))
                    print(f"[{i}/{n}] {design} {params} 失败：{_first_line(e)}", flush=True)
                    continue
                ran += 1
                _check_fp(rec)
                indexed.append((i, rec))
        else:
            _warm_source_set_cache(design)
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futs = {}
                for i, params in todo:
                    futs[pool.submit(_run_one, design, params, liberty,
                                     sim, period_ns, keep_vcd)] = (i, params)
                    # 开跑与完成各打一行：并行日志里「最后一行是第几条」不再等于
                    # 进度，被杀之后只能靠两侧对照才读得出哪些跑完了。
                    print(f"[{i}/{n}] {design} {params} 开跑", flush=True)
                for fut in as_completed(futs):
                    i, params = futs[fut]
                    try:
                        rec, dt = fut.result()
                    except Exception as e:  # 测量失败：记下，接着收其余的
                        failures.append((i, params, _first_line(e)))
                        print(f"[{i}/{n}] {design} {params} 失败：{_first_line(e)}", flush=True)
                        continue
                    ran += 1
                    _check_fp(rec)
                    indexed.append((i, rec))
                    print(f"[{i}/{n}] {design} {params} 完成 ({dt:.1f} s)",
                          flush=True)
    finally:
        # 「跑完了」与「跳过了一大半」在输出上必须可区分，失败路径上也一样 ——
        # 已经跑完的那些是真实产出。
        # 这里**重数一遍记录**而不是 have + ran：算出来的那个数在「某条实验跑了
        # 但没写进记录」时仍然是满的，重数一遍会露出来。
        final = existing_combos(design, log_path, fingerprint=current_fp,
                                sources=current_src)
        got = len(final & {combo_key(c) for c in combos})
        print(f"# sweep {design} 结束: 本轮跑了 {ran} 条，{scope}现有 {got}/{n} 个组合"
              + ("" if jobs == 1 else f"（并行度 {jobs}）"))
    # 按组合序号还原成**声明顺序**：并行下完成先后是随机的，而下游把返回顺序
    # 当稳定的次序基底用，按完成顺序返回会让同一批数据两次跑出不同的表行序。
    rows = [rec for _, rec in sorted(indexed, key=lambda x: x[0])]
    # 档位搜索整组无效的条数单报（search-noop-pass 的 R1）：工具或库一变让所有设计的搜索
    # 失效时，以前当场报错，现在会写出一批 search_effective = false 的记录
    noop = sum(1 for r in rows if (r.get("synth") or {}).get("search_effective") is False)
    if noop:
        print(f"# sweep {design}: 本轮 {noop} 条记录的档位搜索整组无效"
              "（synth.search_effective = false，fmax_method = analytic；D-31）")
    if failures:
        failures.sort(key=lambda x: x[0])
        print(f"# sweep {design}: {len(failures)} 个组合失败：")
        for i, params, why in failures:
            print(f"#   [{i}/{n}] {params}：{why}")
        raise SweepFailures(failures, rows)
    return rows


def scores_by_id(design, log_path=None, config_path=None):
    """{experiment_id: score}。

    分数只有 `scripts/score.py` 一份实现，这里不重算公式。打分要读**全部**记录
    而不只是本次跑出来的行 —— 归一化基线是配置里指定的一个固定实现，它可能根本
    不在本次扫的范围里（比如跳过开关跳过了它）。

    打不了分不该让扫参白跑：扫参的产出是测量数据，分数是事后导出量。所以这里
    吞掉 ScoringError，把原因打到 stderr，score 列留空。
    """
    try:
        cfg = score.load_config(config_path or score.DEFAULT_CONFIG)
        rows = score.score_rows(score.load_records(log_path, design), design, cfg)
    except (score.ScoringError, FileNotFoundError) as e:
        print(f"# 未打分：{e}", file=sys.stderr)
        return {}
    return {r["experiment_id"]: r["score"] for r in rows}


def print_table(rows, design, log_path=None, config_path=None):
    """按分数降序打印。算不出分的行 score 列是 `-`，排在最后而不是被丢掉。"""
    scores = scores_by_id(design, log_path, config_path)
    param_names = list(load_params_spec(design))
    header = param_names + [
        "passed", "cell_count", "area_um2",
        "critical_path_stages", "critical_path_delay_ns", "slack_ns",
        "fmax_mhz", "dynamic_power_w", "static_power_w", "score",
    ]
    print("\t".join(header))
    ordered = sorted(
        rows,
        key=lambda r: (scores.get(r["experiment_id"]) is None,
                       -(scores.get(r["experiment_id"]) or 0.0)))
    for r in ordered:
        s = scores.get(r["experiment_id"])
        vals = [
            *(r["params"][n] for n in param_names),
            r["sim"]["passed"],
            r["synth"]["cell_count"],
            r["synth"]["area_um2"],
            r["synth"]["critical_path_stages"],
            r["synth"]["critical_path_delay_ns"],
            r["sta"]["slack_ns"],
            r["sta"].get("fmax_mhz"),
            r["sta"]["dynamic_power_w"],
            r["sta"]["static_power_w"],
            "-" if s is None else f"{s:.6g}",
        ]
        print("\t".join(str(v) for v in vals))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--sim", default="icarus", choices=["icarus", "verilator"])
    ap.add_argument("--period-ns", type=float, default=5.0)
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="并行跑几个组合（默认 1，串行）。并行不换代也不改数字："
                         "sweep.py 不在 METRIC_MODULES 里，测量路径上没有墙钟依赖")
    ap.add_argument("--config", default=None,
                    help="打分配置（默认仓库根的 scoring.yaml）")
    ap.add_argument("--skip-existing", action="store_true",
                    help="跳过记录中已有的组合，匹配 (design, params, synth.sources_sha256) —— "
                         "不含流程版本，同一份 RTL 跑过就算已有；用于续跑中断的同一轮扫参")
    ap.add_argument("--skip-existing-generation", action="store_true",
                    help="只跳过**本代**已有的组合，匹配 "
                         "(design, params, flow.fingerprint, synth.sources_sha256)；"
                         "用于换代重跑的断点续跑。与 --skip-existing 互斥")
    ap.add_argument("--points", default="",
                    help="只跑 params.yaml 的 sweep_points 里这几个点名（空格分隔，#332）")
    ap.add_argument("--keep-vcd", action="store_true",
                    help="保留每个组合的 RTL / 门级 VCD（默认功耗算完就删，#172）")
    args = ap.parse_args()

    try:
        rows = sweep(args.design, args.liberty, args.sim, args.period_ns,
                     args.skip_existing, args.skip_existing_generation,
                     jobs=args.jobs, keep_vcd=args.keep_vcd, points=args.points.split() or None)
    except (SweepError, ExcludeError) as e:
        print(f"FLOW-ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except SweepFailures as e:
        print_table(e.rows, args.design, config_path=args.config)
        print(f"MEASUREMENT-FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    print_table(rows, args.design, config_path=args.config)
