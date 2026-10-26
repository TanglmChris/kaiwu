"""两个提交之间的规格差分（scripts/spec_diff.py，内部#228，spec-diff）。

夹具是一个临时 git 仓库，LRS / LLD 按现行写法造（加粗 R 定义行、按类型分节的接口表与字段行、
`**图 X-Y**` 图注、LLD「设计断言」表），第二个提交按评审答复轮常见的改法改几处。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "spec_diff.py"
_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

LRS = """# DEMO 逻辑需求规格（LRS）

## 0. 文档信息

| 项 | 内容 |
|---|---|
| 顶层 | `DEMO` |

## 1. 概述

![DEMO 框图](doc/demo_block.svg)

**图 1-1** DEMO 框图 —— 数据从 s 侧进、m 侧出

## 5. 接口

### 5.1 数据通道

| 信号 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| `s_vld` | input | 1 | 有效 |
| `s_dat` | input | `DAT_W` | 数据 |
| | | | `s_dat[7:0]` 是低字节 |
| `m_vld` | output | 1 | 有效 |

## 6. 功能描述

- **R.001** 输入握手后第 2 拍输出。
- **R.002** `m_dat` 等于 `s_dat` 按位取反。
- **R.003** 复位后 `m_vld` 为 0。
"""

LLD = """# DEMO 逻辑详细设计（LLD）

## 0. 文档信息

| 项 | 内容 |
|---|---|
| 对应 LRS | v1.0 |

## 2. 框图与模块划分

![流水](doc/lld_pipe.svg)

**图 2-1** 两级流水 —— 第一拍寄存、第二拍取反

## 9. 设计断言

| 编号 | 位置 | 部署 | 性质 | 违反后果 | 需求 |
|---|---|---|---|---|---|
| A1 | 输出 | bind `tb/sva_demo.sv` | `m_vld` 拉起时 `m_dat` 不是 X | 下游采到 X | R.002 |
"""


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True, env=_ENV).stdout.strip()


def _commit(root, msg):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    d = root / "designs" / "demo"
    (d / "doc").mkdir(parents=True)
    (d / "lrs.DEMO.md").write_text(LRS)
    (d / "lld.DEMO.md").write_text(LLD)
    (d / "doc" / "demo_block.svg").write_text("<svg/>")
    (d / "doc" / "lld_pipe.svg").write_text("<svg/>")
    _git(root, "init", "-q", "-b", "main")
    base = _commit(root, "base")
    return root, base


def _answer(root):
    """答复轮的典型改动：改 R.001 条文、删 R.003、加 R.004；改 s_dat 位宽、加 m_dat；
    改图 1-1 标题；删 lld_pipe.svg 但 LLD 仍引用；断言表加 A2。"""
    d = root / "designs" / "demo"
    lrs = (LRS.replace("- **R.001** 输入握手后第 2 拍输出。", "- **R.001** 输入握手后第 3 拍输出。")
              .replace("- **R.003** 复位后 `m_vld` 为 0。\n", "- **R.004** `m_vld` 不依赖 `m_rdy`。\n")
              .replace("| `s_dat` | input | `DAT_W` | 数据 |", "| `s_dat` | input | `DAT_W + 1` | 数据 |")
              .replace("| `m_vld` | output | 1 | 有效 |", "| `m_vld` | output | 1 | 有效 |\n| `m_dat` | output | `DAT_W` | 数据 |")
              .replace("**图 1-1** DEMO 框图 —— 数据从 s 侧进、m 侧出", "**图 1-1** DEMO 框图 —— 两个通道的走向"))
    (d / "lrs.DEMO.md").write_text(lrs)
    (d / "lld.DEMO.md").write_text(LLD + "| A2 | 输入 | bind `tb/sva_demo.sv` | 握手期间 `s_dat` 保持 | 采错数据 | R.001 |\n")
    (d / "doc" / "lld_pipe.svg").unlink()
    return _commit(root, "answer")


def _run(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root, capture_output=True, text=True)


def test_diff_lists_each_change_by_item(repo):
    root, base = repo
    head = _answer(root)
    r = _run(root, "--from", base, "--to", head)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "| `designs/demo/lrs.DEMO.md` | R | 1 | 1 | 1 |" in out, out
    assert "| `designs/demo/lrs.DEMO.md` | 接口表 | 0 | 1 | 1 |" in out, out
    assert "| `designs/demo/lrs.DEMO.md` | 图注 | 0 | 0 | 1 |" in out, out
    assert "| `designs/demo/lld.DEMO.md` | 设计断言 | 0 | 1 | 0 |" in out, out
    assert "  删 R.003" in out and "  增 R.004" in out and "  改 R.001" in out
    assert "    + - **R.001** 输入握手后第 3 拍输出。" in out
    assert "  改 s_dat" in out and "    + input DAT_W + 1" in out and "  增 m_dat" in out
    assert "s_dat[7:0]" not in out  # 字段行不当端口
    assert "  增 A2" in out
    # 缺图只在 to 一侧报，路径按文档目录解析
    assert "- `designs/demo/lld.DEMO.md`（to）：`doc/lld_pipe.svg`" in out
    assert "（from）" not in out


def test_same_fails_only_on_listed_items(repo):
    root, base = repo
    head = _answer(root)
    r = _run(root, "--from", base, "--to", head, "--same", "R,节标题")
    assert r.returncode == 1 and "--same 要求不变的项有差异：R\n" in r.stderr, r.stderr  # 节标题没变，不点名
    (root / "designs" / "demo" / "lld.DEMO.md").write_text(
        (root / "designs" / "demo" / "lld.DEMO.md").read_text() + "\n补一句说明。\n")
    head2 = _commit(root, "prose only")
    r = _run(root, "--from", head, "--to", head2, "--same", "R,接口表,图注,设计断言,节标题")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "比过的项全部没有差异" in r.stdout


def test_document_on_one_side_counts_whole(repo):
    root, base = repo
    (root / "designs" / "demo" / "lld.DEMO.md").unlink()
    head = _commit(root, "drop lld")
    r = _run(root, "--from", base, "--to", head, "--top", "DEMO")
    assert r.returncode == 0, r.stderr
    assert "| `designs/demo/lld.DEMO.md`（文档已删） | 设计断言 | 1 | 0 | 0 |" in r.stdout, r.stdout


def test_bad_ref_and_unknown_item_exit_2(repo):
    root, base = repo
    r = _run(root, "--from", "no-such-ref", "--to", base)
    assert r.returncode == 2 and "no-such-ref" in r.stderr
    r = _run(root, "--from", base, "--to", base, "--same", "R,端口")
    assert r.returncode == 2 and "端口" in r.stderr
    r = _run(root, "--from", base, "--to", base, "--top", "NOPE")
    assert r.returncode == 2 and "NOPE" in r.stderr


def test_out_file_matches_stdout(repo, tmp_path):
    root, base = repo
    head = _answer(root)
    out = tmp_path / "diff.md"
    r = _run(root, "--from", base, "--to", head, "--out", str(out))
    assert r.returncode == 0 and out.read_text() == r.stdout
