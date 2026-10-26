"""记录实验之前工作区必须干净。

为什么值得有这个测试：记录里的 `git_commit` 来自 `git rev-parse HEAD`。工作区脏着
跑出来的记录，其 `git_commit` **不包含产出它的那份代码** —— 而这件事**事后无法从
记录里识别**：那一行看上去与任何一条正常记录没有区别。CLAUDE.md 的红线 3 说的就是
这个，但在 2026-09-14 之前它没有任何机械判据，全靠人记得。

当天就栽了一次：为验证一个新设计的 TB 跑了三次 `make exp`，而 STA 的 `-scope` 修复、
时钟改动、延时比例改动都还没提交，三条记录的 `git_commit` 指向一个不含这些改动的
commit。那三条按红线 2（不删、不回填、不重写历史行）保留，见
`docs/data-credibility.md`。

⚠️ `results/experiments.jsonl` **本身**不算脏：扫参是一条一条往里追加的，
第一条写完工作区就"脏"了，拿它当判据会让扫参在第二条上自锁。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_experiment import _assert_clean_worktree


def test_clean_worktree_passes():
    _assert_clean_worktree("")


def test_dirty_worktree_is_refused():
    """脏工作区必须当场报错，且错误信息点名是哪些文件。"""
    with pytest.raises(RuntimeError) as excinfo:
        _assert_clean_worktree(" M flow/sta/run_sta.py\n M scripts/score.py\n")
    msg = str(excinfo.value)
    assert "flow/sta/run_sta.py" in msg
    assert "git_commit" in msg


def test_the_log_file_itself_is_not_dirtiness():
    """扫参会一条条往 jsonl 里追加 —— 拿它当判据会让扫参在第二条上自锁。"""
    _assert_clean_worktree(" M results/experiments.jsonl\n")


def test_the_log_file_does_not_mask_other_dirt():
    """但它不能给别的脏文件打掩护。"""
    with pytest.raises(RuntimeError):
        _assert_clean_worktree(" M results/experiments.jsonl\n M flow/paths.py\n")


def test_untracked_files_count_as_dirty():
    """未跟踪文件同样算 —— 新加的 RTL 没提交，记录照样指向不含它的 commit。"""
    with pytest.raises(RuntimeError):
        _assert_clean_worktree("?? designs/foo/rtl/foo.v\n")


# --- 脏树守卫只拦与测量有关的路径（flow-batch-2026-10 的 1.4，内部#67）--------------
#
# 项目本来就是多个会话并行：另一个会话没提交的 keel 升级、文档改动不该卡住这里的
# 实验。豁免是黑名单 —— 没列进来的路径一律拦，漏列只会多拦，不会少拦。

IGNORABLE = " M AGENTS.md\n M .claude/skills/x/SKILL.md\n?? docs/y.md\n M openspec/changes/z/tasks.md\n" \
            " M CLAUDE.md\n M knowledge/a.md\n M .agents/skills/b/SKILL.md\n"


def test_files_unrelated_to_measurement_do_not_block_and_are_listed(capsys):
    _assert_clean_worktree(IGNORABLE)
    err = capsys.readouterr().err
    assert "AGENTS.md" in err and "openspec/changes/z/tasks.md" in err, (
        "被豁免的条目要列出来，不能静默忽略：\n" + err)


@pytest.mark.parametrize("line", [
    " M designs/a/rtl/b.v", " M flow/x.py", "?? CLAUDE.md.bak", " M scoring.yaml",
    "R  docs/old.md -> flow/new.py",
])
def test_measurement_relevant_paths_still_block(line):
    with pytest.raises(RuntimeError, match="工作区不干净"):
        _assert_clean_worktree(IGNORABLE + line + "\n")


# --- 记录必须带上这次网表的寄存器数 ------------------------------------------
#
# 为什么值得有这个测试：「这次组合有没有触发器」决定了时序字段该不该被断言
# （`flow/sta/run_sta.py::_assert_timing_came_from_a_real_path`），但在记录里
# 一直查不到 —— 想知道一批记录里哪些是零触发器的，只能回头翻 `runs/` 下的产物
# （gitignore 的，早期记录的早就不在了）或者按参数组合反推（要求读者知道每个
# 设计的 `PIPE_STAGES=0` 意味着什么）。本仓 内部#32。
#
# 新增字段受红线 2 约束：只增不改名、不删、不回填。老记录缺这个字段是**可检测
# 的**，这正是「已有记录必须保持可读」规定的那一侧。

import json                                                # noqa: E402
import os                                                  # noqa: E402
import shutil                                              # noqa: E402

LIBERTY = Path(os.environ.get(
    "PPA_LIBERTY", Path.home() / "pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib"))

needs_flow = pytest.mark.skipif(
    any(shutil.which(t) is None for t in ("yosys", "sta", "iverilog"))
    or not LIBERTY.is_file(),
    reason="需要 yosys / sta / iverilog 在 PATH 上与合并 liberty 在本机")



@needs_flow
@pytest.mark.parametrize("design,params,expected", [
    ("SHAPE_COMB", {"DAT_W": 8}, 0),                                          # 零触发器
    ("ADDER32", {"DAT_W": 8, "SCHEME": 0, "PIPE_STAGES": 2, "CSEL_BLK_W": 4}, 8),  # 段间进位与低位和，综合后 8 个
])
@pytest.mark.flow
def test_record_carries_the_register_count(tmp_path, monkeypatch, fixture_designs,
                                           design, params, expected):
    """端到端一条记录：`sta.register_count` 在，且等于这次 STA 数出来的数。

    早先是 `ADDER32 DAT_W=8` 的 `PIPE_STAGES` 0 / 2 两档（2026-10-01 删除）；零触发器那一档
    改用夹具 SHAPE_COMB（`tests/fixtures/designs/shapes/`）；有触发器的 2026-10-14 起换回开源的 ADDER32（内部#305）。
    """
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    # 与 tests/test_fmax_search.py::test_record_says_which_rung_won 同一个理由：
    # 本用例写的是 tmp 目录下的日志，不是数据集，而它必然在开发中的脏工作区里跑。
    # 绕过写在这里，而不是让守卫自己长出一条"日志不是数据集就不查"的隐式例外。
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")

    record = rx.run_experiment(design, params, LIBERTY)

    assert record["sta"]["register_count"] == expected
    # 落盘的那一行也要带上 —— 返回值对而写出去的不对，是最难发现的那种错
    written = json.loads(log.read_text().strip())
    assert written["sta"]["register_count"] == expected


@needs_flow
@pytest.mark.flow
def test_the_record_says_which_pins_the_activity_was_annotated_on(tmp_path, monkeypatch):
    """记录带 `sta.activity_annotation`（flow-batch-2026-10 的 1.5，内部#65），落盘那一行也带。

    gate-level-activity 起功耗来自胜出网表的零延时门级 VCD，标注到网表内部
    （`scope == internal`）；之前 RTL VCD 只对得上端口（`ports`，D-27）。
    """
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")
    monkeypatch.setattr(rx, "run_dir", lambda *a: tmp_path.joinpath("runs", *a))
    # Kogge-Stone：内部节点多，门级反标的引脚数远超端口位数（2026-10-14 实测 1325 对 100，内部#305）
    record = rx.run_experiment("ADDER32", {"DAT_W": 32, "SCHEME": 4, "PIPE_STAGES": 1, "CSEL_BLK_W": 4}, LIBERTY)
    for rec in (record, json.loads(log.read_text().strip())):
        ann = rec["sta"]["activity_annotation"]
        assert ann["scope"] == "internal" and ann["pins"] > 10 * ann["port_bits"], ann
        assert ann["port_bits"] == 100, ann   # clk rst_n i_cin o_cout + i_a / i_b / o_sum 各 32
        assert rec["sim"]["gate_passed"] is True
        assert rec["sta"]["dynamic_power_w"] is not None
        for c in rec["sta"]["corners"].values():
            assert c["dynamic_power_w"] is not None and c["static_power_w"] is not None
    run = tmp_path / "runs" / record["experiment_id"]
    gate_vcds = list((run / "sim_gate").glob("*.vcd"))
    assert gate_vcds, f"{run / 'sim_gate'} 下没有门级 VCD"
    tcl = (run / "sta" / "run_sta.tcl").read_text()
    assert str(gate_vcds[0]) in tcl, "runs/<id>/sta/ 的 STA 读的应是门级 VCD"


@needs_flow
@pytest.mark.flow
def test_the_record_names_both_the_top_and_its_design_root(tmp_path, monkeypatch):
    """一条记录要同时回答「测的是哪个顶层」与「它的源文件在哪个设计根」。

    `design` 的含义**不变**：它一直是被测顶层名。在「设计根名 MUST 等于顶层名」
    成立的全部历史里，根名与顶层名被强制逐字相同，所以 `design` 一直同时是两者；
    收根之后两者会分开，而把 `design` 留给顶层可以让 1403 条历史行**全部仍然正确**
    （`openspec/specs/experiment-record/spec.md` 的「记录必须区分被测顶层与它所在的
    设计根」）。新增的是 `design_root`。

    落盘那一行也要核：**返回值对而写出去的不对，是最难发现的那种错。**
    """
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")

    record = rx.run_experiment(
        "ADDER32",
        {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 1, "CSEL_BLK_W": 4},
        LIBERTY)

    assert record["design"] == "ADDER32", "design 必须仍然是被测顶层名"
    assert "design_root" in record, f"记录里没有 design_root：{sorted(record)}"
    assert record["design_root"] == "adder32", (
        "`ADDER32` 住在 `designs/adder32/` 里 —— 顶层名大写、根名小写，两者**不同**"
        f"（2026-09-21 起，本仓 #46 的 2.1）。实际拿到 {record['design_root']!r}")

    written = json.loads(log.read_text().strip())
    assert "design_root" in written, f"记录里没有 design_root（落盘那一行）：{sorted(written)}"
    assert written["design_root"] == record["design_root"]


# design.md D2 的记录键映射（`ADDER32` 那三个；其余顶层的由各自的任务加进来）。
PARAM_RENAMES = {"WIDTH": "DAT_W", "CARRY_STRUCT": "SCHEME", "CSEL_BLOCK": "CSEL_BLK_W"}


# 契约允许整段为 null 的字典段：按需开、不开时写 null（experiment-record，reference-ppa 内部#202）。
# 这些段在新记录里为 null 时不比键；别的段为 null 照报（内部#241）。
NULLABLE_SECTIONS = {"reference"}


def _nullable_absent(section, record):
    """新记录里该段为 null 且契约允许 —— 跳过比键。不允许为 null 的段为 null 时报错。"""
    if record.get(section, {}) is not None:
        return False
    assert section in NULLABLE_SECTIONS, f"{section} 段在新记录里是 null，契约不允许 —— 红线 2 禁止删字段"
    return True


def test_nullable_section_absent_is_skipped_others_still_fail():
    """内部#241：历史里 reference 是字典、新记录不开参考口径为 null —— 不算删字段；
    sta 这类必有段为 null 照报（失败臂）。"""
    assert _nullable_absent("reference", {"reference": None})
    assert not _nullable_absent("reference", {"reference": {"equiv": "PROVED"}})
    with pytest.raises(AssertionError, match="sta 段在新记录里是 null"):
        _nullable_absent("sta", {"sta": None})


@needs_flow
@pytest.mark.flow
def test_the_schema_only_grows(tmp_path, monkeypatch):
    """既有记录的每一个字段名在新记录里都还在（红线 2）。

    判据取**全部历史记录**的字段名并集，而不是"最后一行"：并集是这条契约的
    字面意思（"已经出现过的字段名 MUST NOT 被改名，MUST NOT 被删除"），
    而最后一行只是它的一个抽样。

    ⚠️ 这里刻意**不**断言"某某字段是新加的"。那是一个**时点事实**，不是契约：
    2026-09-14 就栽过一次 —— 原来的写法是
    `assert "register_count" in set(record["sta"]) - set(previous["sta"])`，
    在 `register_count` 落盘的那一代跑完之后，"最后一行"本身就带上了它，
    差集变空，用例失败。失败时它看起来像一次真的回归，其实数据长了而已。
    护栏的判据必须是契约本身，不能是当下恰好为真的一个事实。
    """
    from flow import records
    if not records.source_files():
        pytest.skip("没有 results/<设计根>/experiments.jsonl：记录闭源，不在导出集合（open-export「导出结果自足」）")
    import scripts.run_experiment as rx

    # `params` 是**按设计**的，不是 schema 的一部分：一个设计的记录没有另一个设计的参数
    # （ADDER32 的旧记录有 CARRY_STRUCT，CBB_LZD 的没有）。跨设计取并集会把"这个设计没这个
    # 参数"误判成"字段被删了"。契约条款举的例子是 `sta.fmax_mhz` / `flow.fingerprint`
    # 这类**所有记录共有**的字段，所以 params 按同一设计单独收。
    DESIGN = "CBB_LZD"    # 开源构件（内部#305）：210 条历史记录的 params 键与当前声明一致，params 段照比
    seen = {"__top__": set()}
    for old in records.load():
        seen["__top__"] |= set(old)
        for section, value in old.items():
            if not isinstance(value, dict):
                continue
            if section == "params" and old.get("design") != DESIGN:
                continue
            seen.setdefault(section, set())
            seen[section] |= set(value)

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")
    record = rx.run_experiment(
        DESIGN, {"DAT_W": 32, "MSB_EN": 0, "SCHEME": 0},
        LIBERTY)

    missing = seen["__top__"] - set(record)
    assert not missing, f"顶层字段少了 {sorted(missing)} —— 红线 2 禁止删字段"
    for section, names in seen.items():
        if section == "__top__":
            continue
        if _nullable_absent(section, record):
            continue
        present = set(record.get(section, {}))
        if section == "params":
            # `params` 的键换过一次名（experiment-record 的「`params` 的键换过一次名，
            # 映射表是唯一合法的跨分界配对方式」，unify-rtl-naming 2026-09-28）。
            # 旧键**只有**在它映射到的新键出现时才算「还在」；映射表之外的键照旧
            # 不许少 —— 这里放行的是一张显式的表，不是「params 不查了」。
            present |= {old for old, new in PARAM_RENAMES.items() if new in present}
        gone = names - present
        assert not gone, f"{section} 段少了 {sorted(gone)} —— 红线 2 禁止删字段"


# --- 多时钟：记录新增 sta.clocks，既有标量不动 --------------------------------
#
# 为什么值得有这个测试：这是一次 schema 变更，而 `results/experiments.jsonl` 的
# 字段集合**只增不改、不可逆**（红线 2）。加错了的字段删不掉、改不了名。
#
# 三个既有标量在多时钟记录上必须仍然有值（取最差的那个域），否则每一个读记录的
# 工具都要先支持数组才能处理多时钟设计 —— 而它们今天读的是标量。

MULTICLOCK_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "multiclock"


@needs_flow
@pytest.mark.flow
def test_single_clock_record_keeps_its_scalars_and_gains_one_entry(
        tmp_path, monkeypatch):
    """单时钟：`sta.clocks` 恰好一项，三个既有标量取值不变。

    `slack_ns` 与 `fmax_mhz` 在单时钟下必须与那一项逐位相同 —— 两者同式
    （`fmax = 1000 / (period - slack)`），不同就说明聚合口径和逐域口径分了家。
    """
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")

    record = rx.run_experiment(
        "ADDER32",
        {"DAT_W": 32, "SCHEME": 0, "PIPE_STAGES": 1, "CSEL_BLK_W": 4},
        LIBERTY)

    sta = record["sta"]
    assert len(sta["clocks"]) == 1, sta["clocks"]
    entry = sta["clocks"][0]
    assert entry["name"] == "clk"
    assert entry["port"] == "clk"
    assert entry["period_ns"] == sta["clock_period_ns"]
    assert entry["slack_ns"] == sta["slack_ns"]
    assert entry["fmax_mhz"] == sta["fmax_mhz"], (
        "单时钟下逐域 fmax 与顶层标量不同 —— 两者同式，分家说明有一处算错了")

    written = json.loads(log.read_text().strip())
    assert written["sta"]["clocks"] == sta["clocks"]


def test_the_worst_domain_drives_the_scalar():
    """多时钟聚合口径：标量取最差的域，`None` 的域不参与。

    不跑真实流程 —— 要测的是聚合规则本身，而构造「某个域没有域内路径」需要一份
    特定形状的网表（`tests/fixtures/multiclock/nopath.v`），那是 2.1 的判据。
    这里只钉住规则：`None` 必须被跳过，不能让它参与取最小或把结果变成 `None`。
    """
    from scripts.run_experiment import _worst_clock_slack

    assert _worst_clock_slack([{"slack_ns": 1.5}, {"slack_ns": 0.3}]) == 0.3
    assert _worst_clock_slack([{"slack_ns": None}, {"slack_ns": 0.3}]) == 0.3
    assert _worst_clock_slack([{"slack_ns": 2.0}, {"slack_ns": None}]) == 2.0
    # 一个域都没测到时，聚合结果只能是缺席 —— 编一个数出来正是红线要防的
    assert _worst_clock_slack([{"slack_ns": None}]) is None
    assert _worst_clock_slack([]) is None


# --- 记录必须带上域内保持时间余量 ---------------------------------------------
#
# 为什么值得有这个测试：`sta.hold_slack_ns` 与 `sta.register_count` 看上去是
# 同进同退的两个字段，**它们不是**。单级流水的网表有触发器，却一条
# 寄存器到寄存器的路径都没有 —— 那些触发器全部只被「输入端口→reg」与
# 「reg→输出端口」两类路径触及，而那两类的 min 结果由 `set_input_delay 0` /
# `set_output_delay 0` 决定，是约束里的假设不是电路的性质。
#
# 当前代 92 条里这个形态有 29 条。把「缺席」判成「没有触发器」，这 29 条会带着
# OpenSTA 的无路径哨兵值 1.0000000433293989e+39 落进记录，而且不报错 ——
# 一个语法合法的浮点数，会被读成「余量无穷大」。本仓 内部#24。

@needs_flow
@pytest.mark.parametrize("design,params,regs,has_hold", [
    ("SHAPE_COMB", {"DAT_W": 8}, 0, False),    # 零触发器
    ("SHAPE_REG1", {"DAT_W": 8}, 8, False),    # 有触发器，但一条域内路径都没有
    ("ADDER32", {"DAT_W": 8, "SCHEME": 0, "PIPE_STAGES": 2, "CSEL_BLK_W": 4}, 8, True),  # 有域内路径
])
@pytest.mark.flow
def test_record_carries_the_intra_domain_hold_margin(
        tmp_path, monkeypatch, fixture_designs, design, params, regs, has_hold):
    """端到端一条记录：`sta.hold_slack_ns` 在，且缺席的依据不是触发器数。

    三种形状早先都取自 ADDER32 的 `PIPE_STAGES` 0 / 1 / 2（2026-10-01 删除）；前两种改用夹具
    （`tests/fixtures/designs/shapes/`）；有域内路径的 2026-10-14 起换回开源的 ADDER32 PIPE_STAGES=2（内部#305）。
    """
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")

    record = rx.run_experiment(design, params, LIBERTY)

    assert record["sta"]["register_count"] == regs
    hold = record["sta"]["hold_slack_ns"]
    if has_hold:
        assert hold is not None and hold > 0, (
            f"{design} 有域内路径，hold 余量却是 {hold!r}")
    else:
        assert hold is None, (
            f"{design}（{regs} 个触发器、0 条域内路径）报了 {hold!r}；"
            "缺席的依据必须是「有没有域内路径」，不是「有没有触发器」")

    # 落盘的那一行也要带上 —— 返回值对而写出去的不对，是最难发现的那种错
    written = json.loads(log.read_text().strip())
    assert written["sta"]["hold_slack_ns"] == hold


# --- 顶层名与设计根名不同时，三个流程步骤各自拿到的是顶层（任务 1.2 / 本仓 内部#45）---
#
# ⚠️ 这一条**没有诚实的红，是实测出来的**。任务 1.1 把 `resolve_design_root(名字)`
# 从「拼目录名」改成「查 params.yaml 的 tops: 声明」之后，`run_sim` 的
# `hdl_toplevel=design`、`synth` 的 `top=design`、`run_sta` 的 `top=design` 三处里的
# `design` 拿到的**已经就是顶层名** —— 它们是被 1.1 顺带改对的，而不是本任务改的。
# 在 1.1 之前这个夹具根本构造不出来（`designs/mytop` 不存在，解析当场失败），
# 所以也不存在「改动前的红」。
#
# 那为什么还要写：这个性质**从未被任何用例覆盖过**，而它一旦回退，失效是静默的 ——
# 综合器拿到一个不存在的 `-top` 会挑别的模块顶上，照常出网表、照常出数。
# 收根（任务 2.1）之后本仓才真的出现「顶层名 ≠ 根名」的设计根，那时这条就从
# 「锁住一个碰巧正确的性质」变成「守着日常路径」。

def _root_with_differently_named_top(tmp_path):
    """一个叫 myroot 的设计根，声明的唯一顶层叫 mytop。"""
    root = tmp_path / "designs" / "myroot"
    (root / "rtl").mkdir(parents=True)
    (root / "tb").mkdir(parents=True)
    (root / "rtl" / "mytop.v").write_text(
        "module mytop #(parameter W = 4)\n"
        "  (input wire clk, input wire rst_n,\n"
        "   input wire [W-1:0] a, output reg [W-1:0] y);\n"
        "  always @(posedge clk or negedge rst_n)\n"
        "    if (!rst_n) y <= {W{1'b0}}; else y <= a;\n"
        "endmodule\n")
    (root / "params.yaml").write_text(
        "design_root: myroot\n"
        "tops:\n"
        "  mytop:\n"
        "    sim:\n      clock_signal: clk\n"
        "    sta:\n      ideal_drive_ports: [rst_n]\n"
        "    params:\n      W:\n        values: [4]\n")
    return tmp_path


def test_the_design_root_is_found_by_the_top_name_not_the_directory_name(tmp_path):
    """解析入口：给顶层名，拿到声明它的那个根。"""
    from flow.paths import resolve_design_root

    repo = _root_with_differently_named_top(tmp_path)
    assert resolve_design_root("mytop", repo_root=repo).name == "myroot"


@needs_flow
def test_synth_and_sta_are_handed_the_top_not_the_root(tmp_path, monkeypatch):
    """综合脚本的 `-top` 与 STA 的 `link_design` 收到的都是 `mytop`。

    判据取**生成出来的脚本文本**而不是「跑通了」：yosys 拿到一个不存在的 `-top`
    不会停下来，它会挑别的模块顶上，照常出网表、照常出数（本仓头号失效模式
    「跑通了但数字不可信」）。所以要核的是送进去的那个名字，不是退出码。
    """
    import flow.paths as fp
    import flow.synth.synth as synth

    repo = _root_with_differently_named_top(tmp_path)
    # `resolve_design_root(design, repo_root=REPO_ROOT)` 的默认值是**定义时**绑定的，
    # 所以 monkeypatch `flow.paths.REPO_ROOT` 对它无效 —— 改 patch `synth` 自己
    # 命名空间里的那三个名字。被测的仍然是真实实现，只是换了仓库根。
    # 缓存也要跟着换到夹具仓库里：否则夹具冒名的顶层会覆盖真仓库
    # runs/.source_sets/ 里同名的那份，下一次真用到时白算一遍（ADDER32 约 25 s），
    # 在 pytest -n 下还会与读它的 worker 撞车。
    monkeypatch.setattr(synth, "SOURCE_SET_CACHE", Path(repo) / "runs" / ".source_sets")
    monkeypatch.setattr(synth, "resolve_design_root",
                        lambda d: fp.resolve_design_root(d, repo_root=repo))
    monkeypatch.setattr(synth, "validate_params",
                        lambda d, pr: fp.validate_params(d, pr, repo_root=repo))
    monkeypatch.setattr(synth, "keep_hierarchy_modules",
                        lambda d: fp.keep_hierarchy_modules(d, repo_root=repo))

    out = tmp_path / "synthrun"
    synth.run_synth("mytop", {"W": 4}, LIBERTY, out_dir=out)
    script = (out / "synth.ys").read_text()
    # ⚠️ 顶层名送进 yosys 的位置在 2026-09-21 换过：以前是 `synth -top mytop`，
    # 现在 `hierarchy -check -top` 显式做在前面、`synth` 不带 `-top`
    # （`hierarchy` 之后顶层已被改名成 `$paramod…`，再给 `-top 原名` 会
    # `Module not found`，见 flow/synth/synth.py 的注释与 docs/pitfalls.md 的 P-14）。
    # 本用例钉的性质没变 —— **送进去的是顶层名，不是根名**。
    assert "hierarchy -check -top mytop" in script, (
        f"hierarchy 的 -top 不是顶层名：\n{script}")
    assert "rename -top mytop" in script
    assert "chparam -set W 4 mytop" in script, (
        f"chparam 的目标模块不是顶层名：\n{script}")
    # 根名**只**允许作为路径出现（read_verilog 的源文件在 designs/myroot/rtl/ 下）。
    # 判据因此按行看「拿模块名当参数」的那几条命令，而不是全文搜根名 ——
    # 全文搜会把 read_verilog 的路径算成违规（第一版就是这么假红的）。
    for line in script.splitlines():
        if line.startswith(("synth", "rename ", "chparam ", "hierarchy ",
                            "select ", "setattr ")):
            assert "myroot" not in line, (
                f"设计根名被当成模块名用了：{line}")


# --- 三角：SS / FF 在同一份网表上各测一次（add-ss-ff-corner-sta） ----------------
#
# 为什么值得有这个测试：这是 schema 变更（红线 2，加错了删不掉）。要守三件事：
# 角的数真的来自角的库（SS 慢于 TT 慢于 FF —— 三个数对调了、或者三角读的是同一份库，
# 都过不了这条）；每角自报 PVT（ASAP7 的 SS 在 100 °C，漏电比 TT 大一个数量级，
# 不带温度就会被读成「慢角漏电大」）；TT 的既有字段不被任何一角改写。

@needs_flow
@pytest.mark.flow
def test_the_record_carries_the_ss_and_ff_corners_on_the_same_netlist(tmp_path, monkeypatch):
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")
    record = rx.run_experiment(
        "ADDER32", {"DAT_W": 8, "SCHEME": 0, "PIPE_STAGES": 2, "CSEL_BLK_W": 4}, LIBERTY)   # PIPE_STAGES=2：有域内路径，角上才有 hold 余量

    corners = record["sta"]["corners"]
    assert set(corners) == {"SS", "FF"}
    tt = record["synth"]["critical_path_delay_ns"]
    ss, fast = corners["SS"], corners["FF"]
    assert ss["critical_path_delay_ns"] > tt > fast["critical_path_delay_ns"], (
        f"SS {ss['critical_path_delay_ns']} / TT {tt} / FF {fast['critical_path_delay_ns']}"
        " —— 角的数不像来自角的库")
    assert ss["pvt"] == {"voltage_v": 0.63, "temperature_c": 100.0}
    assert fast["pvt"] == {"voltage_v": 0.77, "temperature_c": 0.0}
    for c in (ss, fast):
        assert c["fmax_method"] == "analytic"
        assert c["dynamic_power_w"] is not None and c["static_power_w"] is not None
        assert c["hold_slack_ns"] is not None            # ADDER32 PIPE_STAGES=2 有域内路径
    # TT 的既有字段没被哪一角顶掉
    assert record["sta"]["slack_ns"] == pytest.approx(
        record["sta"]["clock_period_ns"] - tt, abs=1e-6)
    assert record["flow"]["corner_liberty_sha256"].keys() == {"SS", "FF"}
    written = json.loads(log.read_text().strip())
    assert written["sta"]["corners"] == corners


# ---- 出 PPA 记录之前验证方案必须声明已验证（repo-layout，内部#68 缺口 2）----
# 出自没有验证方案的电路的记录，是「跑通了但数字不可信」的一种：数字照样出、
# 报告照样画，没有任何东西失败。状态行是显式声明，按正文猜会漏判（各文档写
# 「未验证」的方式不统一）。

class _Reached(Exception):
    pass


def _gate(tmp_path, monkeypatch, verify_text, design="VTOP"):
    """把被测顶层的设计根指到 tmp_path；检查通过时撞上打桩的参数校验（_Reached）。"""
    import scripts.run_experiment as rx
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    if verify_text is not None:
        (root / f"verify.{design}.md").write_text(verify_text)
    log = tmp_path / "experiments.jsonl"
    log.write_text("")
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")
    monkeypatch.setattr(rx, "resolve_design_root", lambda d, *a, **k: root)

    def _reached(*a, **k):
        raise _Reached()
    monkeypatch.setattr(rx, "validate_params", _reached)
    monkeypatch.setattr(rx, "run_sim", lambda *a, **k: pytest.fail("验证状态不合格时不得跑任何工具"))
    return rx, log


@pytest.mark.parametrize("text, why", [
    ("# V\n\n验证状态：未验证\n", "未验证"),
    ("# V\n\n还没写状态行\n", "没有状态行"),
    ("# V\n验证状态：已验证（tb/a.py）\n验证状态：未验证\n", "不止一行"),
    ("# V\n验证状态：已验证\n", "依据"),
    ("# V\n验证状态：已验证（ ）\n", "依据"),
    (None, "不存在"),
])
def test_records_need_a_declared_verified_status(tmp_path, monkeypatch, text, why):
    rx, log = _gate(tmp_path, monkeypatch, text)
    with pytest.raises(RuntimeError, match=why) as e:
        rx.run_experiment("VTOP", {}, "unused.lib")
    assert "验证状态：" in str(e.value), "拒绝时要给出状态行的格式"
    assert log.read_text() == ""


def test_verified_with_evidence_passes_the_gate(tmp_path, monkeypatch):
    rx, _ = _gate(tmp_path, monkeypatch, "# V\n\n验证状态：已验证（tb/test_VTOP.py，全参数组合）\n")
    with pytest.raises(_Reached):
        rx.run_experiment("VTOP", {}, "unused.lib")


# ---- 功耗改由门级 VCD 反标（gate-level-activity，内部#65）----
# RTL 仿真的 VCD 只对得上网表端口，内部节点的活动率是 OpenSTA 按概率传播的 ——
# 结构之间的动态功耗排名因此不能当结论用（D-27）。改由胜出网表的零延时门级仿真
# 产出 VCD。下面这组打桩用例不跑真工具，只看 run_experiment 怎么接这几段。

_TIMING = {"clock_period_ns": 5.0, "register_count": 3, "clocks": [], "slack_ns": 4.0,
           "hold_slack_ns": 0.1, "critical_path_delay_ns": 1.0, "critical_path_stages": 4,
           "fmax_mhz": 1000.0, "fmax_method": "analytic"}


def _stub_flow(tmp_path, monkeypatch, *, rtl_passed=True, gate=None, scope="internal",
               rerun_timing=None):
    """把 run_experiment 的每一段换成桩，返回 (rx, log, calls)。

    `gate`：门级仿真的返回值（默认通过、带 VCD）；`scope`：带 VCD 的 STA 报的反标层级；
    `rerun_timing`：带 VCD 重跑的 STA 想要覆盖的时序字段（默认与搜索胜出档相同）。
    """
    import scripts.run_experiment as rx

    log = tmp_path / "experiments.jsonl"
    calls = {"gate": [], "sta": []}
    monkeypatch.setattr(rx, "EXPERIMENTS_LOG", log)
    monkeypatch.setattr(rx, "_worktree_status", lambda: "")
    monkeypatch.setattr(rx, "_sources_sha256", lambda design: "src-digest")   # RTL 仿真失败的记录要它（内部#334）
    monkeypatch.setattr(rx, "_assert_verified", lambda d: None)
    monkeypatch.setattr(rx, "validate_params", lambda d, p: p)
    monkeypatch.setattr(rx, "corner_liberties", lambda lib: {"SS": "ss.lib", "FF": "ff.lib"})
    monkeypatch.setattr(rx, "_liberty_pvt", lambda lib: {})
    monkeypatch.setattr(rx, "new_experiment_id", lambda d, p: "EXP")
    monkeypatch.setattr(rx, "run_dir", lambda *a: tmp_path.joinpath("runs", *a))
    monkeypatch.setattr(rx, "resolve_design_root", lambda d, *a, **k: tmp_path)
    monkeypatch.setattr(rx, "flow_fingerprint", lambda lib, sim="icarus", *, design: {"fingerprint": "f"})
    monkeypatch.setattr(rx, "git_commit_hash", lambda: "c")
    monkeypatch.setattr(rx, "run_sim", lambda *a, **k: {
        "passed": rtl_passed, "vcd_path": "rtl.vcd", "build_dir": "b", "results_xml": "r"})
    monkeypatch.setattr(rx, "vcd_stats", lambda vcd, clk: {"total_toggles": 7, "cycles": 9})
    monkeypatch.setattr(rx, "clock_signal", lambda d: "clk")
    monkeypatch.setattr(rx, "area_breakdown", lambda d, stats, lib: {"stub": True})  # area-breakdown：替身综合没有 stats.json
    monkeypatch.setattr(rx, "scenarios", lambda d, params=None: [])   # sta-scenarios：替身顶层没有 params.yaml

    def search(design, params, liberty, vcd=None, period_ns=5.0, out_dir=None):
        assert vcd is None, "档位搜索不看功耗（pick_best），各档 STA 不该读 VCD"
        return {"delay_target_ps": None, "search_effective": True,
                "synth": {"netlist_path": "win.v", "stats_path": "win.json", "cell_count": 10, "area_um2": 2.5,
                          "sources_sha256": "s"},
                "sta": {**_TIMING, "fmax_method": "search:abc-D", "dynamic_power_w": None,
                        "static_power_w": None, "activity_annotation": None}}
    monkeypatch.setattr(rx, "search_fmax", search)

    def sta(design, netlist, liberty, vcd=None, period_ns=5.0, out_dir=None):
        calls["sta"].append({"liberty": liberty, "vcd": vcd, "out_dir": out_dir})
        timing = {**_TIMING, **(rerun_timing or {})} if liberty == "tt.lib" else _TIMING
        power = vcd is not None
        return {**timing, "dynamic_power_w": 1e-5 if power else None,
                "static_power_w": 1e-8 if power else None,
                "activity_annotation": {"pins": 900 if scope == "internal" else 40,
                                        "port_bits": 40, "scope": scope} if power else None}
    monkeypatch.setattr(rx, "run_sta", sta)

    def gate_activity(design, params, netlist, out_dir):
        calls["gate"].append({"netlist": netlist, "out_dir": out_dir})
        return gate if gate is not None else {"passed": True, "vcd_path": "gate.vcd", "note": ""}
    monkeypatch.setattr(rx, "gate_activity", gate_activity)
    return rx, log, calls


def test_power_comes_from_the_gate_level_vcd_of_the_winning_netlist(tmp_path, monkeypatch):
    rx, log, calls = _stub_flow(tmp_path, monkeypatch)
    rec = rx.run_experiment("TOP", {}, "tt.lib")
    assert calls["gate"] == [{"netlist": "win.v", "out_dir": tmp_path / "runs" / "EXP" / "sim_gate"}]
    assert [c["vcd"] for c in calls["sta"]] == ["gate.vcd"] * 3, "TT 与两角都用门级 VCD"
    assert calls["sta"][0]["out_dir"] == tmp_path / "runs" / "EXP" / "sta"
    assert rec["sim"]["gate_passed"] is True
    assert rec["sta"]["activity_annotation"]["scope"] == "internal"
    assert rec["sta"]["dynamic_power_w"] == 1e-5
    assert rec["sta"]["fmax_method"] == "search:abc-D", "取值来源仍是档位搜索"
    assert rec["sim"]["total_toggles"] == 7, "total_toggles 仍来自 RTL 仿真"
    assert json.loads(log.read_text())["sim"]["gate_passed"] is True


def test_a_failed_gate_sim_leaves_activity_dependent_fields_null(tmp_path, monkeypatch):
    rx, log, calls = _stub_flow(tmp_path, monkeypatch,
                                gate={"passed": False, "vcd_path": "gate.vcd", "note": "TB 失败"})
    rec = rx.run_experiment("TOP", {}, "tt.lib")
    assert rec["sim"]["gate_passed"] is False
    for sec in (rec["sta"], *rec["sta"]["corners"].values()):
        assert sec["dynamic_power_w"] is None and sec["static_power_w"] is None
    assert rec["sta"]["activity_annotation"] is None
    assert all(c["vcd"] is None for c in calls["sta"]), "没过的门级 VCD 不得交给 STA"
    assert rec["synth"]["area_um2"] == 2.5 and rec["sta"]["slack_ns"] == 4.0
    assert json.loads(log.read_text())["sim"]["gate_passed"] is False


def test_a_failed_rtl_sim_skips_the_gate_sim(tmp_path, monkeypatch):
    """RTL 仿真没过：不跑门级仿真，也不跑 STA（内部#334 起整条流程停在仿真）。"""
    rx, _, calls = _stub_flow(tmp_path, monkeypatch, rtl_passed=False)
    rec = rx.run_experiment("TOP", {}, "tt.lib")
    assert calls["gate"] == [] and calls["sta"] == []
    assert rec["sim"]["gate_passed"] is None
    assert rec["sta"]["dynamic_power_w"] is None
    assert rec["synth"]["sources_sha256"] == "src-digest"


