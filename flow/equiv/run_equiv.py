"""形式化等价证明：证明「拆成多个 step 的实现」与「平坦参考」逐输出相同。

为什么值得有这一层：仿真能证伪，不能证明。这类拆分的典型错误——某一位的移位量
差一、某个字段没透传——只在极少数输入上体现，随机激励撞上它的概率可以任意低。
而这几对实现的关系是「应当逐位相同」，正好是 SAT 判定得了的形状。

覆盖边界（不要高估）：证的是**组合等价**。带寄存器的顶层、握手时序、复位行为
都不在射程内，那些仍然只有 cocotb 证据。契约在
openspec/specs/formal-equivalence/spec.md。

用 miter -equiv 而不是 equiv_opt：两侧是**不同的模块名**，miter 正是为这种
「两个独立模块比对」设计的；equiv_opt 更适合「同一模块优化前后」。

sat 必须带 -verify：yosys 的 sat 默认在找到反例时仍以 0 退出并只打印信息。
不带 -verify 的脚本会在两份实现不同时照样「通过」——那种护栏比没有更糟。

必须先 `setattr -mod -unset keep_hierarchy` 再 flatten：本仓库按 CLAUDE.md 红线 6
在关键 building block 上保住层级（为的是别让综合把不同微架构优化成同一个电路）。
2026-09-21 起这个意图由 `designs/<根>/params.yaml` 的
`tops:<顶层>:synth:keep_hierarchy:` 声明、由 `flow/synth/synth.py` 施加，
不再写在 RTL 里（#46 的 2.2）——**但本脚本仍要 unset**：`flow/equiv/frozen/`
下的冻结件按契约不适用那条书写约定，仍可能自带属性，而属性在这里会挡住
flatten，SAT 于是把子模块当黑盒，报 `No SAT model available for cell ...`。
解除它只影响本脚本建的这份临时设计，不碰 RTL 源码，也不影响 flow/synth 的综合。
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.paths import resolve_design_root  # noqa: E402


class Pair:
    """一对待证明的实现。srcs 里第一个文件必须包含同名顶层模块。

    默认情况下两侧同源同参：都从设计根的 `rtl/` 读文件，都收同一组 `chparam`。
    那是 split ≡ flat 这类实现对的形状——它们本来就是同一批 RTL 的两种划分。

    黄金参照打破这个默认。它是**外部的第二实现**：
      * `gold_dir` —— 它不在被测设计的 rtl/ 下（同名模块会在 elaborate 时撞车，
        也会被 fast_check.sh 的「同名源文件逐字节相同」拦下），所以要自己的源目录。
      * `gold_extra` —— gold 侧额外的参数，覆盖 cfg 里的同名项。
      * `gold_no_cfg` —— gold 侧**完全不接** cfg。冻结原版是参数化之前的那份代码，
        它根本没有规模参数，照着 cfg 发过去 yosys 会直接报
        `Can't find object for defparam`。
    """

    def __init__(self, name, gold_top, gold_srcs, gate_top, gate_srcs, configs=None,
                 gold_dir=None, gold_extra=None, gold_no_cfg=False):
        self.name = name
        self.gold_top, self.gold_srcs = gold_top, gold_srcs
        self.gate_top, self.gate_srcs = gate_top, gate_srcs
        # [{参数名: 值}, ...]；空 dict 表示无参数
        self.configs = configs or [{}]
        self.gold_dir = Path(gold_dir) if gold_dir else None
        self.gold_extra = dict(gold_extra or {})
        self.gold_no_cfg = gold_no_cfg

    def gold_params(self, cfg):
        base = {} if self.gold_no_cfg else dict(cfg)
        base.update(self.gold_extra)
        return base


WRAPPER_ROOT = REPO_ROOT / "flow" / "equiv" / "wrappers"

# 多结构构件：每种结构对一份独立写的行为级参考（equiv-cbb-structures，#66）。
# 参考不复用被比较的任何一种结构（TOOL 写错时「各结构对 TOOL」会照样证过）；
# 全零输入时位置输出无意义，两侧经同一个掩码包装件比较。取值与 params.yaml 的声明一致。
# 按 MSB_EN 分成两对：找最低位与找最高位是两种功能，各自对参考证。
#
# 2026-10-01 起这是表里唯一的设计（trim-design-roots）：另外两个已删设计根的配对、冻结件与包装件，
# 以及 LZD 的配对，随设计根一起删除；历史上的证明在 git 历史与 `proved.json` 的旧提交里。
CBB_LZD_DAT_W = (2, 5, 16, 32, 33)
CBB_LZD_SCHEMES = range(3)


def _cbb_lzd(design_dir):
    wrap = WRAPPER_ROOT / "cbb_lzd"
    return [Pair(f"cbb_lzd_{side}_vs_ref",
                 "CBB_LZD_REF_MASKED", [wrap / "cbb_lzd_ref_masked.v"],
                 "CBB_LZD_MASKED", [wrap / "cbb_lzd_masked.v", "cbb_lzd.v"],
                 configs=[{"DAT_W": w, "MSB_EN": e, "SCHEME": s}
                          for w in CBB_LZD_DAT_W for s in CBB_LZD_SCHEMES])
            for side, e in (("lsb", 0), ("msb", 1))]


PAIRS = {"CBB_LZD": _cbb_lzd}


def _chparam(top, params):
    if not params:
        return ""
    sets = " ".join(f"-set {k} {v}" for k, v in params.items())
    return f"chparam {sets} {top}\n"


def _script(pair, cfg, rtl_dir):
    gold_dir = pair.gold_dir or rtl_dir
    gold_files = " ".join(str(gold_dir / f) for f in pair.gold_srcs)
    gate_files = " ".join(str(rtl_dir / f) for f in pair.gate_srcs)
    gold_params = pair.gold_params(cfg)
    return f"""
