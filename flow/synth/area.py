"""按层次拆开的面积（area-breakdown，内部#174；experiment-record「记录必须携带按层次拆开的面积」）。

读综合产出的 `stats.json`（yosys `stat -json -liberty`），拆成记录里的 `synth.area_breakdown`：

- `gate_unit`：折算门数用的单元与它在综合 liberty 里的面积（门数本身是导出值，由报告现算）；
- `sequential_area_um2`：整个设计的时序单元面积；
- `hierarchy`：保留下来的模块实例，展开到第 `MAX_LEVEL` 级。每行 `{path, level, module, instances,
  area_um2, cell_count, sequential_area_um2}`，面积与单元数都已乘实例数、含下层；每层的胶合逻辑
  单列一行（`module` 为 null，路径 `<父>/(glue)`）。同一父模块下同一个派生模块的多个实例合成一行；
- `memory_models`：设计声明的存储模型（`paths.memory_models`），按实例数累计到任意深度的面积合计。

yosys `stat` 的口径：每个模块的 `area` / `sequential_area` 含下层子模块，`num_cells` 只数本层
（子模块实例算一个单元），`num_cells_by_type` 里子模块按模块名计数。
在 METRIC_MODULES 里：它决定记录字段的值，改它换代。
"""
import json
import re
from pathlib import Path

GATE_UNIT_CELL = "NAND2x1_ASAP7_75t_R"   # 换 PDK 时跟着换（docs/toolchain.md「换 PDK 时要一起改的地方」）
MAX_LEVEL = 2
GLUE = "(glue)"


def gate_unit(liberty):
    """{cell, area_um2}：从 liberty 现读 GATE_UNIT_CELL 的面积；读不到就报错，不退回常数。"""
    text = Path(liberty).read_text()
    m = re.search(r"cell\s*\(\s*\"?%s\"?\s*\)\s*\{(.*?)\barea\s*:\s*([0-9.eE+-]+)" % re.escape(GATE_UNIT_CELL),
                  text, re.S)
    if m is None:
        raise RuntimeError(f"综合 liberty {liberty} 里找不到 {GATE_UNIT_CELL} 的面积（门数单位，#174）")
    return {"cell": GATE_UNIT_CELL, "area_um2": float(m.group(2))}


def base_module_name(name):
    """yosys 的模块名 → RTL 模块名：`$paramod\\X\\P=…` 与 `$paramod$<hash>\\X` 都取 X。"""
    if name.startswith("$paramod"):
        return name.split("\\")[1]
    return name.lstrip("\\")


def breakdown(design, stats_path, liberty, memory_models=None):
    from flow.paths import memory_models as declared_memory_models
    stats = json.loads(Path(stats_path).read_text())
    mods = stats["modules"]
    tops = [m for m in mods if base_module_name(m) == design]
    if len(tops) != 1:
        raise RuntimeError(f"{stats_path} 里找不到唯一的顶层模块 {design}（找到 {tops}）")
    top = tops[0]
    mem = list(declared_memory_models(design) if memory_models is None else memory_models)
    _assert_declared_in_rtl(design, mem)

    def area(m):
        return float(mods[m].get("area") or 0.0)

    def seq(m):
        return float(mods[m].get("sequential_area") or 0.0)

    def subs(m):
        return [(t, int(n)) for t, n in (mods[m].get("num_cells_by_type") or {}).items() if t in mods]

    def own_cells(m):
        return sum(int(n) for t, n in (mods[m].get("num_cells_by_type") or {}).items() if t not in mods)

    def cells(m):   # 含下层的叶单元数
        return own_cells(m) + sum(cells(t) * n for t, n in subs(m))

    rows = []

    def row(path, level, module, n, a, s, c):
        # 胶合行是父减子，会留下 1e-15 量级的浮点尾巴：统一保留 6 位小数（liberty 面积本身是 5 位）
        rows.append({"path": path, "level": level, "module": module, "instances": n,
                     "area_um2": round(a, 6), "cell_count": c, "sequential_area_um2": round(s, 6) + 0.0})

    def expand(m, path, level, mult):
        kids = sorted(subs(m), key=lambda tn: (-area(tn[0]) * tn[1], tn[0]))
        for t, n in kids:
            k = n * mult
            row(f"{path}/{base_module_name(t)}", level, base_module_name(t), k,
                area(t) * k, seq(t) * k, cells(t) * k)
            if level < MAX_LEVEL:
                expand(t, f"{path}/{base_module_name(t)}", level + 1, k)
        if kids:
            row(f"{path}/{GLUE}", level, None, mult,
                (area(m) - sum(area(t) * n for t, n in kids)) * mult,
                (seq(m) - sum(seq(t) * n for t, n in kids)) * mult,
                own_cells(m) * mult)

    row(design, 0, design, 1, area(top), seq(top), cells(top))
    expand(top, design, 1, 1)
    # 同名派生模块（同一父下、同一 RTL 模块的不同参数化）路径会重名：加序号区分，面积各自保留
    seen = {}
    for r in rows:
        seen[r["path"]] = seen.get(r["path"], 0) + 1
        if seen[r["path"]] > 1:
            r["path"] = f"{r['path']}#{seen[r['path']]}"

    mem_area = mem_seq = 0.0
    for name in mem:
        variants = [m for m in mods if base_module_name(m) == name]
        for v in variants:
            k = sum(n * (1 if t == v else _count_exact(mods, t, v)) for t, n in subs(top))
            mem_area += area(v) * k
            mem_seq += seq(v) * k
    return {
        "gate_unit": gate_unit(liberty),
        "sequential_area_um2": round(seq(top), 6),
        "hierarchy": rows,
        "memory_models": {"modules": mem, "area_um2": round(mem_area, 6),
                          "sequential_area_um2": round(mem_seq, 6)},
    }


def _count_exact(mods, m, target):
    """模块 target（yosys 名，精确）在 m 之下的实例数，任意深度。"""
    total = 0
    for t, n in (mods[m].get("num_cells_by_type") or {}).items():
        if t not in mods:
            continue
        total += int(n) * (1 if t == target else _count_exact(mods, t, target))
    return total


def _assert_declared_in_rtl(design, names):
    """声明的存储模型必须是该顶层读入源文件里的模块（area-breakdown D3）。

    与保层级同一纪律：拼错的名字不会让任何东西失败，只会让「扣除存储模型后」的面积悄悄等于总面积。
    某个配置里存储模型被 generate 掉（合计为 0）是合法的 —— 所以按 RTL 查名字，不按网表查。
    """
    if not names:
        return
    from flow.synth.synth import MODULE_DECL_RE, source_files
    mods = set()
    for src in source_files(design):
        mods.update(MODULE_DECL_RE.findall(Path(src).read_text()))
    missing = [m for m in names if m not in mods]
    if missing:
        raise RuntimeError(f"{design} 的 synth.memory_models 声明了读入源文件里没有的模块：{missing}"
                           "（拼错了，或者不在这个顶层的依赖闭包里）")
