"""设计根解析、参数校验、单次产物目录。

设计树有两棵，布局对等，用同一套逻辑解析：专用设计树 `designs/`，构件树 `cbb/`。
专用设计与构件的区别只在依赖方向（构件被别的设计例化），不在结构。开源与闭源的设计根
同放这两棵树，开源与否只看开源白名单 `flow/export/manifest.yaml`（用户 2026-10-15，内部#305）。
设计根都在仓库根下第二层，「设计根的上两级就是仓库根」因此一直成立。
流程代码不应出现设计树的字面量：要遍历用 `DESIGN_TREES`，要分类用 `CBB_TREES`。
"""
import itertools
import re
import uuid
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

# 全部设计树，唯一的权威名单（fast_check、freeze、sigeq 都由它派生）。不存在的树跳过；
# 同一个顶层名在两处被声明时报错，不静默择一。
DESIGN_TREES = ("designs", "cbb")
# 其中的构件树：deps 只能指向这里；fast_check 按它区分构件与专用设计的文档口径。
CBB_TREES = ("cbb",)

# 本地 CBB 副本名单（rtl-structure-authority「模块名必须全大写」的例外）：全仓一份，
# 加上各设计根自带的一份，取并集（内部#305：设计根专属的条目随设计根走）。
LOCAL_CBB_LIST = "flow/lint/local_cbb.txt"
LOCAL_CBB_ROOT_LIST = "local_cbb.txt"


def is_cbb_path(rel):
    """仓库根相对路径是否落在构件树（`CBB_TREES`）里。"""
    return Path(rel).parts[:1] in [(t,) for t in CBB_TREES]


def tree_glob(pattern, kind=None, repo_root=".", recursive=False):
    """在每棵设计树下展开 `<树>/<pattern>`，返回仓库根相对路径（排序、去重）。

    `kind` 为 "cbb" 只看构件树，"design" 只看专用设计树，None 看全部。`pattern`
    以 `/` 结尾时结果也保留结尾的 `/`（与 `glob` 对目录模式的行为一致）。
    fast_check 的各段检查都经它遍历，不再各写一份 `designs/*`、`cbb/*`。
    """
    import glob
    import os
    trees = [t for t in DESIGN_TREES
             if kind is None or (kind == "cbb") == (t in CBB_TREES)]
    out = set()
    for t in trees:
        for hit in glob.glob(os.path.join(str(repo_root), t, pattern), recursive=recursive):
            rel = os.path.relpath(hit, str(repo_root))
            out.add(rel + "/" if pattern.endswith("/") else rel)
    return sorted(out)


def local_cbb_copies(repo_root="."):
    """本地 CBB 副本名单：({路径: 应有的模块名}, [问题])，路径与问题都是仓库根相对的。

    全仓名单的每一行要落在某个专用设计根的 `rtl/` 下；设计根自带的名单只能列**本根**
    `rtl/` 下的文件。文件要存在，文件名全小写，模块名就是文件名去掉 `.v`。
    """
    import os
    import re
    repo_root = Path(repo_root)
    design_trees = "|".join(re.escape(t) for t in DESIGN_TREES if t not in CBB_TREES)
    lists = [(LOCAL_CBB_LIST, rf"(?:{design_trees})/[^/]+")]
    for rel in tree_glob(f"*/{LOCAL_CBB_ROOT_LIST}", kind="design", repo_root=repo_root):
        lists.append((rel, re.escape(os.path.dirname(rel))))
    found, problems = {}, []
    for listfile, root_re in lists:
        path = repo_root / listfile
        if not path.is_file():
            continue
        entry = re.compile(rf"{root_re}/rtl/([a-z][a-z0-9_]*)\.v")
        for no, line in enumerate(path.read_text().splitlines(), 1):
            p = line.split("#", 1)[0].strip()
            if not p:
                continue
            m = entry.fullmatch(p)
            if m and (repo_root / p).is_file():
                found[p] = m.group(1)
                continue
            where = "本设计根" if listfile != LOCAL_CBB_LIST else "某个设计根"
            problems.append(f"{listfile}:{no}: {p} 不存在，或不在{where}的 rtl/ 下（本地 CBB 副本名单）")
    return found, problems


# 设计没在 params.yaml 里声明 sim.clock_signal 时的约定回退端口名。
# 回退只是省事，不是兜底：拼出来的名字在 VCD 里找不到会报错（见 vcd_stats）。
DEFAULT_CLOCK_PORT = "clk"


class DesignRootError(Exception):
    pass


class ParamError(Exception):
    pass


_MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)


