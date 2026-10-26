"""由实验记录（results/<设计根>/experiments.jsonl）生成某个设计的 REPORT.md。

    python scripts/gen_report.py --design CBB_LZD

这是一条独立命令。run_experiment.py / sweep.py 都不会调它——报告刷新绝不能是
实验执行的副作用，否则扫参会把工作区弄脏，后续记录的 git_commit provenance
就不可信了（见 CLAUDE.md「记录实验前先提交」）。

输出必须逐字节可复现：不写时间戳，行序按参数稳定排序，浮点固定位数。
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.flow_fingerprint import (generation_label, latest_generation,
                                   split_by_generation)
from flow import records as record_store
from flow.paths import load_params_spec, resolve_design_root


MISSING = "—"

# (列名, 取值函数, 格式化)。列的选择见 design.md D13。
METRIC_COLUMNS = [
    ("run", lambda r: run_tag(r), "{}"),
    ("area_um2", lambda r: get(r, ("synth", "area_um2")), "{:.4f}"),
    ("cp_delay_ns", lambda r: get(r, ("synth", "critical_path_delay_ns")), "{:.6f}"),
    ("period_ns", lambda r: period_ns(r), "{:.1f}"),
    ("fmax_mhz", lambda r: fmax_mhz(r), "{:.1f}"),
    ("dyn_power_w", lambda r: get(r, ("sta", "dynamic_power_w")), "{:.3e}"),
    ("static_power_w", lambda r: get(r, ("sta", "static_power_w")), "{:.3e}"),
]

# 同一份 TT 网表在 SS / FF 的结果（sta.corners，2026-09-27 起的记录才有，本仓 内部#60 / 内部#61）。
# 角的 fmax **不进**这张表：它是 analytic（TT 网表在该角下的关键路径倒数），与 TT 列的
# search:abc-D 口径不同，并排放会被当成同一个量来排名。
CORNER_COLUMNS = [
    ("ss_cp_delay_ns", lambda r: get(r, ("sta", "corners", "SS", "critical_path_delay_ns")), "{:.6f}"),
    ("ss_slack_ns", lambda r: get(r, ("sta", "corners", "SS", "slack_ns")), "{:.6f}"),
    ("ff_hold_ns", lambda r: get(r, ("sta", "corners", "FF", "hold_slack_ns")), "{:.6f}"),
    ("ss_static_w", lambda r: get(r, ("sta", "corners", "SS", "static_power_w")), "{:.3e}"),
    ("ff_static_w", lambda r: get(r, ("sta", "corners", "FF", "static_power_w")), "{:.3e}"),
]

AREA = ("synth", "area_um2")
DELAY = ("synth", "critical_path_delay_ns")

ROLES = ("microarch", "scale")


def param_role(design, name, spec):
    """该参数改的是实现方式还是功能本身。`sweep: false` 的返回 None。

    判据一句话：**换一个取值之后，这个电路做的活是不是一样多？**
    一样多是 `microarch`（同一条 Pareto 前沿上比它们有意义），
    不一样多是 `scale`（比绝对面积是同义反复）。

    **没有默认值，漏了就报错。** 默认成 `microarch` 会让一个规模旋钮静默地
    混进前沿，产出一张看起来完全正常的表 —— 本仓 `ADDER32` 的 `WIDTH` 就是
    这么坏了很久没被发现的（内部#44）。与本仓 D-1（Annotated 0 不报错）同形：
    跑通了、有输出、没人问输出是不是在回答一个有意义的问题。

    ⚠️ **这个函数必须留在 gen_report.py。** 把它放到 `load_params_spec` 旁边
    （`flow/paths.py`）是最自然的写法，也是最贵的：那个文件在
    `flow_fingerprint.METRIC_MODULES` 里，动它会换代，当前全部记录要重跑。
    本文件被明确排除在指纹之外（见 flow_fingerprint.py 的注释）。
    """
    if spec.get("sweep", True) is False:
        return None                     # 不进叉乘，就不会出现在前沿里
    role = spec.get("role")
    if role is None:
        raise ValueError(
            f"{design} 的扫参维度 {name} 没有声明 role。"
            f"合法取值：{' / '.join(ROLES)}。"
            "microarch = 同一功能的不同实现（同一条 Pareto 前沿）；"
            "scale = 改的是功能本身（必须分组）。"
            "没有默认值是有意的：默认会让规模旋钮静默混进前沿。")
    if role not in ROLES:
        raise ValueError(
            f"{design} 的 {name} 声明了 role={role!r}，"
            f"而合法取值只有：{' / '.join(ROLES)}。")
    return role


def scale_params(design, records):
    """该设计出现在记录里、且 role 为 scale 的参数名，已排序。"""
    spec = load_params_spec(design)
    present = param_names(records)
    return sorted(n for n in present
                  if n in spec and param_role(design, n, spec[n]) == "scale")


def microarch_params(design, records):
    """同上，role 为 microarch 的那些。"""
    spec = load_params_spec(design)
    present = param_names(records)
    return sorted(n for n in present
                  if n in spec and param_role(design, n, spec[n]) == "microarch")


def run_tag(record):
    """experiment_id 的末 8 位十六进制，用来区分同一参数组合的多次测量。

    取后缀而不是全串：前缀是设计名和参数值，在表里已经有专门的列，是冗余的。
    """
    eid = record.get("experiment_id")
    return eid.rsplit("-", 1)[-1] if eid else None


def period_ns(record):
    """本次 slack 是在哪个周期下测的。

    2026-09-05 之前的记录没有 clock_period_ns 字段，但 period = slack + 关键路径
    延时是恒等式，可以精确反推——这里推导而不是回填，历史记录一个字节都不动。
    """
    p = get(record, ("sta", "clock_period_ns"))
    if p is not None:
        return p
    slack, delay = get(record, ("sta", "slack_ns")), get(record, DELAY)
    if slack is None or delay is None:
        return None
    return round(slack + delay, 6)


def fmax_mhz(record):
    """老记录没有 fmax_mhz，但 fmax_method 恒为 analytic，即 1000 / 关键路径延时。"""
    f = get(record, ("sta", "fmax_mhz"))
    if f is not None:
        return f
    delay = get(record, DELAY)
    if not delay:
        return None
    return 1000.0 / delay


def load_records(design, log_path=None):
    """该顶层的记录。`log_path` 为 None 时读全部设计根的记录文件（内部#422，flow/records.py）。"""
    if log_path is not None and not Path(log_path).is_file():
        return []
    return record_store.load(design, path=log_path)


