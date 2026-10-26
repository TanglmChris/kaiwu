# fast_check 的「spec 端口表与 RTL 一致」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文除下面一行注释外未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_ports [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import is_cbb_path as _IS_CBB  # 设计树遍历（内部#305）
import fnmatch, math, os, re, sys

def spec_table(path):
    # 反引号写成 \x60：本段原来内嵌在 fast_check.sh 的 $( ... <<'EOPY') 里，bash 3.2 会数反引号（内部#336 迁出后照旧这么写）
    """文档里所有表头含「方向」「信号/端口」「位宽/宽度」的表合起来（LRS 的接口按类型分节、
    每节一张表，lrs-section-revise）。返回 [(名, 方向, 位宽原文)]；一张都没有返回 None。"""
    rows, found = [], False
    state = None             # None：不在表里；"port"：端口表；"other"：别的表
    for line in open(path, encoding="utf-8"):
        if not line.lstrip().startswith("|"):
            state = None     # 一张表结束，继续找下一张
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if state is None:    # 表头行
            idx = {c: i for i, c in enumerate(cells)}
            name = idx.get("信号", idx.get("端口"))
            width = idx.get("位宽", idx.get("宽度"))
            if "方向" in idx and name is not None and width is not None:
                state, cols, found = "port", (name, idx["方向"], width), True
            else:
                state = "other"
            continue
        if state != "port" or not "".join(cells).strip("-: "):
            continue         # 别的表的行，或分隔行
        if not cells[cols[1]].strip("\x60 "):
            continue         # 方向为空：端口行下的字段行（一个接口一张表，lrs-writing-rules D4）
        rows.append((cells[cols[0]].strip("\x60 "), cells[cols[1]].strip("\x60 ").lower(),
                     cells[cols[2]].strip("\x60 ")))
    return rows if found else None

def planned_names(path):
    """表头含「规划信号」「方向」「位宽」的表：还没有 RTL 的端口，不参与比对（内部#112，flow-guard-feedback D3）。"""
    names, state = [], None
    for line in open(path, encoding="utf-8"):
        if not line.lstrip().startswith("|"):
            state = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if state is None:
            idx = {c: i for i, c in enumerate(cells)}
            ok = "规划信号" in idx and "方向" in idx and ("位宽" in idx or "宽度" in idx)
            state, col = ("plan", idx.get("规划信号")) if ok else ("other", None)
            continue
        if state == "plan" and "".join(cells).strip("-: "):
            names.append(cells[col].strip("\x60 "))
    return names

def evaluate(expr, params):
    e = expr.replace("$clog2", "clog2")
    if not e or not re.fullmatch(r"[A-Za-z0-9_ +\-*/()]+", e):
        raise ValueError
    e = e.replace("/", "//")
    v = eval(e, {"__builtins__": {}},
             dict(params, clog2=lambda x: max(0, math.ceil(math.log2(x))) if x > 0 else 0))
    if not isinstance(v, int):
        raise ValueError
    return v

DIRS = {"INPUT": "in", "OUTPUT": "out", "INOUT": "inout"}

PORT_DOC = {}   # 顶层 -> 声明的 port_doc（集成期的过渡端口表，内部#119，integration-port-doc D1）

def iface_doc(root, top):
    """接口文档：专用设计树下是 LRS，构件树下是 spec（lrs-lld-docs；designs/ 的旧格式 spec 已退役，内部#134）；
    顶层在 params.yaml 声明了 port_doc 时是那份文档（集成期，LRS 只写最终接口）。"""
    root = root.rstrip("/")
    try:
        import yaml
        cfg = ((yaml.safe_load(open(os.path.join(root, "params.yaml"))) or {}).get("tops") or {}).get(top) or {}
    except Exception:
        cfg = {}
    if cfg.get("port_doc"):
        rel = str(cfg["port_doc"])
        path = os.path.normpath(os.path.join(root, rel))
        if not path.startswith(root + os.sep):
            return f"{root}/params.yaml 的 port_doc 要在设计根里：{rel}"
        PORT_DOC[top] = rel
        return path
    stem = "spec" if _IS_CBB(root) else "lrs"
    return os.path.join(root, f"{stem}.{top}.md")

def vvp_top(path, top):
    """-s <顶层> 下根作用域就是顶层：取第一处 `.scope module, "<顶层>"` 的端口与参数。"""
    ports, params, inside, seen = {}, {}, False, False
    for line in open(path, errors="replace"):
        m = re.search(r'\.scope module, "([^"]+)" "([^"]+)"', line)
        if m:
            inside = m.group(1) == top and not seen
            seen = seen or inside
            continue
        if not inside:
            continue
        m = re.search(r'\.port_info \d+ /(\w+) (\d+) "([^"]+)"', line)
        if m:
            ports[m.group(3)] = (DIRS.get(m.group(1), m.group(1).lower()), int(m.group(2)))
        m = re.search(r'\.param/l "(\w+)" .*?C4<([01]+)>', line)
        if m:
            params[m.group(1)] = int(m.group(2), 2)
    return ports, params

