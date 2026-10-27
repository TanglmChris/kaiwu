"""最坏外部耦合下的顶层组合环（io-comb-loops，内部#281；用户 2026-10-12 定，内部#281 issuecomment-6124031790）。

io_comb_deps 实测出「输出端口 ← 组合依赖的输入端口」之后，在端口图上补一层外部模型，再求强连通分量：
- 内部边：输入 → 输出（io_comb_deps 实测）；
- 外部边（D2，用户 2026-10-12 定「AXI 基线 + 显式声明」）：
  - AXI 基线：对方的 rdy 可以组合依赖本方给它的 vld 与数据 —— 本方每个非 rdy 输出 → 同一对方的本方 `*_rdy` 输入；
  - 显式声明：对端已知会随本方 rdy 组合变化的输入（只限用户或器件文档给出、LRS 标了「例外，出处」的，
    docs/spec-writing.md §3），在 `iodeps_loops.rdy_dependent`
    里逐个列出 —— 本方每个 `*_rdy` 输出 → 同一对方的这些输入。没声明的对方输入按 AXI 视为不随本方 rdy 变。

对方按两档算：按对方整体（`s` 侧 / `m` 侧）判 FAIL；按通道（`s_cmd`、`m_rdat`…）只作参考。外部边对一个端口的
每一位都连，所以端口级图上成环与逐位网表上成环等价，不会因按端口归并而多报。

端口归组（D1）：按名字前缀 `<侧>_<通道>_` 自动分（`s_cmd_vld` → 对方 `s`、通道 `s_cmd`），sideband 跟着
前缀走。第一段是方向 `i` / `o` 的（通用构件的 `i_src_vld`、`o_dst_rdy`）按 `<方向>_<对方>_` 读，对方与通道都取
第二段（`src`、`dst`），不把 `i` / `o` 当成对方（内部#449）。按对方整体一条外部边都没连上时，结果的 loop_notes 里说出来。分不进组的端口要在 `params.yaml` 的 `tops:<顶层>:iodeps_loops:` 里显式声明，没声明就报错：

    iodeps_loops:
      peers:                       # 自成一个对方（按通道那档也当一个通道）
        csr: [ecc_*_intr*, ...]
      no_peer: [o_cg_idle]         # 外部不把它组合送回本模块的端口，不参与外部模型
      rdy_dependent: [m_rdat_*_flg] # 对端随本方 rdy 组合变化的输入（清单来自 LRS 的对端假设）

时钟、复位与 `sta.static_ports` 的端口（io_comb_deps 不计的那些）不参与，也不用声明。

LRS 可以有一张「允许的接口组合环」表（D3）：表头第一格「环上端口」，每行一个环，反引号写端口名或通配，
用「、」分隔。按对方整体算出的环，端口集合与某一行恰好对得上（每个端口都匹配某个通配、每个通配都
匹配到端口）就算允许，不判 FAIL。没有这张表等于不允许任何环。
"""
import fnmatch
import re

PREFIX = re.compile(r"^([a-z])_([a-z0-9]+)_")
ALLOW_HEADER = "环上端口"


class GroupError(ValueError):
    """端口分不进组，或 iodeps_loops 写错。"""


