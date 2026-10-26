#!/usr/bin/env python3
"""两代记录逐字段配对 —— 「这次换代数字变没变」的一条命令。

在它之前，每次换代的零差异结论（D-11 / D-12 / D-13 / D-20 / D-22 ……）都是
临时写一段脚本配出来的，然后把输出转述进 `docs/data-credibility.md`。
口径每次都要重新说一遍（排除哪些字段、键怎么取、配不上的怎么报），
而转述本身就是出错面。这里把口径固定下来：

- **键**：`(design 大写归一, params)`。design 大写归一是因为 2026-09-21 之前的
  记录是小写顶层名（内部#46）；`design_root` 不进键 —— 它是位置不是身份，根搬家
  之后两代照样要配得上，它的变化作为普通字段差异报出来。
- **比什么**：记录摊平成字段路径逐项**严格相等**。零差异的声明就是逐位相同，
  不设容差。默认排除 `experiment_id` / `timestamp` / `git_commit` / `flow.*`
  以及任何以 `_path` 结尾的字段 —— 它们每次必变，不是测量值。
- **同代内重复键**：取文件里最后一条（与 `score.latest_per_params` 同一口径），
  并报出有几个。
- **配不上的必须点名**，不能消失在计数里（D-22 的 120 = 117 + 3 就是这么被
  发现的）。
- **只在一侧出现的字段**单列：那是 schema 只增（红线 2）带来的，不是测量变化，
  不影响退出码。

退出码：配上的组里没有任何值不同、两侧也没有配不上的、同代内重复测量也都
一致 → 0，否则 1。
所以它就是「零差异」类任务（keel `Strategy: equivalence`，内部#59）的判据命令。

用法：
    scripts/pair_generations.py --list [--design CBB_LZD]
    scripts/pair_generations.py --base 08e2aa1d --head 07ed6ae2 [--design CBB_LZD]
    scripts/pair_generations.py --base previous --head latest --show 5
"""
import argparse
import subprocess
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow.flow_fingerprint import (generation_key, generation_label,  # noqa: E402
                                   split_by_generation)
from scripts.score import DEFAULT_RECORDS, load_records  # noqa: E402

IGNORED_PREFIXES = ("experiment_id", "timestamp", "git_commit", "flow")


class PairError(Exception):
    pass


def flatten(obj, prefix=""):
    """{a: {b: 1}, c: [x, y]} → {"a.b": 1, "c.0": x, "c.1": y}。"""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = obj
    return out


def ignored(path, extra=()):
    head = path.split(".", 1)[0]
    if head in IGNORED_PREFIXES or path.endswith("_path"):
        return True
    return any(path == p or path.startswith(p + ".") for p in extra)


def pair_key(rec):
    params = rec.get("params") or {}
    return ((rec.get("design") or "").upper(),
            json.dumps(params, sort_keys=True, ensure_ascii=False))


def generations(records):
    """[(代的键, [记录…])]，按每一代**第一次**出现的文件序。"""
    return list(split_by_generation(records).items())


def parse_param_map(items):
    """["WIDTH=DAT_W", ...] → {"WIDTH": "DAT_W"}。格式不对、同一个旧键映射两次都拒绝。"""
    out = {}
    for it in items:
        old, sep, new = it.partition("=")
        if not sep or not old or not new:
            raise PairError(f"--param-map 要写成 旧=新，实得 {it!r}")
        if old in out and out[old] != new:
            raise PairError(f"--param-map 把 {old} 映射了两次：{out[old]} / {new}")
        out[old] = new
    return out


def apply_param_map(records, mapping):
    """把 records 的 params 键按 mapping 改名（返回副本，不动原记录）。

    只给调用方**显式**传进来的键改名：experiment-record 的「`params` 的键换过一次名，
    映射表是唯一合法的跨分界配对方式」。改名后若与已有键撞名，说明映射表写错了。
    """
    if not mapping:
        return records
    out = []
    for rec in records:
        params = rec.get("params") or {}
        renamed = {}
        for k, v in params.items():
            nk = mapping.get(k, k)
            if nk in renamed:
                raise PairError(f"{rec.get('experiment_id')}: 映射后参数 {nk} 撞名")
            renamed[nk] = v
        out.append(dict(rec, params=renamed))
    return out


