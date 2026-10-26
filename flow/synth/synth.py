"""Yosys synthesis targeting an ASAP7 liberty cell library.

Usable as a library (run_synth()) from scripts/run_experiment.py, or standalone:
    python flow/synth/synth.py --design CBB_LZD --param DAT_W=32 --param MSB_EN=0 --param SCHEME=0 --liberty <path>

综合不加 -flatten，配合 RTL 上的 (* keep_hierarchy *)：否则 ABC 的 &dch 会跨模块
边界从布尔功能重推电路，把不同微架构收敛成同一个映射结果（见 docs/pitfalls.md 的 P-3）。

abc 必须带 -constr。yosys 对 -liberty 有两套默认 ABC 脚本（`yosys -h abc`）：
不给 -constr 时只有技术映射，给了才在末尾接上 buffer; upsize; dnsize; stime -p。
不给的后果不是精度损失而是量级错误 —— 一个 INVx1 可以硬扛 436 个负载
（超 max_capacitance 5 倍），一个 cell 就占掉关键路径的一半以上，
而且没有任何工具会报错。见 docs/data-credibility.md 的 D-3 与 tests/test_synth_electrical.py。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import (_declared_tops, adhoc_run_dir, cli_params,
                        dependency_roots, include_dirs, include_files,
                        keep_hierarchy_modules, resolve_design_root,
                        rtl_candidates, validate_params)
from flow.param_exclude import declared_combos


# --- 读入哪些源文件（本仓 内部#50）-------------------------------------------------
#
# 以前这里是 `sorted(rtl_dir.glob("*.v"))` —— 全读进来，靠 `synth -top` 里的
# `hierarchy` 删掉没用到的。删是删干净了（yosys 日志明确写着
# `Removing unused module`，产出的网表里只有一个模块、端口表逐字相同），
# 但**删得掉不等于没影响**：
#
#   一个 256 位宽的组合地址子块（一处例化都没有）的单元数
#   随 rtl/ 里有几份文件在 13 / 33 / 36 / 15 之间变，最大 2.5 倍。
#   固定读入集合连跑三次逐字节相同 —— 这是**确定性的偏差，不是运行间随机**。
#
# 确定性比随机更坏：随机会被察觉，确定性的偏差会被当成真实差异记进
# 实验记录（results/<设计根>/experiments.jsonl），而记录里没有任何字段能看出读入集合变过
# （所以这一批同时新增了 synth.sources_sha256）。
#
# 闭包由 yosys 自己算（`chparam` + `hierarchy -top`，看哪些模块活下来），
# 不手写 Verilog 解析：手写的解析在 `generate` 里的条件例化、参数化模块名、
# 宏展开这几处都会错，而错的方向是**少读一个文件**，那会让综合当场失败 ——
# 响亮，但也意味着流程会在正常情况下频繁误报。
#
# ⚠️ **取的是「该顶层在全部声明取值下的并集」，不是「本次参数下的闭包」。**
# 两者都试过，后者行不通，理由是实测出来的，不是推的：
#
#   1. 闭包是参数的函数。`ADDER32` 取 `CARRY_STRUCT=RIPPLE` 时例化
#      `ripple_adder`，取 `BRENT_KUNG` 时例化 `prefix_adder` 那三份。
#   2. 只读本次参数的那几份，yosys 会**在别处**失败：它照样要 elaborate 读进来的
#      每一个模块的**默认参数**形态，于是 `\adder_core`（默认 RIPPLE）引用的
#      `ripple_adder` 不在设计里 —— `ERROR: Module ... is not part of the design`。
#   3. 绕过它要 `read_verilog -defer`。而 `-defer` **本身就会改变综合结果**：
#      实测同一份源文件、同一组参数，只加这个开关，一个地址流水设计的面积
#      69.4737 → 69.7361（+0.38%）、一个压缩流水设计 393.3101 → 394.3307。
#      为了换一种取源口径而引入一个会动数字的解析开关，是拿两个混淆因子换一个。
#
# 并集还有一个好处：**同一个顶层的全部扫参点读同一组文件**，于是
# `synth.sources_sha256` 可以当横向可比性的判据用（experiment-record 的
# 「两条记录指纹相同而源文件摘要不同」）。按本次参数取闭包的话，
# `ADDER32` 六种进位结构的摘要各不相同，那个字段就只剩描述作用。
#
# 代价是并集要把声明得出来的每一组参数都探一遍（`ADDER32` 是 288 组，
# 一次 yosys 调用里 `design -load` 复用同一份读入，约 56 秒）。所以结果按
# 「全部候选文件的内容 + 涉及的各 params.yaml」的摘要缓存在 runs/ 下：键变了就重算，
# 不存在读到过期缓存的情况。候选跨进 cbb/ 依赖根之后（add-design-cbb-deps），
# 依赖文件与依赖根的 params.yaml（它的 deps 决定闭包）同样进键。
MODULE_DECL_RE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)

SOURCE_SET_CACHE = REPO_ROOT / "runs" / ".source_sets"


def _base_module_name(name):
    """yosys 打印的模块名映射回源码里写的那个名字。

    参数化例化会被派生成 `$paramod\\<名字>\\<参数>=<值>` 或
    `$paramod$<哈希>\\<名字>`，直接拿这串去和源码里的 `module <名字>` 比会全部落空 ——
    而落空的表现是「闭包里只剩顶层自己」，综合当场失败，不会静默。
    """
    if name.startswith("$paramod\\"):
        return name[len("$paramod\\"):].split("\\")[0]
    if name.startswith("$"):
        return name.split("\\")[-1]
    return name.lstrip("\\")


def _chparam_sets(params):
    """`chparam` 的 `-set` 串。字符串参数要带引号，数值原样。"""
    return " ".join(
        f'-set {k} "{v}"' if isinstance(v, str) else f"-set {k} {v}"
        for k, v in params.items())


def _all_declared_combos(root, design):
    """params.yaml 给这个顶层声明得出来的**全部**参数组合。

    与扫参的区别是这里**不尊重 `sweep: false`**：
    那个键只挡扫参，不挡 `make exp` 单跑一组，所以一个只在某个 `sweep: false`
    取值下才被例化的模块照样必须在读入集合里（`ADDER32`：288 组，不是 72 组）。
    `cross: false` 的参数叉乘里只取 values[0]，其余取值经 `sweep_points` 探到（内部#214）；
    展开在 `flow/param_exclude.py::declared_combos`，与 fast_check、sweep 同一处实现。
    不减 exclude，与以前一样。

    声明从**传进来的那个根**读，不是从 `design` 再查一遍 —— 两者本该一致，
    而「本该一致的两条路径」是测试替身最容易替掉一条的地方。
    """
    return declared_combos(design, _declared_tops(root)[design])


def _inc_flags(incs):
    """`read_verilog` 的 include 开关。没有 include 目录时是空串，脚本与以前逐字相同。"""
    return "".join(f"-I{d} " for d in incs)


def _alive_modules_over(sources, top, combos, yosys, incs=()):
    """一次 yosys 调用里把 `combos` 全探一遍，返回**并集**存活模块名。

    `design -save` / `design -load` 让 288 组共用同一次 `read_verilog`——
    重读源文件才是这件事的大头。
    """
    lines = [f"read_verilog {_inc_flags(incs)}{s}" for s in sources] + ["design -save RTL"]
    for combo in combos:
        chparam = _chparam_sets(combo)
        lines += ["design -load RTL"]
        if chparam:
            lines.append(f"chparam {chparam} {top}")
        lines += [f"hierarchy -check -top {top}", "tee -o /dev/stdout ls"]
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "probe.ys"
        script.write_text("\n".join(lines) + "\n")
        proc = subprocess.run([yosys, "-q", "-s", str(script)],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"解析 {top!r} 的模块依赖失败（yosys hierarchy）：\n"
            + (proc.stderr or proc.stdout)[-4000:]
            + f"\n若缺的是 cbb/ 下的构件，检查 {top} 在 params.yaml 里的 deps "
            "是否写了它（add-design-cbb-deps）")
    # `ls` 打印的是 "  <名字>" 的缩进列表，夹在 "modules:" 之后
    seen, collecting = set(), False
    for line in proc.stdout.splitlines():
        if line.strip().endswith("modules:"):
            collecting = True
            continue
        if collecting:
            name = line.strip()
            if not name or " " in name:
                collecting = False
                continue
            seen.add(_base_module_name(name))
    if top not in seen:
        raise RuntimeError(
            f"`hierarchy -top {top}` 之后 {top!r} 不在存活模块里，解析结果是 "
            f"{sorted(seen)} —— 不继续，否则会拿一个残缺的读入集合去综合")
    return seen


def _source_set_key(candidates, roots, design):
    """缓存键：每个候选文件的路径与内容，加上涉及的每个设计根的 params.yaml。

    这些决定并集的全部输入：候选文件是被探的源，本根 params.yaml 给出声明组合，
    依赖根的 params.yaml 里的 deps 决定哪些根进候选。键变了就重算，所以不存在
    读到过期缓存。路径按仓库相对写，换个 checkout 位置不该让缓存失效。
    """
    repo_root = roots[0].parent.parent
    h = hashlib.sha256()
    for src in candidates:
        h.update(src.relative_to(repo_root).as_posix().encode()); h.update(b"\0")
        h.update(src.read_bytes()); h.update(b"\0")
    for root in roots:
        h.update((root / "params.yaml").read_bytes()); h.update(b"\0")
    h.update(design.encode())
    return h.hexdigest()


def _read_cache(cache, key):
    """命中则返回缓存的相对路径表，否则 None。坏文件（空、截断）当未命中（内部#57）。"""
    try:
        cached = json.loads(cache.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("key") != key:
        return None
    return cached.get("files")


def source_files(design, yosys=None):
    """该被测顶层的源文件集合：它自己，加上它在**任何一组声明取值下**会例化到的模块。

    候选是 `flow.paths.rtl_candidates`：本根 `rtl/*.v` 加上 `deps` 声明的 cbb 构件根的
    `rtl/*.v`（add-design-cbb-deps）。返回按路径排序的列表。读入集合是一条能改变 PPA
    的自变量（本仓 内部#50），所以它必须由声明与例化关系确定，而不是由「目录里碰巧有什么」
    确定。为什么取并集而不是按本次参数取闭包，见本节开头的注释。
    """
    yosys = yosys or shutil.which("yosys")
    if yosys is None:
        raise RuntimeError("yosys not found in PATH (need oss-cad-suite env sourced)")
    root = resolve_design_root(design)
    repo_root = root.parent.parent
    deps = dependency_roots(design, repo_root)
    candidates = rtl_candidates(design, repo_root)
    incs = include_dirs(design, repo_root)
    if not candidates:
        raise FileNotFoundError(f"no RTL sources found in {root / 'rtl'}")

    # 片段会改参数、从而改存活模块，所以也进缓存键
    key = _source_set_key(candidates + include_files(design, repo_root),
                          [root] + [r for _, r in deps], design)
    cache = SOURCE_SET_CACHE / f"{design}.json"
    cached = _read_cache(cache, key)
    if cached is not None:
        return [repo_root / n for n in cached]

    alive = _alive_modules_over(candidates, design,
                                _all_declared_combos(root, design), yosys, incs)
    keep = [src for src in candidates
            if set(MODULE_DECL_RE.findall(src.read_text())) & alive]
    if not keep:
        raise RuntimeError(f"{design!r} 的读入集合算出来是空的（存活模块 {sorted(alive)}）")
    # 声明必须用上（D5）：一个依赖根的文件一个都没进读入集合，说明这条 deps 拼错了
    # 目标或已经过期。放行的话它什么也不改变 —— 正因如此它会一直留在那里误导读者。
    for dep, dep_root in deps:
        if not any(src.parent == dep_root / "rtl" for src in keep):
            raise RuntimeError(
                f"{design!r} 的依赖闭包里有 {dep}（{dep_root}），但它的模块在任何声明"
                f"取值下都没被例化。删掉这条 deps，或检查是否写错了构件")
    cache.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：先写临时文件再 os.replace，并发的读者要么读到旧文件、要么读到新文件，
    # 不会读到截断的空文件（本仓 内部#57；读侧另把坏文件当未命中）。
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(
        {"key": key, "files": [s.relative_to(repo_root).as_posix() for s in keep]},
        indent=2) + "\n")
    os.replace(tmp, cache)
    return keep