def test_a_gate_vcd_annotated_only_on_ports_is_refused(tmp_path, monkeypatch):
    rx, log, _ = _stub_flow(tmp_path, monkeypatch, scope="ports")
    with pytest.raises(RuntimeError, match="内部"):
        rx.run_experiment("TOP", {}, "tt.lib")
    assert not log.exists() or log.read_text() == ""


def test_the_power_rerun_must_reproduce_the_searched_timing(tmp_path, monkeypatch):
    rx, log, _ = _stub_flow(tmp_path, monkeypatch, rerun_timing={"critical_path_delay_ns": 1.2})
    with pytest.raises(RuntimeError, match="critical_path_delay_ns"):
        rx.run_experiment("TOP", {}, "tt.lib")
    assert not log.exists() or log.read_text() == ""


# ---- 档位搜索无效时放行并标明（search-noop-pass，内部#85）----

@pytest.mark.parametrize("effective", [True, False])
def test_the_record_says_whether_the_search_did_anything(tmp_path, monkeypatch, effective):
    rx, log, _ = _stub_flow(tmp_path, monkeypatch)
    real_search = rx.search_fmax

    def search(*a, **k):
        r = real_search(*a, **k)
        return {**r, "search_effective": effective}
    monkeypatch.setattr(rx, "search_fmax", search)
    rec = rx.run_experiment("TOP", {}, "tt.lib")
    assert rec["synth"]["search_effective"] is effective
    assert json.loads(log.read_text())["synth"]["search_effective"] is effective


def test_a_zero_cell_netlist_annotated_only_on_ports_is_recorded(tmp_path, monkeypatch):
    """零单元网表（输出直接连到输入）没有内部节点，只标到端口就是完整反标（内部#86）。"""
    rx, log, _ = _stub_flow(tmp_path, monkeypatch, scope="ports")
    real_search = rx.search_fmax

    def search(*a, **k):
        r = real_search(*a, **k)
        return {**r, "synth": {**r["synth"], "cell_count": 0}}
    monkeypatch.setattr(rx, "search_fmax", search)
    rec = rx.run_experiment("TOP", {}, "tt.lib")
    assert rec["synth"]["cell_count"] == 0
    assert rec["sta"]["activity_annotation"]["scope"] == "ports"
    assert json.loads(log.read_text())["sta"]["activity_annotation"]["scope"] == "ports"