def _match(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def group_ports(ports, decl, exclude=()):
    """{端口: (对方, 通道)}，只含参与外部模型的端口。ports 是 {端口: 'input'|'output'}。

    分不进组的端口一次全部报出（GroupError）。"""
    decl = decl or {}
    if not isinstance(decl, dict) or set(decl) - {"peers", "no_peer", "rdy_dependent"}:
        raise GroupError("iodeps_loops 只认 peers（{对方: [端口通配]}）、no_peer 与 rdy_dependent（[端口通配]）三项")
    peers = decl.get("peers") or {}
    no_peer = decl.get("no_peer") or []
    if not isinstance(peers, dict) or not all(isinstance(v, list) for v in peers.values()) \
            or not isinstance(no_peer, list) or not isinstance(decl.get("rdy_dependent") or [], list):
        raise GroupError("iodeps_loops.peers 要写成 {对方: [端口通配]}，no_peer / rdy_dependent 要写成 [端口通配]")
    out, bad = {}, []
    for name in sorted(ports):
        if _match(name, exclude):
            continue
        hit = [p for p, pats in peers.items() if _match(name, pats)]
        if len(hit) > 1:
            bad.append(f"{name}（同时匹配 peers 的 {', '.join(hit)}）")
            continue
        if hit:
            out[name] = (hit[0], hit[0])
            continue
        if _match(name, no_peer):
            continue
        m = PREFIX.match(name)
        if m and m.group(1) in "io":      # 通用构件的方向前缀：i_src_vld → 对方 src（内部#449）
            out[name] = (m.group(2), m.group(2))
            continue
        if m:
            out[name] = (m.group(1), f"{m.group(1)}_{m.group(2)}")
            continue
        bad.append(name)
    if bad:
        raise GroupError("这些端口按前缀分不进通道，要在 params.yaml 的 iodeps_loops 里声明"
                         "（peers 归到某个对方，或 no_peer 表示外部不组合送回）：" + "、".join(bad))
    return out


def _scc(nodes, succ):
    """强连通分量（Tarjan，迭代）。"""
    index, low, on, stack, comps, counter = {}, {}, set(), [], [], 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(succ.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(succ.get(w, ()))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    comps.append(comp)
    return comps


def _rdy(name):
    return name.endswith("_rdy")


def external_edges(ports, groups, by="peer", rdy_dependent=()):
    """外部模型的边 [(本方输出, 本方输入)]：同一对方（或通道）里，AXI 基线与显式声明的那些。"""
    key = 0 if by == "peer" else 1
    edges = []
    for o, go in groups.items():
        if ports.get(o) != "output":
            continue
        for i, gi in groups.items():
            if ports.get(i) != "input" or gi[key] != go[key]:
                continue
            if (_rdy(i) and not _rdy(o)) or (_rdy(o) and _match(i, rdy_dependent)):
                edges.append((o, i))
    return edges


def find_loops(deps, ports, groups, by="peer", rdy_dependent=()):
    """外部模型下的组合环。返回 [{ports: [...], internal: [(输入, 输出)...]}]，按端口名排序。

    deps 是 {输出: {输入}}；by 取 'peer'（按对方整体）或 'channel'（按通道）。"""
    succ = {}
    for out, ins in deps.items():
        for i in ins:
            succ.setdefault(i, set()).add(out)
    for o, i in external_edges(ports, groups, by, rdy_dependent):
        succ.setdefault(o, set()).add(i)
    nodes = sorted(set(ports) | set(succ))
    loops = []
    for comp in _scc(nodes, {k: sorted(v) for k, v in succ.items()}):
        if len(comp) < 2:
            continue
        members = set(comp)
        internal = sorted((i, o) for o, ins in deps.items() if o in members for i in ins if i in members)
        loops.append(dict(ports=sorted(members), internal=internal))
    return sorted(loops, key=lambda x: x["ports"])


def parse_allowed(text):
    """LRS 的「允许的接口组合环」表 → [(行号, [端口通配])]。没有这张表返回 []。"""
    rows, in_table = [], False
    for n, line in enumerate(text.splitlines(), 1):
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else None
        if cells is None:
            in_table = False
            continue
        if cells[0] == ALLOW_HEADER:
            in_table = True
            continue
        if not in_table or set(cells[0]) <= set("-: "):
            continue
        pats = re.findall(r"`([^`]+)`", cells[0])
        if not pats or re.sub(r"`[^`]+`|、|\s", "", cells[0]):
            raise GroupError(f"LRS 第 {n} 行：「{ALLOW_HEADER}」格只能是反引号写的端口名或通配，用「、」分隔")
        rows.append((n, pats))
    return rows


def allowed_by(loop, rows):
    """环的端口集合与某一行恰好对得上时返回那一行的行号，否则 None。"""
    for n, pats in rows:
        if all(_match(p, pats) for p in loop["ports"]) and \
                all(any(fnmatch.fnmatchcase(p, pat) for p in loop["ports"]) for pat in pats):
            return n
    return None


def check(deps, ports, decl, exclude, allowed_rows):
    """一组配置的结果：按对方整体的环（带 allowed 行号）、按通道的环（参考）、passed。"""
    groups = group_ports(ports, decl, exclude)
    rdy_dep = (decl or {}).get("rdy_dependent") or []
    unmatched = [p for p in rdy_dep if not any(fnmatch.fnmatchcase(n, p) for n in groups if ports[n] == "input")]
    if unmatched:
        raise GroupError("iodeps_loops.rdy_dependent 里这些通配没匹配到任何参与外部模型的输入：" + "、".join(unmatched))
    peer = find_loops(deps, ports, groups, "peer", rdy_dep)
    for loop in peer:
        loop["allowed"] = allowed_by(loop, allowed_rows)
    channel = find_loops(deps, ports, groups, "channel", rdy_dep)
    notes = []
    if not external_edges(ports, groups, "peer", rdy_dep):
        # 只提示不判失败：没有握手的纯组合构件本来就连不上边（内部#449）
        notes.append("外部模型没有连上任何边，环检查等于没做：核对端口分组（报告的对方 / 通道），"
                     "需要时用 iodeps_loops.peers 声明")
    return dict(peer_loops=peer, channel_loops=channel, loop_notes=notes,
                passed=all(loop["allowed"] is not None for loop in peer))