def sources_digest(sources):
    """读入集合的内容摘要：文件名与内容都进哈希，**与给出顺序无关**。

    与顺序无关是有意的：换个排序不是换了一组文件，摘要不该因此变化 ——
    否则这个字段会把「排序变了」报成「读的东西变了」，而那种噪音会让人不再看它。
    """
    h = hashlib.sha256()
    for src in sorted(Path(s) for s in sources):
        h.update(Path(src).name.encode())
        h.update(b"\0")
        h.update(Path(src).read_bytes())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def read_set_digest(design, sources):
    """记录里的 `synth.sources_sha256`：读入的源文件加上该顶层 include 目录下的参数片段
    （experiment-record「读入集合摘要必须包含参数片段」，内部#76）。

    片段改了参数就改了电路；不进摘要的话，跳过开关会把最该重跑的组合跳过（D-14 同形）。
    没有 `rtl/inc/` 的顶层与 `sources_digest(sources)` 逐字节相同，历史记录的摘要照样可比。
    """
    root = resolve_design_root(design)
    return sources_digest(list(sources) + include_files(design, root.parent.parent))


# ABC 的边界条件约束文件。它存在的**真正原因**不是里面那两行的取值，而是
# -constr 这个开关本身（见模块头注释）。刻意保持成两行、不加注释：
# 这个文件是原样交给 ABC 的 read_constr 的，它未必认 `#` 注释。
#
# - set_driving_cell 与 PDK 绑定。换 PDK 必须改这里的 cell 名，否则 ABC 找不到它。
#   BUFx2 是 ASAP7 最小的缓冲之一（area 0.0729，输入电容 0.534 fF）。
# - set_load 是加在每个主输出上的负载（fF）。0.5 fF 约等于一个输入引脚，
#   是与本仓库 STA 环境（输出零负载）最接近的取值。
#   **这不是一个需要调优的旋钮**：2026-09-09 实测 0.1 / 0.5 / 1.0 三档，
#   面积与延时基本相同。小设计上那几个百分点的抖动来自 upsize/dnsize 按 ABC
#   自己的时序模型重新定尺寸，与 OpenSTA 口径不完全一致，调 set_load 消不掉。
ABC_CONSTR = Path(__file__).resolve().parent / "abc.constr"

