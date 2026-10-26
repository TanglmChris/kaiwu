"""实验记录的存放位置：每个设计根一个文件 `results/<设计根>/experiments.jsonl`（内部#422）。

写到哪、从哪读、历史单文件怎么搬，都只在这里定。契约在 `openspec/specs/experiment-record/spec.md`
的「实验记录按设计根分文件存放」「历史记录按设计根搬迁且逐字节守恒」。

不在 `flow/flow_fingerprint.py` 的 METRIC_MODULES 里：本模块不碰测量值，只决定记录落在哪个文件
（与 score.py / gen_report.py「只读记录、不写测量值」同一判据）。`scripts/run_experiment.py` 在
METRIC_MODULES 里，改它就换代，所以写入目标由 `scripts/exp.py` / `scripts/sweep.py` 用
`log_path()` 覆盖它的模块常量，与 TRIAL 同一写法。

搬迁只认原始字节：不 json.dumps 回写，不改空白和键序，每个文件内同一顶层的行保持原相对顺序 ——
读者靠「后追加的最新」挑同一参数组合的最新记录（score.latest_per_params）。

用法：
    python -m flow.records migrate [--dry-run]    # 把 results/experiments.jsonl 搬进各设计根文件
"""
import argparse
import heapq
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_NAME = "experiments.jsonl"
LEGACY_REL = "results/experiments.jsonl"


class MigrationError(RuntimeError):
    pass


def root_of(record):
    """新记录的设计根：`design_root` 字段。没有时取 `design`（那段历史里设计根名等于顶层名）。"""
    return record.get("design_root") or record["design"]


def legacy_roots(recs):
    """历史行的归属：一个顶层的全部行进同一个文件（design.md D1、F8）。

    取该顶层**最后一条**带 `design_root` 的记录的设计根，一条都没有时取 `design`。逐行按
    `root_of` 分会把两个后来换了设计根的老顶层各劈成两个文件，读者按文件名
    拼接时同一顶层的先后就乱了。
    """
    roots = {}
    for rec in recs:
        if rec.get("design_root"):
            roots[rec["design"]] = rec["design_root"]
        else:
            roots.setdefault(rec["design"], rec["design"])
    return roots


def _repo(repo_root):
    return Path(repo_root) if repo_root is not None else REPO_ROOT


def log_path(design, repo_root=None):
    """顶层 `design` 的新记录写到哪：它当前所在设计根的记录文件。"""
    from flow import paths
    repo_root = _repo(repo_root)
    root = paths.resolve_design_root(design, repo_root=repo_root)
    return repo_root / "results" / root.name / RECORD_NAME


def rel_log_path(design, repo_root=None):
    """同上，相对仓库根（脏树守卫比对 `git status --porcelain` 用）。"""
    return log_path(design, repo_root).relative_to(_repo(repo_root)).as_posix()


@contextmanager
def redirect(rx, path, repo_root=None):
    """让 `scripts/run_experiment` 这一段把记录追加到 `path`，脏树守卫只放行这一个文件，退出时复原。

    改的是 rx 的三个模块级名字（调用时才读）：`EXPERIMENTS_LOG`、`LOG_PATH_IN_STATUS`、`_worktree_status`。
    最后一个换成 `--untracked-files=all`：新设计根的第一条记录写完，`git status --porcelain` 默认只报
    `?? results/<根>/` 这个目录，与守卫放行的文件路径对不上，扫参会在第二个组合上自锁；逐文件列出以后
    守卫看到的条目只多不少，拦什么不变。`path` 不在仓库里（测试夹具）时不改放行路径。
    """
    repo_root = _repo(repo_root)
    saved = (rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS, rx._worktree_status)
    path = Path(path)
    try:
        rel = path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        rel = rx.LOG_PATH_IN_STATUS

    def status_all():
        return subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo_root,
                              capture_output=True, text=True, check=True).stdout

    rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS, rx._worktree_status = path, rel, status_all
    try:
        yield path
    finally:
        rx.EXPERIMENTS_LOG, rx.LOG_PATH_IN_STATUS, rx._worktree_status = saved


def record_files(repo_root=None):
    """全部设计根的记录文件，按路径排序。已删除设计根的文件照样在里面。"""
    return sorted((_repo(repo_root) / "results").glob(f"*/{RECORD_NAME}"))


def source_files(repo_root=None):
    """`load()` 实际读的文件：全部设计根的记录文件；一个都没有而旧单文件还在时（搬迁之前）读旧单文件。

    两者都在时只读设计根文件，不把旧文件叠加进来 —— 合并带回的旧文件里多半是已搬过的行，叠加会重复计数；
    那个状态由 fast_check 的「旧文件不得残留」拦下，提示 `python -m flow.records migrate`。
    """
    files = record_files(repo_root)
    legacy = _repo(repo_root) / LEGACY_REL
    return files if files or not legacy.is_file() else [legacy]