def _declared_tops(root):
    """一个设计根声明的 {顶层名: 该顶层的配置}。没有 `tops:` 段时报错。

    **不提供「省略 `tops:` 时以目录名为顶层」的回退。** 留了回退就有两条解析
    路径，而只有一条会被日常使用 —— 另一条的失效是静默的，只在有人真的漏写时
    暴露，而那正是最需要报错的时刻。本仓踩过同形的坑（两个 SKIP 开关口径不同、
    输出长得一模一样，`CLAUDE.md` 为此专门写了一段）。
    """
    path = root / "params.yaml"
    if not path.is_file():
        raise ParamError(f"设计根 {root} 缺少 params.yaml")
    doc = yaml.safe_load(path.read_text()) or {}
    tops = doc.get("tops")
    if not isinstance(tops, dict) or not tops:
        raise ParamError(
            f"{path} 没有 `tops:` 段。一个设计根 MUST 显式声明它的被测顶层，"
            f"只有一个顶层时同样要写 —— 流程不提供「省略 tops: 时以目录名为顶层」"
            f"的回退（openspec/specs/repo-layout/spec.md 的"
            f"「设计根可以声明多个被测顶层」）。"
        )
    return tops


def _spec_only(root):
    """规格先行的设计根：既没有 `params.yaml` 也没有 `rtl/`，只放规格（repo-layout
    「设计根可以先只有规格」，内部#74）。解析跳过它。

    有 `rtl/` 却没有 `params.yaml` 不算 —— 那是漏写了被测顶层声明，交给
    `_declared_tops` 照旧报错。两样都没有、也没有规格的空目录同样报错：它不是
    任何一种合法形态，静默跳过会让拼错的目录名永远没人发现。
    """
    if (root / "params.yaml").is_file() or (root / "rtl").exists():
        return False
    doc = root / "doc"
    has_spec = any(root.glob("spec.*.md")) or any(root.glob("lrs.*.md")) or (
        doc.is_dir() and any(p.is_file() for p in doc.rglob("*")))
    if not has_spec:
        raise DesignRootError(
            f"设计根 {root} 既没有 params.yaml / rtl/，也没有规格（spec.*.md、lrs.*.md 或 doc/ 下的文件）。"
            f"规格先行的设计根至少要有一份规格（openspec/specs/repo-layout/spec.md 的"
            f"「设计根可以先只有规格」）")
    return True


def _top_index(repo_root=REPO_ROOT):
    """{顶层名: (设计根路径, 该顶层的配置)}，扫 designs/ 与 cbb/ 下全部设计根。

    顶层名在两处被声明时报错并指出两处，MUST NOT 静默择一 —— 静默择一意味着
    「跑的是哪一份」取决于目录遍历顺序，而记录里看不出来。
    """
    repo_root = Path(repo_root)
    index = {}
    for tree in DESIGN_TREES:
        base = repo_root / tree
        if not base.is_dir():
            continue
        for root in sorted(p for p in base.iterdir() if p.is_dir()):
            if _spec_only(root):
                continue
            for top, cfg in _declared_tops(root).items():
                if top in index:
                    raise DesignRootError(
                        f"顶层名 {top!r} 被两个设计根同时声明，无法唯一解析: "
                        f"{index[top][0]}; {root}"
                    )
                index[top] = (root, cfg or {})
    return index


def resolve_design_root(design, repo_root=REPO_ROOT):
    """按**被测顶层名**找到它所在的设计根。

    参数名仍叫 `design` 是因为它就是记录里 `design` 字段的值，也是全部 CLI 的
    `--design` —— 那个字段一直是、今后也是**被测顶层名**（在「设计根名 MUST 等于
    顶层名」成立的全部历史里两者被强制相同，所以历史记录不受影响，见
    `openspec/specs/experiment-record/spec.md` 的「记录必须区分被测顶层与它所在的
    设计根」）。变的只是**怎么从这个名字找到目录**：以前拼目录名，现在查声明。
    """
    index = _top_index(repo_root)
    if design not in index:
        raise DesignRootError(
            f"没有设计根声明顶层 {design!r}。已声明的顶层是 "
            f"{sorted(index)}（各设计根 params.yaml 的 `tops:` 段）"
        )
    root, _ = index[design]
    # 声明了但 rtl/ 下没有，最坏的结局不是报错而是综合器挑了别的模块照常出数。
    rtl = root / "rtl"
    declared_here = set()
    for src in sorted(rtl.glob("*.v")) + sorted(rtl.glob("*.sv")):
        declared_here.update(_MODULE_RE.findall(src.read_text()))
    if design not in declared_here:
        raise DesignRootError(
            f"设计根 {root.name} 声明了顶层 {design!r}，但它的 rtl/ 下没有同名 "
            f"module。{rtl} 里声明的是 {sorted(declared_here)}"
        )
    return root


def include_dirs(design, repo_root=REPO_ROOT):
    """该顶层的 include 目录：它的设计根与 `deps` 传递闭包里各 cbb 根的 `rtl/inc/`，
    存在的才列，按路径排序（repo-layout「参数片段的位置与 include 目录」，内部#76）。

    片段不在 params.yaml 里声明（用户 2026-10-01 选定）：多一个声明就多一个「忘了写，
    某个工具里找不到文件」的开关。综合、RTL 仿真、等价证明、fast_check 都经这里取，
    同一份口径。片段不是编译单元，只给 `-I`，不当源文件交给工具。
    """
    repo_root = Path(repo_root)
    roots = [resolve_design_root(design, repo_root)] + [
        r for _, r in dependency_roots(design, repo_root)]
    return sorted({r / "rtl" / "inc" for r in roots if (r / "rtl" / "inc").is_dir()})


