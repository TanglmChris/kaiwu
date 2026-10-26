"""`scripts/score.py` 的打分逻辑，用固定 fixture 记录，不碰真实的实验记录。

为什么值得有这个测试：打分是「事后从记录算」的导出量，改权重不重跑实验
（design.md 的 D2）。这条便利的代价是 —— 一旦读记录的规则写错（把老格式记录
当成缺字段、把功耗口径换算方向搞反），产出的分数看上去完全正常，没有任何
工具会报错。所以这里的断言全部拿**手算的期望值**比，不复用 score.py 的
任何中间函数去算期望。

fixture 里的记录是**合成的**，不是从 results/experiments.jsonl 里取的：
真实记录会随重跑而变，拿它当基线断言的测试早晚会因为数据更新而假红。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import scripts.score as score


# --- fixture 记录 -----------------------------------------------------------
# design 一律叫 demo，params 只有一个 K，方便手算。
def _rec(k, *, period, delay, dyn, area, fmax=..., cycles=58):
    sta = {"slack_ns": round(period - delay, 6)}
    if period is not None:
        sta["clock_period_ns"] = period
    if fmax is not ...:
        sta["fmax_mhz"] = fmax
        sta["fmax_method"] = "analytic"
    sta["dynamic_power_w"] = dyn
    sta["static_power_w"] = 1e-9
    return {
        "experiment_id": f"demo-{k}",
        "timestamp": f"2026-09-09T0{k}:00:00+00:00",
        "git_commit": "0" * 40,
        "design": "demo",
        "params": {"K": k},
        "sim": {"passed": True, "cycles": cycles, "total_toggles": 100},
        "synth": {"cell_count": 10, "area_um2": area,
                  "critical_path_stages": 3, "critical_path_delay_ns": delay},
        "sta": sta,
        "ref_metrics": None,
    }


# K=0 基线：5.0 ns 下测，fmax 200 MHz，动态功耗 1e-5 W，面积 100 µm²
BASELINE = _rec(0, period=5.0, delay=5.0, dyn=1e-5, area=100.0, fmax=200.0)

# K=1 老格式：sta 里没有 clock_period_ns / fmax_mhz（2026-09-05 之前的 9 条就是
# 这个形状）。周期必须由 slack_ns + critical_path_delay_ns 推出来 = 5.0。
_OLD = _rec(1, period=5.0, delay=4.0, dyn=1e-5, area=100.0, fmax=...)
_OLD["sta"].pop("clock_period_ns")

# K=2 面积极差、其余与基线相同：权重为 0 的维度不得影响总分
_FAT = _rec(2, period=5.0, delay=5.0, dyn=1e-5, area=10000.0, fmax=200.0)

# K=3 在 2.0 ns 下测、fmax 2000 MHz：用来验功耗口径换算（两个换算因子都不是 1）
_FAST = _rec(3, period=2.0, delay=0.5, dyn=4e-5, area=100.0, fmax=2000.0)

FP_NEW = "sha256:" + "a" * 64
FP_OLD = "sha256:" + "b" * 64


def _with_flow(rec, fingerprint):
    """给 fixture 记录贴一个流程代。真实记录由 flow/flow_fingerprint.py 现算，
    这里只关心"同不同代"，所以直接写死指纹。"""
    rec = json.loads(json.dumps(rec))
    rec["flow"] = {"fingerprint": fingerprint, "yosys": "y", "opensta": "o",
                   "sim": "s", "liberty_sha256": "l",
                   "synth_recipe_sha256": "sy", "sta_recipe_sha256": "st"}
    return rec


# 老流程代的两条。参数取 K=7/K=8，新代里没有这两个组合 —— 这才像真实情况：
# 老记录往往连参数标签都和今天不一样（ADDER32 那 28 条只有两个 key），
# 所以"同参数只留最新一条"那层去重根本盖不住它们，必须靠分代把它们挡在外面。
# 它们排在前面（jsonl 是追加写的，文件序就是时间序）。
OLD_GEN_A = _with_flow(_rec(7, period=5.0, delay=5.0, dyn=1e-4, area=50.0,
                            fmax=200.0), FP_OLD)
OLD_GEN_B = _with_flow(_rec(8, period=5.0, delay=2.5, dyn=1e-4, area=60.0,
                            fmax=400.0), FP_OLD)

RECORDS = [OLD_GEN_A, OLD_GEN_B] + [
    _with_flow(r, FP_NEW) for r in (BASELINE, _OLD, _FAT, _FAST)]

CONFIG = {
    "power_basis": "iso_frequency",
    "reference_period_ns": 5.0,
    "metrics": [
        {"name": "fmax_mhz", "field": "sta.fmax_mhz",
         "direction": "higher", "weight": 1.0},
        {"name": "dynamic_power_w", "field": "sta.dynamic_power_w",
         "direction": "lower", "weight": 1.0},
        {"name": "area_um2", "field": "synth.area_um2",
         "direction": "lower", "weight": 0.0},
    ],
}
DEMO_BASELINES = {"demo": {"K": 0}}   # 夹具设计不在任何设计根里，基线经 --baseline-config 给（内部#314）


@pytest.fixture
def jsonl(tmp_path):
    p = tmp_path / "experiments.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in RECORDS))
    return p


def _write_cfg(tmp_path, baselines=None, **overrides):
    """写打分配置 scoring.yaml，基线另写一份 baselines.yaml（当 --baseline-config 用）。"""
    cfg = json.loads(json.dumps(CONFIG))       # 深拷贝
    cfg.update(overrides)
    p = tmp_path / "scoring.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    _bl(p).write_text(yaml.safe_dump({"baselines": baselines or DEMO_BASELINES}, allow_unicode=True))
    return p


def _bl(cfg_path):
    return cfg_path.parent / "baselines.yaml"


def _load(tmp_path, **kw):
    p = _write_cfg(tmp_path, **kw)
    return score.load_config(p, baseline_config=_bl(p))


def _by_k(rows):
    return {r["params"]["K"]: r for r in rows}


# --- M1 ---------------------------------------------------------------------
def test_baseline_is_one_old_format_readable_zero_weight_ignored(tmp_path, jsonl):
    cfg = _load(tmp_path)
    rows = _by_k(score.score_rows(score.load_records(jsonl, "demo"), "demo", cfg))

    base = rows[0]
    assert base["ratios"] == {"fmax_mhz": 1.0, "dynamic_power_w": 1.0,
                              "area_um2": 1.0}
    assert base["score"] == 1.0

    # 老格式记录：周期由 slack_ns + critical_path_delay_ns 推出 = 1.0 + 4.0
    old = rows[1]
    assert old["clock_period_ns"] == pytest.approx(5.0)
    # fmax 也缺，按 1000 / critical_path_delay_ns = 250 MHz 推
    assert old["ratios"]["fmax_mhz"] == pytest.approx(250.0 / 200.0)
    assert old["score"] == pytest.approx((1.25 + 1.0) / 2)

    # 权重 0 的维度：出现在输出里，但总分与基线相同
    fat = rows[2]
    assert fat["ratios"]["area_um2"] == pytest.approx(100.0 / 10000.0)
    assert fat["score"] == pytest.approx(1.0)


# --- M2 ---------------------------------------------------------------------
def test_power_basis_switches_without_calling_any_eda_tool(tmp_path, jsonl,
                                                           monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("打分调用了外部进程 —— 它必须只读记录")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)

    records = score.load_records(jsonl, "demo")

    iso = _load(tmp_path, power_basis="iso_frequency")
    at_fmax = _load(tmp_path, power_basis="at_fmax")

    # K=3：测量周期 2.0 ns、fmax 2000 MHz（最短周期 0.5 ns）、实测 4e-5 W
    #   iso_frequency → 4e-5 × (2.0 / 5.0)      = 1.6e-5
    #   at_fmax       → 4e-5 × (2.0 × 2000/1000) = 1.6e-4
    fast_iso = _by_k(score.score_rows(records, "demo", iso))[3]
    fast_max = _by_k(score.score_rows(records, "demo", at_fmax))[3]
    assert fast_iso["values"]["dynamic_power_w"] == pytest.approx(1.6e-5)
    assert fast_max["values"]["dynamic_power_w"] == pytest.approx(1.6e-4)

    # 基线在 5.0 ns 下测，iso 口径下不变；at_fmax 口径下按 5.0 × 200/1000 = 1.0 也不变
    base_iso = _by_k(score.score_rows(records, "demo", iso))[0]
    base_max = _by_k(score.score_rows(records, "demo", at_fmax))[0]
    assert base_iso["values"]["dynamic_power_w"] == pytest.approx(1e-5)
    assert base_max["values"]["dynamic_power_w"] == pytest.approx(1e-5)

    # 功耗是「越小越好」，所以口径切换后 K=3 的功耗比值恶化 10 倍
    assert fast_iso["ratios"]["dynamic_power_w"] == pytest.approx(1e-5 / 1.6e-5)
    assert fast_max["ratios"]["dynamic_power_w"] == pytest.approx(1e-5 / 1.6e-4)


# --- M3 ---------------------------------------------------------------------
def test_missing_baseline_errors_and_prints_no_scores(tmp_path, jsonl):
    cfg_path = _write_cfg(tmp_path, baselines={"demo": {"K": 99}})

    with pytest.raises(score.BaselineMissing) as e:
        score.score_rows(score.load_records(jsonl, "demo"), "demo",
                         score.load_config(cfg_path, baseline_config=_bl(cfg_path)))
    msg = str(e.value)
    assert "demo" in msg and "K" in msg and "99" in msg

    # 命令行同样：非零退出，标准输出里没有分数表
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/score.py"),
         "--design", "demo", "--config", str(cfg_path), "--baseline-config", str(_bl(cfg_path)), "--records", str(jsonl)],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode != 0
    assert "score" not in r.stdout.lower()
    assert "K" in (r.stderr + r.stdout) and "99" in (r.stderr + r.stdout)


# --- M1（流程代限定）---------------------------------------------------------
def test_default_scores_only_latest_generation_and_refuses_cross_gen_baseline(
        tmp_path, jsonl):
    """默认只给最新一代打分；基线落在更早的一代时报错，且一行分数都不输出。

    跨代比值把"流程改了多少"算进了"设计好了多少"里 —— 那是个看不出错的错数，
    所以宁可报错，也不给一个能用的数。
    """
    cfg = _load(tmp_path)
    rows = score.score_rows(score.load_records(jsonl, "demo"), "demo", cfg)

    assert len(rows) == 4, "只有新代那四条该参与"
    assert all(r["record"]["flow"]["fingerprint"] == FP_NEW for r in rows)
    # 老代那两条的面积是 50/60，绝不能混进来
    assert all(r["values"]["area_um2"] not in (50.0, 60.0) for r in rows)

    # 基线指向一个只存在于老代的实现（K=7）：报错，且错误里点明是"流程代"的问题，
    # 而不是笼统地说"基线不存在"——后者会把人引去重跑一个其实已经跑过的组合
    cross = _load(tmp_path, baselines={"demo": {"K": 7}})
    with pytest.raises(score.ScoringError) as e:
        score.score_rows(score.load_records(jsonl, "demo"), "demo", cross)
    assert "流程代" in str(e.value)

    # 命令行同样：非零退出，标准输出里没有分数表
    cfg_path = _write_cfg(tmp_path, baselines={"demo": {"K": 7}})
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/score.py"),
         "--design", "demo", "--config", str(cfg_path), "--baseline-config", str(_bl(cfg_path)), "--records", str(jsonl)],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode != 0
    assert "score" not in r.stdout.lower()
    assert "流程代" in (r.stderr + r.stdout)


def test_excluded_count_is_reported_on_stderr(tmp_path, jsonl):
    """被排除的条数必须能看见 —— 静默丢行和悄悄给错数是同一类错误。"""
    cfg_path = _write_cfg(tmp_path)
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/score.py"),
         "--design", "demo", "--config", str(cfg_path), "--baseline-config", str(_bl(cfg_path)), "--records", str(jsonl)],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0
    assert "2 条" in r.stderr and "--all-generations" in r.stderr
    assert len([l for l in r.stdout.splitlines() if l.strip()]) == 5   # 表头 + 4 行


# --- M2（不限定流程代）-------------------------------------------------------
def test_all_generations_switch_scores_everything(tmp_path, jsonl):
    cfg = _load(tmp_path)
    rows = score.score_rows(score.load_records(jsonl, "demo"), "demo", cfg,
                            all_generations=True)
    fps = {r["record"]["flow"]["fingerprint"] for r in rows}
    assert fps == {FP_NEW, FP_OLD}, "两代的记录都要参与"
    assert len(rows) == 6

    cfg_path = _write_cfg(tmp_path)
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/score.py"), "--all-generations",
         "--design", "demo", "--config", str(cfg_path), "--baseline-config", str(_bl(cfg_path)), "--records", str(jsonl)],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0
    assert "流程代" in r.stderr, "跨代打分必须标明"


# --- 新字段不得让打分工具坏掉 --------------------------------------------------
#
# 为什么值得有这个测试：`sta.clocks` 是 2026-09-15 新增的字段（多时钟支持）。
# 打分读的是三个标量，按设计它从一开始就该无视这个数组 —— 但「以为不会坏」正是
# 本仓最怕的那类假设，而判据只要真喂一条进去就够了。
#
# 夹具里特意放一个 `slack_ns: null` 的域（某个时钟域一条域内路径都没有时就是这个
# 形状），确认 `None` 不会在某处被当成数字参与运算。

def test_a_record_with_the_new_clocks_array_still_scores(tmp_path):
    """带 `sta.clocks` 的记录照常算分，结果与不带它时逐位相同。"""
    plain = _rec(7, period=5.0, delay=5.0, dyn=1e-5, area=100.0, fmax=200.0)
    withc = _rec(7, period=5.0, delay=5.0, dyn=1e-5, area=100.0, fmax=200.0)
    withc["sta"]["clocks"] = [
        {"name": "clk_a", "port": "clk_a", "period_ns": 5.0,
         "slack_ns": 0.0, "fmax_mhz": 200.0},
        {"name": "clk_b", "port": "clk_b", "period_ns": 3.0,
         "slack_ns": None, "fmax_mhz": None},
    ]

    cfg = _load(tmp_path)

    def _rows(name, records):
        path = tmp_path / name
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return score.score_rows(score.load_records(path, "demo"), "demo", cfg)

    a = _rows("plain.jsonl", [BASELINE, plain])
    b = _rows("withc.jsonl", [BASELINE, withc])
    assert [r["score"] for r in a] == [r["score"] for r in b], (
        "多出来一个 sta.clocks 就改了分数 —— 打分读的是标量，不该读它")


# --- design_root 的回退（任务 1.2 / 本仓 内部#45）----------------------------------

def test_a_record_without_design_root_falls_back_to_its_design():
    """缺 `design_root` 的历史行必须能读，回退到该行的 `design`。

    1403 条历史行一条都不带这个字段（红线 2：只增不改、不回填），所以读它们的
    工具**必须**有回退，否则新增一个字段就把整个历史读崩了 —— 而「已有记录必须
    保持可读」正是 `experiment-record` 规定的那一侧。

    回退值的来历要说清楚：历史上根名与顶层名被强制相同，所以对当时**就是**
    一个设计根的那些行，回退值是对的；对**当时是独立设计根、后来被并入别处**的
    那些行（两个已删设计，分别 9 条与 2 条），
    回退出来的是**旧根名**，而那个目录收根之后已不存在。所以这个值只能用于
    分组与展示，**不能拿去在文件系统上定位源文件**。
    """
    from scripts.score import record_design_root

    # 带字段的新行：原样返回
    assert record_design_root(
        {"design": "OLD_SUB_TOP",
         "design_root": "OLD_ROOT_TOP"}) == "OLD_ROOT_TOP"
    # 缺字段的历史行：回退到 design，不报错、不返回 None
    assert record_design_root({"design": "ADDER32"}) == "ADDER32"
    assert record_design_root(
        {"design": "OLD_SUB_TOP"}) == "OLD_SUB_TOP"
    # 显式 null 与缺席同义 —— 两者都当作「这一行没说」
    assert record_design_root(
        {"design": "ADDER32", "design_root": None}) == "ADDER32"


def test_the_fallback_warns_that_it_is_not_a_filesystem_path():
    """回退值可能指向一个已不存在的目录 —— 这一点必须写在函数自己的文档里。

    判据取 docstring 而不是取注释：注释在重构时会被连同代码一起挪走或删掉，
    而 docstring 是函数契约的一部分，`help()` 读得到。这条防的是有人照着
    `record_design_root(rec)` 的名字去 `resolve_design_root(那个值)` ——
    对那 11 条历史行，那会指到一个不存在的目录。
    """
    from scripts.score import record_design_root

    doc = record_design_root.__doc__ or ""
    assert "不存在" in doc or "已不存在" in doc, (
        "record_design_root 的文档没说明回退值可能指向一个已不存在的目录")


def test_the_source_set_digest_is_unknown_when_the_record_does_not_carry_one():
    """缺席的 `synth.sources_sha256` 读作「未知」，而不是「与某条相同」。

    为什么值得有这条：1403 条历史行一条都不带这个字段（红线 2 不许回填）。
    读侧最容易犯的错是把缺席当成一个普通取值 —— 那样两条都缺的记录会「相等」，
    一条缺一条有的会「不等」，看上去都挺合理，直到有人拿它去判断
    「这两条读的是不是同一组文件」：对缺席的那些，谁也不知道。
    未知就要读作未知，判等一律为假（`None == None` 在这里不成立，
    所以判等要走 `same_source_set()`，不能直接比两次取值的返回）。
    """
    from scripts.score import record_sources_sha256, same_source_set

    known = {"synth": {"sources_sha256": "sha256:aa"}}
    other = {"synth": {"sources_sha256": "sha256:bb"}}
    absent = {"synth": {"cell_count": 13}}
    no_synth = {"design": "ADDER32"}

    assert record_sources_sha256(known) == "sha256:aa"
    assert record_sources_sha256(absent) is None
    assert record_sources_sha256(no_synth) is None

    assert same_source_set(known, dict(known)) is True
    assert same_source_set(known, other) is False
    # 有 vs 无：MUST NOT 推定它们读了同一组文件
    assert same_source_set(known, absent) is False
    assert same_source_set(absent, known) is False
    # 无 vs 无：两条都没说，同样不能断定相同
    assert same_source_set(absent, no_synth) is False


# --- 3.2：`design` 的大小写是两个不同的电路标签，读侧不许归一化 ----------------
#
# 2026-09-21 顶层模块名改大写（本仓 内部#46 的 2.1），于是同一个电路在记录里
# 先后有过两个名字：`adder32`（到 `5792722d` 那一代为止）与 `ADDER32`
# （`08e2aa1d` 起）。读法记在 `docs/data-credibility.md`。
#
# **读侧绝不能替人把它们合起来。** 合并看起来贴心，代价是把一条分界线抹掉：
# 两边的 `flow.fingerprint` 不同（换代了），合并之后 Pareto 前沿里会并排
# 出现两代的点，而图上看不出来。分开成组时人至少会问「怎么有两个 adder32」。

def _named(rec, design):
    rec = json.loads(json.dumps(rec))
    rec["design"] = design
    rec["experiment_id"] = f"{design}-{rec['params']['K']}"
    return rec


def test_two_designs_differing_only_in_case_are_not_merged(tmp_path):
    """M2: `adder32` 与 `ADDER32` 分别成组 —— 不报错、不跳过、更不合并。"""
    cfg = _load(tmp_path, baselines={
        "demo": {"K": 0}, "DEMO": {"K": 0}})
    lower = [_named(r, "demo") for r in RECORDS]
    upper = [_named(r, "DEMO") for r in RECORDS]
    both = lower + upper

    rows_upper = score.score_rows(both, "DEMO", cfg)
    rows_lower = score.score_rows(both, "demo", cfg)

    assert rows_upper, "大写名一条都没打上分"
    assert rows_lower, "小写名一条都没打上分"
    # 行里不带 design 字段，用 experiment_id 的前缀分辨（_named 就是这么造的）
    got_upper = {r["experiment_id"].split("-")[0] for r in rows_upper}
    got_lower = {r["experiment_id"].split("-")[0] for r in rows_lower}
    assert got_upper == {"DEMO"}, (
        "读 ADDER32 这种大写名时把小写名的记录也算了进来 —— 大小写被归一化了。"
        "两边的 flow.fingerprint 不同（大写名起是新的一代），合并之后前沿里会"
        f"并排出现两代的点，而图上看不出来：{got_upper}")
    assert got_lower == {"demo"}, f"小写名那一组混进了别的 design：{got_lower}"
    # 条数也要对上：合并会让同参数去重把两边压成一份
    assert len(rows_upper) == len(rows_lower), (
        f"两组条数不同（{len(rows_upper)} vs {len(rows_lower)}），"
        "说明某一侧被另一侧的同参数记录顶掉了")


# --- 基线必须按被测顶层名声明（ppa-scoring，unify-rtl-naming 3.2，内部#63） ------------
#
# 为什么值得有这条：2026-09-21 模块名改大写之后，`scoring.yaml` 的基线键还是小写的
# `adder32`，`score.py --design ADDER32` 直接失败 —— 失败了 6 天，没有任何东西报错，
# 因为打分是事后命令，不在 sweep / report / 任何用例的路径上。这条读**真实的**
# `scoring.yaml` 与全部 `params.yaml`，把「每个顶层都有基线、基线用的是当前的参数键」
# 钉成一个会失败的东西。

def _declared_top_specs():
    from flow.paths import _declared_tops, load_params_spec
    tops = {}
    from flow.paths import tree_glob   # 全部设计树（flow.paths.DESIGN_TREES，内部#305）
    for pfile in (REPO_ROOT / p for p in tree_glob("*/params.yaml", repo_root=REPO_ROOT)):
        for top in (yaml.safe_load(pfile.read_text()) or {}).get("tops", {}):
            tops[top] = load_params_spec(top)
    return tops


def test_every_declared_top_has_a_baseline_keyed_by_its_top_name():
    """每个 `tops:` 顶层在自己的设计根 params.yaml 里有 `score_baseline`，键是当前参数、值在声明里（内部#314）。"""
    from flow.paths import score_baseline
    tops = _declared_top_specs()
    missing = sorted(t for t in tops if score_baseline(t) is None)
    assert not missing, f"这些被测顶层没有 score_baseline：{missing}"
    for top, spec in tops.items():
        base = score_baseline(top)
        assert set(base) == set(spec), (
            f"{top} 的基线参数键 {sorted(base)} 与声明 {sorted(spec)} 不一致")
        for k, v in base.items():
            assert v in spec[k]["values"], f"{top} 基线的 {k}={v!r} 不在声明的取值 {spec[k]['values']} 里"