def load(design=None, repo_root=None, path=None):
    """读记录。`path` 给了就只读那一个文件（旧的单文件用法），否则读全部设计根的文件。

    多个文件按 `timestamp` **归并**（heapq.merge：各文件内部的行序原样保留，文件之间按时间交错），
    不按文件名拼接。读者里有两处靠全局次序：「最新一代 = 序列里最后一条记录所属的代」
    （score.select_generation，netlist_equiv / pair_generations 不带 --design 时跨设计用它）。
    搬迁时实测：3464 行按此归并后与原单文件逐行同序（design.md F9）。按 `design` 过滤；None 时全读。
    """
    files = [Path(path)] if path is not None else source_files(repo_root)
    streams = []
    for f in files:
        if not f.is_file():
            continue
        recs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        streams.append(recs)
    merged = heapq.merge(*streams, key=lambda r: r.get("timestamp") or "")
    return [r for r in merged if design is None or r.get("design") == design]


def _raw_lines(path):
    """文件的非空行，原始文本（不含行尾）。"""
    if not path.is_file():
        return []
    return [l for l in path.read_bytes().decode().splitlines() if l.strip()]


def _write_file(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(lines) + "\n").encode())


def _check(legacy, by_root, repo_root):
    """搬迁后的自检：原文件每一行恰好在一个记录文件里，每个文件内的原文件行保持原相对顺序。"""
    index = {l: i for i, l in enumerate(legacy)}
    seen = {}
    for root in by_root:
        got = _raw_lines(Path(repo_root) / "results" / root / RECORD_NAME)
        pos = [index[l] for l in got if l in index]
        if pos != sorted(pos):
            raise MigrationError(f"results/{root}/{RECORD_NAME} 里原文件行的相对顺序变了")
        for l in got:
            if l in index:
                seen[l] = seen.get(l, 0) + 1
    missing = [l for l in legacy if l not in seen]
    dup = [l for l, n in seen.items() if n > 1]
    if missing or dup:
        raise MigrationError(f"原文件 {len(legacy)} 行里有 {len(missing)} 行没搬到、{len(dup)} 行出现在多个文件里")


def migrate(repo_root=None, dry_run=False):
    """把 `results/experiments.jsonl` 按设计根搬进各记录文件，自检通过后删掉原文件。

    可以重复执行：目标文件里已有逐字节相同的行就跳过（原文件 3464 行互不相同，design.md F1），
    所以合并又带回一个多了几行的原文件时，只补那几行。自检失败时 MigrationError，原文件保留。
    """
    repo_root = _repo(repo_root)
    legacy_path = repo_root / LEGACY_REL
    legacy = _raw_lines(legacy_path)
    if len(set(legacy)) != len(legacy):
        raise MigrationError(f"{LEGACY_REL} 里有逐字节重复的行，去重补搬会少搬，先人工核")
    roots = legacy_roots([json.loads(l) for l in legacy])
    by_root = {}
    for l in legacy:
        by_root.setdefault(roots[json.loads(l)["design"]], []).append(l)
    summary = {"lines": len(legacy), "added": 0,
               "roots": {r: len(ls) for r, ls in sorted(by_root.items())}}
    if dry_run or not legacy:
        return summary
    for root, lines in sorted(by_root.items()):
        path = repo_root / "results" / root / RECORD_NAME
        have = _raw_lines(path)
        known = set(have)
        new = [l for l in lines if l not in known]
        if new:
            _write_file(path, have + new)
            summary["added"] += len(new)
    _check(legacy, by_root, repo_root)
    legacy_path.unlink()
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help=f"把 {LEGACY_REL} 搬进 results/<设计根>/{RECORD_NAME}")
    m.add_argument("--dry-run", action="store_true", help="只报各设计根的行数，不写文件")
    m.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    a = ap.parse_args(argv)
    try:
        s = migrate(a.repo_root, dry_run=a.dry_run)
    except MigrationError as e:
        print(f"FAIL  搬迁自检没过，{LEGACY_REL} 原样保留：{e}", file=sys.stderr)
        return 1
    print(f"{LEGACY_REL}：{s['lines']} 行，{len(s['roots'])} 个设计根"
          + ("（--dry-run，没写文件）" if a.dry_run else f"，新补 {s['added']} 行"))
    for r, n in s["roots"].items():
        print(f"  results/{r}/{RECORD_NAME}  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