def include_files(design, repo_root=REPO_ROOT):
    """include 目录下的全部参数片段（`*.vh`），按路径排序。"""
    return sorted(f for d in include_dirs(design, repo_root) for f in d.glob("*.vh"))


def dependency_roots(design, repo_root=REPO_ROOT):
    """该顶层声明的构件依赖，按传递闭包展开：[(构件顶层名, 它的设计根), ...]。

    依赖写在 `tops:<顶层>:deps:`，每项是**构件的顶层名**（add-design-cbb-deps 的 D1），
    与流程其他地方一样按顶层名解析。三条规则各对应一种安静的失效：

    - 名字必须是某个设计根声明过的顶层 —— 拼错的名字若被跳过，读入集合就少一份，
      而缺的那个模块会在别处以「找不到模块」的面目出现，看不出是声明写错了；
    - 只许指向构件树（`CBB_TREES`）—— IP 之间共用的模块要搬进构件树（repo-layout
      「跨设计根复制的源文件必须逐字节相同」），不能让一个 IP 读另一个 IP 的 rtl/；
    - 成环报错 —— 环本身无害，但它几乎总是笔误，而展开时静默去重会把它藏起来。

    「声明了但没被例化」要等 yosys 求出存活模块才能判断，在
    `flow/synth/synth.py::source_files` 里查。
    """
    repo_root = Path(repo_root)
    index = _top_index(repo_root)
    resolve_design_root(design, repo_root)   # 顶层本身的存在性与 rtl/ 校验
    cbb_trees = {repo_root / t for t in CBB_TREES}
    out, seen = [], set()

    def walk(top, chain):
        deps = index[top][1].get("deps") or []
        if not isinstance(deps, list):
            raise ParamError(f"{top} 的 deps 必须是顶层名的列表，收到 {deps!r}")
        for dep in deps:
            if dep in chain:
                raise DesignRootError(
                    f"deps 成环：{' -> '.join(chain + [dep])}")
            if dep not in index:
                raise DesignRootError(
                    f"{top} 的 deps 里的 {dep!r} 不是任何设计根声明的顶层。"
                    f"deps 写的是构件的**顶层名**（如 CBB_LZD），不是目录名")
            dep_root = index[dep][0]
            if dep_root.parent not in cbb_trees:
                raise DesignRootError(
                    f"{top} 的 deps 里的 {dep!r} 在 {dep_root}，deps 只能指向构件树 "
                    f"{'/、'.join(CBB_TREES)}/ 下的构件。IP 之间共用的模块应当搬进构件树")
            if dep not in seen:
                seen.add(dep)
                out.append((dep, dep_root))
            walk(dep, chain + [dep])

    walk(design, [design])
    return out


def rtl_candidates(design, repo_root=REPO_ROOT):
    """该顶层的候选源文件：本根 `rtl/*.v` 加上各依赖根的 `rtl/*.v`，按路径排序、去重。

    这是「读哪些文件」的**唯一**定义：综合 / 仿真经 `source_files` 从这里取候选再求
    闭包，`scripts/fast_check.sh` 的 elaborate / lint 直接用这张表（D3）。两处各写
    一份就是两条口径。没有 `deps` 的顶层返回的正是改动之前的 `sorted(rtl.glob("*.v"))`。
    """
    roots = [resolve_design_root(design, repo_root)]
    roots += [root for _, root in dependency_roots(design, repo_root)]
    files = set()
    for root in roots:
        files.update((root / "rtl").glob("*.v"))
    return sorted(files)


def load_design_config(design, repo_root=REPO_ROOT):
    """**该顶层**那一段配置（`tops:` 下以它为 key 的那个块）。

    ⚠️ 不是整份 params.yaml。同一个设计根下两个顶层的 `sim` / `sta` 可以完全
    相反（同一个根下，组合顶层是 `clock_signal: null` / `ideal=[]`，
    时序顶层是 `clk` / `[rst_n]`），取错一层是**静默失效**：
    STA 照常出数，只是那个数在测别的东西。
    """
    index = _top_index(repo_root)
    if design not in index:
        # 让 resolve_design_root 给出统一的报错文案（它同时负责 rtl/ 缺失那一条）
        resolve_design_root(design, repo_root)
    return index[design][1]


def score_baseline(design, repo_root=REPO_ROOT):
    """打分的归一化基线（ppa-scoring，内部#314）：该顶层的 `tops:<顶层>:score_baseline:`，没写返回 None。

    只给 `scripts/score.py` 用，不进 `design_recipe`：基线是事后打分的分母，不影响任何测量，
    改它不换代。
    """
    base = load_design_config(design, repo_root).get("score_baseline")
    return None if base is None else dict(base)