# 保住层级的模块表由设计按顶层声明（`flow/paths.py::keep_hierarchy_modules`），
# 在这里施加。**位置与写法都是实测定下来的，改之前先读完这段。**
#
# 三条命令各有分工：
#
#   select -assert-any <M>        在 `hierarchy` **之前**逐个断言声明的名字真的
#                                 存在。这是**拼写检查**：此刻源码里每个模块都还
#                                 在（读入的是并集闭包），所以「没命中 = 名字写错
#                                 了」，判据干净、与参数组合无关。不能省 ——
#                                 `setattr` 对选不中的模块只打一句 `Warning:
#                                 Selection "M" did not match any module.` 然后
#                                 退出 0（2026-09-21 实测），那一层就静默地不再
#                                 被保住，而综合照常完成、数字照常进记录。
#   hierarchy -check -top <top>   显式做，不再让 `synth -top` 内部做。原因见下。
#   setattr -mod -set … *<M>*     标在**派生副本**上，所以模式两头都要带 `*`。
#
# ⚠️ **为什么必须排在 `hierarchy` 之后**（2026-09-21 实测，本仓 内部#46 的 2.2）：
# `hierarchy` 把参数化模块换成 `$paramod$<hash>\<名字>` 或
# `$paramod\<名字>\WIDTH=...` 的派生副本，原来那个泛型模块当作 unused 删掉。
# 在它之前 `setattr` 挂的属性**跟着一起没了** —— 10 个模块里只有无参数的
# `PREFIX_NODE` 幸存。RTL 里写 `(* keep_hierarchy *)` 不受影响，因为那是 AST 的
# 一部分，派生时会带过去。
# 实测（`ADDER32 W=64 SKLANSKY`，加 `-flatten` 才看得出差别）：
#   RTL 自带属性            647 cells / 64.41444 µm²
#   hierarchy 之后再标      647 cells / 64.41444 µm²   ← 逐位相同
#   hierarchy 之前标        650 cells / 64.54566 µm²   ← 只保住了 PREFIX_NODE
#   完全不标                546 cells / 32.90706 µm²   ← ABC 跨边界重构（P-3）
# ⚠️ 当前流程**不加 `-flatten`**，所以这四种在今天的产线上给出同一个数 ——
# 这个属性今天是「防止以后误加 -flatten」的护栏，不是承重件。正因为如此，
# 它的正确性只能在加了 `-flatten` 的对照里验，产线上的零差异证明不了任何事。
#
# `select -clear` 收尾：`select` 会改变当前选择集，而后面的 `dfflibmap` / `abc`
# 都按当前选择集工作。不清掉的话它们只对最后一次选中的东西生效。
def _keep_hierarchy_cmds(modules, top):
    """`hierarchy` + 施加保层级属性。没有声明时只做 `hierarchy`。"""
    lines = [f"select -assert-any {m}" for m in modules]
    lines.append(f"hierarchy -check -top {top}")
    if modules:
        # 两头带 `*`：派生副本的名字是 `$paramod$<hash>\<名字>`（后缀）或
        # `$paramod\<名字>\WIDTH=...`（中缀），只有含式模式两种都能命中。
        lines.append("setattr -mod -set keep_hierarchy 1 "
                     + " ".join(f"*{m}*" for m in modules))
    lines.append("select -clear")
    return "\n".join(lines) + "\n"


