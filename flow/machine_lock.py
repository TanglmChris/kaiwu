"""全机互斥（内部#223）：重进程同一时刻只跑一个，各 worktree 共用一把锁。

等价证明（大设计单进程约 7.5 GB）两路同时跑约 15 GB，16 GB 的机器扛不住；depth 的读入集合探测负载高时约 8 分钟，
两个同时开会各跑一遍。锁文件放在 git 公共目录的 `locks/` 下（与 toolchain 的 main-checkout.owner 同一处），
所有 worktree 看到的是同一个文件。用 `fcntl.flock`：进程退出（含被杀）锁自动释放，不会留下死锁文件。

    with machine_lock("equiv", "netlist_equiv CBB_LZD"):
        ...

拿不到锁时打印「等 <持有者>」，然后阻塞等待；持有者信息写在锁文件里（pid、主机、做什么、开始时刻）。
"""
import fcntl
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_DIR = None      # None 取 git 公共目录下的 locks/；测试可以改


def default_lock_dir():
    common = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common) / "locks"


@contextmanager
def machine_lock(name, what=""):
    d = Path(LOCK_DIR) if LOCK_DIR else default_lock_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = open(d / f"{name}.lock", "a+")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.seek(0)
            holder = f.read().strip() or "（没写持有者）"
            print(f"# 全机锁 {name} 被占用，等 {holder}（#223）", flush=True)
            t0 = time.monotonic()
            fcntl.flock(f, fcntl.LOCK_EX)
            print(f"# 全机锁 {name} 拿到了，等了 {time.monotonic() - t0:.0f} s", flush=True)
        f.seek(0)
        f.truncate()
        f.write(f"pid {os.getpid()} @ {socket.gethostname()}：{what}，开始于 {time.strftime('%m-%d %H:%M:%S')}\n")
        f.flush()
        yield
    finally:
        try:
            f.seek(0)
            f.truncate()
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()
