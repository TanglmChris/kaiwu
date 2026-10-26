"""这次测量是由哪一套流程产出的。

    from flow.flow_fingerprint import flow_fingerprint
    record["flow"] = flow_fingerprint(liberty, sim="icarus", design="CBB_LZD")

`git_commit` 记的是**仓库的版本，不是流程的版本**：换 PDK、换 Vt/corner、
重新生成合并 liberty 都不会改变任何 commit，却会让全部数字整体挪位
（`docs/data-credibility.md` 的 D-2 就是重新生成合并库那一次）。所以每条记录还要带一个
指纹，回答"这两条记录能不能放在一起比"。

进指纹的十项事实（第十项让指纹按设计算，内部#146）：

| 事实 | 为什么 |
|---|---|
| yosys 版本 | 换综合器版本，映射结果就变 |
| OpenSTA 版本 | 换 STA 版本，延时与功耗口径可能变 |
| 仿真器名 + 版本 **+ 驱动它的 cocotb 版本** | VCD 是功耗反标的输入，换掉产出活动率那条链上的任何一层，都是换了活动率来源 |
| liberty 的**内容**哈希 | 换库不改 commit，这是 git_commit 最致命的盲区 |
| 综合配方哈希（yosys 脚本模板 + abc 约束文件内容 + 推导延时目标的那组比例） | `e00e360` 改的就是前两样；比例决定 `fmax` 是在哪一组工作点里取的最好值 |
| STA 配方哈希（OpenSTA tcl 模板） | 约束、单位、时钟定义都在这里 |
| **派生字段的代码哈希**（`METRIC_MODULES` 的 AST） | 同一份工具输出，换一种解析方式就是另一种口径，而模板一个字没变 |
| **角的 liberty 内容哈希**（SS / FF，由 TT 库同名推出） | `sta.corners` 的每个数都来自它们；只哈希 TT 那份，换过 SS 库的两批记录会被判成同一代。单列一项而不并进 `liberty_sha256`：那会改变一个既有字段的含义（红线 2） |
| **单元 Verilog 模型的内容哈希**（门级仿真读的那几份） | 功耗来自胜出网表的门级仿真 VCD（gate-level-activity，内部#65）；模型不在仓库里，换一份不改 commit，与 liberty 同理 |
| **本设计的配方哈希**（`design_recipe`：解析后的时钟、时钟分组、时钟端口、仿真时钟信号、理想驱动端口、保层级模块、静态端口、存储模型、验收场景、参考口径接常数端口） | 用户 2026-10-04（内部#146）：只给某个设计加一种配置写法，不该让其他设计换代。`flow/paths.py` 因此不按代码进 METRIC_MODULES，按它解析出的值进这一项；配置不同的设计永远不同代，跨代配对按设计做 |

**不进**的：`git_commit`（已是独立字段，且 RTL 是被测对象不是流程）、
`period_ns`（已是 `sta.clock_period_ns`，是每次实验的旋钮）、机器与操作系统、
liberty 的**路径**（换个位置放同一份库不该分代）。

取舍是明确的：**太粗比太细危险得多**。太细只会多分几代（噪音，看得见）；
太粗会把不可比的数据判成可比（假结论，看不见）。所以宁可让"给 abc.constr
加一行"也分出一代。

最后那项事实是 2026-09-14 补的。此前只哈希**模块级常量**，理由是"改注释或参数
解析不影响测量结果，不该分代"。前半句仍然成立（AST 哈希正是为此），但
"真正决定结果的是那几个模板/约束的内容"已被本仓 内部#18 证伪：`_count_path_stages`
把所有 path group 的 cell 行加在一起，`critical_path_stages` 虚高 2 —— 那次是
**碰巧**顺带改了 tcl 才切开了代。把那次的 tcl 改动撤回、只留 Python 侧的改动，
`sta_recipe_sha256` 与修复前逐字相同（`d581f8c009b8`）。见 内部#25。

⚠️ cocotb 那一项的取法与另外三个工具**不同**：它取 `importlib.metadata.version`，
不取 PATH 上的 `cocotb-config`。理由见 `_driver_version` 的注释 —— 它是被 import
的库，不是被执行的命令，本机两者根本不是同一份。
"""
import ast
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.sta import run_sta as flow_sta
from flow.synth import search as flow_search
from flow.synth import synth as flow_synth