issues = {}          # (顶层, 消息) -> [组合...]
tops, combos = set(), 0
specs = {}
planned = {}
static_seen = set()
for line in open(sys.argv[1], encoding="utf-8"):
    root, top, vvp, rc, kv = (line.rstrip("\n").split("\t") + [""] * 5)[:5]
    tops.add(top); combos += 1
    add = lambda msg: issues.setdefault((top, msg), []).append(kv or "（无参数）")
    spec_path = iface_doc(root, top)
    if spec_path not in specs:
        specs[spec_path] = spec_table(spec_path) if os.path.exists(spec_path) else "missing"
    table = specs[spec_path]
    if table == "missing":
        add(f"没有 {spec_path}"); continue
    if table is None:
        add(f"{spec_path} 里找不到端口表（表头要含「方向」「信号/端口」「位宽/宽度」三列）"); continue
    if rc != "0" or not os.path.exists(vvp):
        add("elaborate 失败，拿不到端口（elaborate 那一项已列出原因）"); continue
    ports, params = vvp_top(vvp, top)
    if not ports:
        add(f"vvp 里读不到顶层 {top} 的端口（iverilog 输出格式变了？）"); continue
    names = [r[0] for r in table]
    if spec_path not in planned:
        planned[spec_path] = planned_names(spec_path)
    for n in sorted(set(names) - set(ports)):
        add(f"文档有、RTL 无：{n}")
    for n in sorted(set(ports) - set(names)):
        if n in planned[spec_path]:
            add(f"RTL 有、只写在规划信号表里：{n} —— 并了 RTL 就移进正式端口表（表头改回「信号」）")
        else:
            add(f"RTL 有、文档无：{n}")
    for n in sorted({x for x in names if names.count(x) > 1}):
        add(f"{os.path.basename(spec_path)} 里 {n} 写了不止一行")
    for n, d, w in table:
        if n not in ports:
            continue
        if d != ports[n][0]:
            add(f"{n} 方向：文档 {d}，RTL {ports[n][0]}")
        try:
            v = evaluate(w, params)
        except Exception:
            add(f"{n} 位宽表达式求不出值：`{w}`"); continue
        if v != ports[n][1]:
            add(f"{n} 位宽：文档 `{w}` = {v}，RTL {ports[n][1]}")
    # 静态端口必须由设计需求担保、且匹配得到输入端口（内部#154，sta-static-ports D4）
    if top not in static_seen:
        static_seen.add(top)
        try:
            from flow.paths import static_ports
            declared = static_ports(top)
        except Exception as e:
            add(f"sta.static_ports 解析失败：{e}"); declared = []
        doc_text = open(spec_path, encoding="utf-8").read() if declared else ""
        inputs = [n for n, (d, _w) in ports.items() if d == "in"]
        for spec in declared:
            if f"**{spec['by']}**" not in doc_text:
                add(f"sta.static_ports 的 {spec['ports']} 写 by: {spec['by']}，{os.path.basename(spec_path)} 没有定义这条需求"
                    "（排除要由设计需求担保：用户 2026-10-04）")
            for pat in spec["ports"]:
                if not any(fnmatch.fnmatchcase(n, pat) for n in inputs):
                    add(f"sta.static_ports 的模式 {pat} 匹配不到任何输入端口")
        # depth 的验收场景（内部#189）：定值同样要由设计需求担保，端口是输入、值不超位宽
        try:
            from flow.paths import scenarios
            scen = scenarios(top)
        except Exception as e:
            add(f"sta.scenarios 解析失败：{e}"); scen = []
        doc_text = open(spec_path, encoding="utf-8").read() if scen else doc_text
        for sc in scen:
            if f"**{sc['by']}**" not in doc_text:
                add(f"sta.scenarios 的 {sc['name']} 写 by: {sc['by']}，{os.path.basename(spec_path)} 没有定义这条需求")
            for port, val in sc["case"].items():
                if port not in inputs:
                    add(f"sta.scenarios 的 {sc['name']} 给 {port} 定值，它不是输入端口")
                elif val >= (1 << ports[port][1]):
                    add(f"sta.scenarios 的 {sc['name']} 给 {port}（{ports[port][1]} 位）定值 {val}，超出位宽")

for (top, msg), where in sorted(issues.items()):
    more = f"，另 {len(where) - 1} 个组合同样" if len(where) > 1 else ""
    print(f"  {top}: {msg}（{where[0]}{more}）", file=sys.stderr)
if issues:
    print("  端口表的写法见 openspec/specs/repo-layout/spec.md「spec 的端口表必须能被机械地读出」；"
          "接口文档在专用设计树下是 lrs.<顶层>.md、在构件树下是 spec.<顶层>.md；"
          "改了 RTL 端口就同一个提交里改文档。", file=sys.stderr)
with open(os.path.join(os.path.dirname(sys.argv[1]), "portdoc.txt"), "w", encoding="utf-8") as f:
    f.write("、".join(f"{t} 按 {d}" for t, d in sorted(PORT_DOC.items())))
print(f"{len(tops)} {combos}")
sys.exit(1 if issues else 0)