def parse_value_map(items):
    """["SCHEME:CLA=1", ...] → {("SCHEME", "CLA"): 1}。键是**映射之后**的参数名。

    新值是整数字面量时按整数比（结构枚举 2026-09-29 起取整数），否则按字符串。
    格式不对、同一个 (键, 旧值) 映射两次都拒绝。
    """
    out = {}
    for it in items:
        key, sep1, rest = it.partition(":")
        old, sep2, new = rest.partition("=")
        if not (sep1 and sep2 and key and old and new) or "=" in key or "=" in new:
            raise PairError(f"--value-map 要写成 键:旧值=新值，实得 {it!r}")
        val = int(new) if new.lstrip("-").isdigit() else new
        if (key, old) in out and out[(key, old)] != val:
            raise PairError(f"--value-map 把 {key}:{old} 映射了两次：{out[(key, old)]} / {val}")
        out[(key, old)] = val
    return out


def apply_value_map(records, mapping):
    """把 records 的 params 取值按 mapping 改写（返回副本）。只改显式列出的
    (键, 旧值)，没列出的原样保留 —— 不按 labels 猜编号（experiment-record 的
    「取值映射同样只能显式给出」）。旧值按字符串比，记录里的 "CLA" 与 1 都能写。"""
    if not mapping:
        return records
    out = []
    for rec in records:
        params = rec.get("params") or {}
        out.append(dict(rec, params={k: mapping.get((k, str(v)), v) for k, v in params.items()}))
    return out


