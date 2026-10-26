"""draw.io 作图库、带超时的导出、图元重叠检查（内部#227，drawio-figlib）。

导出用桩 draw.io（DRAWIO 指向它）：真 draw.io 在沙箱里会挂住，测试不依赖它；真导出另在沙箱外实测。
"""
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
OVERLAP = REPO_ROOT / "flow" / "doc" / "drawio_overlap.py"
EXPORT = REPO_ROOT / "flow" / "doc" / "drawio_export.py"


def _fig():
    try:
        from flow.doc import figlib
    except ImportError:
        pytest.fail("flow/doc/figlib.py 还没有：作图库与重叠检查都不在")
    return figlib.Fig()


def _overlap(path):
    return subprocess.run([sys.executable, str(OVERLAP), str(path)], capture_output=True, text=True)


def test_figlib_writes_readable_drawio_with_section6_colors(tmp_path):
    f = _fig()
    f.title("数据通路")
    a = f.box(20, 40, 100, 40, "写缓冲", kind="data")
    b = f.box(160, 40, 100, 40, "仲裁", kind="merge")
    f.edge(a, b, kind="data")
    f.line(10, 100, 300, 100)
    p = tmp_path / "x.drawio"
    f.save(p, "测试页")
    root = ET.parse(p).getroot()
    styles = {c.get("value"): c.get("style") for c in root.iter("mxCell")}
    assert "fillColor=#DAE8FC" in styles["写缓冲"] and "fillColor=#D5E8D4" in styles["仲裁"], styles
    assert "html=0" in styles["写缓冲"]
    assert any("strokeColor=#6C8EBF" in (c.get("style") or "") for c in root.iter("mxCell") if c.get("edge") == "1")


def test_two_overlapping_boxes_are_reported(tmp_path):
    f = _fig()
    f.box(20, 40, 100, 40, "命令缓冲", kind="ctrl")
    f.box(90, 60, 100, 40, "读缓冲", kind="data")
    p = tmp_path / "x.drawio"
    f.save(p, "测试页")
    r = _overlap(p)
    assert r.returncode == 1 and "命令缓冲" in r.stdout and "读缓冲" in r.stdout and "重叠" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("case", ["nested", "marked", "apart", "label-inside"])
def test_containers_marked_and_apart_are_not_reported(tmp_path, case):
    f = _fig()
    f.box(10, 10, 300, 200, "", kind="plain")
    if case == "nested":
        f.box(40, 40, 100, 40, "子模块", kind="data")
    elif case == "marked":
        f.text(280, 90, 60, 20, "M_CMD", ok_overlap=True)
    elif case == "apart":
        f.box(400, 10, 80, 40, "远处", kind="data")
    elif case == "label-inside":
        f.text(20, 20, 120, 20, "时钟域 A", align="left")
    p = tmp_path / "x.drawio"
    f.save(p, "测试页")
    r = _overlap(p)
    assert r.returncode == 0, case + "\n" + r.stdout + r.stderr


def test_a_label_straddling_a_box_edge_is_reported(tmp_path):
    f = _fig()
    f.box(10, 10, 300, 200, "", kind="plain")
    f.text(280, 90, 60, 20, "M_CMD")
    p = tmp_path / "x.drawio"
    f.save(p, "测试页")
    r = _overlap(p)
    assert r.returncode == 1 and "M_CMD" in r.stdout and "重叠" in r.stdout, r.stdout + r.stderr


# ---- 导出 ----

HANG = "#!/bin/sh\nsleep 60 &\necho $! > \"$CHILD_PID\"\nwait\n"
OK = "#!/bin/sh\nfor a in \"$@\"; do last=$prev; prev=$a; done\nout=$(echo \"$@\" | sed 's/.*-o \\([^ ]*\\).*/\\1/')\necho '<svg/>' > \"$out\"\n"


def _stub(tmp_path, text):
    p = tmp_path / "drawio"
    p.write_text(text)
    p.chmod(0o755)
    return p


# 桩要在超时之内起来并写出子进程号。2 秒在全量 merge_check（-n 4）里不够：macOS 第一次执行新写出的脚本要先过一遍
# 系统检查，加上负载，桩还没写 child.pid 就被杀了（内部#398、内部#227 chief 10-22 两次实撞，单跑 3/3 过）。
HANG_TIMEOUT = 10


def test_export_that_hangs_is_killed_with_its_children(tmp_path):
    src = tmp_path / "x.drawio"
    src.write_text("<mxfile/>")
    child = tmp_path / "child.pid"
    env = dict(os.environ, DRAWIO=str(_stub(tmp_path, HANG)), CHILD_PID=str(child))
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, str(EXPORT), str(src), "--timeout", str(HANG_TIMEOUT)], capture_output=True,
                       text=True, env=env)
    assert r.returncode != 0 and "挂住" in r.stdout + r.stderr, r.stdout + r.stderr
    assert time.monotonic() - t0 < HANG_TIMEOUT + 20
    assert child.exists(), f"桩 draw.io {HANG_TIMEOUT} 秒内没起来（没写出子进程号）：本机太忙，不是导出脚本的错"
    pid = int(child.read_text())
    time.sleep(0.3)
    alive = subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode == 0
    assert not alive, "超时后子进程还活着：没有杀整个进程组"


def test_export_writes_the_svg(tmp_path):
    src = tmp_path / "x.drawio"
    src.write_text("<mxfile/>")
    env = dict(os.environ, DRAWIO=str(_stub(tmp_path, OK)))
    r = subprocess.run([sys.executable, str(EXPORT), str(src)], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and (tmp_path / "x.svg").stat().st_size > 0, r.stdout + r.stderr