read_verilog -sv {gold_files}
{_chparam(pair.gold_top, gold_params)}hierarchy -check -top {pair.gold_top}
proc; opt_expr; opt_clean
setattr -mod -unset keep_hierarchy
flatten; opt -purge
rename {pair.gold_top} gold
design -stash gold

read_verilog -sv {gate_files}
{_chparam(pair.gate_top, cfg)}hierarchy -check -top {pair.gate_top}
proc; opt_expr; opt_clean
setattr -mod -unset keep_hierarchy
flatten; opt -purge
rename {pair.gate_top} gate
design -stash gate

design -copy-from gold -as gold gold
design -copy-from gate -as gate gate
miter -equiv -flatten -make_assert gold gate miter
hierarchy -top miter
opt -purge
sat -verify -prove-asserts -show-ports -seq 0 miter
"""


# --- 账 -------------------------------------------------------------------
#
# 等价证明的产物**不进 results/experiments.jsonl**，所以 flow_fingerprint
# 覆盖不到本文件 —— 指纹回答的是「两条记录能不能横向比」，而等价证明不产出
# 记录字段。于是把某条 assume 放宽、把某个模块从对照表里删掉，SAT 照样通过、
# 输出与完整证明完全一样（本仓 #39）。
#
# 账记的是「这一组是对**哪些字节**证的」：被证源文件的内容哈希 + 证明器自身的
# recipe 哈希。RTL 变了，该设计重证；证明器变了，**全部**账目失效。
#
# ⚠️ 这不是防篡改机制。谁都能手改 proved.json —— 而那正是可以接受的：
# 锁死只会变成绕过对象（#39 明确否掉了 nano-kpu 那套「拒绝出分」）。
# 账的价值是**可见性**：改账目会出现在 diff 里，而现在削弱证明器根本不出现在
# 任何地方。
LEDGER_PATH = REPO_ROOT / "flow" / "equiv" / "proved.json"

# recipe 里算什么：本文件的**内容**（不是 AST）。flow_fingerprint 的
# metrics_code_sha256() 哈希 AST，为的是让「只改注释」不换代 —— 那对测量代码是
# 对的。证明器不同：本文件的注释里写着覆盖边界（「证的是组合等价」「带寄存器的
# 顶层不在射程内」），改了注释而不改行为，恰恰是最该有人重看一遍的情形。
# 宁可多证一次。见 design.md 的 D3。
RECIPE_FILES = (Path(__file__).resolve(),)


def _sha256_bytes(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


def recipe_sha256():
    """证明器自身的哈希。它变了，全部账目失效 —— 不分设计（D4）。

    只重证「受影响的设计」需要先知道哪些受影响，而那正是被削弱的那件事自己
    说了算 —— 循环。
    """
    h = hashlib.sha256()
    for f in RECIPE_FILES:
        h.update(f.read_bytes())
    return "sha256:" + h.hexdigest()


def entry_key(design, pair_name, cfg):
    """账目的键。config 按键排序序列化，保证同一个配置永远同一个键。"""
    body = ",".join(f"{k}={cfg[k]}" for k in sorted(cfg))
    return f"{design}::{pair_name}::{{{body}}}"


def pair_sources(pair, rtl_dir):
    """一对实现被证到的全部源文件，去重后按仓库相对路径排序。"""
    gold_dir = pair.gold_dir or rtl_dir
    paths = {(gold_dir / f) for f in pair.gold_srcs}
    paths |= {(rtl_dir / f) for f in pair.gate_srcs}
    out = {}
    for path in sorted(paths):
        try:
            rel = str(path.resolve().relative_to(REPO_ROOT))
        except ValueError:
            rel = str(path.resolve())      # --rtl-dir 指到仓库外（注入反例用）
        out[rel] = _sha256_bytes(path.read_bytes())
    return out


def load_ledger(path=None):
    path = Path(path) if path else LEDGER_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_ledger(ledger, path=None):
    """规范形式写出：键有序、缩进固定、末尾一个换行。

    不这么做的话 diff 全是噪声，而账的全部价值就是「改动在 diff 里看得见」——
    噪声大到没人读，护栏就等于没有。
    """
    path = Path(path) if path else LEDGER_PATH
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n")


def design_rtl_dir(design):
    """该**被测顶层**的源文件目录 —— 按顶层名查它所在的设计根，不拿它当目录名。

    ⚠️ 这里的 `design` 与账目键 `<design>::<pair>::<cfg>` 里的第一段、与
    `results/experiments.jsonl` 的 `design` 字段是同一个东西：**被测顶层名**。
    原来这两处写死 `REPO_ROOT / "designs" / design / "rtl"`，在「设计根名 MUST
    等于顶层名」成立的那段历史里是对的；#45 收根之后不再成立，而当时**没有红**，
    因为账本里那两个 design 碰巧既是顶层名也是根名（本仓 #51）。
    2026-09-21 顶层名改大写之后它当场炸了：`designs/<大写顶层名>/` 不存在。
    """
    return resolve_design_root(design) / "rtl"


def declared_entries(design, rtl_dir=None):
    """该设计当下声明的全部组：{账目键: 该组的源文件哈希}。"""
    rtl_dir = Path(rtl_dir) if rtl_dir else design_rtl_dir(design)
    out = {}
    for pair in PAIRS[design](rtl_dir):
        srcs = pair_sources(pair, rtl_dir)
        for cfg in pair.configs:
            out[entry_key(design, pair.name, cfg)] = srcs
    return out


def stale_entries(design, ledger=None, rtl_dir=None, yosys=None,
                  ledger_path=None):
    """该设计里**需要重证**的组，逐条带上原因。

    `yosys` 只为签名对齐而存在：核账**不调用求解器**，所以传什么都一样。
    用例靠这一点验证「账命中就不跑 SAT」。
    """
    led = load_ledger(ledger_path) if ledger is None else ledger
    recipe = recipe_sha256()
    stale = []
    for key, srcs in declared_entries(design, rtl_dir).items():
        got = led.get(key)
        if got is None:
            stale.append((key, "账里没有这一组"))
        elif got.get("recipe_sha256") != recipe:
            stale.append((key, "证明器变了，全部账目失效"))
        elif got.get("sources_sha256") != srcs:
            stale.append((key, "被证的源文件变了"))
    return stale


def orphan_entries(ledger=None):
    """账里有、但当下**没有**被任何设计声明的组。

    它不是「还需要证」，而是「这条账目说的事已经不在射程内了」。必须报告出来 ——
    否则一个被悄悄删掉的对照仍然在账上留着一条 PROVED，读的人会以为它还被证着。
    """
    led = load_ledger() if ledger is None else ledger
    declared = set()
    for design in PAIRS:
        declared |= set(declared_entries(design))
    return sorted(k for k in led if k not in declared)


def _say(msg):
    """打一行并**立刻刷新**。

    不能用裸 print：stdout 重定向到文件时是全缓冲的，而大设计
    一轮**串行**要跑约 100 分钟（`-j` 能把它压下来，但默认是串行）——
    全缓冲下日志**全程 0 字节**，「还在跑」与「卡死了」在外部看来完全一样，
    只能靠数 yosys 子进程来分辨（2026-09-17 实撞过）。
    逐组耗时本来就是这一层的诊断依据，攒到进程退出才吐出来等于没有。

    ⚠️ 并行之后这条**更要紧**：`-j N` 时 N 组同时起跑，第一组完成之前
    十几分钟里一行都不会有 —— 所以每组在**开跑时**也打一行（见 prove()）。
    """
    print(msg, flush=True)


def _label(pair, cfg):
    return pair.name + (f" [{', '.join(f'{k}={v}' for k, v in cfg.items())}]"
                        if cfg else "")


def _prove_one(pair, cfg, rtl_dir, yosys, on_start=None):
    """证一组，返回 (proved, 耗时秒, 合并输出)。

    组与组之间**没有任何共享状态** —— 临时脚本各自 `NamedTemporaryFile`、
    yosys 是独立子进程、账本在全部组结束之后才一次写出。所以这个函数可以
    直接丢进线程池，不需要锁（本仓 #54）。

    `on_start` 在**真的开始跑之前**调一次。它必须在这里调、不能在提交到线程池
    的地方调：`-j 3` 提交 9 组时，后 6 组只是在队列里排着，那时打一行「开跑」
    是在**谎报进度** —— 读的人会以为九个 yosys 在跑，而实际只有三个
    （2026-09-21 实撞：第一版就是在提交处打的，9 组的「开跑」一次性全出来了）。
    """
    if on_start is not None:
        on_start()
    with tempfile.NamedTemporaryFile("w", suffix=".ys", delete=False) as fh:
        fh.write(_script(pair, cfg, rtl_dir))
        ys = fh.name
    t0 = time.monotonic()
    try:
        r = subprocess.run([yosys, "-q", "-s", ys],
                           capture_output=True, text=True)
    finally:
        Path(ys).unlink(missing_ok=True)
    return r.returncode == 0, time.monotonic() - t0, r.stdout + r.stderr


def prove(design, only=None, rtl_dir=None, yosys="yosys", skip_proved=False,
          ledger_path=None, jobs=1):
    """对一个设计根的全部实现对逐配置证明。返回 (ok, [每次证明的结果])。

    **覆盖摘要不是装饰。** 这一层的失效方式是「削弱了的证明与完整的证明，
    在输出上完全一样」——把某条 assume 放宽、把某个模块从对照表里删掉，
    SAT 照样通过。所以每一轮都要说清：声明了多少组、实际证了多少、跳过哪些、
    为什么跳过、各用了多久。与 `scripts/sweep.py` 的扫参摘要、
    `scripts/fast_check.sh` 的覆盖摘要是同一条原则（`guardrail-scope`）。

    **一组都没证不算通过。** 空的对照表、或者过滤器把所有组排除掉，
    以前会返回 `(True, [])` ——「一条都没证」与「全证过了」在退出码上一模一样。

    `ledger_path` 给测试用：需要真跑一轮来观察行为的用例（例如验覆盖摘要的
    格式）把账写到自己的 tmp 目录，不碰仓库里那一份。以前不给这个口子，
    于是跑一次 `pytest tests/` 就把 `flow/equiv/proved.json` 的三条
    `proved_at` 改脏（本仓 #49）。后果有两层：跑完测试接着记实验会撞红线 3
    的脏树守卫；而且账的全部价值是「改动在 diff 里看得见」，每跑一次测试
    就产生几行无意义 diff，久了没人细看，那正好废掉它唯一的用途。
    """
    if design not in PAIRS:
        raise SystemExit(f"设计 '{design}' 没有声明任何待证明的实现对。"
                         f"已声明的是：{', '.join(sorted(PAIRS))}")
    # 账只对设计根自己的 rtl/ 有意义。--rtl-dir 指到别处（注入反例用）时既不读账
    # 也不写账 —— 那份代码不在仓库里，给它记一条「证过了」是在污染账。
    default_dir = design_rtl_dir(design)
    overridden = rtl_dir is not None and Path(rtl_dir) != default_dir
    rtl_dir = Path(rtl_dir) if rtl_dir else default_dir
    pairs = PAIRS[design](rtl_dir)

    ledger = {} if overridden else load_ledger(ledger_path)
    fresh = set()
    if skip_proved and not overridden:
        need = {k for k, _ in stale_entries(design, ledger, rtl_dir)}
        fresh = set(declared_entries(design, rtl_dir)) - need

    todo, skipped = [], []
    for pair in pairs:
        for cfg in pair.configs:
            key = entry_key(design, pair.name, cfg)
            if only and pair.name != only:
                skipped.append((_label(pair, cfg), f"被 --pair {only} 排除"))
            elif key in fresh:
                skipped.append((_label(pair, cfg),
                                "账目命中（源文件与证明器都没变）"))
            else:
                todo.append((pair, cfg))

    n_declared = len(todo) + len(skipped)
    _say(f"# equiv {design}: 声明 {len(pairs)} 对 / {n_declared} 组，"
          f"本轮要证 {len(todo)} 组")
    # 并行度即使是 1 也要写：逐组耗时之和与墙钟不再相等之后，读的人必须能看出
    # 差的那一截是并行省下来的，而不是**有几组根本没跑**（formal-equivalence
    # 的「覆盖摘要」那条）。
    _say(f"#   并行度 {jobs}" + ("（串行）" if jobs == 1 else ""))
    if skipped:
        _say(f"#   跳过 {len(skipped)} 组：")
        for label, why in skipped:
            _say(f"#     跳过 {label} —— {why}")

    results, ok = [], True
    t_all = time.monotonic()

    def _report(i, pair, cfg, proved, dt, log):
        """打这一组的结果行。`i` 是**声明序号**，不是完成序号。

        并行下完成先后是随机的，而 `[i/N]` 被人当作「跑到第几组了」读 ——
        按完成顺序编号会让同一批配置两次跑出不同的编号。
        """
        # gold 侧不在设计根下时要说出来：否则「冻结原版」这一对打印出来是
        # `sub_a == sub_a`，看不出被证的是哪两份代码。
        gold_desc = pair.gold_top + (
            f" @{pair.gold_dir.relative_to(REPO_ROOT)}"
            if pair.gold_dir else "")
        _say(f"[{i}/{len(todo)}] {'PROVED' if proved else 'FAILED'}  {design}: "
              f"{pair.gate_top} == {gold_desc}  {_label(pair, cfg)}  ({dt:.1f} s)")
        if not proved:
            # 指出是哪一对、哪个配置、哪个输出——不许只说"失败了"
            tail = [ln for ln in log.splitlines()
                    if "Assert" in ln or "assert" in ln or "ERROR" in ln]
            for ln in tail[-12:]:
                _say(f"        {ln}")

    indexed = []
    if jobs == 1:
        for i, (pair, cfg) in enumerate(todo, 1):
            proved, dt, log = _prove_one(pair, cfg, rtl_dir, yosys)
            _report(i, pair, cfg, proved, dt, log)
            indexed.append((i, pair, cfg, proved, dt, log))
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = {}
            for i, (pair, cfg) in enumerate(todo, 1):
                # 开跑也打一行。`-j N` 时 N 组同时起跑、第一组完成之前十几分钟
                # 一行都不会有 —— 只报完成的话，最该看见进度的那段时间里输出
                # 停在覆盖摘要上，「还在跑」与「卡死了」又变得无法分辨。
                #
                # ⚠️ 这一行由 `_prove_one` 在**真的开跑时**打，不在这里打：
                # 提交到池里 ≠ 开始跑，在这里打会让 9 组一次性全报「开跑」，
                # 而实际只有 `jobs` 个在跑 —— 那是谎报进度。
                started = (lambda i=i, pair=pair, cfg=cfg:
                           _say(f"[{i}/{len(todo)}] {design}: "
                                f"{_label(pair, cfg)} 开跑"))
                futs[pool.submit(_prove_one, pair, cfg, rtl_dir, yosys,
                                 on_start=started)] = (i, pair, cfg)
            for fut in as_completed(futs):
                i, pair, cfg = futs[fut]
                proved, dt, log = fut.result()
                _report(i, pair, cfg, proved, dt, log)
                indexed.append((i, pair, cfg, proved, dt, log))

    # 还原成**声明顺序**：并行下完成先后是随机的，而下游（账本的写入顺序、
    # 返回给调用方的列表）把这个次序当稳定的基底用。
    for i, pair, cfg, proved, dt, log in sorted(indexed, key=lambda x: x[0]):
        ok &= proved
        results.append({"pair": pair.name, "config": cfg,
                        "label": _label(pair, cfg),
                        "proved": proved, "seconds": dt, "log": log})

    if not overridden:
        recipe = recipe_sha256()
        changed = False
        for pair, cfg in todo:
            key = entry_key(design, pair.name, cfg)
            if not next(r["proved"] for r in results
                        if r["label"] == _label(pair, cfg)):
                ledger.pop(key, None)      # 证失败了，旧账目不能留着顶事
                changed = True
                continue
            ledger[key] = {
                "sources_sha256": pair_sources(pair, rtl_dir),
                "recipe_sha256": recipe,
                "proved_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds").replace("+00:00", "Z"),
            }
            changed = True
        if changed:
            save_ledger(ledger, ledger_path)
        orphans = orphan_entries(ledger)
        if orphans:
            _say(f"#   ⚠️ 账里有 {len(orphans)} 条**声明中不存在**的陈旧账目，"
                  f"它们不是任何一组的证据：")
            for k in orphans:
                _say(f"#     {k}")

    n_proved = sum(r["proved"] for r in results)
    _say(f"# equiv {design} 结束: 证了 {n_proved}/{len(todo)} 组，"
          f"跳过 {len(skipped)} 组，用时 {time.monotonic() - t_all:.1f} s"
          + ("" if jobs == 1 else f"（并行度 {jobs}，逐组耗时之和 "
                                  f"{sum(r['seconds'] for r in results):.1f} s）"))
    if not todo and not fresh:
        # 一组都没证，而且也没有任何一组是因为账命中才免证的。
        # 这不是通过——它与「全证过了」在退出码上必须可区分。
        _say(f"# equiv {design}: **一组都没证**，不算通过")
        ok = False
    return ok, results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design", required=True)
    ap.add_argument("--pair", help="只证某一对")
    ap.add_argument("--rtl-dir", help="覆盖 RTL 目录（测试注入反例用）")
    ap.add_argument("--yosys", default="yosys")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="同时证几组（默认 1，串行）。并行只压墙钟，不改结论、"
                         "不改账目、不改退出码。⚠️ 默认**不**按 CPU 数推 —— "
                         "把一台正在干别的活的机器塞满，代价的承担者是调用方"
                         "（与 flow/Makefile 的 JOBS ?= 1 同一条理由）")
    ap.add_argument("--skip-proved", action="store_true",
                    help="账目命中（源文件与证明器都没变）的组不再重证")
    ap.add_argument("--ledger",
                    help="账本落点（默认 flow/equiv/proved.json）。"
                         "测试用它把账写到自己的 tmp 目录 —— 跑测试不该改"
                         "仓库里那一份，见本仓 #49")
    a = ap.parse_args()
    if a.jobs < 1:
        ap.error(f"--jobs 要 >= 1，给的是 {a.jobs}")
    ok, res = prove(a.design, a.pair, a.rtl_dir, a.yosys,
                    skip_proved=a.skip_proved, ledger_path=a.ledger,
                    jobs=a.jobs)
    # 结论由 prove() 的覆盖摘要末行给出 —— 这里不再单印一次「N/N 组证明通过」。
    # 那一行的问题是它只数**跑过的**组：过滤器把所有组排除掉时它会打印
    # `0/0 组证明通过`，读起来像成功。
    sys.exit(0 if ok else 1)