# --- 基线随设计根走（score-baseline-per-root，内部#314） ------------------------------
#
# 用户 2026-10-14 定：闭源内容只放设计根，所有顶层的打分基线写在各自设计根 params.yaml 的
# `tops:<顶层>:score_baseline:`；仓库根 scoring.yaml 只留全仓规则，留着 baselines 就报错，
# 免得两处各写一份、静默以其中一处为准。

def test_design_root_declares_the_baseline():
    from flow import paths
    spec = paths.load_design_config("CBB_LZD")
    assert paths.score_baseline("CBB_LZD") == dict(spec["score_baseline"])


def test_scoring_config_with_baselines_is_refused(tmp_path):
    p = tmp_path / "scoring.yaml"
    p.write_text(yaml.safe_dump(dict(CONFIG, baselines={"demo": {"K": 0}}), allow_unicode=True))
    with pytest.raises(score.ScoringError) as e:
        score.load_config(p)
    assert "score_baseline" in str(e.value) and "--baseline-config" in str(e.value)


def test_baseline_comes_from_design_root_unless_a_baseline_config_is_given(tmp_path):
    from flow import paths
    cfg = score.load_config(_write_cfg(tmp_path))
    assert score.baseline_params("CBB_LZD", cfg) == paths.score_baseline("CBB_LZD")
    old = tmp_path / "old_scoring.yaml"
    old.write_text(yaml.safe_dump({"baselines": {"OLD_TOP": {"K": 3}}}))
    hist = score.load_config(_write_cfg(tmp_path), baseline_config=old)
    assert score.baseline_params("OLD_TOP", hist) == {"K": 3}