def _assert_no_substring_collision(modules, sources):
    """含式模式要求声明的名字不是别的模块名的子串，否则会误标。

    今天本仓没有这种名字，但这是**名字的性质**而不是契约保证的性质 ——
    加一个 `PREFIX_NODE_X` 就会让 `*PREFIX_NODE*` 连它一起标上，
    而多标一个模块不会让任何东西失败，只会让数字悄悄变。
    """
    declared = set(modules)
    all_mods = set()
    for src in sources:
        all_mods.update(MODULE_DECL_RE.findall(Path(src).read_text()))
    bad = {m: sorted(o for o in all_mods - {m} if m in o) for m in declared}
    bad = {m: v for m, v in bad.items() if v}
    if bad:
        raise RuntimeError(
            "保层级模块表里的名字是别的模块名的子串，含式模式会误标：\n  "
            + "\n  ".join(f"{m} ⊂ {v}" for m, v in bad.items())
            + "\n改名，或者把施加方式换成逐个精确匹配派生副本。")


# `opt_clean -purge`（不是默认的 `opt_clean`）：默认的保留不接任何单元的具名线，
# RTL 里 `integer` 循环变量展开后会留下一行 `wire signed [31:0] i;`，OpenSTA 的
# Verilog 读入器不认 `signed`，整个网表读不进（内部#64，flow-batch-2026-10 的 D5）。
# -purge 只删没有负载的线，单元与连接不变。
# 触发器映射到同功能里面积最小的单元（内部#176，experiment-trust）：dfflibmap 默认只用输出极性相符的单元，
# ASAP7 里 Q 输出的上升沿触发器只有 DFFHQx4（0.3645 µm²），不复位的触发器会全部落在它上面；
# 排除它之后改用 DFFHQNx1（0.2916 µm²）加反相，反相由 ABC 吸收（一个 32 位、深度 8 的 FIFO 实测：256 个触发器全改 x1，反相器 45 → 13，面积 -12.8%）。
# 单元名直接写在模板里（depth.py 用同一份模板，配方哈希也取模板原文）；换 PDK 时跟着换
# （docs/toolchain.md「换 PDK 时要一起改的地方」）。