def load_params_spec(design, repo_root=REPO_ROOT):
    """返回 params.yaml 的 `params` 段：{参数名: {"values": [...]}}。

    参数名就是 RTL 参数名（CARRY_STRUCT / PIPE_STAGES ...），流程原样转发给
    iverilog -P / yosys chparam / cocotb parameters，中间没有映射层。
    """
    return load_design_config(design, repo_root).get("params") or {}


def is_swept(spec):
    """该参数是否参与全量扫参。params.yaml 里写 `sweep: false` 表示不参与。

    动机是「只对别的参数的某些取值才有意义」的参数——比如 ADDER32 的 CSEL_BLOCK
    只对 CARRY_STRUCT=CSEL 有意义。把它放进叉乘会产生一堆参数标签不同、实际电路
    完全相同的冗余记录，污染实验记录（results/<设计根>/experiments.jsonl）。
    """
    return spec.get("sweep", True) is not False


def default_value(name, spec):
    """未给出取值时的默认值：values 列表的第一项。"""
    values = spec.get("values")
    if not values:
        raise ParamError(f"参数 {name} 没有声明 values，无法取默认值")
    return values[0]


def clock_port(design, repo_root=REPO_ROOT):
    """时钟**端口名**，纯组合设计返回 None。

    由设计在 params.yaml 的 `sim:` 段声明；未声明则回退到约定的 `clk`。
    `sim.clock_signal: null` 是显式声明「这个设计没有时钟」，与「没声明」不同。
    放在 `sim:` 段而不是 `params:` 段，是因为它不是扫描维度，混进去会被
    param_combos 当成一个维度枚举。

    **这个声明有两个消费者**：仿真侧按它在 VCD 里数周期（要的是全限定名，
    见 `clock_signal`），STA 侧按它 `create_clock`（要的是裸端口名，就是这里）。
    两处各自写死一个名字会让「设计改了时钟端口名」只在其中一处生效 ——
    STA 那一侧的回退尤其危险：工具找不到端口时只报一句警告就建一个虚拟时钟，
    照常出数（`openspec/specs/experiment-trust/spec.md` 的「无触发器的实现
    必须证明其时序结果来自真实路径」）。
    """
    sim = load_design_config(design, repo_root).get("sim") or {}
    return sim["clock_signal"] if "clock_signal" in sim else DEFAULT_CLOCK_PORT


# 单时钟设计里那个时钟的名字。**不跟着端口名走**：既有 92 条记录就是在这个
# 名字下测出来的，换名字会让 `sta.clocks[0].name` 与历史不可比。
DEFAULT_CLOCK_NAME = "clk"

_CLOCK_KEYS = ("name", "port", "period_ns")

# sta.clocks 的 period_ns 写这个字面量 = 周期取命令行的 --period-ns（clock-period-cli D1）
PERIOD_FROM_CLI = "cli"


def clocks(design, repo_root=REPO_ROOT):
    """这个设计的全部时钟，`[{"name", "port", "period_ns"}, ...]`。

    两种声明形式，**`sta.clocks` 优先**：

    - `sta.clocks:` —— 多时钟。每一项必须给全 `name` / `port` / `period_ns`。
      给不全就报错，MUST NOT 补默认值：漏掉的那一项决定 STA 建出什么约束，
      静默补一个等于让「声明写漏了」通过。`period_ns` 写数字，或显式写 `cli`
      表示取命令行的 `--period-ns`（解析成 `None`，内部#138）：同源同频同相的门控时钟
      这样写，再与主时钟放进同一个 `clock_groups`。
    - 没有 `sta.clocks` 时回退到 `sim.clock_signal`（见 `clock_port`），
      产出**一个**时钟，名字是约定的 `clk`、周期留给调用方（`period_ns` 为
      `None`，由 `--period-ns` 决定）—— 这是现有五个设计走的路，
      本变更一个 `params.yaml` 都不用改。

    纯组合设计（`sim.clock_signal: null` 且没有 `sta.clocks`）返回空列表。

    ⚠️ 周期在两种形式下的来源不同：多时钟时每个时钟自带周期（不同域周期不同
    才是多时钟的意义），单时钟时沿用命令行的 `--period-ns`。调用方要处理
    `period_ns is None` 这一支。
    """
    cfg = load_design_config(design, repo_root)
    declared = (cfg.get("sta") or {}).get("clocks")
    if declared is None:
        port = clock_port(design, repo_root)
        if port is None:
            return []
        return [{"name": DEFAULT_CLOCK_NAME, "port": port, "period_ns": None}]

    if not declared:
        raise ParamError(
            f"设计 {design!r} 的 sta.clocks 是空列表。要声明「没有时钟」"
            f"请用 sim.clock_signal: null —— 空列表与它不可区分，"
            f"而两者写错的后果不同。")
    out = []
    for i, item in enumerate(declared):
        item = item or {}
        missing = [k for k in _CLOCK_KEYS if item.get(k) is None]
        if missing:
            raise ParamError(
                f"设计 {design!r} 的 sta.clocks[{i}] 缺 {missing}。"
                f"三项都必须给全：漏掉哪一项都会改变 STA 建出的约束，"
                f"而补一个默认值会让这个疏漏静默通过。")
        period = item["period_ns"]
        if isinstance(period, str):
            if period != PERIOD_FROM_CLI:
                raise ParamError(
                    f"设计 {design!r} 的 sta.clocks[{i}].period_ns 是 {period!r}：只能写数字，"
                    f"或写 {PERIOD_FROM_CLI!r} 表示取命令行的 --period-ns（#138）。")
            period = None
        out.append({"name": item["name"], "port": item["port"], "period_ns": period})
    names = [c["name"] for c in out]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ParamError(
            f"设计 {design!r} 的 sta.clocks 里时钟名重复：{dup}。"
            f"名字是分组与记录里认它的依据，重名会让两者指向不确定的一个。")
    return out