def test_real_scoring_yaml_has_no_baselines():
    cfg = yaml.safe_load((REPO_ROOT / "scoring.yaml").read_text())
    assert "baselines" not in cfg, "基线已改写在各设计根 params.yaml 的 score_baseline（#314）"


# --- 内部#422：默认读全部设计根的记录文件，`--records` 指一个文件的旧用法照旧 ---

def test_load_records_reads_every_design_root_file(tmp_path, monkeypatch):
    from flow import records
    monkeypatch.setattr(records, "REPO_ROOT", tmp_path)
    a, b = RECORDS[:2], RECORDS[2:]
    for root, recs in (("demo_a", a), ("demo_b", b)):
        f = tmp_path / "results" / root / "experiments.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text("".join(json.dumps(r) + "\n" for r in recs))
    got = score.load_records(design="demo")
    assert sorted(r["experiment_id"] for r in got) == sorted(r["experiment_id"] for r in RECORDS if r["design"] == "demo")
    one = score.load_records(tmp_path / "results" / "demo_a" / "experiments.jsonl", "demo")
    assert [r["experiment_id"] for r in one] == [r["experiment_id"] for r in a if r["design"] == "demo"]
    with pytest.raises(FileNotFoundError):
        score.load_records(tmp_path / "nope.jsonl")
