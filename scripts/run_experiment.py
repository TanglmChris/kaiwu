"""Run one experiment end to end: sim -> synth -> sta -> append to results/experiments.jsonl.

    python scripts/run_experiment.py --design CBB_LZD --param DAT_W=32 --param MSB_EN=0 --param SCHEME=0 --liberty <path>

Requires ~/tools/env.sh sourced (yosys/verilator/iverilog/sta on PATH) -- direnv
does this automatically when you're cd'd into the repo.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.flow_fingerprint import corner_liberties, flow_fingerprint
from flow.paths import (cli_params, clock_signal, equiv_enabled, new_experiment_id, resolve_design_root, run_dir,
                        scenarios, validate_params)
from flow.sim.gate_sim import gate_activity
from flow.sim.run_sim import run_sim
from flow.sim.vcd_stats import vcd_stats
from flow.synth.area import breakdown as area_breakdown
from flow.equiv.netlist_equiv import prove_netlist
from flow.sta.run_sta import SAME_PATH_TOL_NS, run_sta, worst_points
from flow.synth.depth import measure as depth_measure
from flow.synth.reference import synthesize as reference_synthesize
from flow.synth.search import search_fmax

EXPERIMENTS_LOG = REPO_ROOT / "results" / "experiments.jsonl"


def git_commit_hash():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except subprocess.CalledProcessError:
        return None


# 扫参是一条条往 jsonl 里追加的：第一条写完工作区就"脏"了。拿它当判据会让扫参在
# 第二条上自锁，所以它自己不算脏。代价是手工改过的 jsonl 抓不到 —— 那是另一类问题
# （红线 2 管的那类），本守卫防的是 `git_commit` 与产出记录的代码对不上。
# 两个默认值都是搬迁前的单文件。正式运行由 scripts/exp.py / scripts/sweep.py 经 flow/records.redirect
# 换成本设计根的 results/<设计根>/experiments.jsonl（内部#422）；本文件在 METRIC_MODULES 里，不改代码只改注释。
LOG_PATH_IN_STATUS = "results/experiments.jsonl"


# 与测量无关、脏了也不拦实验的路径（parallel-worktree「脏树守卫只拦与测量有关的路径」，
# flow-batch-2026-10 的 D6）。**黑名单**：没列在这里的路径一律当作可能影响测量 ——
# 漏列只会多拦，不会少拦；反过来用白名单的话，漏列一个路径就是静默错数。
UNRELATED_PREFIXES = (".claude/", ".agents/", "docs/", "knowledge/", "openspec/")
UNRELATED_FILES = ("AGENTS.md", "CLAUDE.md")


def _unrelated_to_measurement(path):
    return path.startswith(UNRELATED_PREFIXES) or path in UNRELATED_FILES


def _assert_clean_worktree(porcelain):
    """工作区脏着就不写记录。

    记录里的 `git_commit` 来自 `git rev-parse HEAD`。工作区脏着跑出来的记录，
    它的 `git_commit` **不包含产出它的那份代码** —— 而这件事**事后无法从记录里
    识别**：那一行看上去与任何一条正常记录没有区别。CLAUDE.md 的红线 3 说的就是
    这个，而在此之前它没有任何机械判据，全靠人记得。

    2026-09-14 就栽了一次（见 `docs/data-credibility.md`）：为验证一个新设计的 TB
    跑了三次实验，而流程侧的三处改动都还没提交。那三条按红线 2 保留不删。
    """
    dirty, ignored = [], []
    for ln in porcelain.splitlines():
        if not ln.strip():
            continue
        # 改名条目 `R  旧 -> 新` 两侧都要看：从豁免路径挪进 flow/ 也是动了测量
        paths = [p.strip() for p in ln[3:].split(" -> ")]
        if paths == [LOG_PATH_IN_STATUS]:
            continue
        (ignored if all(_unrelated_to_measurement(p) for p in paths) else dirty).append(ln)
    if ignored:
        print("脏树守卫忽略了与测量无关的未提交条目（parallel-worktree，#67）：\n  "
              + "\n  ".join(ignored), file=sys.stderr)
    if not dirty:
        return
    listed = "\n  ".join(dirty)
    raise RuntimeError(
        "工作区不干净，不写实验记录：\n  " + listed + "\n"
        "记录里的 `git_commit` 来自 `git rev-parse HEAD`，工作区脏着跑出来的记录，"
        "它的 `git_commit` 不包含产出它的那份代码 —— 而这件事事后无法从记录里识别"
        "（CLAUDE.md 红线 3 / docs/pitfalls.md 的 P-7）。先提交再跑。")


# 出 PPA 记录之前验证方案必须声明已验证（repo-layout，内部#68 缺口 2）。出自没有验证
# 方案的电路的记录照样出数、照样画进报告，没有任何东西失败。用显式状态行而不按
# 正文猜：各文档写「未验证」的方式不统一，猜会漏判。
VERIFY_STATUS_RE = re.compile(r"^验证状态：(已验证|未验证)(.*)$", re.M)
VERIFY_STATUS_FORMAT = "`验证状态：已验证（<TB 路径或证据>）` 或 `验证状态：未验证`"


def _assert_verified(design):
    """被测顶层的 verify.<顶层>.md 恰好一行状态，且为「已验证」并写了依据。"""
    path = resolve_design_root(design) / f"verify.{design}.md"
    hint = (f"\n状态行整行写成 {VERIFY_STATUS_FORMAT}，一份文档一行"
            "（openspec/specs/repo-layout「出 PPA 记录之前验证方案必须声明已验证」）。")
    if not path.is_file():
        raise RuntimeError(f"{path} 不存在，不写实验记录。" + hint)
    found = VERIFY_STATUS_RE.findall(path.read_text())
    if not found:
        raise RuntimeError(f"{path} 没有状态行，不写实验记录。" + hint)
    if len(found) > 1:
        raise RuntimeError(f"{path} 的状态行不止一行（{len(found)} 行），不写实验记录。" + hint)
    status, rest = found[0]
    if status != "已验证":
        raise RuntimeError(f"{design} 的验证状态是「未验证」（{path}），不写实验记录："
                           "先写好验证方案、跑通 TB，再把状态改为已验证。" + hint)
    if not rest.strip(" \t（）()—-：:"):
        raise RuntimeError(f"{path} 写了「已验证」但没写依据（TB 路径或证据），不写实验记录。" + hint)


def _worktree_status():
    out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True)
    return out.stdout


def _worst_clock_slack(clock_entries):
    """多个时钟域里最差的那个 slack；一个都没测到时返回 None。

    `None` 的域被**跳过**，不参与取最小 —— 它表示"该域没有可分析的路径"，
    不是"该域 slack 很小"。让它参与会把一个缺席变成一个极值。
    反过来，全部都缺席时结果也必须缺席：编一个数出来正是红线 2 要防的那件事
    （`experiment-trust` 的「无法测得的指标必须缺席，不得以合法值代替」）。

    单时钟时这个函数返回的就是那一个域的 slack，与 `worst_slack -max` 逐位相同
    —— 实测口径一致（`tests/test_run_experiment.py::
    test_single_clock_record_keeps_its_scalars_and_gains_one_entry`）。
    """
    measured = [c["slack_ns"] for c in clock_entries if c["slack_ns"] is not None]
    return min(measured) if measured else None


def _liberty_pvt(liberty):
    """库头的标称电压与温度。只读文件开头：这两项在 library 组的头几行里。"""
    import re

    with open(liberty, errors="replace") as f:
        head = f.read(1 << 20)
    pvt = {}
    for key, name in (("nom_voltage", "voltage_v"), ("nom_temperature", "temperature_c")):
        m = re.search(rf"\b{key}\s*:\s*(-?[\d.]+)\s*;", head)
        if m is None:
            raise RuntimeError(f"{liberty} 的库头里没有 {key} —— 角的 PVT 不能缺席也不能猜")
        pvt[name] = float(m.group(1))
    return pvt


# 带门级 VCD 重跑的 TT STA 与档位搜索胜出那一档必须逐字段相同的时序字段：同一份网表、
# 同一个 tcl 模板，带不带 VCD 只差 read_vcd / report_power 两行（gate-level-activity 的 F3）
POWER_RERUN_TIMING_KEYS = ("clock_period_ns", "register_count", "clocks", "slack_ns",
                           "hold_slack_ns", "critical_path_delay_ns", "critical_path_stages",
                           "fmax_mhz")


REFERENCE_DEPTH_BUDGET = 30     # 参考网表的 depth 预算：docs/toolchain.md「时序验收」的验收值


def _reference(design, params, liberty, period_ns, corner_libs, experiment_id, delay_target_ps):
    rs = reference_synthesize(design, params, liberty, out_dir=run_dir(experiment_id, "synth_reference"),
                              delay_target_ps=delay_target_ps)
    tied = set(rs["case"])
    if equiv_enabled(design):
        status, _, log = prove_netlist(design, params, rs["netlist_path"], liberty, tie=rs["case"])
    else:
        status = "SKIPPED"       # 设计声明不做等价（equiv-optional，内部#232）：照常量、照常报数，标「未经等价验证」
    if status not in ("PROVED", "SKIPPED"):
        # D10（内部#202）：没证过等价的参考网表不报数；正式记录照写，reference 只留结论与证明日志
        log_path = run_dir(experiment_id, "equiv_reference") / "equiv.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(log)
        print(f"# 参考网表与接了常数的 RTL 等价证明不是 PROVED（{status}），reference 只记结论，不报数：{log_path}")
        return {"scenario": rs["scenario"], "case": rs["case"], "delay_target_ps": rs["delay_target_ps"],
                "equiv": status, "equiv_log_path": str(log_path)}
    per = {}
    for corner, lib in (("TT", liberty), *corner_libs.items()):
        sub = "sta_reference" + ("" if corner == "TT" else f"_{corner}")
        r = run_sta(design, rs["netlist_path"], str(lib), vcd=None, period_ns=period_ns,
                    out_dir=run_dir(experiment_id, sub), tied=tied)
        start, end = worst_points(r["checks_report"])
        per[corner] = {**_timing_fields(r), "startpoint": start, "endpoint": end}
    d = depth_measure(design, params=params, out_dir=run_dir(experiment_id, "depth_reference"),
                      netlist=rs["netlist_path"], budget=REFERENCE_DEPTH_BUDGET, tied=tied)
    return {
        "scenario": rs["scenario"],
        "case": rs["case"],
        "delay_target_ps": rs["delay_target_ps"],
        "synth": {"cell_count": rs["cell_count"], "area_um2": rs["area_um2"],
                  "area_breakdown": area_breakdown(design, rs["stats_path"], liberty)},
        "sta": {**per.pop("TT"), "corners": per},
        "depth": {"stages": d["stages"], "budget": REFERENCE_DEPTH_BUDGET,
                  "over_budget_count": d["over_budget"]["count"]},
        "equiv": status,
    }


def _timing_fields(r):
    return {k: r[k] for k in ("clocks", "slack_ns", "critical_path_delay_ns", "critical_path_stages",
                              "fmax_mhz", "fmax_method")}


def _assert_scenario_within_main(name, corner, scen, main):
    """定值只会剪掉路径：场景的关键路径延时大于主字段同角的值，说明约束或网表不是同一份（sta-scenarios D4）。"""
    d, m = scen["critical_path_delay_ns"], main["critical_path_delay_ns"]
    if d is not None and m is not None and d > m + SAME_PATH_TOL_NS:
        raise RuntimeError(f"验收场景 {name} 在 {corner} 的关键路径延时 {d:.6f} ns 大于不定值的 {m:.6f} ns："
                           "定值只会剪掉路径，这说明两次 STA 不是同一份约束或网表，不写记录")


def _assert_same_timing(searched, rerun):
    diff = [k for k in POWER_RERUN_TIMING_KEYS if searched[k] != rerun[k]]
    if diff:
        raise RuntimeError(
            "用门级 VCD 重跑的 TT STA 与档位搜索胜出那一档时序不同："
            + "，".join(f"{k} {searched[k]!r} → {rerun[k]!r}" for k in diff)
            + "。同一份网表、同一个 tcl 模板不该如此 —— 记录的功耗与时序会描述不同的电路，不写记录。")


def _assert_internal_annotation(sta_result, where, cell_count):
    """交的是门级 VCD，活动率就必须标到网表内部；只标到端口说明层次名没对上。

    零单元网表除外（内部#86）：它没有内部节点（例如 `assign o_bin = i_oh[1];`），
    只标到端口就是完整反标，记录如实写 `scope = ports`。
    """
    ann = sta_result["activity_annotation"]
    if ann is not None and ann["scope"] == "ports" and cell_count == 0:
        return
    if ann is None or ann["scope"] != "internal":
        raise RuntimeError(
            f"{where}：交给 STA 的是门级 VCD，活动率却没有标到网表内部（{ann}）。"
            "门级 VCD 的层次名应与网表引脚逐一对上；只标到端口时内部节点仍靠概率传播，"
            "正是这次要消掉的口径（#65，docs/data-credibility.md 的 D-27）。不写记录。")


def _write_record(experiment_id, design, params, liberty, sim, sim_result, activity, gate_passed,
                  synth_result, search_result, sta_result, corners, scenario_entries, reference_block, area):
    """拼一条记录、追加进 EXPERIMENTS_LOG。正常记录与 RTL 仿真失败的记录（内部#334）共用这一处，
    两种记录的字段名因此一个不差（红线 2：停止写一个字段的做法是让它取 null，字段名照留）。"""
    record = {
        "experiment_id": experiment_id,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_commit": git_commit_hash(),
        # 这次测量出自哪一套流程。git_commit 记的是仓库的版本，不是流程的版本 ——
        # 换 PDK、换 Vt/corner、重新生成合并 liberty 都不改任何 commit，却会让
        # 全部数字整体挪位。跨代的记录不能放在一起比，判据就是这个指纹。
        # 写在这里而不是 synth/sta 段里：它描述的是整条链路，不属于其中某一步。
        "flow": flow_fingerprint(liberty, sim=sim, design=design),
        # `design` 一直是**被测顶层名** —— 在「设计根名 MUST 等于顶层名」成立的
        # 全部历史里根名与顶层名被强制相同，所以它一直同时是两者。收根之后两者
        # 分开，把 `design` 留给顶层可以让 1403 条历史行全部仍然正确，一条都不用
        # 加读法（openspec/specs/experiment-record/spec.md 的「记录必须区分被测
        # 顶层与它所在的设计根」）。新增的是 `design_root`，只增不改（红线 2）。
        "design": design,
        "design_root": resolve_design_root(design).name,
        "params": params,
        "sim": {
            "passed": sim_result["passed"],
            "cycles": activity["cycles"],
            "total_toggles": activity["total_toggles"],
            # 胜出网表的零延时门级仿真（同一个 TB）是否通过；功耗来自它的 VCD。
            # RTL 仿真没过时不跑，为 null。2026-10-03 之前的记录没有这个字段（gate-level-activity）。
            "gate_passed": gate_passed,
        },
        "synth": {
            "cell_count": synth_result["cell_count"],
            "area_um2": synth_result["area_um2"],
            # 这次综合实际读入的源文件集合（名字 + 内容）的摘要。它是一条能改变
            # PPA 的自变量：本仓 内部#50 实测同一个顶层在不同的目录内容下差到 2.5 倍。
            # 缺席这个字段的历史记录一律当作「未知」，不能当作「与某条相同」。
            "sources_sha256": synth_result["sources_sha256"],
            # 胜出的那一档 ABC 延时目标（皮秒）；不加压胜出时为 null。
            # 下面几个数全部来自这一档的网表，不是来自不加压的那一次。
            "delay_target_ps": search_result["delay_target_ps"],
            # 档位搜索里至少一档目标改变了网表。false 时整组目标都没改动网表（浅组合，内部#85），
            # 记录取不加压那一档、fmax_method 为 "analytic"。2026-10-03 之前的记录没有这个字段
            # （那时这种情况报错、不写记录），读作「未知」（D-31）。
            "search_effective": search_result["search_effective"],
            "critical_path_stages": sta_result["critical_path_stages"],
            "critical_path_delay_ns": sta_result["critical_path_delay_ns"],
            # 按层次拆开的面积（area-breakdown，内部#174）：门数单位、时序面积、展开到第 2 级的层次、
            # 存储模型合计。只存测量值；门数、组合面积、扣除存储模型后的面积由报告现算。
            # 2026-10-05 之前的记录没有这个字段。
            "area_breakdown": area,
        },
        "sta": {
            # slack is relative to a period, so the period travels with it --
            # records written before this field existed are all at 5.0 ns and
            # can recover it as slack_ns + critical_path_delay_ns.
            "clock_period_ns": sta_result["clock_period_ns"],
            # 这次网表里的时序单元数，由产出上面这些时序数的**同一次** STA 运行
            # 自己数出来（`all_registers -cells`），不是问综合器要的。
            # 为 0 的记录，其时序字段是被断言过"来自一条真实的 I/O 到 I/O 路径"
            # 的 —— 没有这个字段就只能回头翻 gitignore 的 runs/，或者按参数组合
            # 反推。见 flow/sta/run_sta.py::_assert_timing_came_from_a_real_path。
            "register_count": sta_result["register_count"],
            # 每个时钟域各自的周期与 slack。多时钟设计里一个标量 slack 解释不了
            # 任何东西 —— 读记录的人无从知道它是哪个域的、对着哪个周期。
            # 单时钟设计这里恰好一项，三个既有标量与它一致（口径没有分家）。
            # 某个域一条域内路径都没有时，它的 slack_ns/fmax_mhz 是 null：
            # 填 0 会被读成"刚好卡住"，填周期会被读成"完全空闲"，而
            # "这个时钟被建立过"与"它没有域内路径"是两件都要记下来的事。
            "clocks": sta_result["clocks"],
            "slack_ns": sta_result["slack_ns"],
            # 域内（reg→reg）最差 hold 余量。与 slack_ns 是两个方向的量：
            # slack_ns 是 setup（越大越松），这个是 hold（为负即违例）。
            #
            # 为 null 表示**没有可测的域内路径**，它与 register_count == 0
            # **不是**同一件事：单级流水有触发器，但它们只被「输入端口→reg」与
            # 「reg→输出端口」两类路径触及，而那两类的 min 结果由
            # set_input_delay 0 / set_output_delay 0 决定 —— 是约束里的假设，
            # 不是电路的性质，所以被排除在这个字段之外。当前代 92 条里
            # 29 条是这个形态（PIPE_STAGES=1），35 条零触发器，28 条有域内路径。
            #
            # ⚠️ 这个数来自 TT。hold 的真实判据是快角：看 corners.FF.hold_slack_ns
            # —— TT 的 hold_slack_ns > 0 不等于「hold 没问题」。
            "hold_slack_ns": sta_result["hold_slack_ns"],
            "fmax_mhz": sta_result["fmax_mhz"],
            "fmax_method": sta_result["fmax_method"],
            "dynamic_power_w": sta_result["dynamic_power_w"],
            "static_power_w": sta_result["static_power_w"],
            # 动态功耗的活动率反标到了哪一层：{pins, port_bits, scope}。scope 为 "ports"
            # 时内部节点的活动率是 OpenSTA 按概率传播的，看不到毛刺与相关性，结构之间的
            # 动态功耗排名不能当结论用（内部#65，docs/data-credibility.md 的 D-27）。
            # 2026-10-01 之前的记录没有这个字段，读作「未知」。gate-level-activity 起
            # 功耗来自门级 VCD，这里恒为 "internal"（D-30）；门级仿真没过时为 null。
            "activity_annotation": sta_result["activity_annotation"],
            # 同一份网表在 SS / FF 的结果。上面的字段**都是 TT 的**，含义不变；TT 不重复
            # 进这里。主库推不出兄弟角时为 {}。2026-09-27 之前的记录没有这个字段。
            "corners": corners,
            # 每个验收场景（params.yaml 的 sta.scenarios）把静态输入定值后的时序，TT 在本层、SS / FF 在 corners。
            # fmax 是这份网表在该场景下的关键路径倒数（analytic）。上面的主字段不定值，即各场景最坏。
            # 未声明场景为 []；2026-10-05 之前的记录没有这个字段（sta-scenarios）。
            "scenarios": scenario_entries,
        },
        "ref_metrics": None,
        # 参考口径（配置端口按目标配置接成常数、跨层次优化、保层级，reference-ppa）。没开 REFERENCE 为 null；
        # 2026-10-05 之前的记录没有这个字段。与正式口径不可混比：读法见 docs/data-credibility.md。
        "reference": reference_block,
    }

    EXPERIMENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPERIMENTS_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")

    return record


class _NullResult(dict):
    """RTL 仿真失败时代替综合 / 搜档 / STA 的结果：取任何键都是 None，构造时给的键除外。"""
    def __getitem__(self, key):
        return self.get(key)


def _sources_sha256(design):
    """读入集合摘要，与正常记录的 synth.sources_sha256 同一个函数算出（flow/synth/synth.py）。"""
    from flow.synth.synth import read_set_digest, source_files
    return read_set_digest(design, source_files(design))


def run_experiment(design, params, liberty, sim="icarus", period_ns=5.0, reference=False):
    # 工作区先查 —— 放在跑任何工具之前：一次扫参十几分钟，没理由跑完了才发现
    # 这批记录的 provenance 是错的。
    _assert_clean_worktree(_worktree_status())
    # 验证状态同样在跑任何工具之前查
    _assert_verified(design)
    # 参数名与取值在跑任何工具之前先校验，免得错的组合白跑十几分钟
    params = validate_params(design, params)
    # 兄弟角的库也在跑工具之前查：缺一份要在十几分钟之前就知道，不是之后
    corner_libs = corner_liberties(liberty)
    # id 先生成，三段流程的原始产物都落进同一个 runs/<experiment_id>/
    experiment_id = new_experiment_id(design, params)

    sim_result = run_sim(design, params, sim=sim, out_dir=run_dir(experiment_id, "sim"))
    sim_passed = sim_result["passed"]
    vcd_path = sim_result["vcd_path"]

    if not sim_passed:
        # RTL 仿真失败（内部#334，用户 2026-10-18 定）：后面测的是一份错误电路的 PPA，白跑几分钟到几十分钟
        # （内部#304 实撞）。立即停，写一条失败记录：synth / sta 的字段名照留、取值 null，只有读入集合摘要
        # 照写（不用综合就能算，扫参的两个跳过开关按它匹配）。
        null = _NullResult()
        return _write_record(experiment_id, design, params, liberty, sim, sim_result,
                             {"total_toggles": None, "cycles": None}, None,
                             _NullResult(sources_sha256=_sources_sha256(design)), null, null,
                             None, None, None, None)

    if sim_passed and vcd_path is None:
        raise RuntimeError(
            f"仿真通过但未产出 VCD（{sim_result['build_dir']}）。功耗必须由 VCD 反标算得，"
            "拿不到活动率就无法给出可信的功耗，这里不继续。"
            "检查 tb 是否开了波形转储、fst2vcd 是否在 PATH 里。"
        )

    if sim_passed:
        activity = vcd_stats(vcd_path, clock_signal(design))
    else:
        activity = {"total_toggles": None, "cycles": None}

    # 综合不是跑一次，是在一组 ABC 延时目标上各跑一次取最好者（flow/synth/search.py）。
    # 不加压的那一次只是阶梯里的一档 —— 它常常不是最好的那一档。
    #
    # 各档的 STA 不读 VCD：pick_best 不看功耗，功耗只对胜出的那份网表算（下面）。
    search_result = search_fmax(
        design,
        params,
        liberty,
        vcd=None,
        period_ns=period_ns,
        out_dir=run_dir(experiment_id),
    )
    synth_result = search_result["synth"]
    sta_result = search_result["sta"]

    # 功耗的活动率来自胜出网表的零延时门级仿真（gate-level-activity，内部#65）：RTL 仿真的
    # VCD 只对得上网表端口，内部节点靠 OpenSTA 按概率传播，看不到相关性（D-27）。
    # 仿真没过就不拿它的活动率算功耗：那份 VCD 描述的是一次错误的行为，据此算出的功耗
    # 是垃圾 —— 门级没过就不交 VCD，功耗为 null，时序照常测。RTL 仿真没过的到不了这里（上面已停，内部#334）。
    gate_passed, power_vcd = None, None
    if sim_passed:
        gate = gate_activity(design, params, synth_result["netlist_path"],
                             run_dir(experiment_id, "sim_gate"))
        gate_passed = gate["passed"]
        if gate_passed:
            if gate["vcd_path"] is None:
                raise RuntimeError(f"门级仿真通过但未产出 VCD（{run_dir(experiment_id, 'sim_gate')}）。"
                                   "功耗必须由 VCD 反标算得，这里不继续。")
            power_vcd = gate["vcd_path"]
    if power_vcd is not None:
        rerun = run_sta(design, synth_result["netlist_path"], liberty, vcd=power_vcd,
                        period_ns=period_ns, out_dir=run_dir(experiment_id, "sta"))
        _assert_same_timing(sta_result, rerun)
        _assert_internal_annotation(rerun, "TT", synth_result["cell_count"])
        sta_result = {**rerun, "fmax_method": sta_result["fmax_method"]}

    # 同一份网表（TT 选出来的那份）在 SS / FF 各测一次，同一份门级 VCD、同一个 run_sta ——
    # 三角的差别只应来自库（add-ss-ff-corner-sta 的 D4）。综合不按角做。
    corners = {}
    for corner, lib in corner_libs.items():
        r = run_sta(design, synth_result["netlist_path"], str(lib),
                    vcd=power_vcd, period_ns=period_ns,
                    out_dir=run_dir(experiment_id, f"sta_{corner}"))
        if power_vcd is not None:
            _assert_internal_annotation(r, corner, synth_result["cell_count"])
        corners[corner] = {
            # 每角自报 PVT：ASAP7 的 SS 在 100 °C、FF 在 0 °C，静态功耗跟温度走 ——
            # 不带温度，「SS 漏电是 TT 的十几倍」就会被读成「慢角漏电大」
            "pvt": _liberty_pvt(lib),
            "clocks": r["clocks"],
            "slack_ns": r["slack_ns"],
            "hold_slack_ns": r["hold_slack_ns"],
            "critical_path_delay_ns": r["critical_path_delay_ns"],
            "critical_path_stages": r["critical_path_stages"],
            # analytic：这份网表在该角下的关键路径倒数。TT 的 sta.fmax_mhz 是在一组
            # 综合目标里挑出来的（search:abc-D），口径不同，所以各自报出来
            "fmax_mhz": r["fmax_mhz"],
            "fmax_method": r["fmax_method"],
            "dynamic_power_w": r["dynamic_power_w"],
            "static_power_w": r["static_power_w"],
        }

    # 按验收场景的时序（sta-scenarios，内部#189 后续，用户 2026-10-05 定选项 A）：同一份胜出网表，把场景声明的
    # 静态输入定值，TT 与每个兄弟角各跑一遍。不读 VCD：功耗的活动率来自 TB，与定值无关。主字段不变（各场景最坏）。
    main_by_corner = {"TT": sta_result, **corners}
    scenario_entries = []
    for sc in scenarios(design, params):   # 只量本组合适用的场景（内部#198，sta-scenario-when）
        per = {}
        for corner, lib in (("TT", liberty), *corner_libs.items()):
            sub = f"sta_scen_{sc['name']}" + ("" if corner == "TT" else f"_{corner}")
            r = run_sta(design, synth_result["netlist_path"], str(lib), vcd=None, period_ns=period_ns,
                        out_dir=run_dir(experiment_id, sub), case=sc["case"])
            _assert_scenario_within_main(sc["name"], corner, r, main_by_corner[corner])
            per[corner] = _timing_fields(r)
        scenario_entries.append({"name": sc["name"], "case": sc["case"], "by": sc["by"], "when": sc["when"],
                                 **per.pop("TT"),
                                 "corners": per})

    # 参考口径（reference-ppa，内部#202，用户 2026-10-05 定「两种口径都报」）：按需开（make exp REFERENCE=1）。
    # 同一份 RTL、同一组参数、正式口径胜出的那一档延时目标，只差「按唯一适用场景的 case 接常数 + 跨层次优化」。
    reference_block = None
    if reference:
        reference_block = _reference(design, params, liberty, period_ns, corner_libs, experiment_id,
                                     search_result["delay_target_ps"])

    return _write_record(experiment_id, design, params, liberty, sim, sim_result, activity, gate_passed,
                         synth_result, search_result, sta_result, corners, scenario_entries, reference_block,
                         area_breakdown(design, synth_result["stats_path"], liberty))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="RTL 参数取值，可重复；名字必须在设计的 params.yaml 里声明过")
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--sim", default="icarus", choices=["icarus", "verilator"])
    ap.add_argument("--period-ns", type=float, default=5.0)
    ap.add_argument("--reference", action="store_true",
                    help="另量参考口径（按唯一适用场景的 case 接常数、跨层次优化），写进记录的 reference（#202）")
    args = ap.parse_args()

    record = run_experiment(
        args.design, cli_params(args.param), args.liberty, args.sim, args.period_ns, reference=args.reference
    )
    print(json.dumps(record, indent=2))