# 各仿真器取版本的方式。名字与 run_experiment.py / sweep.py 的 --sim 取值一致。
SIM_VERSION_CMD = {
    "icarus": ["iverilog", "-V"],
    "verilator": ["verilator", "--version"],
}

# 驱动仿真器的那一层。`flow/sim/run_sim.py` 不直接调仿真器，它走
# `cocotb_tools.runner.get_runner` —— 激励时序、Timer/Clock 的行为、波形从哪一刻
# 开始转储都由 cocotb 决定。换个版本，VCD 就不同 -> `sim.total_toggles` 不同
# -> `sta.dynamic_power_w` 不同，而仿真器可执行文件一个字节没变。
# 两个仿真器共用同一个驱动层，所以它不进 SIM_VERSION_CMD 那张表。
SIM_DRIVER_PACKAGE = "cocotb"


def _driver_version():
    """驱动层的版本，取自**跑仿真的那个解释器自己**，与 PATH 无关。

    ⚠️ 这里**不能**用 `_tool_version(["cocotb-config", "--version"])`。
    `shutil.which` 那一套对 yosys / OpenSTA / iverilog 是对的 —— 它们就是被 PATH
    解析后执行的那个二进制。cocotb 不是：它是被 **import** 的库，不是被执行的命令。

    2026-09-14 实测，本机有两个 cocotb：`~/tools/oss-cad-suite/bin/cocotb-config`
    报 `2.1.0.dev0+41564633`，`.venv/bin/cocotb-config` 报 `2.1.0`；`~/tools/env.sh`
    把前者排在 PATH 前面。于是"是否 source 过 env.sh"决定了指纹记哪一个，
    而仿真自始至终用的是 venv 那个。两代记录因此在**同一台机器、同一个真正的驱动**
    下记了两个不同的版本串（`06f48f38` 记 2.1.0，`14e73f3e` 记 2.1.0.dev0+…）。

    两个方向都坏：**假分代**（同一驱动换个 shell 就换一代）与**漏真分代**
    （换掉 venv 里的 cocotb，只要 oss-cad-suite 那个不动，指纹一个字不变）——
    后者正是加这项事实要防的那件事。
    """
    try:
        return importlib.metadata.version(SIM_DRIVER_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeError(
            f"跑这段代码的解释器里没有装 {SIM_DRIVER_PACKAGE}，"
            "无法记录驱动仿真那一层的版本。指纹是判断两条记录能否横向比较的唯一依据，"
            "缺了它宁可不写记录。") from None


def _sha256_bytes(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_text(text):
    return _sha256_bytes(text.encode())


def _first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _tool_version(argv):
    """工具自报的版本串，原样存，不做归一化。

    归一化（比如把 `0.68+182 (git sha1 ...-dirty)` 削成 `0.68`）等于替未来的自己
    判断"这两个版本等价"，而那正是这个字段要避免的事。
    """
    exe = shutil.which(argv[0])
    if exe is None:
        raise RuntimeError(
            f"{argv[0]} 不在 PATH 上，无法记录流程指纹（需要 source ~/tools/env.sh）。"
            "指纹是判断两条记录能否横向比较的唯一依据，缺了它宁可不写记录。")
    out = subprocess.run([exe, *argv[1:]], capture_output=True, text=True)
    return _first_line(out.stdout + out.stderr)


def synth_recipe_sha256():
    """决定综合结果的配方：yosys 脚本模板 + abc 约束文件的内容 + 延时目标比例。

    比例必须在里面。`fmax` 是"在这组目标里能拿到的最好值"，换掉这组比例就换掉了
    这个量的定义 —— 两组不同比例却带同一个指纹，正是本仓 内部#25 记的那个缺口。

    进来的是**比例**而不是推出来的皮秒值：皮秒值由每个设计自己的 d0 决定，
    把它们写进指纹会让每个设计自成一代，分代机制就失去意义了。
    """
    constr = Path(flow_synth.ABC_CONSTR).read_text()
    ratios = json.dumps(list(flow_search.DELAY_TARGET_RATIOS))
    return _sha256_text(flow_synth.YOSYS_TEMPLATE
                        + "\n--- abc.constr ---\n" + constr
                        + "\n--- delay target ratios ---\n" + ratios)


# 把工具输出变成记录字段、或决定要工具做什么的那些模块。判据就是这一句。
#
# 以**模块**为单位而不是列一份函数白名单：白名单的失效方式是"有人加了新的派生
# 路径却忘了登记"，与这项事实要防的是同一件事。整模块没有盲区，而噪声成本实测
# 接近零（见 metrics_code_sha256 的 docstring）。
#
# 不含 flow/synth/merge_liberty.py —— 它产出的 liberty 其**内容**已经单独进了指纹。
# 不含 scripts/score.py 与 gen_report.py —— 它们只读记录，不写。
# 不含 flow/paths.py —— 它把各设计的 params.yaml 解析成测量代码用的值，这些值按设计
# 进 design_recipe_sha256（内部#146）。按值哈希只牵连配置真的变了的设计；按代码哈希会让
# 「给某个设计加一种写法」把全部设计都换代。
METRIC_MODULES = (
    "flow/sim/run_sim.py",      # passed、vcd_path
    "flow/sim/vcd_stats.py",    # cycles、total_toggles
    "flow/synth/synth.py",      # cell_count、area_um2
    "flow/synth/search.py",     # delay_target_ps、哪一份网表胜出
    "flow/sta/run_sta.py",      # slack、critical_path_*、fmax、功耗
    "scripts/run_experiment.py",  # 记录字典本身
    "flow/sim/gate_sim.py",     # 功耗反标用的门级 VCD（gate-level-activity）
    "flow/synth/area.py",       # synth.area_breakdown（area-breakdown，内部#174）
    "flow/synth/reference.py",  # reference（参考口径综合，reference-ppa，内部#202）
)


def _metric_module_paths():
    """只给测试留的接缝：让它换掉某一个模块的路径而不动仓库里的那一份。"""
    return tuple(REPO_ROOT / m for m in METRIC_MODULES)


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return tree


def metrics_code_sha256():
    """把工具输出解析成记录字段的那部分**代码**。

    哈希的是 **AST** 而不是源文本，而且显式剥掉 docstring。`ast.dump` 默认
    `include_attributes=False`，不带行号，注释根本不进 AST —— 于是**纯文档改动
    不分代**。这一条是必须的：文档修订很频繁，如果它们也分代，流程代会被噪声
    淹没，人就会开始无视代的边界，这项事实也就白加了。实测 `9db0feb`
    （提交信息就是"纠正说法，不动流程"）与 `f881f4e`（纯文档）在这七个模块上
    AST 哈希一个都没变；而 `a65029f`、`b252f22` 这些有行为的改动都被抓到了。

    模块清单本身进哈希：从清单里删掉一项是一次静默的覆盖面收缩。

    **按路径读源码，不 import** —— `scripts/run_experiment.py` 反向 import 了
    本模块，import 会成环。

    ⚠️ `ast.dump` 的输出形态随 Python 版本可能变化，所以换 Python 大版本会让全部
    指纹改变。那不是缺陷：解释器就是跑测量代码的那个工具。
    """
    parts = []
    for path in _metric_module_paths():
        tree = _strip_docstrings(ast.parse(Path(path).read_text()))
        parts.append(f"--- {Path(path).name} ---\n{ast.dump(tree)}")
    return _sha256_text("\n".join(METRIC_MODULES) + "\n" + "\n".join(parts))


def design_recipe(design, repo_root=None):
    """本设计**解析后**交给测量代码的配置值（fingerprint-per-design D1）。

    测量代码读设计配置只经这十一个函数（逐个 grep METRIC_MODULES 核过；static_ports 是
    sta-static-ports 加的，memory_models 是 area-breakdown 加的，scenarios 是 sta-scenarios 加的，reference_ports 是 reference-ppa 加的，
    equiv 是 equiv-optional 加的）。读入集合那一组
    （`rtl_candidates` / `include_*` / `_declared_tops`）的影响由每条记录的
    `synth.sources_sha256` 承担，不在这里。单时钟回退时 `clocks` 的周期是 `None`：
    周期是命令行旋钮，已是 `sta.clock_period_ns`。
    """
    from flow import paths
    kw = {} if repo_root is None else {"repo_root": Path(repo_root)}
    return {
        "clocks": paths.clocks(design, **kw),
        "clock_groups": paths.clock_groups(design, **kw),
        "clock_port": paths.clock_port(design, **kw),
        "clock_signal": paths.clock_signal(design, **kw),
        "ideal_drive_ports": paths.ideal_drive_ports(design, **kw),
        "keep_hierarchy": paths.keep_hierarchy_modules(design, **kw),
        "static_ports": paths.static_ports(design, **kw),
        "memory_models": paths.memory_models(design, **kw),
        "scenarios": paths.scenarios(design, **kw),
        "reference_ports": paths.reference_ports(design, **kw),
        "equiv": paths.equiv_enabled(design, **kw),
    }


def design_recipe_sha256(design, repo_root=None):
    return _sha256_text(json.dumps(design_recipe(design, repo_root), sort_keys=True,
                                   ensure_ascii=False))


def sta_recipe_sha256():
    """决定时序/功耗结果的配方：OpenSTA 的 tcl 模板。"""
    return _sha256_text(flow_sta.STA_TCL_TEMPLATE)


# 综合按主库（TT）做，STA 另在这两角各做一次（add-ss-ff-corner-sta）。
CORNERS = ("SS", "FF")
_TT_SUFFIX = "_TT.lib"


def corner_liberties(liberty):
    """{角: 该角 liberty 路径}，由 TT 库同目录同名替换推出（`…_TT.lib` → `…_SS.lib`）。

    主库名不以 `_TT.lib` 结尾（测试的假库、或有人拿别的角当主库）时返回 `{}` ——
    推不出兄弟角，就不做多角，那些字段缺席（「无法测得的指标必须缺席」）。
    推得出而文件不在是**配置错了**：报错并点名，不静默少测一角。
    """
    p = Path(liberty)
    if not p.name.endswith(_TT_SUFFIX):
        return {}
    out = {}
    for corner in CORNERS:
        sibling = p.with_name(p.name[:-len(_TT_SUFFIX)] + f"_{corner}.lib")
        if not sibling.is_file():
            raise FileNotFoundError(
                f"主库 {p.name} 的 {corner} 角 {sibling} 不存在。12 份合并库的生成与"
                "常驻清单见 docs/toolchain.md；不补齐就不写记录，免得这一批静默少一角。")
        out[corner] = sibling
    return out


def _cell_model_files():
    """门级仿真读的单元 Verilog 模型。延迟 import：gate_sim 经 netlist_equiv 反向用到本模块。"""
    from flow.sim.gate_sim import cell_models
    return cell_models()


def cell_models_sha256():
    """单元模型按文件名排序，「文件名 + 内容」的哈希。模型不在仓库里，与 liberty 同理按内容进指纹。"""
    h = hashlib.sha256()
    for f in sorted(_cell_model_files(), key=lambda p: Path(p).name):
        h.update(Path(f).name.encode() + b"\0" + Path(f).read_bytes() + b"\0")
    return "sha256:" + h.hexdigest()


def flow_fingerprint(liberty, sim="icarus", *, design):
    """十项事实加一个合成指纹。纯函数：同一环境下连算两次结果逐字相同。

    `design` 必填（fingerprint-per-design D3）：指纹按设计算，漏传当场 TypeError，
    不退回不含设计配方的全仓指纹。
    """
    if sim not in SIM_VERSION_CMD:
        raise ValueError(f"未知的仿真器 {sim!r}，认识的是 {sorted(SIM_VERSION_CMD)}")
    facts = {
        "yosys": _tool_version(["yosys", "-V"]),
        "opensta": _tool_version(["sta", "-version"]),
        # 仿真那一项记的是**整条产出活动率的链**，不只是仿真器可执行文件。
        # 两层的版本串原样拼在一起，中间用 " + " 隔开：对不上的时候要能一眼看出
        # 是哪一层不同，而不是只知道"这一项变了"。
        "sim": (f"{sim} {_tool_version(SIM_VERSION_CMD[sim])}"
                f" + {SIM_DRIVER_PACKAGE} {_driver_version()}"),
        "liberty_sha256": _sha256_bytes(Path(liberty).read_bytes()),
        "synth_recipe_sha256": synth_recipe_sha256(),
        "sta_recipe_sha256": sta_recipe_sha256(),
        "metrics_code_sha256": metrics_code_sha256(),
        "corner_liberty_sha256": {c: _sha256_bytes(p.read_bytes())
                                  for c, p in corner_liberties(liberty).items()},
        "cell_models_sha256": cell_models_sha256(),
        "design_recipe_sha256": design_recipe_sha256(design),
    }
    # 指纹就是这十项的规范 JSON 的哈希：加一项事实、或者把某一项取得更全，
    # 都会改变全部记录的指纹 —— 那是对的，那时确实换了"我们知道哪些事实决定
    # 结果"这件事本身。
    canonical = json.dumps(facts, sort_keys=True, ensure_ascii=False)
    return {"fingerprint": _sha256_text(canonical), **facts}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--sim", default="icarus", choices=sorted(SIM_VERSION_CMD))
    ap.add_argument("--design", required=True, help="被测顶层（指纹按设计算）")
    args = ap.parse_args()
    print(json.dumps(flow_fingerprint(args.liberty, args.sim, design=args.design), indent=2,
                     ensure_ascii=False))


# --- 读取侧：记录属于哪一代 ---------------------------------------------------
# 下面这几个函数**只读记录**，不起子进程、不碰工具，`scripts/score.py` 有一条
# "不起任何子进程"的测试断言，靠的就是这一点。分代的规则只写这一份，
# `gen_report.py` 与 `score.py` 共用。

def generation_key(record):
    """这条记录属于哪一代。返回一个可哈希的键，不要拿它去给人看（用 label）。

    带 `flow` 段的按指纹分代。没有的（2026-09-09 之前的记录）归入"未知代"，
    并按 `git_commit` 再分组 —— 同一个 commit 至少意味着同一份流程代码，
    这是对老记录能做到的最好近似。**它只用于分组，不是指纹**：同一 commit 下
    换掉 liberty 是认不出来的，所以未知代永远不与任何带指纹的代合并。
    """
    fingerprint = (record.get("flow") or {}).get("fingerprint")
    if fingerprint:
        return ("flow", fingerprint)
    return ("legacy", record.get("git_commit") or "")


def generation_label(key):
    """给人看的短标签。"""
    kind, value = key
    if kind == "flow":
        return f"flow={value.split(':')[-1][:8]}"
    return f"未知代（无 flow 段，commit={(value or '?')[:7]}）"


def split_by_generation(records):
    """{代: [记录…]}，保持传入的顺序（jsonl 是追加写的，顺序就是时间序）。"""
    out = {}
    for rec in records:
        out.setdefault(generation_key(rec), []).append(rec)
    return out


def latest_generation(records):
    """最新一代 = 序列里**最后一条**记录所属的代；records 为空时返回 None。

    不用 timestamp：它是字符串，且同一批扫参里各条只差几秒，按文件序更直白，
    也让报告的输出稳定（`REPORT.md` 要求逐字节可复现）。
    """
    return generation_key(records[-1]) if records else None