def clock_groups(design, repo_root=REPO_ROOT):
    """时钟分组，`[[时钟名, ...], ...]`。同组内按同步处理，组间按异步处理。

    **未声明时默认「每个时钟自成一组」，也就是互为异步。** 取保守的那一侧是
    有实测依据的（OpenSTA 3.1.0，2026-09-15）：不设分组时，跨异步域的路径会被
    当作真实路径参与 setup 分析，`worst_slack` 取自一条 `clk_a` 发、`clk_b` 收的
    路径（0.9233），设了分组之后是域内的（4.9233）—— 两个都是 `slack (MET)`、
    都不触发警告、差 5.3 倍，而前者不说明电路的任何性质。

    声明了就必须**分全**：漏掉一个时钟报错，不给它默默补一组。补一组是「合理的
    默认」，但它让「漏写」与「有意把它单独分出来」不可区分，而两者对跨域路径的
    处理完全相同、对读记录的人含义完全不同。
    """
    declared_clocks = clocks(design, repo_root)
    known = [c["name"] for c in declared_clocks]
    if not known:
        return []

    groups = (load_design_config(design, repo_root).get("sta") or {}).get("clock_groups")
    if groups is None:
        return [[name] for name in known]

    seen = []
    for i, group in enumerate(groups):
        unknown = [n for n in group if n not in known]
        if unknown:
            raise ParamError(
                f"设计 {design!r} 的 sta.clock_groups[{i}] 里有没声明过的时钟名 "
                f"{unknown}；已声明的是 {known}。静默忽略它会让你以为两个域被并成了"
                f"同步组，而实际那一组只有一个时钟、跨域路径照样被排除 —— "
                f"一个看起来生效但没有的约束。")
        seen.extend(group)
    missing = [n for n in known if n not in seen]
    if missing:
        raise ParamError(
            f"设计 {design!r} 声明了 sta.clock_groups，但 {missing} 不在任何一组里。"
            f"声明了就要分全 —— 给漏掉的时钟默默补一组，会让「漏写」与"
            f"「有意把它单独分出来」不可区分。")
    dup = sorted({n for n in seen if seen.count(n) > 1})
    if dup:
        raise ParamError(
            f"设计 {design!r} 的 sta.clock_groups 里 {dup} 出现在多个组中。"
            f"一个时钟同时属于两组时，它与哪些时钟同步是不确定的。")
    return [list(g) for g in groups]


_STATIC_KINDS = ("false_path", "multicycle")
_REQ_ID = re.compile(r"R\.\d{3}")


def static_ports(design, repo_root=REPO_ROOT):
    """时序分析里按 false path / multicycle 处理的输入端口（sta-static-ports，内部#154）。

    `tops:<顶层>:sta:static_ports:` 的每一项：`ports`（端口名或通配，一个或多个）、
    `kind`（`false_path` 或 `multicycle`）、`cycles`（只给 multicycle，≥ 2）、
    `by`（接口文档里担保这些端口可以这样处理的需求 `R.xxx`）。用户 2026-10-04：
    「正式 STA 也排除，但你要在设计上就保证这里可以设 false_path 或 multicycle」——
    所以 `by` 必填，fast_check 核它在接口文档里有定义。写错当场报错，不补默认值。
    返回 `[{"ports": [...], "kind", "cycles", "by"}]`，未声明返回空表。
    """
    declared = (load_design_config(design, repo_root).get("sta") or {}).get("static_ports") or []
    if not isinstance(declared, list):
        raise ParamError(f"设计 {design!r} 的 sta.static_ports 要写成列表")
    out = []
    for i, item in enumerate(declared):
        where = f"设计 {design!r} 的 sta.static_ports[{i}]"
        if not isinstance(item, dict):
            raise ParamError(f"{where} 要写成 {{ports, kind, by}} 映射")
        missing = [k for k in ("ports", "kind", "by") if item.get(k) in (None, "", [])]
        if missing:
            raise ParamError(f"{where} 缺 {missing}：by 是担保这些端口可以排除的需求编号，必须写")
        ports = item["ports"] if isinstance(item["ports"], list) else [item["ports"]]
        kind, cycles, by = item["kind"], item.get("cycles"), item["by"]
        if kind not in _STATIC_KINDS:
            raise ParamError(f"{where} 的 kind 是 {kind!r}，只能是 {list(_STATIC_KINDS)}")
        if kind == "multicycle" and (not isinstance(cycles, int) or cycles < 2):
            raise ParamError(f"{where} 是 multicycle，cycles 要写成 ≥ 2 的整数，实得 {cycles!r}")
        if kind == "false_path" and cycles is not None:
            raise ParamError(f"{where} 是 false_path，不该写 cycles（{cycles!r}）")
        if not isinstance(by, str) or not _REQ_ID.fullmatch(by):
            raise ParamError(f"{where} 的 by 是 {by!r}，要写成接口文档里的需求编号 R.<三位数字>")
        out.append({"ports": [str(x) for x in ports], "kind": kind,
                    "cycles": cycles if kind == "multicycle" else None, "by": by})
    return out