def sort_key(record):
    """按参数排序：数值按数值比，字符串按字面量比，两类之间数值在前。

    不能直接 str() 排——那样 PIPE_STAGES=10 会排在 2 前面。
    """
    params = record.get("params") or {}
    key = []
    for name in sorted(params):
        v = params[name]
        if isinstance(v, bool):
            key.append((1, 0.0, str(v)))
        elif isinstance(v, (int, float)):
            key.append((0, float(v), ""))
        else:
            key.append((1, 0.0, str(v)))
    # 参数相同的记录（同一组合的多次测量）还要有一个稳定的次序，否则
    # 产出会随 experiments.jsonl 的行序变化 —— experiment_id 是唯一且稳定的。
    key.append((2, 0.0, str(record.get("experiment_id") or "")))
    return key


def get(record, path):
    cur = record
    for seg in path:
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def fmt(value, spec):
    if value is None:
        return MISSING
    return spec.format(value)


def param_names(records):
    names = set()
    for r in records:
        names |= set(r.get("params") or {})
    return sorted(names)


def pareto_front(records):
    """面积-延时的非支配集。两个指标都是越小越好。

    任一指标缺失的记录不参与——支配关系无从判断，硬塞进去会得出假结论。
    """
    usable = [
        r for r in records
        if get(r, AREA) is not None and get(r, DELAY) is not None
    ]
    front = []
    seen = set()
    for r in usable:
        a, d = get(r, AREA), get(r, DELAY)
        dominated = any(
            get(o, AREA) <= a and get(o, DELAY) <= d
            and (get(o, AREA) < a or get(o, DELAY) < d)
            for o in usable
        )
        if dominated:
            continue
        # 同一个 (面积, 延时) 点只列一次：重复行不增加信息，只会让读者
        # 误以为存在多个不同的配置。同组合但指标不同的仍然各自参与判断。
        if (a, d) in seen:
            continue
        seen.add((a, d))
        front.append(r)
    return front


