"""从实验记录（results/<设计根>/experiments.jsonl）事后算分。

    python scripts/score.py --design CBB_LZD
    python scripts/score.py --design CBB_LZD --config scoring.yaml --all

**只读记录，不跑任何 EDA 工具**：分数是导出量，不进实验记录（design.md 的 D2）。
改权重、换功耗口径只要改 `scoring.yaml` 再跑一次这个脚本，实验一次都不用重跑。

所有评分参数（权重、方向、功耗口径、参考周期、基线）都只允许出现在 `scoring.yaml`
里。**这个文件里不得出现任何具体的权重或方向** —— 目标变了要能只改 YAML 就换掉
评分规则。

归一化基线是配置里写死的一个具体实现，不是批内 min/max：批内归一化会让「往库里
加一条新记录」改掉所有旧记录的分数（D3）。
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow import paths
from flow.flow_fingerprint import (generation_key, generation_label,
                                   latest_generation, split_by_generation)
DEFAULT_CONFIG = REPO_ROOT / "scoring.yaml"
# None = 全部设计根的记录文件 results/<设计根>/experiments.jsonl（内部#422，flow/records.py）；给路径则只读那一个文件
DEFAULT_RECORDS = None

# 动态功耗是唯一需要按口径换算的量（P_dyn ∝ f，design.md 的 F1）。用字段路径认它，
# 而不是用 metric 的名字 —— 名字是配置里可以随便改的标签。
DYNAMIC_POWER_FIELD = "sta.dynamic_power_w"

POWER_BASES = ("iso_frequency", "at_fmax")
DIRECTIONS = ("higher", "lower")


class ScoringError(Exception):
    """配置或记录不足以算分。一律不输出分数，而不是给个凑合的数。"""


class BaselineMissing(ScoringError):
    """配置指定的基线实现在记录里找不到。"""


class BaselineCrossGeneration(ScoringError):
    """基线存在，但只存在于另一个流程代里。

    跨代比值把"流程改了多少"算进了"设计好了多少"里 —— 那是个看不出错的错数，
    所以宁可报错。"""


# --- 配置 -------------------------------------------------------------------
def load_config(path=DEFAULT_CONFIG, baseline_config=None):
    cfg = yaml.safe_load(Path(path).read_text()) or {}

    basis = cfg.get("power_basis")
    if basis not in POWER_BASES:
        raise ScoringError(f"power_basis 必须是 {POWER_BASES} 之一，得到 {basis!r}")
    ref = cfg.get("reference_period_ns")
    if not isinstance(ref, (int, float)) or ref <= 0:
        raise ScoringError(f"reference_period_ns 必须是正数，得到 {ref!r}")

    metrics = cfg.get("metrics") or []
    if not metrics:
        raise ScoringError("metrics 为空，没有可计分的维度")
    for m in metrics:
        for key in ("name", "field", "direction", "weight"):
            if key not in m:
                raise ScoringError(f"metric {m!r} 缺少 {key}")
        if m["direction"] not in DIRECTIONS:
            raise ScoringError(
                f"metric {m['name']} 的 direction 必须是 {DIRECTIONS} 之一")
        if m["weight"] < 0:
            raise ScoringError(f"metric {m['name']} 的 weight 不能为负")
    if sum(m["weight"] for m in metrics) <= 0:
        raise ScoringError("所有维度的权重都是 0，总分无从谈起")

    if "baselines" in cfg:
        raise ScoringError(
            f"{path} 里还有 baselines：基线已改写在各设计根 params.yaml 的 "
            f"tops:<顶层>:score_baseline:（#314）。给已删顶层的历史记录打分，用 "
            f"--baseline-config <旧 scoring.yaml> 显式取旧文件里的基线")
    if baseline_config is not None:
        old = yaml.safe_load(Path(baseline_config).read_text()) or {}
        if not isinstance(old.get("baselines"), dict) or not old["baselines"]:
            raise ScoringError(f"--baseline-config {baseline_config} 里没有 baselines")
        cfg["baselines"] = old["baselines"]
    return cfg


# --- 读记录 -----------------------------------------------------------------
def load_records(path=DEFAULT_RECORDS, design=None):
    from flow import records
    if path is not None and not Path(path).is_file():
        raise FileNotFoundError(path)
    return records.load(design, path=path)


def latest_per_params(records):
    """同一参数组合被测过多次时只留最后一条（jsonl 是追加写的，最后一条最新）。"""
    seen = {}
    for rec in records:
        seen[tuple(sorted((rec.get("params") or {}).items()))] = rec
    return list(seen.values())


def select_generation(records):
    """(最新一代的记录, {更早的代: [记录…]})。

    "最新"= 序列里最后一条记录所属的代（jsonl 追加写）。分代规则本身在
    `flow/flow_fingerprint.py`，这里不重写。
    """
    latest = latest_generation(records)
    if latest is None:
        return [], {}
    selected = [r for r in records if generation_key(r) == latest]
    others = split_by_generation(
        [r for r in records if generation_key(r) != latest])
    return selected, others


def record_period_ns(rec):
    """本次测量所用的时钟周期。

    2026-09-05 之前的记录没有 `sta.clock_period_ns`，但 `run_sta.py` 里
    `critical_path_delay_ns := period − worst_slack` 是恒等式，所以周期可以精确
    反推。**只反推，不回填** —— 历史记录不改写（experiment-record spec）。
    """
    sta = rec.get("sta") or {}
    if sta.get("clock_period_ns") is not None:
        return float(sta["clock_period_ns"])
    slack = sta.get("slack_ns")
    delay = (rec.get("synth") or {}).get("critical_path_delay_ns")
    if slack is None or delay is None:
        raise ScoringError(
            f"{rec.get('experiment_id')}: 既没有 clock_period_ns，也无法由 "
            f"slack_ns + critical_path_delay_ns 反推")
    return float(slack) + float(delay)


def record_design_root(rec):
    """这条记录的设计根名；缺席时回退到它的 `design`。

    1403 条历史行一条都不带 `design_root`（红线 2：只增不改、不回填），
    所以读记录的工具必须有回退 —— 否则新增一个字段就把整个历史读崩了。
    回退到 `design` 是对的：历史上「设计根名 MUST 等于顶层模块名」，两者相同。

    ⚠️ **回退值只能用于分组与展示，不能拿去在文件系统上定位源文件。**
    对当时是独立设计根、后来被并入别处的那些行（两个已删设计，分别 9 条与
    2 条），回退出来的是**旧根名**，而那个目录已不存在。
    照着这个值去 `resolve_design_root()` 会当场报错 —— 报错还算好的，
    真正的风险是有人据此以为那些记录不可用。它们完全可用，只是根搬了家。
    具体哪些行、怎么读，见 `docs/data-credibility.md`。

    显式 `null` 与缺席同义：两者都表示「这一行没说」。
    """
    root = rec.get("design_root")
    return root if root is not None else rec.get("design")


def record_sources_sha256(rec):
    """这次综合读了哪组源文件的摘要；这一行没说就是 `None`（未知）。

    1403 条历史行一条都不带（红线 2：只增字段、不回填），所以取不到值是常态，
    **不是错误**：读到这样的记录既不许报错，也不许跳过它（experiment-record
    的「读到一条没有源文件摘要的历史记录」）。
    """
    return (rec.get("synth") or {}).get("sources_sha256")


def same_source_set(a, b):
    """两条记录**已知**读了同一组源文件时为真。

    ⚠️ 这是「已知相同」，不是「不同」的反义：任一边未知都返回 False，
    两边都未知也返回 False —— 那是「不知道」，而把不知道当成相同，正是
    experiment-record 那条 MUST NOT 要挡的事。

    ⚠️ **不要拿它当分组键。** 用它分组会把 1403 条历史记录（全部未知）
    炸成 1403 个单元素组。分组要用一个把未知归到同一桶的键，
    那是报告侧（`scripts/gen_report.py`）的事，不是本函数的事。
    """
    left, right = record_sources_sha256(a), record_sources_sha256(b)
    return left is not None and left == right


def record_fmax_mhz(rec):
    """性能标量。

    老记录同样没有 `fmax_mhz`：那批记录全部出自 yosys+ABC 这个**非时序驱动**的
    流程，网表与目标周期无关，最小可收敛周期就等于关键路径延时（design.md 的
    D1/F1），所以 `1000 / critical_path_delay_ns` 就是当时该记的值。
    接了时序驱动综合（DC）之后写的记录一定带 `fmax_mhz`，走不到这个分支。
    """
    sta = rec.get("sta") or {}
    if sta.get("fmax_mhz") is not None:
        return float(sta["fmax_mhz"])
    delay = (rec.get("synth") or {}).get("critical_path_delay_ns")
    if not delay:
        raise ScoringError(
            f"{rec.get('experiment_id')}: 既没有 fmax_mhz，也没有 "
            f"critical_path_delay_ns")
    return 1000.0 / float(delay)


def _field(rec, dotted):
    cur = rec
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def metric_value(rec, metric, cfg):
    """一条记录在某个维度上参与打分的值；测不出来时返回 None。"""
    field = metric["field"]
    if field == "sta.fmax_mhz":
        return record_fmax_mhz(rec)
    if field != DYNAMIC_POWER_FIELD:
        return _field(rec, field)

    raw = _field(rec, field)
    if raw is None:          # 仿真没过 → 功耗字段是 null，不能拿来打分
        return None
    # P_dyn ∝ f（F1），所以两种口径由同一份测量数据换算，不用重跑 STA。
    period = record_period_ns(rec)
    if cfg["power_basis"] == "iso_frequency":
        factor = period / float(cfg["reference_period_ns"])
    else:                     # at_fmax：各自跑在自己的 fmax 上
        factor = period * record_fmax_mhz(rec) / 1000.0
    return float(raw) * factor


def is_sim_failure_record(rec):
    """RTL 仿真失败、流程没往下跑的记录（内部#334 起）：sim.passed 为假且没有综合结果。
    2026-10-18 之前的仿真失败记录照样带综合与 STA 的数，不算这一类（data-credibility 的读法）。"""
    return (rec.get("sim") or {}).get("passed") is False and _field(rec, "synth.cell_count") is None


def _values(rec, cfg):
    if is_sim_failure_record(rec):      # 没有可打分的数：每一维都是 None，行排在最后
        return {m["name"]: None for m in cfg["metrics"]}
    return {m["name"]: metric_value(rec, m, cfg) for m in cfg["metrics"]}


def baseline_params(design, cfg):
    """本设计的基线参数（内部#314）：默认取设计根 params.yaml 的 `score_baseline`；
    `--baseline-config` 给了旧配置时（cfg 里有 `baselines`），只取那份旧配置。"""
    if "baselines" in cfg:
        want = cfg["baselines"].get(design)
        if want is None:
            raise BaselineMissing(f"--baseline-config 的 baselines 里没有设计 {design!r} 的基线")
        return dict(want)
    try:
        want = paths.score_baseline(design)
    except paths.DesignRootError as e:
        raise BaselineMissing(
            f"设计 {design!r} 不在任何设计根的 tops: 里（{e}）。给已删顶层的历史记录打分，"
            f"用 --baseline-config <旧 scoring.yaml>") from e
    if want is None:
        raise BaselineMissing(
            f"设计 {design!r} 所在设计根的 params.yaml 没有 score_baseline")
    return want


def find_baseline(records, design, cfg, among=None):
    """在 records 里找配置指定的基线。

    `among` 是未按流程代过滤的全集：基线在当前代里没有、却在别的代里有，
    要报"跨流程代"而不是"不存在" —— 后者会把人引去重跑一个其实已经跑过的组合。
    """
    want = baseline_params(design, cfg)
    hits = [r for r in records if (r.get("params") or {}) == want]
    if not hits:
        elsewhere = [r for r in (among or []) if (r.get("params") or {}) == want]
        if elsewhere:
            where = "、".join(
                generation_label(k) for k in split_by_generation(elsewhere))
            raise BaselineCrossGeneration(
                f"设计 {design!r} 的基线实现 {want} 不在当前流程代里，"
                f"它只存在于 {where}。跨流程代的比值会把「流程改了多少」算进"
                f"「设计好了多少」里，所以这里不给数。三条出路：在当前流程下把这个"
                f"组合跑出来、改 score_baseline 换一个基线、或者显式用 "
                f"--all-generations 承认这次打分是跨代的")
        raise BaselineMissing(
            f"设计 {design!r} 的基线实现 {want} 在实验记录中不存在 —— "
            f"先把这个组合跑出来（make -f flow/Makefile exp DESIGN={design} "
            f"PARAMS=\"{' '.join(f'{k}={v}' for k, v in want.items())}\"），"
            f"或改设计根 params.yaml 的 score_baseline 换一个基线")
    base = hits[-1]           # 同一组合测过多次时以最新一条为准
    missing = [n for n, v in _values(base, cfg).items() if v is None]
    if missing:
        raise ScoringError(
            f"设计 {design!r} 的基线记录 {base.get('experiment_id')} 缺少 "
            f"{missing}，不能当分母")
    return base


def score_rows(records, design, cfg, latest_only=True, all_generations=False):
    """算分。行按总分降序；算不出分的行 score 为 None，排在最后且不被丢弃。

    默认只给**最新一个流程代**的记录打分：跨代的分数把"流程改了多少"混进了
    "设计好了多少"里。`all_generations=True` 是显式的逃生口。
    """
    all_of_design = [r for r in records if r.get("design") == design]
    records = all_of_design
    if not all_generations:
        records, _others = select_generation(all_of_design)
    if latest_only:
        records = latest_per_params(records)
    base_vals = _values(
        find_baseline(records, design, cfg, among=all_of_design), cfg)
    weight_sum = sum(m["weight"] for m in cfg["metrics"])

    rows = []
    for rec in records:
        vals = _values(rec, cfg)
        ratios, missing = {}, []
        for m in cfg["metrics"]:
            v, b = vals[m["name"]], base_vals[m["name"]]
            if v is None or not v:
                missing.append(m["name"])
                ratios[m["name"]] = None
                continue
            # 先化成「越大越好」的比值，再加权求和（D5）
            ratios[m["name"]] = (v / b) if m["direction"] == "higher" else (b / v)
        total = None if missing else sum(
            ratios[m["name"]] * m["weight"] for m in cfg["metrics"]) / weight_sum
        rows.append({
            "experiment_id": rec.get("experiment_id"),
            "params": rec.get("params") or {},
            "clock_period_ns": None if is_sim_failure_record(rec) else record_period_ns(rec),
            "values": vals,
            "ratios": ratios,
            "score": total,
            # 分数算不出来的原因跟着行走，不静默丢行；RTL 仿真失败的记录（内部#334）整行没有数
            "missing": ["RTL 仿真失败"] if is_sim_failure_record(rec) else missing,
            "record": rec,
        })
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))
    return rows


# --- 输出 -------------------------------------------------------------------
def format_table(rows, cfg):
    param_names = []
    for r in rows:
        for n in r["params"]:
            if n not in param_names:
                param_names.append(n)
    names = [m["name"] for m in cfg["metrics"]]
    header = param_names + names + [f"{n}_ratio" for n in names] + ["score"]
    out = ["\t".join(header)]
    for r in rows:
        cells = [str(r["params"].get(n, "")) for n in param_names]
        cells += [_fmt(r["values"][n]) for n in names]
        cells += [_fmt(r["ratios"][n]) for n in names]
        cells.append(_fmt(r["score"]))
        out.append("\t".join(cells))
    return "\n".join(out)


def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design", required=True)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--baseline-config", default=None,
                    help="给已删顶层的历史记录打分：只从这份旧 scoring.yaml 取 baselines（#314）")
    ap.add_argument("--records", default=DEFAULT_RECORDS,
                    help="只读这一个记录文件（默认读全部 results/<设计根>/experiments.jsonl）")
    ap.add_argument("--all", action="store_true",
                    help="每条记录都打分（默认同一参数组合只留最新一条）")
    ap.add_argument("--all-generations", action="store_true",
                    help="不限定流程代（默认只给最新一代打分）")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config, baseline_config=args.baseline_config)
        records = load_records(args.records, args.design)
        rows = score_rows(records, args.design, cfg, latest_only=not args.all,
                          all_generations=args.all_generations)
    except ScoringError as e:
        print(f"打分失败：{e}", file=sys.stderr)
        return 2

    of_design = [r for r in records if r.get("design") == args.design]
    _selected, others = select_generation(of_design)
    generations = split_by_generation(of_design)
    print(f"# design={args.design} power_basis={cfg['power_basis']} "
          f"reference_period_ns={cfg['reference_period_ns']} "
          f"baseline={baseline_params(args.design, cfg)}", file=sys.stderr)
    if args.all_generations and len(generations) > 1:
        print(f"# ⚠️ 本次打分跨 {len(generations)} 个流程代（"
              + "、".join(f"{generation_label(k)}: {len(v)} 条"
                          for k, v in generations.items())
              + "）：这些分数之间不可比", file=sys.stderr)
    elif others:
        excluded = sum(len(v) for v in others.values())
        print(f"# 只给最新一代 {generation_label(latest_generation(of_design))} "
              f"打分；另有 {excluded} 条属于更早的流程代（"
              + "、".join(f"{generation_label(k)}: {len(v)} 条"
                          for k, v in others.items())
              + "），未参与。全部记录用 --all-generations", file=sys.stderr)
    print(format_table(rows, cfg))
    for r in rows:
        if r["missing"]:
            print(f"# {r['experiment_id']}: 缺 {r['missing']}，未计分",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
