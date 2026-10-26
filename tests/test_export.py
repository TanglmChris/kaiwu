"""flow/export/export.py：从提交导出开源集合、改写私有 issue 引用（open-export，open-export-tool 1.1）。

夹具按真实形态造：Python 字符串里嵌 Verilog 延时（照 tests/test_sigeq.py）、代码字符串里拼
issue 号（照 fast_check 的「[豁免 内部#285]」）、私有仓 issue 链接的三种写法（照 cbb/README.md）。
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORT = REPO_ROOT / "flow" / "export" / "export.py"
URL = "https://github.com/TanglmChris/rtl_ppa_prj/issues"

# 规则与真实清单同形：issue-ref / private-repo 的 pattern 照抄 flow/export/manifest.yaml
MANIFEST = """\
include:
  - flow/**
  - scripts/**
  - cbb/**
  - README.md
exclude:
  - cbb/cbb_secret/**
verbatim:
  - flow/equiv/run_equiv.py
rewrite:
  issue_repos:
    - TanglmChris/rtl_ppa_prj
    - TanglmChris/kaiwu-ip
rules:
  block:
    - name: secret-name
      pattern: '\\bsecret_ip\\b'
      ignore_case: true
  warn:
    - name: issue-ref
      pattern: '(?<![\\w&])#\\d+\\b'
    - name: private-repo
      pattern: 'TanglmChris/rtl_ppa_prj'
    - name: private-repo-kaiwu
      pattern: 'TanglmChris/kaiwu-ip'
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _repo(tmp_path, files, links=None, modes=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    files = {"flow/export/manifest.yaml": MANIFEST, **files}
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode())
    for rel, target in (links or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, p)
    for rel, mode in (modes or {}).items():
        os.chmod(repo / rel, mode)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _export(repo, out, *args):
    return subprocess.run([sys.executable, str(EXPORT), "--repo", str(repo),
                           "--out", str(out), *args],
                          capture_output=True, text=True)


# ---- 导出器从提交导出开源集合 ----

def test_block_hit_writes_nothing(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "x = 1\n", "flow/b.md": "line\nsee secret_ip\n"})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "flow/b.md:2: secret-name [block]" in r.stdout
    assert not out.exists()


def test_block_hit_in_path_writes_nothing(tmp_path):
    repo = _repo(tmp_path, {"cbb/secret_ip/x.v": "module x; endmodule\n"})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode != 0
    assert "cbb/secret_ip/x.v:0: secret-name [block]" in r.stdout
    assert not out.exists()


def test_nonempty_out_is_refused(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "x = 1\n"})
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("old\n")
    r = _export(repo, out)
    assert r.returncode != 0
    assert sorted(p.name for p in out.iterdir()) == ["keep.txt"]
    assert (out / "keep.txt").read_text() == "old\n"


def test_empty_out_dir_is_accepted(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "x = 1\n"})
    out = tmp_path / "out"
    out.mkdir()
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "flow/a.py").read_text() == "x = 1\n"


def test_closed_by_default_and_manifest_not_exported(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "x = 1\n", "foo/b.txt": "closed\n",
                            "cbb/cbb_secret/c.v": "module c; endmodule\n",
                            "cbb/cbb_open/d.v": "module d; endmodule\n"})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    got = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert got == ["cbb/cbb_open/d.v", "flow/a.py"]


def test_exports_the_commit_not_the_worktree(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "x = 1\n"})
    (repo / "flow/a.py").write_text("x = 2  # secret_ip\n")
    (repo / "flow/untracked.py").write_text("y = 1\n")
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "flow/a.py").read_text() == "x = 1\n"
    assert not (out / "flow/untracked.py").exists()


def test_mode_and_symlink_and_binary_preserved(tmp_path):
    binary = b"\x00\x01#12\x00"
    repo = _repo(tmp_path, {"scripts/run.sh": "#!/bin/bash\necho ok  # see #3\n",
                            "flow/blob.bin": binary},
                 links={"flow/link.py": "../scripts/run.sh"},
                 modes={"scripts/run.sh": 0o755})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.access(out / "scripts/run.sh", os.X_OK)
    assert (out / "scripts/run.sh").read_text() == "#!/bin/bash\necho ok  # see 内部#3\n"
    assert os.readlink(out / "flow/link.py") == "../scripts/run.sh"
    assert (out / "flow/blob.bin").read_bytes() == binary


# ---- 私有 issue 引用在导出时改写 ----

PY_SRC = '''\
"""模块说明（#305）。"""
import os  # 见 #12

TB = """
module tb;
  initial begin
    #1 clk = ~clk;
  end
endmodule
"""


def f(n):
    """函数说明，见 #7。"""
    msg = "拒绝开跑（#173）"
    return f"[豁免 #{n}] {msg}"
'''

PY_OUT = '''\
"""模块说明（内部#305）。"""
import os  # 见 内部#12

TB = """
module tb;
  initial begin
    #1 clk = ~clk;
  end
endmodule
"""


def f(n):
    """函数说明，见 内部#7。"""
    msg = "拒绝开跑（#173）"
    return f"[豁免 #{n}] {msg}"
'''

V_SRC = "// 时钟（#12）\nmodule m(input a, output reg b);\n  always @(a) #1 b = a; // 延时 #2\nendmodule\n"
V_OUT = "// 时钟（内部#12）\nmodule m(input a, output reg b);\n  always @(a) #1 b = a; // 延时 内部#2\nendmodule\n"


def test_comment_and_docstring_refs_rewritten_code_untouched(tmp_path):
    repo = _repo(tmp_path, {
        "flow/a.py": PY_SRC,
        "cbb/cbb_open/rtl/m.v": V_SRC,
        "flow/lint/w.vlt": "`verilator_config\n// 豁免（#4）\nlint_off -rule WIDTH\n",
        "flow/c.yaml": "# 说明 #5\nkey: 1  # 见 #6\n",
        "README.md": "见 #8 与 PR #9；`&#123;` 不是 issue。\n",
    })
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "flow/a.py").read_text() == PY_OUT
    assert (out / "cbb/cbb_open/rtl/m.v").read_text() == V_OUT
    assert (out / "flow/lint/w.vlt").read_text() == "`verilator_config\n// 豁免（内部#4）\nlint_off -rule WIDTH\n"
    assert (out / "flow/c.yaml").read_text() == "# 说明 内部#5\nkey: 1  # 见 内部#6\n"
    assert (out / "README.md").read_text() == "见 内部#8 与 PR 内部#9；`&#123;` 不是 issue。\n"


def test_private_links_removed(tmp_path):
    md = (f"[#7]({URL}/7)。\n"
          f"[规则]({URL}/30#issuecomment-1)\n"
          f"见 {URL}/31 与 {URL}/32#issuecomment-6185182753。\n")
    repo = _repo(tmp_path, {"README.md": md})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    got = (out / "README.md").read_text()
    assert got == "内部#7。\n规则（内部#30）\n见 内部#31 与 内部#32。\n"
    assert "TanglmChris/rtl_ppa_prj" not in got


def test_summary_reports_remaining_refs(tmp_path):
    repo = _repo(tmp_path, {
        "flow/a.py": PY_SRC,
        "flow/b.py": "x = '#1'\ny = 'TanglmChris/rtl_ppa_prj'\n",
        "flow/clean.py": "# 见 #3\n",
    })
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    # a.py：Verilog 的 内部#1 与报错文本的 内部#173 两处；b.py：'内部#1' 一处
    assert "剩余 issue-ref [warn]: 3" in r.stdout
    assert "  flow/a.py: 2" in r.stdout
    assert "  flow/b.py: 1" in r.stdout
    assert "剩余 private-repo [warn]: 1" in r.stdout
    assert "flow/clean.py:" not in r.stdout
    assert "改写 2 个" in r.stdout


def test_renamed_repo_links_removed(tmp_path):
    """仓改名后（内部#305 P2）新旧两个仓名的 issue 链接都改写，导出里不留任何一个仓名。"""
    new = "https://github.com/TanglmChris/kaiwu-ip/issues"
    md = f"[#7]({URL}/7) 与 [#8]({new}/8)，见 {new}/9#issuecomment-1。\n"
    repo = _repo(tmp_path, {"README.md": md})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    got = (out / "README.md").read_text()
    assert got == "内部#7 与 内部#8，见 内部#9。\n"
    assert "剩余 private-repo-kaiwu [warn]: 0" in r.stdout


# ---- 原样导出名单 ----

def test_verbatim_file_untouched(tmp_path):
    src = "# 证明器（#39）\nRECIPE = 1  # 见 #49\n"
    repo = _repo(tmp_path, {"flow/equiv/run_equiv.py": src})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "flow/equiv/run_equiv.py").read_bytes() == src.encode()
    assert "  flow/equiv/run_equiv.py: 2" in r.stdout


# ---- 替代文件（open-export-substitute） ----

SUBST = (MANIFEST.replace("  - README.md\n", "  - README.md\n  - docs/a.open.md\n")
         + "substitute:\n  docs/a.md: docs/a.open.md\n")


def test_substitute_exports_source_bytes_under_published_path(tmp_path):
    """导出目录里 docs/a.md 是源的字节，没有 docs/a.open.md；可执行位跟随源（M3）。"""
    repo = _repo(tmp_path, {"flow/export/manifest.yaml": SUBST,
                            "docs/a.md": "full\nsee secret_ip\n",
                            "docs/a.open.md": "general\nno private refs\n"},
                 modes={"docs/a.open.md": 0o755})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (out / "docs" / "a.open.md").exists(), "docs/a.open.md 不该以自己的名字导出"
    assert (out / "docs" / "a.md").read_bytes() == b"general\nno private refs\n"
    assert os.access(out / "docs" / "a.md", os.X_OK)


def test_substitute_with_missing_source_writes_nothing(tmp_path):
    """源不在树里：导出器非零退出、点名源路径，导出目录不写（M4）。"""
    manifest = MANIFEST + "substitute:\n  docs/a.md: docs/missing.md\n"
    repo = _repo(tmp_path, {"flow/export/manifest.yaml": manifest, "flow/a.py": "x = 1\n"})
    out = tmp_path / "out"
    r = _export(repo, out)
    assert r.returncode != 0
    assert "docs/missing.md" in r.stdout + r.stderr
    assert not out.exists() or not any(out.iterdir())