def param_labels(design):
    """{参数名: {编号: 名字}}，取自该设计**当前**的 params.yaml（unify-rtl-naming D14）。

    只给人读：记录里的取值不改写，排序、分组、前沿判断仍按编号。
    """
    return {n: s["labels"] for n, s in load_params_spec(design).items()
            if isinstance(s, dict) and s.get("labels")}


def cell(value, labels):
    """结构枚举显示成「编号 (名字)」。字符串取值（分界之前的记录）与 labels 里
    没有的编号原样显示 —— 名字是今天的 params.yaml 给的，不替历史记录猜。"""
    if isinstance(value, int) and not isinstance(value, bool) and value in (labels or {}):
        return f"{value} ({labels[value]})"
    return str(value)


def table(records, names, columns, labels=None):
    labels = labels or {}
    header = names + [c[0] for c in columns]
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for r in records:
        params = r.get("params") or {}
        cells = [cell(params.get(n, MISSING), labels.get(n)) for n in names]
        cells += [fmt(getter(r), spec) for _, getter, spec in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def generation_summary(groups, limit=3):
    """把 {代: [记录…]} 说成一句话。

    代数多的时候不逐个列 —— ADDER32 有 8 个历史代，全列出来那一行会长到没人读，
    读者真正要的是"有多少条被排除了、最近的一代是哪个"。
    """
    items = list(groups.items())
    if len(items) <= limit:
        return "、".join(f"{generation_label(k)}: {len(v)} 条" for k, v in items)
    k, v = items[-1]
    return (f"{len(items)} 个流程代，最近的一个是 {generation_label(k)}: {len(v)} 条")


def front_sections(design, records, names):
    """面积-延时前沿。按 `role: scale` 的参数取值分组，每组一节。

    支配关系 MUST 只在同一组规模内判断。把规模不同的点放进同一条前沿，
    得到的不是取舍而是同义反复：做的活少的那档必然又小又快，于是前沿永远
    由最小的那档独占（本仓 内部#44，一个设计的前沿曾三行全是最小那档）。
    这与"报告必须限定在单一流程代内"是同一个形状的错误 —— 那条防的是拿不同
    流程的点互相支配，这条防的是拿不同功能规模的点互相支配。

    没有任何 microarch 维度时**不印前沿**：分组之后每组只剩一个点，那样的
    "前沿"每张都是单行表，印出来比不印更误导 —— 它看起来像一个结论，
    实际上只是把每条记录各抄了一遍。
    """
    cols = [c for c in METRIC_COLUMNS[:3] if c[0] != "run"]
    labels = param_labels(design)
    scale = scale_params(design, records)
    micro = microarch_params(design, records)

    if scale and not micro:
        return ["", "## 面积-延时 Pareto 前沿", "",
                "**本设计没有微架构维度，无取舍可言。** 它的扫参维度 "
                + "、".join(f"`{n}`" for n in scale)
                + " 全部是规模旋钮（`role: scale`，见 `params.yaml`），"
                "按规模分组之后每组只剩一个点 —— 那样的前沿只是把上表每行"
                "各抄一遍，不构成任何取舍。全部数字见上表。"]

    if not scale:
        front = sorted(pareto_front(records), key=sort_key)
        body = (table(front, names, cols, labels) if front
                else ["没有可比较的记录（面积或关键路径延时缺失）。"])
        return ["", "## 面积-延时 Pareto 前沿", ""] + body

    lines = []
    groups = {}
    for r in records:
        key = tuple((r.get("params") or {}).get(n) for n in scale)
        groups.setdefault(key, []).append(r)
    for key in sorted(groups, key=lambda k: tuple(
            (v is None, v) for v in k)):
        # 取值为 None 的那一组是**该参数存在之前**的记录（例如某个设计
        # 在 内部#11 参数化之前的 3 条，见 docs/data-credibility.md 的 D-15）。
        # 把它们单独成组比塞进某一档更对：它们跑的是另一份 RTL。
        label = ", ".join(
            f"{n} = {v}" if v is not None else f"{n} 未记录 —— 该参数存在之前的记录"
            for n, v in zip(scale, key))
        lines += ["", f"## 面积-延时 Pareto 前沿（{label}）", ""]
        front = sorted(pareto_front(groups[key]), key=sort_key)
        lines += (table(front, names, cols, labels) if front
                  else ["没有可比较的记录（面积或关键路径延时缺失）。"])
    return lines


def read_set_key(record):
    """这条记录读了哪组源文件。缺 `synth.sources_sha256` 的一律归入同一个「未知」桶。

    为什么未知要**合成一桶**而不是一行一桶：1403 条历史行全部缺这个字段
    （红线 2 不许回填）。一行一桶等于把整份历史报告拆成一行一张表 ——
    那不是谨慎，是把报告弄没了。而未知**不与任何已知合桶**，因为那等于替它们
    断言「读的是同一组文件」，谁也不知道（experiment-record 的
    「读到一条没有源文件摘要的历史记录」）。
    """
    return (record.get("synth") or {}).get("sources_sha256") or "未知"


def split_by_read_set(records):
    """{读入集合: [记录…]}，保持传入顺序。与 `split_by_generation` 同形。"""
    out = {}
    for rec in records:
        out.setdefault(read_set_key(rec), []).append(rec)
    return out


def read_set_label(key):
    """给人看的短标签。"""
    return "读入集合未知" if key == "未知" else f"读入集合 {key.split(':')[-1][:8]}"


def render(design, records, all_generations=False, source="results/<设计根>/experiments.jsonl"):
    """默认只呈现最新一个流程代的记录。

    跨代的点放进同一条 Pareto 前沿会得出**假取舍**：老流程的记录可能在面积轴上
    "支配"新流程的同一个配置（真出现过，见 docs/data-credibility.md 的 D-5），
    读者会以为存在一个根本不存在的配置。

    被排除的记录**必须在报告里说清楚**，不能静默消失 —— 与"测不到的指标必须
    缺席且说明"是同一条口径。
    """
    lines = [f"# {design} 实验报告", ""]
    lines.append(
        f"> 本文件由 `scripts/gen_report.py` 从 `{source}` 生成，"
        f"不要手工编辑。刷新：`python scripts/gen_report.py --design {design}`"
    )
    lines.append("")

    if not records:
        lines += ["尚无实验数据。", ""]
        lines.append(
            f"`{source}` 中没有 `design` 为 `{design}` 的记录。"
        )
        lines.append("")
        return "\n".join(lines)

    by_generation = split_by_generation(records)
    latest = latest_generation(records)
    excluded = []
    if not all_generations:
        excluded = [r for r in records if r not in by_generation[latest]]
        records = by_generation[latest]

    # 同一代里读入集合不同的记录也不可横向比较：`flow` 指纹不含读入集合
    # （它属于被测对象，不是流程），而读入集合实测能把结果改到 2.5 倍（本仓 内部#50）。
    # 与分代同一套做法：留最后一条所属的那一组，其余在报告里点名，不静默丢。
    excluded_read_set = []
    if not all_generations and records:
        by_read_set = split_by_read_set(records)
        keep = read_set_key(records[-1])
        if len(by_read_set) > 1:
            excluded_read_set = [r for r in records if read_set_key(r) != keep]
            records = by_read_set[keep]

    records = sorted(records, key=sort_key)
    names = param_names(records)

    if all_generations and len(by_generation) > 1:
        heading = f"## 全部记录（{len(records)} 条，跨 {len(by_generation)} 个流程代）"
    elif latest is not None:
        heading = f"## 全部记录（{len(records)} 条，{generation_label(latest)}）"
    else:
        heading = f"## 全部记录（{len(records)} 条）"
    lines += [heading, ""]

    if all_generations and len(by_generation) > 1:
        lines.append(
            "⚠️ **这些记录跨越 "
            + str(len(by_generation))
            + " 个流程代**（"
            + generation_summary(by_generation)
            + "）。不同流程代之间并排比较无效 —— 换库、换工具、改综合配方都会让"
            "数字整体挪位。"
        )
        lines.append("")
    elif excluded:
        others = split_by_generation(excluded)
        lines.append(
            "> 另有 "
            + str(len(excluded))
            + " 条属于更早的流程代（"
            + generation_summary(others)
            + "），未参与本表与 Pareto 前沿。全部记录用 `--all-generations`。"
        )
        lines.append("")

    if excluded_read_set:
        groups = split_by_read_set(excluded_read_set)
        lines.append(
            "> 另有 "
            + str(len(excluded_read_set))
            + " 条属于同一流程代、但**综合读入的源文件集合不同**（"
            + "、".join(f"{read_set_label(k)}：{len(v)} 条"
                        for k, v in groups.items())
            + "），未参与本表与 Pareto 前沿。`flow` 指纹不含 `synth.sources_sha256`"
              "（读入集合属于被测对象，不是流程），所以这一层要单独分 —— 实测同一个"
              "顶层只因为目录里多了几个从不被例化的文件，结果就能差 2.5 倍（本仓 #50）。"
        )
        lines.append("")

    # RTL 仿真失败的记录（内部#334 起）没有综合与 STA 的数：不进表与 Pareto 前沿，单列出来，不静默丢
    from scripts.score import is_sim_failure_record
    failed = [r for r in records if is_sim_failure_record(r)]
    if failed:
        records = [r for r in records if not is_sim_failure_record(r)]
        lines.append(f"> 另有 {len(failed)} 组参数 RTL 仿真失败，流程停在仿真、没有综合与 STA 的数，未参与本表与 Pareto 前沿：")
        for r in failed:
            lines.append(f"> - `{r.get('experiment_id')}`：" + "，".join(f"{k}={v}" for k, v in (r.get("params") or {}).items()))
        lines.append("")

    labels = param_labels(design)
    lines += table(records, names, METRIC_COLUMNS, labels)
    lines += front_sections(design, records, names)
    lines += corner_section(records, names, labels)
    lines += area_section(records, names, labels)
    lines += scenario_section(records, names, labels)
    lines += reference_section(records, names, labels)

    lines += ["", "## 测量口径", ""]
    periods = sorted({period_ns(r) for r in records} - {None})
    if len(periods) > 1:
        lines.append(
            "⚠️ **这些记录不在同一个时钟周期下测得**（"
            + "、".join(f"{p:.1f} ns" for p in periods)
            + "）。动态功耗正比于频率，所以直接并排比 `dyn_power_w` 会得出错误"
            "结论，先按 `period_ns` 换算到同一频率再比。面积与关键路径延时不受"
            "周期影响，可以直接比。"
        )
    elif periods:
        lines.append(f"全部记录测于 {periods[0]:.1f} ns 周期。")
    lines.append("")

    derived_period = sum(
        1 for r in records if get(r, ("sta", "clock_period_ns")) is None
    )
    derived_fmax = sum(1 for r in records if get(r, ("sta", "fmax_mhz")) is None)
    if derived_period or derived_fmax:
        lines.append(
            f"其中 {max(derived_period, derived_fmax)} 条是 2026-09-05 之前的旧格式记录。"
            "它们的 `period_ns` 由恒等式 `slack_ns + cp_delay_ns` 推导，"
            "`fmax_mhz` 由 `1000 / cp_delay_ns` 推导（`fmax_method` 恒为 `analytic`）。"
            "推导只发生在生成报告时，历史记录本身未被回填改写。"
        )
        lines.append("")
    lines.append(
        "`fmax_mhz` 是 setup-only、单角（TT）、无时钟不确定度与 OCV 的理想值，"
        "用于横向比架构，不是这个电路真能跑到的频率。"
    )
    lines.append("")
    return "\n".join(lines)


def _pvt_label(records, corner):
    """该角的 PVT，取自记录自报的 `pvt`。各条不一致时全列出来 —— 不替读者挑一个。"""
    seen = sorted({(p["voltage_v"], p["temperature_c"])
                   for r in records
                   for p in [get(r, ("sta", "corners", corner, "pvt"))] if p})
    return "、".join(f"{v:g} V / {t:g} °C" for v, t in seen) or MISSING


def corner_section(records, names, labels=None):
    """SS / FF 两角的表。一条带角的记录都没有时整节不出现（老代记录）。"""
    with_corners = [r for r in records if get(r, ("sta", "corners"))]
    if not with_corners:
        return []
    lines = ["", "## SS / FF 两角（同一份 TT 网表）", ""]
    lines.append(
        f"综合按 TT；同一份网表另在 **SS（{_pvt_label(with_corners, 'SS')}）** 与 "
        f"**FF（{_pvt_label(with_corners, 'FF')}）** 各做一次 STA，同一份 VCD 反标。"
        "上表的数都是 TT 的。")
    lines.append("")
    lines.append(
        "⚠️ 静态功耗跟**温度**走，不跟快慢走：SS 的漏电比 TT 大一个数量级是因为它在 100 °C。"
        "角的 fmax 不列在这里 —— 它是这份 TT 网表在该角下的关键路径倒数（analytic），"
        "与上表 `fmax_mhz` 的搜索口径不同。读法见 `docs/data-credibility.md` 的 D-24。")
    missing = len(records) - len(with_corners)
    if missing:
        lines.append("")
        lines.append(f"> 其中 {missing} 条记录没有角的数（写于 2026-09-27 之前），显示为 {MISSING}。")
    lines.append("")
    lines += table(records, names, CORNER_COLUMNS, labels)
    return lines


AREA_HEADER = "| 层次 | 实例数 | 面积 µm² | 门数 | 单元数 | 时序面积 µm² | 组合面积 µm² | 占比 |"
GLUE_LABEL = "（本层胶合逻辑）"


def _area_row(name, inst, area, seq, cells, unit, total):
    """一行面积表。门数 = 面积 ÷ 门数单位面积；组合 = 面积 − 时序；占比相对顶层（全是现算的导出值）。"""
    return (f"| {name} | {inst} | {area:,.1f} | {area / unit:,.0f} | "
            f"{cells if isinstance(cells, str) else f'{cells:,}'} | {seq:,.1f} | {area - seq:,.1f} | "
            f"{(f'{area / total * 100:.1f}%' if total else '—')} |")   # 零单元网表顶层面积为 0


def area_section(records, names, labels=None):
    """每个配置一张面积拆分表（area-breakdown D5，内部#174）。一条带拆分的记录都没有时整节不出现。"""
    if not any(get(r, ("synth", "area_breakdown")) for r in records):
        return []
    unit = next(get(r, ("synth", "area_breakdown", "gate_unit")) for r in records
                if get(r, ("synth", "area_breakdown")))
    lines = ["", f"## 面积拆分（门数 = 面积 ÷ `{unit['cell']}` {unit['area_um2']:g} µm²）", ""]
    lines.append("层次按综合后保留的模块实例展开到第 2 级，面积与单元数已乘实例数、含下层；每层的胶合逻辑单列一行。"
                 "门数、组合面积、占比都由记录现算；声明了存储模型的设计另有两行：存储模型的合计面积，与扣掉它们之后的逻辑面积。")
    for r in records:
        tag = "、".join(f"{n}={cell(get(r, ('params', n)), (labels or {}).get(n))}" for n in names)
        lines += ["", f"### {tag}（`{run_tag(r)}`）", ""]
        bd = get(r, ("synth", "area_breakdown"))
        if not bd:
            lines.append("记录无面积拆分（area-breakdown 之前写的记录）。")
            continue
        u = bd["gate_unit"]["area_um2"]
        rows = bd["hierarchy"]
        total = rows[0]["area_um2"]
        lines += [AREA_HEADER, "|---|---|---|---|---|---|---|---|"]
        for x in rows:
            name = GLUE_LABEL if x["module"] is None else x["path"].rsplit("/", 1)[-1]
            lines.append(_area_row("　" * x["level"] + name, x["instances"], x["area_um2"],
                                   x["sequential_area_um2"], x["cell_count"], u, total))
        mem = bd.get("memory_models") or {}
        if mem.get("modules"):
            ma, ms = mem["area_um2"], mem["sequential_area_um2"]
            lines.append(_area_row(f"存储模型合计（{'、'.join(mem['modules'])}）", "—", ma, ms, "—", u, total))
            lines.append(_area_row("**扣除存储模型后**", "—", total - ma, rows[0]["sequential_area_um2"] - ms,
                                   "—", u, total))
    return lines


def _scenario(r, name):
    return next((x for x in get(r, ("sta", "scenarios")) or [] if x.get("name") == name), {})


def scenario_section(records, names, labels=None):
    """按验收场景的时序（sta-scenarios D5）。没有记录带非空 sta.scenarios 时整节不出现。"""
    scen = []
    for r in records:
        for x in get(r, ("sta", "scenarios")) or []:
            if x["name"] not in scen:
                scen.append(x["name"])
    if not scen:
        return []
    cols = [("主 TT 延时 ns", lambda r: get(r, ("synth", "critical_path_delay_ns")), "{:.6f}")]
    for n in scen:
        cols += [
            (f"{n} TT 延时 ns", lambda r, n=n: _scenario(r, n).get("critical_path_delay_ns"), "{:.6f}"),
            (f"{n} 级数", lambda r, n=n: _scenario(r, n).get("critical_path_stages"), "{}"),
            (f"{n} fmax MHz", lambda r, n=n: _scenario(r, n).get("fmax_mhz"), "{:.1f}"),
            (f"{n} SS 延时 ns", lambda r, n=n: get(_scenario(r, n), ("corners", "SS", "critical_path_delay_ns")), "{:.6f}"),
            (f"{n} SS slack ns", lambda r, n=n: get(_scenario(r, n), ("corners", "SS", "slack_ns")), "{:.6f}"),
        ]
    lines = ["", "## 按场景的时序（同一份网表，静态输入定值）", ""]
    decl = {}
    for r in records:
        for x in get(r, ("sta", "scenarios")) or []:
            decl.setdefault(x["name"], (x["case"], x["by"]))
    lines.append("、".join(f"**{n}**：{decl[n][0]}（{decl[n][1]}）" for n in scen) + "。")
    lines.append("")
    lines.append("每个场景把 `params.yaml` 声明的静态输入定值（set_case_analysis）后重跑 STA；fmax 是这份网表在该场景下的"
                 "关键路径倒数（analytic）。上表的主字段不定值，是**各场景最坏**（保守）。场景延时不会大于主 TT 延时"
                 "（写记录前断言过）。")
    lines.append("")
    lines += table(records, names, cols, labels)
    return lines


def _diff(a, b):
    return None if a is None or b is None else a - b


def _ref_gates(r):
    area = get(r, ("reference", "synth", "area_um2"))
    unit = get(r, ("reference", "synth", "area_breakdown", "gate_unit", "area_um2"))
    return None if area is None or not unit else area / unit


REFERENCE_COLUMNS = [
    ("场景", lambda r: get(r, ("reference", "scenario")), "{}"),
    ("等价", lambda r: {"PROVED": "已证", "SKIPPED": "未经等价验证"}.get(get(r, ("reference", "equiv"))), "{}"),
    ("参考面积 µm²", lambda r: get(r, ("reference", "synth", "area_um2")), "{:.1f}"),
    ("参考门数", _ref_gates, "{:,.0f}"),
    ("参考时序面积 µm²", lambda r: get(r, ("reference", "synth", "area_breakdown", "sequential_area_um2")), "{:.1f}"),
    ("参考 TT fmax MHz", lambda r: get(r, ("reference", "sta", "fmax_mhz")), "{:.1f}"),
    ("参考级数", lambda r: get(r, ("reference", "sta", "critical_path_stages")), "{}"),
    ("超预算终点", lambda r: get(r, ("reference", "depth", "over_budget_count")), "{}"),
    ("Δ面积 µm²", lambda r: _diff(get(r, ("reference", "synth", "area_um2")), get(r, ("synth", "area_um2"))),
     "{:.1f}"),
    ("Δ时序面积 µm²", lambda r: _diff(get(r, ("reference", "synth", "area_breakdown", "sequential_area_um2")),
                                    get(r, ("synth", "area_breakdown", "sequential_area_um2"))), "{:.1f}"),
    ("Δfmax MHz", lambda r: _diff(get(r, ("reference", "sta", "fmax_mhz")), fmax_mhz(r)), "{:.1f}"),
]


def reference_section(records, names, labels=None):
    """参考口径（reference-ppa D8，内部#202）。没有记录带 reference 时整节不出现；只列带 reference 的配置。"""
    with_ref = [r for r in records if get(r, ("reference",))]
    if not with_ref:
        return []
    lines = ["", "## 参考口径（配置输入接成常数、跨层次优化）", ""]
    lines.append("同一份 RTL、同一组参数、正式口径胜出的那一档延时目标；把该组合唯一适用场景的定值（`reference.case`）"
                 "在顶层接成常数，`synth -hieropt` 跨层次传常数、删掉用不到的逻辑，保层级的模块照保。"
                 "反映 SoC 把这些输入接成常数后的情况，**与上面的正式口径不是同一种数**，不要混比。"
                 "Δ = 参考 − 正式；门数按记录里的 `gate_unit` 折算。参考网表与接了常数的 RTL 等价（`reference.equiv`）。"
                 "读法见 `docs/data-credibility.md`。")
    lines.append("")
    # SKIPPED：设计声明不做等价（equiv-optional，内部#232），照常报数，「等价」列写「未经等价验证」
    proved = [r for r in with_ref if get(r, ("reference", "equiv")) in ("PROVED", "SKIPPED")]
    unproved = [r for r in with_ref if get(r, ("reference", "equiv")) not in ("PROVED", "SKIPPED")]
    if proved:
        lines += table(proved, names, REFERENCE_COLUMNS, labels)
    if unproved:
        # D10（内部#202）：参考网表没证过等价，不报参考值与差值
        if proved:
            lines.append("")
        lines += table(unproved, names, [
            ("场景", lambda r: get(r, ("reference", "scenario")), "{}"),
            ("参考口径", lambda r: f"未证等价（{get(r, ('reference', 'equiv'))}），不报数", "{}"),
        ], labels)
    return lines


def gen_report(design, log_path=None, repo_root=REPO_ROOT,
               all_generations=False):
    """写 `designs/<设计根>/REPORT.<被测顶层>.md`。

    ⚠️ 文件名必须带顶层名，不能是 `REPORT.md`：收根之后
    （本仓 内部#45）一个设计根挂两个被测顶层，两份报告写同一个文件名时**后跑的静默
    覆盖先跑的** —— 没有任何工具会报错，看到的人只会以为「解压侧的报告怎么全是
    压缩侧的数」。
    """
    root = resolve_design_root(design, repo_root)
    out_path = root / f"REPORT.{design}.md"
    source = f"results/{root.name}/{record_store.RECORD_NAME}"
    out_path.write_text(
        render(design, load_records(design, log_path), all_generations, source=source))
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--all-generations", action="store_true",
                    help="不限定流程代，列出全部记录（默认只列最新一代）")
    args = ap.parse_args()
    print(gen_report(args.design, all_generations=args.all_generations))