_SCENARIO_NAME = re.compile(r"[A-Za-z_][\w-]*")


def scenarios(design, params=None, repo_root=REPO_ROOT):
    """该顶层声明的验收场景（内部#189；sta-scenarios）：`tops:<顶层>:sta:scenarios:`，每项
    `{name, case: {静态输入端口: 值}, by: R.xxx}`。

    互斥排布由静态输入选择时，STA 把这些输入定值（set_case_analysis）各跑一遍：`make depth` 按场景验收级数，
    正式 STA 另写按场景的时序（记录的 `sta.scenarios`）。`by` 是接口文档里担保该输入静态的需求，与
    `static_ports` 同一纪律，fast_check 核它有定义、端口是输入、值不超位宽。写错当场报错，不补默认值。
    可选的 `when: {参数: 值 | [值, …]}`（内部#198）限定场景适用的参数组合：各键之间是「与」，值列表是该参数的「或」；
    键必须是 params.yaml 声明的参数，值必须在它的 values 里。没写 `when` 的场景对所有组合适用。
    返回 `[{"name", "case", "by", "when"}]`（`when` 归一成 {参数: [值, …]}，没写为 None），未声明返回空表。
    给了 `params`（一个参数组合）就只返回适用的场景；`when` 的键不在组合里时报错，不取默认值 ——
    depth 的 `--param` 可以只给一部分，悄悄补默认值会量错场景。
    """
    declared = (load_design_config(design, repo_root).get("sta") or {}).get("scenarios") or []
    if not isinstance(declared, list):
        raise ParamError(f"设计 {design!r} 的 sta.scenarios 要写成列表")
    out, names = [], set()
    for i, item in enumerate(declared):
        where = f"设计 {design!r} 的 sta.scenarios[{i}]"
        if not isinstance(item, dict) or not {"name", "case", "by"} <= set(item) <= {"name", "case", "by", "when"}:
            raise ParamError(f"{where} 要写全 name / case / by，另外只能写 when：{item!r}")
        name, case, by = item["name"], item["case"], item["by"]
        if not isinstance(name, str) or not _SCENARIO_NAME.fullmatch(name) or name in names:
            raise ParamError(f"{where} 的 name 要是不重复的标识符：{name!r}")
        if not isinstance(case, dict) or not case or not all(
                isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0
                for k, v in case.items()):
            raise ParamError(f"{where} 的 case 要是非空的 {{端口: 非负整数}}：{case!r}")
        if not isinstance(by, str) or not _REQ_ID.fullmatch(by):
            raise ParamError(f"{where} 的 by 是 {by!r}，要写成接口文档里的需求编号 R.<三位数字>")
        when = _scenario_when(design, where, item.get("when"), "when" in item, repo_root)
        names.add(name)
        out.append({"name": name, "case": dict(case), "by": by, "when": when})
    if params is None:
        return out
    return [sc for sc in out if _when_matches(design, sc, params)]


def _scenario_when(design, where, when, given, repo_root):
    """校验并归一 `when`：{参数: [值, …]}；没写返回 None。"""
    if not given:
        return None
    if not isinstance(when, dict) or not when:
        raise ParamError(f"{where} 的 when 要是非空的 {{参数: 值 | [值, …]}}：{when!r}")
    declared = load_params_spec(design, repo_root)
    out = {}
    for name, vals in when.items():
        if name not in declared:
            raise ParamError(f"{where} 的 when 用了未声明的参数 {name!r}；已声明的是 {sorted(declared)}")
        vals = vals if isinstance(vals, list) else [vals]
        allowed = declared[name].get("values")
        resolved = []
        for v in vals:
            match = [a for a in (allowed or []) if a == v or str(a) == str(v)]
            if not match:
                raise ParamError(f"{where} 的 when 给 {name} 的值 {v!r} 不在它的 values {allowed} 里")
            resolved.append(match[0])
        out[name] = resolved
    return out