class _Ancestry:
    """「这个提交是不是分界提交或它的后代」，按提交缓存。

    改名不换代（指纹不含 RTL），所以分界两侧常在同一代里，只能按 git 祖先关系切。
    记录里的提交在仓库里找不到时直接报错：那样切出来的两侧不可信。
    """

    def __init__(self, repo, split_ref):
        self.repo = str(repo)
        self.split = self._rev(split_ref)
        if self.split is None:
            raise PairError(f"--split-at {split_ref!r} 不在仓库 {self.repo} 里")
        self.cache = {}

    def _rev(self, ref):
        r = subprocess.run(["git", "-C", self.repo, "rev-parse", "--verify", "--quiet",
                            f"{ref}^{{commit}}"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    def at_or_after(self, commit):
        if commit not in self.cache:
            if not commit or self._rev(commit) is None:
                raise PairError(f"记录里的 git_commit {commit!r} 不在仓库 {self.repo} 里，"
                                "没法判断它在分界的哪一侧")
            r = subprocess.run(["git", "-C", self.repo, "merge-base", "--is-ancestor",
                                self.split, commit], capture_output=True)
            self.cache[commit] = r.returncode == 0
        return self.cache[commit]


def resolve_generation(spec, gens):
    """`latest` / `previous` / 指纹前缀 → 代的键。前缀必须唯一命中。"""
    keys = [k for k, _ in gens]
    if not keys:
        raise PairError("记录里一代都没有")
    if spec == "latest":
        return keys[-1]
    if spec == "previous":
        if len(keys) < 2:
            raise PairError("只有一代，没有 previous")
        return keys[-2]
    want = spec.split(":")[-1].lower()
    hits = [k for k in keys
            if k[0] == "flow" and k[1].split(":")[-1].startswith(want)]
    if len(hits) != 1:
        raise PairError(f"指纹前缀 {spec!r} 命中 {len(hits)} 代，要恰好 1 代"
                        + ("（前缀给长一点）" if hits else ""))
    return hits[0]


def _measured(rec, extra_ignore=()):
    return {p: v for p, v in flatten(rec).items() if not ignored(p, extra_ignore)}


def index(records, extra_ignore=()):
    """{键: 记录}，同键取最后一条；外加 (重复键的个数, 其中与前一条值不一致的个数, 其中换过 RTL 的个数)。

    第二个数本身就是一条判据：同一代、同一组合跑两遍而数字不同，说明测量
    不确定 —— 那样的话任何跨代配对的「零差异」都不作数。
    两条的读入集合（`synth.sources_sha256`）不同时，中间改过 RTL（流程指纹不含 RTL），数字不同是电路变了，
    不是测量不稳：单列成第三个数，不计入第二个（内部#334 实撞：同一代里混着前后两版 RTL）。
    """
    out, dup, disagree, rtl_changed = {}, 0, 0, 0
    for rec in records:
        k = pair_key(rec)
        if k in out:
            dup += 1
            src_a = (out[k].get("synth") or {}).get("sources_sha256")
            src_b = (rec.get("synth") or {}).get("sources_sha256")
            if src_a and src_b and src_a != src_b:
                rtl_changed += 1
            else:
                disagree += _measured(out[k], extra_ignore) != _measured(rec, extra_ignore)
        out[k] = rec
    return out, (dup, disagree, rtl_changed)


def compare(base_recs, head_recs, extra_ignore=()):
    base, base_dup = index(base_recs, extra_ignore)
    head, head_dup = index(head_recs, extra_ignore)
    common = sorted(set(base) & set(head))
    diffs = {}          # 字段 → [(键, base 值, head 值)]
    only_side = {}      # 字段 → [base 有几组, head 有几组]
    for k in common:
        a, b = _measured(base[k], extra_ignore), _measured(head[k], extra_ignore)
        for p in set(a) | set(b):
            if p in a and p in b:
                if a[p] != b[p]:
                    diffs.setdefault(p, []).append((k, a[p], b[p]))
            else:
                cnt = only_side.setdefault(p, [0, 0])
                cnt[0 if p in a else 1] += 1
    return {
        "paired": len(common),
        "only_base": sorted(set(base) - set(head)),
        "only_head": sorted(set(head) - set(base)),
        "dup": (base_dup, head_dup),
        "diffs": diffs,
        "only_side": only_side,
    }


def _fmt_key(k):
    design, params = k
    return f"{design} {params}"


def report(res, base_label, head_label, n_base, n_head, show=0, notes=()):
    lines = [
        f"# 配对 {base_label}（{n_base} 条）↔ {head_label}（{n_head} 条）",
        "#   键 (design 大写归一, params)；排除 experiment_id / timestamp / "
        "git_commit / flow.* / *_path",
        f"#   配上 {res['paired']} 组；只有 base 一侧有 {len(res['only_base'])}；"
        f"只有 head 一侧有 {len(res['only_head'])}",
        f"#   同代内重复键 base {res['dup'][0][0]} / head {res['dup'][1][0]}（取最后一条），"
        f"其中与前一条值不一致 base {res['dup'][0][1]} / head {res['dup'][1][1]}",
    ]
    lines += [f"#   {n}" for n in notes]
    if res["diffs"]:
        lines.append("# 值不同的字段（组数）：")
        for p in sorted(res["diffs"]):
            lines.append(f"#   {p}  {len(res['diffs'][p])}")
            for k, a, b in res["diffs"][p][:show]:
                lines.append(f"#     {_fmt_key(k)}: {a!r} → {b!r}")
    if res["only_side"]:
        lines.append("# 只在一侧出现的字段（schema 只增带来的，不算测量变化）：")
        for p in sorted(res["only_side"]):
            nb, nh = res["only_side"][p]
            lines.append(f"#   {'+' if nh else '-'} {p}  base {nb} 组 / head {nh} 组")
    for side in ("only_base", "only_head"):
        if res[side]:
            lines.append(f"# 只有 {side[5:]} 一侧有：")
            lines += [f"#   {_fmt_key(k)}" for k in res[side]]
    changed = res["dup"][0][2] + res["dup"][1][2]
    if changed:
        lines.append(f"# 同一代内同一组合换过 RTL（读入集合不同）{changed} 组（base {res['dup'][0][2]} / head {res['dup'][1][2]}）："
                     "取最后一条比，不算测量不稳")
    unstable = res["dup"][0][1] + res["dup"][1][1]
    if unstable:
        lines.append(f"# ⚠️ 同一代内同一组合的重复测量不一致 {unstable} 处 —— "
                     "测量不确定时，跨代零差异不作数")
    zero = (not res["diffs"] and not res["only_base"] and not res["only_head"]
            and not unstable)
    lines.append("# 结论：" + ("零差异" if zero else "有差异（见上）"))
    return "\n".join(lines), zero


def list_generations(gens):
    """每一代一行：标签、条数、设计、时间范围、与上一代相比指纹里变了哪几项。"""
    lines, prev = [], None
    for key, recs in gens:
        flow = recs[0].get("flow") or {}
        designs = sorted({(r.get("design") or "").upper() for r in recs})
        ts = sorted(r.get("timestamp") or "" for r in recs)
        changed = ""
        if prev is not None and flow:
            moved = [f for f in flow if f != "fingerprint" and flow.get(f) != prev.get(f)]
            changed = "  变：" + (", ".join(moved) if moved else "（无）")
        lines.append(f"{generation_label(key)}  {len(recs):4d} 条  "
                     f"{ts[0][:10]}..{ts[-1][:10]}  {','.join(designs)}{changed}")
        prev = flow or prev
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", default=DEFAULT_RECORDS,
                    help="只读这一个记录文件（默认读全部 results/<设计根>/experiments.jsonl）")
    ap.add_argument("--design", help="只看这个被测顶层（大小写不敏感）")
    ap.add_argument("--list", action="store_true", help="列出各代")
    ap.add_argument("--base", help="指纹前缀 / previous / latest")
    ap.add_argument("--head", help="指纹前缀 / previous / latest")
    ap.add_argument("--ignore", action="append", default=[],
                    help="再排除一个字段（路径或前缀，如 synth.sources_sha256），可重复")
    ap.add_argument("--show", type=int, default=0, help="每个不同字段举几例")
    ap.add_argument("--param-map", action="append", default=[], metavar="旧=新",
                    help="只对 base 一侧把 params 的这个键改名后再配对（显式映射，可重复）")
    ap.add_argument("--value-map", action="append", default=[], metavar="键:旧值=新值",
                    help="只对 base 一侧把 params 里这个键的这个取值改写后再配对（在 --param-map "
                         "之后执行，键写改名之后的名字；显式映射，可重复）")
    ap.add_argument("--split-at", metavar="提交",
                    help="按 git 祖先关系切两侧：base 取分界之前的记录，head 取分界提交及其后代的记录")
    ap.add_argument("--repo", default=str(REPO_ROOT),
                    help="--split-at 用哪个 git 仓判断祖先关系（默认本仓）")
    a = ap.parse_args(argv)

    recs = load_records(a.records)
    if a.design:
        recs = [r for r in recs if (r.get("design") or "").upper() == a.design.upper()]
    gens = generations(recs)
    if a.list:
        print(list_generations(gens))
        return 0
    if not (a.base and a.head):
        ap.error("要么 --list，要么同时给 --base 与 --head")
    try:
        bk, hk = resolve_generation(a.base, gens), resolve_generation(a.head, gens)
    except PairError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2
    by = dict(gens)
    base_recs, head_recs, notes = by[bk], by[hk], []
    try:
        mapping = parse_param_map(a.param_map)
        vmap = parse_value_map(a.value_map)
        if a.split_at:
            anc = _Ancestry(a.repo, a.split_at)
            base_recs = [r for r in base_recs if not anc.at_or_after(r.get("git_commit"))]
            head_recs = [r for r in head_recs if anc.at_or_after(r.get("git_commit"))]
            notes.append(f"分界提交 {anc.split[:12]}：base 取它之前的记录，head 取它及其后代的记录")
        base_recs = apply_value_map(apply_param_map(base_recs, mapping), vmap)
    except PairError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2
    if mapping:
        notes.append("参数改名映射（只作用于 base 一侧）："
                     + "、".join(f"{o}→{n}" for o, n in mapping.items()))
    if vmap:
        notes.append("取值映射（只作用于 base 一侧，在改名之后）："
                     + "、".join(f"{k}:{o}→{n}" for (k, o), n in vmap.items()))
    res = compare(base_recs, head_recs, a.ignore)
    text, zero = report(res, generation_label(bk), generation_label(hk),
                        len(base_recs), len(head_recs), a.show, notes)
    print(text)
    return 0 if zero else 1


if __name__ == "__main__":
    sys.exit(main())
