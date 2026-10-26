#!/usr/bin/env python3
"""冻结一轮功能验证的输入，并记录设计侧、验证侧与流程侧的出处（内部#80）。

设计与验证分属两条分支、两个工作区时（docs/toolchain.md「设计与验证分属两个
worktree」），一轮验证要回答两个问题：测的是哪一版设计、用的是哪一版 TB。本模块
把这轮要读的文件按仓库布局复制到 `<out>/tree/`，设为只读，并写 `<out>/manifest.json`：

- 设计树（`flow/paths.py` 的 `DESIGN_TREES`：`designs/`、`cbb/`）取自设计侧：`--design-ref` 给的提交（从 git 对象库取，不读
  任何工作区），或 `--design-worktree` 给的工作区（只作开发运行，结果不可交付）；
- 被测设计根下的 `tb/` 与 `verify.<顶层>.md` 取自验证侧：`--tb-ref` 给的提交，或
  本工作区（默认）；
- `params.yaml` 取自设计侧，但各顶层的 `sim:` 段取自验证侧（分工表：`sim:` 归验证）；
- 叠加（内部#341）：`--overlay <ref>:<路径>` 把设计树下的一个路径换成另一个提交里的（组合被测，如设计提交 +
  另一提交的 `cbb/`），`--overlay-local <源>:<路径>` 换成本地文件或目录（RTL 变异体做失败臂，不可交付）。
  不许越出 `designs/`、`cbb/`，不许碰被测设计根的 `tb/` 与 `verify.*.md`。

`deliverable` 为真，当且仅当设计与 TB 都来自提交、没有本地叠加、且流程侧（运行本模块的这份
checkout 的 `flow/` 与 `scripts/`）没有未提交的改动。

各设计的 runner 以 `tree` 为 `repo_root` 调 `flow.paths.rtl_candidates(top, repo_root=tree)`
取源文件，用 `flow.verify.judge` 判结果。契约在 openspec/specs/design-verify-collaboration。

    .venv/bin/python3 flow/verify/freeze.py --top <顶层> \\
        --design-ref origin/worktree-<设计> --out runs/verify_x
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import yaml

FLOW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FLOW_ROOT))

from flow.paths import (DESIGN_TREES, DesignRootError, ParamError,  # noqa: E402
                        resolve_design_root, rtl_candidates)

DESIGN_DIRS = DESIGN_TREES


class FreezeError(Exception):
    pass


def _git(repo, *args, binary=False):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=not binary)
    if r.returncode != 0:
        err = r.stderr if not binary else r.stderr.decode(errors="replace")
        raise FreezeError(f"git {' '.join(args)} 失败：{err.strip()}")
    return r.stdout


def _commit_of(repo, ref, side):
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise FreezeError(
            f"{side}的 ref {ref!r} 解析不到提交。别的分支的提交要先在那边 git push、"
            f"这边 git fetch，再用 origin/<分支>")
    return r.stdout.strip()


def _worktree_files(wt, pathspecs):
    """工作区里已跟踪的加上未忽略的未跟踪文件（D6）。"""
    out = _git(wt, "ls-files", "-co", "--exclude-standard", "-z", "--", *pathspecs)
    return sorted({p for p in out.split("\0") if p and (Path(wt) / p).is_file()})


def _worktree_dirty(wt, pathspecs):
    return bool(_git(wt, "status", "--porcelain", "--", *pathspecs).strip())


def _extract_commit(repo, commit, pathspecs, dest):
    present = [p for p in pathspecs if _git(repo, "ls-tree", "--name-only", commit, "--", p).strip()]
    if not present:
        return
    data = _git(repo, "archive", "--format=tar", commit, "--", *present, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        # 内容来自本仓的 git 对象库；本机 Python 的 tarfile 还没有 filter= 参数
        tar.extractall(dest)


def _copy_worktree(wt, pathspecs, dest):
    for rel in _worktree_files(wt, pathspecs):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(wt) / rel, target)


def _tb_specs(root_rel):
    return [f"{root_rel}/tb", f":(glob){root_rel}/verify.*.md"]


def _overlay_tb(tree, root_rel, *, repo, tb_commit, tb_worktree):
    """设计根下的 tb/ 与 verify.<顶层>.md 换成验证侧的；返回换进来的相对路径。"""
    shutil.rmtree(tree / root_rel / "tb", ignore_errors=True)
    for old in (tree / root_rel).glob("verify.*.md"):
        old.unlink()
    staging = tree.parent / "tb_staging"
    staging.mkdir()
    if tb_commit:
        _extract_commit(repo, tb_commit, [f"{root_rel}/tb"], staging)
        names = _git(repo, "ls-tree", "--name-only", tb_commit, f"{root_rel}/").split("\n")
        verify_docs = [n for n in names if Path(n).name.startswith("verify.") and n.endswith(".md")]
        if verify_docs:
            _extract_commit(repo, tb_commit, verify_docs, staging)
    else:
        _copy_worktree(tb_worktree, _tb_specs(root_rel), staging)
    moved = []
    for p in sorted(staging.rglob("*")):
        if p.is_file():
            rel = p.relative_to(staging)
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), tree / rel)
            moved.append(rel.as_posix())
    shutil.rmtree(staging)
    return moved


def _tb_params(root_rel, *, repo, tb_commit, tb_worktree):
    rel = f"{root_rel}/params.yaml"
    if tb_commit:
        r = subprocess.run(["git", "-C", str(repo), "show", f"{tb_commit}:{rel}"],
                           capture_output=True, text=True)
        return yaml.safe_load(r.stdout) if r.returncode == 0 else None
    p = Path(tb_worktree) / rel
    return yaml.safe_load(p.read_text()) if p.is_file() else None


def _overlay_sim(tree, root_rel, tb_params):
    """各顶层的 sim: 段换成验证侧的。验证侧没有这个顶层时保留设计侧的。返回是否改动。"""
    if not tb_params:
        return False
    path = tree / root_rel / "params.yaml"
    params = yaml.safe_load(path.read_text())
    tb_tops = tb_params.get("tops") or {}
    changed = False
    for top, cfg in (params.get("tops") or {}).items():
        if top not in tb_tops:
            continue
        tb_sim = (tb_tops[top] or {}).get("sim")
        if cfg.get("sim") != tb_sim:
            changed = True
            if tb_sim is None:
                cfg.pop("sim", None)
            else:
                cfg["sim"] = tb_sim
    if changed:
        path.write_text(yaml.safe_dump(params, allow_unicode=True, sort_keys=False))
    return changed


def _split_overlay(spec):
    """`<来源>:<路径>` 按最后一个冒号拆开（路径里没有冒号）。"""
    src, sep, path = spec.rpartition(":")
    if not sep or not src or not path:
        raise FreezeError(f"叠加 {spec!r} 要写成 <来源>:<路径>（用冒号分开）")
    return src, path


def _overlay_path(path, root_rel):
    """规范化叠加路径并核合法：在设计树之下，不碰被测设计根的 tb/ 与 verify 文档。"""
    norm = os.path.normpath(path).replace(os.sep, "/")
    if norm.startswith("../") or os.path.isabs(norm) or norm.split("/")[0] not in DESIGN_DIRS:
        raise FreezeError(f"叠加路径 {path!r} 不在 {'、'.join(d + '/' for d in DESIGN_DIRS)} 之下")
    tb = f"{root_rel}/tb"
    if norm == tb or norm.startswith(tb + "/") or root_rel.startswith(norm + "/") or norm == root_rel \
            or (Path(norm).parent.as_posix() == root_rel and Path(norm).name.startswith("verify.")):
        raise FreezeError(f"叠加路径 {path!r} 碰到了被测设计根的 tb/ 或 verify 文档（那是验证侧的输入，用 --tb-ref）")
    return norm


def _apply_overlays(tree, root_rel, repo, overlays, overlays_local, reasons):
    """按给出顺序叠加；返回 manifest 的 overlays 列表。"""
    done = []
    for kind, spec in [("ref", s) for s in overlays] + [("local", s) for s in overlays_local]:
        src, path = _split_overlay(spec)
        path = _overlay_path(path, root_rel)
        target = tree / path
        if kind == "ref":
            commit = _commit_of(repo, src, "叠加")
            if not _git(repo, "ls-tree", "--name-only", commit, "--", path).strip():
                raise FreezeError(f"叠加的提交 {src}（{commit[:8]}）里没有 {path}")
            _remove(target)
            _extract_commit(repo, commit, [path], tree)
            done.append({"path": path, "ref": src, "commit": commit})
        else:
            s = Path(src)
            if not s.exists():
                raise FreezeError(f"叠加的本地源 {src} 不存在")
            _remove(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if s.is_dir() else shutil.copyfile)(s, target)
            done.append({"path": path, "local": str(s)})
            reasons.append(f"叠加了本地文件 {s} → {path}，不是提交")
    return done


def _remove(p):
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def _make_read_only(tree):
    for dirpath, dirnames, filenames in os.walk(tree, topdown=False):
        for f in filenames:
            os.chmod(os.path.join(dirpath, f), 0o444)
        os.chmod(dirpath, 0o555)


def freeze(top, out, *, design_ref=None, design_worktree=None, tb_ref=None, tb_worktree=None,
           overlays=(), overlays_local=(), repo=None, flow_root=FLOW_ROOT):
    """冻结 `top` 的一轮验证输入到 `out`，返回 manifest（同时写 `out/manifest.json`）。

    `repo`：解析 ref 用的 git 仓（同一仓的任一工作区都行，对象库共享），默认当前目录。
    设计侧给 `design_ref` 或 `design_worktree` 之一；验证侧给 `tb_ref` 或 `tb_worktree`
    之一，都不给时取 `repo` 的工作区。`overlays` / `overlays_local` 是 `<来源>:<路径>` 的列表（内部#341）。
    """
    if (design_ref is None) == (design_worktree is None):
        raise FreezeError("设计侧要给 design_ref 或 design_worktree 之一")
    if tb_ref is not None and tb_worktree is not None:
        raise FreezeError("验证侧 tb_ref 与 tb_worktree 只能给一个")
    repo = Path(repo or os.getcwd()).resolve()
    if tb_ref is None and tb_worktree is None:
        tb_worktree = repo
    out = Path(out)
    if out.exists():
        raise FreezeError(f"输出目录已存在：{out}（每轮用新目录，旧结果不覆盖）")

    reasons = []
    if design_ref is not None:
        d_commit = _commit_of(repo, design_ref, "设计侧")
        design = {"ref": design_ref, "commit": d_commit}
    else:
        wt = Path(design_worktree).resolve()
        d_commit = None
        design = {"worktree": str(wt), "head": _git(wt, "rev-parse", "HEAD").strip(),
                  "dirty": _worktree_dirty(wt, list(DESIGN_DIRS))}
        reasons.append("设计侧取自工作区（--design-worktree），不是一个提交")
    if tb_ref is not None:
        t_commit = _commit_of(repo, tb_ref, "验证侧")
        tb = {"ref": tb_ref, "commit": t_commit}
    else:
        t_commit = None
        tb = {"worktree": str(Path(tb_worktree).resolve()),
              "head": _git(tb_worktree, "rev-parse", "HEAD").strip()}

    out.mkdir(parents=True)
    tree = out / "tree"
    tree.mkdir()
    try:
        if d_commit:
            _extract_commit(repo, d_commit, list(DESIGN_DIRS), tree)
        else:
            _copy_worktree(design_worktree, list(DESIGN_DIRS), tree)
        try:
            root = resolve_design_root(top, repo_root=tree)
        except DesignRootError as e:
            raise FreezeError(f"设计侧没有可用的顶层 {top}：{e}") from e
        root_rel = root.relative_to(tree).as_posix()
        overlay_log = _apply_overlays(tree, root_rel, repo, overlays, overlays_local, reasons)
        if t_commit is None:
            tb["dirty"] = _worktree_dirty(tb_worktree, _tb_specs(root_rel) + [f"{root_rel}/params.yaml"])
            if tb["dirty"]:
                reasons.append(f"TB 有未提交的改动（{root_rel}/tb、verify 文档或 params.yaml）")
            reasons.append("TB 取自工作区，不是一个提交")
        tb_files = set(_overlay_tb(tree, root_rel, repo=repo, tb_commit=t_commit, tb_worktree=tb_worktree))
        sim_from_tb = _overlay_sim(tree, root_rel,
                                   _tb_params(root_rel, repo=repo, tb_commit=t_commit, tb_worktree=tb_worktree))
        try:
            rtl_candidates(top, repo_root=tree)
        except (DesignRootError, ParamError) as e:
            raise FreezeError(f"{top} 的依赖在设计侧不完整：{e}") from e
    except BaseException:
        shutil.rmtree(out)
        raise

    flow = {"root": str(Path(flow_root).resolve()),
            "commit": _git(flow_root, "rev-parse", "HEAD").strip(),
            "dirty": _worktree_dirty(flow_root, ["flow", "scripts"])}
    if flow["dirty"]:
        reasons.append("流程侧（flow/、scripts/）有未提交的改动")

    files = {}
    over = [o["path"] for o in overlay_log]
    for p in sorted(tree.rglob("*")):
        if p.is_file():
            rel = p.relative_to(tree).as_posix()
            side = "tb" if rel in tb_files else "design"
            if any(rel == o or rel.startswith(o + "/") for o in over):
                side = "overlay"
            if rel == f"{root_rel}/params.yaml" and sim_from_tb:
                side = "design+tb(sim)"
            files[rel] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "side": side}
    _make_read_only(tree)

    manifest = {"top": top, "design_root": root_rel, "tree": str(tree.resolve()),
                "design": design, "tb": tb, "flow": flow, "overlays": overlay_log,
                "deliverable": not reasons, "not_deliverable_because": reasons,
                "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", required=True, help="被测顶层名（如 CBB_LZD）")
    d = ap.add_mutually_exclusive_group(required=True)
    d.add_argument("--design-ref", help="设计侧的提交 / 分支（可交付）")
    d.add_argument("--design-worktree", help="设计侧的工作区路径（只作开发运行，不可交付）")
    t = ap.add_mutually_exclusive_group()
    t.add_argument("--tb-ref", help="验证侧的提交 / 分支；不给则取当前工作区")
    t.add_argument("--tb-worktree", help="验证侧的工作区路径（默认当前工作区）")
    ap.add_argument("--overlay", action="append", default=[], metavar="REF:PATH",
                    help="设计树下的 PATH 换成提交 REF 里的（可重复，按顺序生效；可交付）")
    ap.add_argument("--overlay-local", action="append", default=[], metavar="SRC:PATH",
                    help="设计树下的 PATH 换成本地文件或目录 SRC（如变异体；该轮不可交付）")
    ap.add_argument("--out", required=True, help="新的输出目录；已存在则拒绝")
    ap.add_argument("--repo", default=None, help="解析 ref 用的 git 仓（默认当前目录）")
    a = ap.parse_args(argv)
    try:
        m = freeze(a.top, a.out, design_ref=a.design_ref, design_worktree=a.design_worktree,
                   tb_ref=a.tb_ref, tb_worktree=a.tb_worktree, overlays=a.overlay,
                   overlays_local=a.overlay_local, repo=a.repo)
    except FreezeError as e:
        print(f"freeze: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: m[k] for k in ("top", "design_root", "tree", "design", "tb", "flow", "overlays",
                                        "deliverable", "not_deliverable_because")},
                     indent=2, ensure_ascii=False))
    print(f"manifest：{Path(a.out) / 'manifest.json'}（{len(m['files'])} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