def _when_matches(design, sc, params):
    if sc["when"] is None:
        return True
    missing = [k for k in sc["when"] if k not in params]
    if missing:
        raise ParamError(f"设计 {design!r} 的场景 {sc['name']} 按 {missing} 选组合，参数组合里没给这几个（不补默认值）")
    return all(any(v == params[k] or str(v) == str(params[k]) for v in vals) for k, vals in sc["when"].items())


def clock_signal(design, repo_root=REPO_ROOT):
    """VCD 中时钟信号的全限定名，纯组合设计返回 None。

    只是 `clock_port` 之上的一层拼接 —— 声明仍然只有一份。
    """
    port = clock_port(design, repo_root)
    if port is None:
        return None
    return f"{design}.{port}"


def validate_params(design, params, repo_root=REPO_ROOT):
    """校验参数名与取值都在 params.yaml 里声明过，返回带 yaml 声明类型的取值。

    取值也要校验：RTL 里 `CARRY_STRUCT` 的分派是 if/else-if 链，没有 else，
    传一个拼错的值不会报错，只会综合出一个悬空的电路——正是「流程跑通了但
    指标不可信」那类翻车。宁可在这里拒掉。
    """
    declared = load_params_spec(design, repo_root)
    unknown = sorted(set(params) - set(declared))
    if unknown:
        raise ParamError(
            f"设计 {design!r} 的 params.yaml 未声明参数 {unknown}；"
            f"已声明的是 {sorted(declared)}"
        )
    # 缺失的参数：只有不参与扫参的那些可以省略（回填 values[0]）。扫参维度缺失
    # 通常是笔误，照旧报错——这个守卫是有价值的，不要为了少敲几个字拆掉它。
    missing = sorted(set(declared) - set(params))
    required_missing = [n for n in missing if is_swept(declared[n])]
    if required_missing:
        raise ParamError(f"设计 {design!r} 缺少参数取值 {required_missing}")
    if missing:
        params = dict(params)
        for name in missing:
            params[name] = default_value(name, declared[name])

    resolved = {}
    for name, value in params.items():
        allowed = declared[name].get("values")
        if allowed is None:
            resolved[name] = value
            continue
        # CLI 传进来的都是字符串，按字面量比对后回填 yaml 里声明的类型
        match = [a for a in allowed if a == value or str(a) == str(value)]
        if not match:
            raise ParamError(
                f"参数 {name} 的取值 {value!r} 未在 params.yaml 中声明；"
                f"允许的取值是 {allowed}"
            )
        resolved[name] = match[0]
    return resolved


def param_combos(design, repo_root=REPO_ROOT):
    """params.yaml 声明的全部参数组合，用于扫参。

    只有 is_swept() 为真的参数进入叉乘；其余取 values[0] 填进每个组合。
    填而不是省，是因为记录的 params 段不能缺键——缺了就没法只凭该段复现一次运行。
    键顺序保持 params.yaml 的声明顺序。
    """
    declared = load_params_spec(design, repo_root)
    swept = [n for n in declared if is_swept(declared[n])]
    fixed = {n: default_value(n, declared[n]) for n in declared if n not in swept}
    for combo in itertools.product(*(declared[n]["values"] for n in swept)):
        picked = dict(zip(swept, combo))
        yield {n: picked[n] if n in picked else fixed[n] for n in declared}


def params_slug(params):
    """参数组合的稳定短标识，用于 experiment_id 与目录名。"""
    return "-".join(f"{v}" for _, v in sorted(params.items()))


def new_experiment_id(design, params):
    return f"{design}-{params_slug(params)}-{uuid.uuid4().hex[:8]}"


def run_dir(experiment_id, stage=None, repo_root=REPO_ROOT):
    """单次实验的原始产物目录：runs/<experiment_id>/[<stage>/]。

    `runs/` 在 .gitignore 里，且以 experiment_id 分目录，所以扫 N 个组合会得到
    N 个互不覆盖的目录，也不会有任何东西落进设计根内部。
    """
    d = Path(repo_root) / "runs" / experiment_id
    if stage:
        d = d / stage
    return d


def ideal_drive_ports(design, repo_root=REPO_ROOT):
    """STA 按**理想驱动**建模的输入端口名，未声明则返回空列表。

    由设计在 params.yaml 的 `sta:` 段声明，理由与时钟一样：这个流程既不综合时钟树，
    也不综合复位树。一个压缩流水设计的 `rst_n` 扇出到 2433 个触发器的复位端，
    负载约 1200 fF —— 是 `BUFx2` 自己 `max_capacitance`（92.16 fF）的 13 倍。
    给它设一个 BUFx2 的话，那一跳就要 3.56 ns，关键路径从 REG→REG 的 0.688330
    变成这条 recovery 路径的 3.434010。**那个数度量的是驱动网络的缺席，不是电路。**

    键名说的是**建模决定**而不是信号角色：判据是"扇出超过驱动单元能扛的"，
    与这个端口叫什么、干什么无关。将来出现别的广播端口（全局 enable、flush）
    同一条规则直接适用。

    未声明时回退到"全部输入都设驱动单元"，**不按名字猜哪个是复位** ——
    `flow-parameterization` 明确禁止流程代码内嵌具体设计的信号命名假设。
    漏声明不会静默变对：`tests/test_sta_boundary.py` 会算出超标的端口并报错。
    """
    sta = load_design_config(design, repo_root).get("sta") or {}
    return list(sta.get("ideal_drive_ports") or [])


