"""磁盘护栏（内部#173，用户 2026-10-05 定；那天 Data 卷写满，全部会话的 shell 失败、正在跑的结果作废）。

    .venv/bin/python3 flow/disk.py check            # 剩余空间低于阈值就退出 1
    .venv/bin/python3 flow/disk.py check --need 30  # 另外还要 30 GB

两件事：
- `require_free`：大任务（综合、扫参、回归、全链路试跑）开跑前查剩余空间，低于 `MIN_FREE_GB`
  （加上本任务预估要用的）就拒绝开跑。阈值可用环境变量 `RTL_PPA_MIN_FREE_GB` 改。
- `prune_old`：按名字排序（时间戳目录名即时间序），只留最近 `keep` 份，删更旧的；
  还有进程打开着的（`lsof +D`）跳过不删。

只删 `runs/` 下的可重建产物（与 `make clean` 的约定一致），不碰记录与证据。
不进 `METRIC_MODULES`，不改任何测量值。
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIN_FREE_GB = 20.0
KEEP_BUILDS = 3


class DiskSpaceError(RuntimeError):
    pass


def free_gb(path=REPO_ROOT):
    return shutil.disk_usage(path).free / 1e9


def min_free_gb():
    return float(os.environ.get("RTL_PPA_MIN_FREE_GB", MIN_FREE_GB))


def require_free(need_gb=0.0, what="本任务", path=REPO_ROOT):
    """剩余空间低于 阈值 + need_gb 就抛 DiskSpaceError。返回当前剩余（GB）。"""
    free, floor = free_gb(path), min_free_gb() + need_gb
    if free < floor:
        raise DiskSpaceError(
            f"磁盘剩余 {free:.1f} GB，低于 {floor:.1f} GB（阈值 {min_free_gb():.0f} GB + {what}预估 {need_gb:.1f} GB），"
            f"拒绝开跑：先清自己产生的 runs/（docs/toolchain.md「磁盘使用」，#173）")
    return free


def in_use(path):
    """有进程打开着 path 下的文件就返回 True。只看 stdout 有没有行：本机 lsof +D 找到了也可能退出 1
    （2026-10-05 实测），不能按退出码判。"""
    r = subprocess.run(["lsof", "+D", str(path)], capture_output=True)
    return bool(r.stdout.strip())


def prune_old(parent, keep=KEEP_BUILDS, by_mtime=False, match="*"):
    """parent 下匹配 match 的子目录按名字（时间戳目录名）或修改时间排序，只留最新 keep 份；返回删掉的目录列表。
    名字不是时间序的（比如按提交号做键的构建缓存）给 by_mtime=True；一个目录里混着几类构建的，用 match 分开各留各的。"""
    parent = Path(parent)
    if not parent.is_dir():
        return []
    key = (lambda p: p.stat().st_mtime) if by_mtime else (lambda p: p.name)
    dirs = sorted((p for p in parent.glob(match) if p.is_dir()), key=key)
    removed = []
    for d in dirs[:max(0, len(dirs) - keep)]:
        if in_use(d):
            continue
        shutil.rmtree(d)
        removed.append(d)
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="剩余空间低于阈值就退出 1")
    c.add_argument("--need", type=float, default=0.0, help="本任务预估还要多少 GB")
    a = ap.parse_args(argv)
    try:
        free = require_free(a.need)
    except DiskSpaceError as e:
        print(f"DISK-ERROR: {e}", file=sys.stderr)
        return 1
    print(f"# 磁盘剩余 {free:.1f} GB（阈值 {min_free_gb():.0f} GB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
