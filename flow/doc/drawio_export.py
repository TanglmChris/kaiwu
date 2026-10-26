"""draw.io 导出 svg，带超时（内部#227，drawio-figlib D2）。

    .venv/bin/python3 flow/doc/drawio_export.py designs/<根>/doc/<图名>.drawio [<图名>.svg] [--timeout 60]

**要在 Claude Code 的 Bash 沙箱外跑**：沙箱里 draw.io 会挂住，`perl alarm` 也停不掉（Electron 的子进程还占着管道，
内部#227 spec 10-18）。用 draw.io 本体 `--no-sandbox`，不用 Homebrew 的 `drawio` 软链（找不到 helper 会挂住，内部#227 10-06）；
`$DRAWIO` 可以指定别的路径。在新进程组里跑，超时杀掉整个组、退出 3。导出后 svg 不存在或为空退出 1。
导出后用 `qlmanage -t -s 1600 -o /tmp <图名>.svg` 转 png 看一眼排版。
"""
import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

APP = "/Applications/draw.io.app/Contents/MacOS/draw.io"


def drawio():
    return os.environ.get("DRAWIO") or APP


def export(src, out=None, timeout=60.0):
    """(退出码, 说明)。"""
    src = Path(src)
    out = Path(out) if out else src.with_suffix(".svg")
    exe = drawio()
    if not Path(exe).exists():
        return 2, f"找不到 draw.io（{exe}）；装 draw.io.app，或用 DRAWIO 指定本体路径"
    cmd = [exe, "-x", "-f", "svg", "--disable-gpu", "--no-sandbox", "-o", str(out), str(src)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        log, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        return 3, (f"draw.io {timeout:g} 秒没退出，挂住了，已杀掉整个进程组；多半是在 Claude Code 的 Bash 沙箱里跑的，"
                   "关掉沙箱再跑")
    if p.returncode != 0:
        return 1, f"draw.io 退出码 {p.returncode}：{(log or b'').decode(errors='replace')[-500:]}"
    if not out.exists() or out.stat().st_size == 0:
        return 1, f"draw.io 退出 0 但 {out} 不存在或为空"
    return 0, f"已导出 {out}（{out.stat().st_size} 字节）"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--timeout", type=float, default=60.0)
    a = ap.parse_args(argv)
    rc, msg = export(a.src, a.out, a.timeout)
    print(msg, file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    sys.exit(main())