def keep_hierarchy_modules(design, repo_root=REPO_ROOT):
    """综合时要**保住层级**的模块名，未声明则返回空表。

    由设计在 params.yaml 的 `synth:` 段按**被测顶层**声明，与 `sim:` / `sta:` 同级。
    2026-09-21 之前这件事是 RTL 里的一个 `(* keep_hierarchy *)` 属性（本仓 内部#46
    的 2.2）：那是综合指令，不该写在描述电路的文件里。

    **为什么按顶层而不是按设计根**：一个根可以挂多个顶层，而每个顶层综合时只读入
    **它自己的依赖闭包**。同根的两个顶层闭包互不相交（例如压缩侧
    三块、解压侧两块），按根声明的话每个顶层下都有一批
    「不在本次设计里」的模块，流程就只能接受「声明的 ∩ 读进来的」——
    而那恰好让**打错的模块名**也被放行，判据当场退化成没有判据。

    ⚠️ 这个声明的失效是静默的，所以消费侧必须逐个校验命中：yosys 对选择不到的
    模块只打一句 `Warning: Selection "X" did not match any module.` 然后退出 0。
    校验在 `flow/synth/synth.py` 里，用 `select -assert-any`（见那里的注释）。
    没有校验的话，一个拼错的名字会让那一层静默地不再被保住，而
    `docs/pitfalls.md` 的 P-3 记着那意味着什么：ABC 的 `&dch` 把三种手写加法器
    结构收敛成同一个映射结果 —— 架构对比整条失效，而两边都不报错。
    """
    synth = load_design_config(design, repo_root).get("synth") or {}
    return list(synth.get("keep_hierarchy") or [])


def reference_ports(design, repo_root=REPO_ROOT):
    """参考口径（内部#202）必须接成常数的顶层输入端口模式（`tops:<顶层>:synth:reference_ports:`），未声明返回空表。

    参考口径按本组合唯一适用场景的 `case` 接常数；这里声明的模式匹配到的每个输入都要在 `case` 里有定值，
    漏一个就当场报错（flow/synth/reference.py）—— 否则漏定的那个照样是输入，参考值偏大也不会有任何东西失败。
    """
    synth = (load_design_config(design, repo_root).get("synth") or {})
    pats = synth.get("reference_ports") or []
    if not isinstance(pats, list) or not all(isinstance(x, str) and x for x in pats):
        raise ParamError(f"{design} 的 synth.reference_ports 必须是端口模式列表，现在是 {pats!r}")
    return list(pats)


def equiv_enabled(design, repo_root=REPO_ROOT):
    """该顶层要不要做网表等价证明（`tops:<顶层>:equiv:`，布尔，缺省 true；equiv-optional，内部#232）。

    用户 2026-10-06 定等价证明在流程里可选：规模大的设计在可接受的时间内证不完。
    声明了 false 的，参考口径不做参考网表等价（`reference.equiv = SKIPPED`，照常报数），
    事后的 `flow/equiv/netlist_equiv.py` 跳过它。
    """
    v = load_design_config(design, repo_root).get("equiv", True)
    if not isinstance(v, bool):
        raise ParamError(f"{design} 的 equiv 必须是 true / false，现在是 {v!r}")
    return v


def memory_models(design, repo_root=REPO_ROOT):
    """该顶层声明为**存储模型**的模块名（`tops:<顶层>:synth:memory_models:`），未声明返回空表。

    行为模型的 SRAM（实际芯片会换成工艺 SRAM）综合出来是触发器，会把逻辑
    面积撑大；记录的 `synth.area_breakdown.memory_models` 按这张表累计，报告据此给出「扣除存储
    模型后」的面积（area-breakdown，内部#174）。名字的校验在 `flow/synth/synth.py`（必须是本次读入的模块）。
    """
    synth = load_design_config(design, repo_root).get("synth") or {}
    names = synth.get("memory_models") or []
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        raise ParamError(f"{design} 的 synth.memory_models 必须是模块名列表，现在是 {names!r}")
    return list(names)


def adhoc_run_dir(design, stage, repo_root=REPO_ROOT):
    """独立调用某一段流程（没有 experiment_id）时的产物目录。"""
    return run_dir(f"adhoc-{design}-{uuid.uuid4().hex[:8]}", stage, repo_root)


def cli_params(pairs):
    """把命令行的 --param NAME=VALUE 列表转成 dict（取值的类型校验交给 validate_params）。"""
    out = {}
    for item in pairs:
        if "=" not in item:
            raise ParamError(f"--param 需要 NAME=VALUE 形式，收到 {item!r}")
        name, _, value = item.partition("=")
        out[name.strip()] = value.strip()
    return out