# 综合之后的映射与产出：正式口径与参考口径（flow/synth/reference.py，内部#202）共用这一段，两者只差 synth 那一步。
MAP_TEMPLATE = """\
dfflibmap -liberty {liberty} -dont_use DFFHQx4_ASAP7_75t_R
abc -liberty {liberty} -constr {abc_constr}{delay_opt}
opt_clean -purge
rename -top {top}
tee -o {stats_json} stat -json -liberty {liberty}
write_verilog {netlist}
"""
YOSYS_TEMPLATE = """\
{read_verilog_cmds}
chparam {chparam_sets} {top}
{keep_hierarchy_cmds}synth
""" + MAP_TEMPLATE


def run_synth(design, params, liberty, out_dir=None, delay_target_ps=None):
    """delay_target_ps=None 表示不给 ABC 延时目标，行为与本参数存在之前逐字相同。

    ⚠️ `design` 这个形参装的是**被测顶层模块名**，不是设计根的目录名。
    两者在「设计根名 MUST 等于顶层名」成立的全部历史里逐字相同，收根之后
    （本仓 内部#45）分开：一个根可以挂两个顶层（例如一个地址流水与它的组合子块）。形参名没改是因为它就是记录里 `design`
    字段的值、也是全部 CLI 的 `--design`，而那个字段一直指顶层。
    根目录由 `resolve_design_root(design)` 查 `params.yaml` 的 `tops:` 声明得到。

    给了目标就是 `abc -D <ps>`。⚠️ 这个旋钮有**静默死区**：目标给得太紧时 ABC
    照常退出 0，产出的却是与不给 `-D` 逐字节相同的网表，不报错也不警告
    （2026-09-13 实测，死区上界是设计相关的 —— `BRENT_KUNG W=32` 在 70，
    `SKLANSKY W=64` 在 85）。所以**调用方必须自己核对网表真的变了**，
    见 `flow/synth/search.py` 与 docs/data-credibility.md 的 D-7。
    """
    yosys = shutil.which("yosys")
    if yosys is None:
        raise RuntimeError("yosys not found in PATH (need oss-cad-suite env sourced)")

    params = validate_params(design, params)
    # 只读该顶层的依赖闭包，不读整个目录（本仓 内部#50，见 source_files 的注释）
    sources = source_files(design, yosys=yosys)
    keep_hierarchy = keep_hierarchy_modules(design)
    _assert_no_substring_collision(keep_hierarchy, sources)

    run_dir = Path(out_dir) if out_dir else adhoc_run_dir(design, "synth")
    run_dir.mkdir(parents=True, exist_ok=True)

    stats_json = run_dir / "stats.json"
    netlist = run_dir / f"{design}_netlist.v"
    script_path = run_dir / "synth.ys"
    log_path = run_dir / "yosys.log"

    incs = include_dirs(design, resolve_design_root(design).parent.parent)
    read_verilog_cmds = "\n".join(f"read_verilog {_inc_flags(incs)}{src}" for src in sources)
    # 字符串参数要带引号，数值参数原样
    chparam_sets = _chparam_sets(params)
    if not ABC_CONSTR.is_file():
        raise FileNotFoundError(f"缺少 ABC 约束文件 {ABC_CONSTR}（没有它就没有缓冲插入）")
    script = YOSYS_TEMPLATE.format(
        read_verilog_cmds=read_verilog_cmds,
        top=design,
        chparam_sets=chparam_sets,
        keep_hierarchy_cmds=_keep_hierarchy_cmds(keep_hierarchy, design),
        liberty=liberty,
        abc_constr=ABC_CONSTR,
        delay_opt="" if delay_target_ps is None else f" -D {delay_target_ps}",
        stats_json=stats_json,
        netlist=netlist,
    )
    script_path.write_text(script)

    proc = subprocess.run(
        [yosys, "-s", str(script_path)],
        cwd=run_dir,
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        # 带上日志尾巴，不只给一个路径：最常见的失败是保层级模块表里有个名字
        # 没命中（`select -assert-any` 抛的 `Assertion failed: selection is
        # empty: <M>`），而那句话里就有答案。只给路径的话，读的人还要再开一个文件
        # 才知道是拼错了还是真的漏读了源文件。
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
        raise RuntimeError(
            f"yosys failed (see {log_path})\n  " + "\n  ".join(tail))

    stats = json.loads(stats_json.read_text())
    design_stats = stats["design"]
    cell_count = design_stats.get("num_cells", 0)
    area = design_stats.get("area", None)

    return {
        "cell_count": cell_count,
        "area_um2": area,
        "sources_sha256": read_set_digest(design, sources),
        "delay_target_ps": delay_target_ps,
        "netlist_path": str(netlist),
        "log_path": str(log_path),
        "stats_path": str(stats_json),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", required=True)
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="RTL 参数取值，可重复；名字必须在设计的 params.yaml 里声明过")
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--delay-target-ps", type=int, default=None,
                    help="ABC 的延时目标（皮秒）。不给就是今天的行为；"
                         "给得太紧会静默失效，见 run_synth() 的 docstring")
    args = ap.parse_args()

    result = run_synth(args.design, cli_params(args.param), args.liberty,
                       delay_target_ps=args.delay_target_ps)
    print(json.dumps(result, indent=2))
