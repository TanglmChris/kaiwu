"""flow/export/leak_scan.py：开源白名单与泄漏扫描（open-export，kaiwu-layout-decouple 1.1）。

夹具是一个临时 git 仓，清单随提交走：扫描读的是 `--ref` 那个提交里的
`flow/export/manifest.yaml` 与文件内容，工作区里没提交的东西不影响结论（D3）。
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN = REPO_ROOT / "flow" / "export" / "leak_scan.py"

MANIFEST = """\
include:
  - flow/**
  - cbb/**
  - README.md
exclude:
  - cbb/cbb_secret/**
rules:
  block:
    - name: secret-name
      pattern: '\\bsecret_ip\\b'
      ignore_case: true
    - name: abs-path
      pattern: '/fixture-home/'
  warn:
    - name: issue-ref
      pattern: '#\\d+'
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    files = {"flow/export/manifest.yaml": MANIFEST, **files}
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _scan(repo, *args):
    return subprocess.run([sys.executable, str(SCAN), "--repo", str(repo), *args],
                          capture_output=True, text=True)


def test_new_directory_is_closed_by_default(tmp_path):
    repo = _repo(tmp_path, {"foo/a.txt": "secret_ip here\n", "flow/ok.py": "x = 1\n"})
    r = _scan(repo, "--list")
    assert r.returncode == 0, r.stderr
    listed = r.stdout.split()
    assert "flow/ok.py" in listed
    assert not any(p.startswith("foo/") for p in listed)
    assert "flow/export/manifest.yaml" not in listed      # 清单本身是闭源名字表，永远不公开


def test_exclude_wins_over_include(tmp_path):
    repo = _repo(tmp_path, {"cbb/cbb_lzd/rtl/a.v": "module A; endmodule\n",
                            "cbb/cbb_secret/rtl/b.v": "module B; endmodule\n"})
    listed = _scan(repo, "--list").stdout.split()
    assert "cbb/cbb_lzd/rtl/a.v" in listed
    assert "cbb/cbb_secret/rtl/b.v" not in listed


def test_block_hit_reports_line_and_fails(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "x = 1\n# uses SECRET_IP here\n"})
    r = _scan(repo)
    assert r.returncode == 1
    assert "flow/a.py:2: secret-name" in r.stdout


def test_block_hit_in_path_name_fails(tmp_path):
    repo = _repo(tmp_path, {"flow/secret_ip/a.py": "x = 1\n"})
    r = _scan(repo)
    assert r.returncode == 1
    assert "flow/secret_ip/a.py:0: secret-name" in r.stdout


def test_closed_path_with_same_string_is_ignored(tmp_path):
    repo = _repo(tmp_path, {"cbb/cbb_secret/x.md": "secret_ip /fixture-home/me\n",
                            "private/y.md": "secret_ip\n",
                            "flow/a.py": "x = 1\n"})
    r = _scan(repo)
    assert r.returncode == 0, r.stdout
    assert "secret" not in r.stdout.replace("secret-name", "")


def test_warn_only_exits_zero_with_counts(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "# see #12 and #34\n", "README.md": "#5\n"})
    r = _scan(repo)
    assert r.returncode == 0, r.stdout
    assert "issue-ref" in r.stdout
    assert "warn issue-ref: 3" in r.stdout


def test_uncommitted_worktree_does_not_change_result(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "x = 1\n"})
    (repo / "flow" / "a.py").write_text("secret_ip\n")             # 改了没提交
    (repo / "flow" / "new.py").write_text("secret_ip\n")           # 未跟踪
    assert _scan(repo).returncode == 0
    _git(repo, "commit", "-qam", "now committed")
    assert _scan(repo).returncode == 1


def test_only_limits_report_to_subset(tmp_path):
    repo = _repo(tmp_path, {"flow/a.py": "secret_ip\n", "README.md": "secret_ip\n"})
    r = _scan(repo, "--only", "README.md")
    assert r.returncode == 1
    assert "README.md:1: secret-name" in r.stdout
    assert "flow/a.py" not in r.stdout


def test_binary_files_are_skipped(tmp_path):
    repo = _repo(tmp_path, {})
    (repo / "flow" / "blob.bin").write_bytes(b"\x00\x01secret_ip\x00")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "bin")
    r = _scan(repo)
    assert r.returncode == 0, r.stdout


# ---- 替代文件（open-export-substitute） ----

SUBST = (MANIFEST.replace("  - README.md\n", "  - README.md\n  - docs/a.open.md\n")
         + "substitute:\n  docs/a.md: docs/a.open.md\n")


def test_substitute_publishes_the_source_under_the_published_path(tmp_path):
    """仓内完整版闭源、含闭源名字；开源集合里同一路径换成通用版，通用版不以自己的名字出现（M1）。"""
    repo = _repo(tmp_path, {"flow/export/manifest.yaml": SUBST,
                            "docs/a.md": "full\nsee secret_ip\n",
                            "docs/a.open.md": "general\nnothing closed\n"})
    listed = _scan(repo, "--list").stdout.split()
    assert "docs/a.md" in listed and "docs/a.open.md" not in listed, listed
    r = _scan(repo)
    assert r.returncode == 0, r.stdout


def test_substitute_hits_are_reported_on_the_published_path(tmp_path):
    """源里的命中按发布路径与源里的行号报（M2）。"""
    repo = _repo(tmp_path, {"flow/export/manifest.yaml": SUBST,
                            "docs/a.md": "full\n",
                            "docs/a.open.md": "one\ntwo\nsecret_ip three\n"})
    r = _scan(repo)
    assert r.returncode == 1, r.stdout
    assert "docs/a.md:3: secret-name [block]" in r.stdout, r.stdout
    assert "docs/a.open.md" not in r.stdout


def test_substitute_with_missing_source_fails_loudly(tmp_path):
    """源不在树里：非零退出、点名源路径，不跳过（M4）。"""
    manifest = MANIFEST + "substitute:\n  docs/a.md: docs/missing.md\n"
    repo = _repo(tmp_path, {"flow/export/manifest.yaml": manifest, "docs/a.md": "full\n"})
    for args in ((), ("--list",)):
        r = _scan(repo, *args)
        assert r.returncode not in (0, 1), (args, r.returncode, r.stdout + r.stderr)
        assert "docs/missing.md" in r.stdout + r.stderr


def test_substitute_mapping_errors_are_rejected(tmp_path):
    """同一源对应两个发布路径、发布 = 源：白名单无效（M4）。"""
    sys.path.insert(0, str(SCAN.parent))
    import leak_scan
    for body, needle in (("  a.md: s.md\n  b.md: s.md\n", "s.md"), ("  a.md: a.md\n", "a.md")):
        m = tmp_path / "m.yaml"
        m.write_text(MANIFEST + "substitute:\n" + body)
        try:
            leak_scan.load_manifest(tmp_path, None, m)
        except (ValueError, SystemExit) as e:
            assert needle in str(e), e
        else:
            raise AssertionError(f"没有拒绝：{body!r}")


# ---- 闭源设计根的标识符自动进 block 扫描（open-export-closed-vocab）----
# 夹具：cbb/cbb_secret/ 被 exclude（闭源根），cbb/cbb_open/ 被 include（开源根）。

VOCAB = MANIFEST + "closed_vocab: {}\n"

SECRET_V = """\
// 闭源核：注释里的 o_comment_only 不算词
module secret_core #(
  parameter DAT_W = 8,
  parameter SECRET_DEPTH = 4
) (
  input  wire             clk,
  input  wire [DAT_W-1:0] i_dat,
  output wire             o_secret_col,
  output wire             o_q
);
  function automatic [7:0] pass_through(input [7:0] value);
    pass_through = value;
  endfunction
  assign o_secret_col = i_dat[0];
  assign o_q = 1'b0;
endmodule
"""

OPEN_V = """\
module open_core #(
  parameter DAT_W = 8
) (
  input  wire             clk,
  input  wire [DAT_W-1:0] i_dat,
  output wire             o_dat
);
  assign o_dat = i_dat[0];
endmodule
"""


def _vocab_repo(tmp_path, manifest=VOCAB, extra=None):
    files = {
        "flow/export/manifest.yaml": manifest,
        "cbb/cbb_secret/rtl/secret_core.v": SECRET_V,
        "cbb/cbb_open/rtl/open_core.v": OPEN_V,
        "flow/a.py": "x = 1\n# 接 o_secret_col\nDAT_W = 8\nvalue = SECRET_DEPTH\n",
    }
    files.update(extra or {})
    return _repo(tmp_path, files)


def test_closed_root_port_in_open_file_is_blocked(tmp_path):
    repo = _vocab_repo(tmp_path)
    r = _scan(repo)
    assert "flow/a.py:2: closed-vocab [block]" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 1
    assert "flow/a.py:3:" not in r.stdout           # DAT_W：开源根也定义，自动豁免
    assert "flow/a.py:4: closed-vocab [block]" in r.stdout   # SECRET_DEPTH 是闭源参数；value 只是函数参数，不是端口
    assert "o_secret_col" not in r.stdout             # 默认不打印命中的词


def test_value_from_function_argument_is_not_a_port(tmp_path):
    repo = _vocab_repo(tmp_path, extra={"flow/a.py": "value = 1\no_comment_only = 2\n"})
    r = _scan(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "closed-vocab: 0" in r.stdout


def test_allow_and_allow_patterns_and_min_len_exempt(tmp_path):
    for d in "abcd":
        (tmp_path / d).mkdir()
    only_port = {"flow/a.py": "# 接 o_secret_col\n"}
    assert _scan(_vocab_repo(tmp_path / "d", extra=only_port)).returncode == 1   # 对照：不豁免就命中
    allow = MANIFEST + "closed_vocab:\n  allow: [o_secret_col]\n"
    assert _scan(_vocab_repo(tmp_path / "a", allow, only_port)).returncode == 0
    pat = MANIFEST + "closed_vocab:\n  allow_patterns: ['o_secret_\\w+']\n"
    r = _scan(_vocab_repo(tmp_path / "b", pat, only_port))
    assert r.returncode == 0, r.stdout
    short = _scan(_vocab_repo(tmp_path / "c", extra={"flow/a.py": "o_q = 1\n"}))
    assert short.returncode == 0, short.stdout        # o_q 短于缺省 min_len 4


def test_closed_code_file_name_is_blocked_and_show_terms_prints_it(tmp_path):
    repo = _vocab_repo(tmp_path, extra={"cbb/cbb_secret/tb/secret_regress.py": "pass\n",
                                        "flow/a.py": "x = 1\n",
                                        "flow/run.sh": "secret_regress --sva\n"})
    shown = _scan(repo, "--show-terms")
    assert "flow/run.sh:1: closed-vocab [block] secret_regress" in shown.stdout, shown.stdout + shown.stderr
    r = _scan(repo)
    assert r.returncode == 1
    assert "flow/run.sh:1: closed-vocab [block]" in r.stdout
    assert "secret_regress" not in r.stdout


def test_self_check_rejects_tokenizer_that_misses_extracted_names(tmp_path, monkeypatch):
    import re
    sys.path.insert(0, str(REPO_ROOT / "flow" / "export"))
    import leak_scan
    repo = _vocab_repo(tmp_path)
    monkeypatch.setattr(leak_scan, "TOKEN", re.compile(r"[A-Za-z]+"), raising=False)   # 切不出带下划线的词
    try:
        leak_scan.load_manifest(repo, "HEAD")
    except leak_scan.ManifestError as e:
        assert "自检" in str(e) and "o_secret_col" in str(e)
    else:
        raise AssertionError("切词器失效时 load_manifest 应当报自检失败")


def test_self_check_rejects_closed_rtl_with_no_names(tmp_path):
    repo = _repo(tmp_path, {"flow/export/manifest.yaml": VOCAB,
                            "cbb/cbb_secret/rtl/empty.v": "// 只有注释\n",
                            "flow/a.py": "x = 1\n"})
    r = _scan(repo)
    assert "自检" in r.stdout and "cbb/cbb_secret" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 2


def test_exporter_and_ratchet_pick_up_closed_vocab(tmp_path):
    repo = _vocab_repo(tmp_path, extra={"flow/export/leak_baseline.txt": "0\n"})
    rat = subprocess.run([sys.executable, str(REPO_ROOT / "flow" / "export" / "leak_ratchet.py"),
                          "--repo", str(repo)], capture_output=True, text=True)
    assert "flow/a.py" in rat.stdout, rat.stdout + rat.stderr
    out = tmp_path / "out"
    exp = subprocess.run([sys.executable, str(REPO_ROOT / "flow" / "export" / "export.py"),
                          "--repo", str(repo), "--out", str(out)], capture_output=True, text=True)
    assert exp.returncode != 0, exp.stdout
    assert not out.exists() or not any(out.iterdir())
    assert rat.returncode == 1
    assert "o_secret_col" not in rat.stdout and "SECRET_DEPTH" not in rat.stdout


def test_load_manifest_without_ref_builds_vocab_from_head(tmp_path):
    # tests/test_team_layout.py 只读白名单文件、不给 ref（扫工作区的 team/），closed_vocab 要按 HEAD 的树抽词
    sys.path.insert(0, str(REPO_ROOT / "flow" / "export"))
    import leak_scan
    repo = _vocab_repo(tmp_path)
    manifest = leak_scan.load_manifest(repo, None, repo / leak_scan.MANIFEST)
    matcher = next(rx for _, name, rx in manifest["rules"] if name == "closed-vocab")
    assert matcher.search("接 o_secret_col")


# ---- 闭源词表纳入 git 历史里删掉的设计根（open-export-closed-vocab-history）----

GONE_V = """\
module gone_core (
  input  wire clk,
  output wire o_gone_col
);
  assign o_gone_col = clk;
endmodule
"""


def _hist_repo(tmp_path, manifest, before, delete, after):
    """两个提交：先提交 `before`，再删掉 `delete` 里的目录并写入 `after`，模拟设计根被整个删除。"""
    repo = _repo(tmp_path, {"flow/export/manifest.yaml": manifest, **before})
    for d in delete:
        _git(repo, "rm", "-rq", d)
    for rel, text in after.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "delete")
    return repo


HIST = MANIFEST + "closed_vocab:\n  history: true\n"


def test_deleted_closed_root_names_are_blocked_with_history(tmp_path):
    before = {"cbb/cbb_gone/rtl/gone_core.v": GONE_V, "cbb/cbb_gone/tb/gone_regress.py": "pass\n",
              "cbb/cbb_open/rtl/open_core.v": OPEN_V}
    after = {"flow/a.py": "# 接 o_gone_col\n", "flow/run.sh": "gone_regress --sva\n"}
    (tmp_path / "h").mkdir()
    (tmp_path / "n").mkdir()
    repo = _hist_repo(tmp_path / "h", HIST, before, ["cbb/cbb_gone"], after)
    r = _scan(repo)
    assert "flow/a.py:1: closed-vocab [block]" in r.stdout, r.stdout + r.stderr
    assert "flow/run.sh:1: closed-vocab [block]" in r.stdout
    assert r.returncode == 1
    plain = _hist_repo(tmp_path / "n", VOCAB, before, ["cbb/cbb_gone"], after)
    assert _scan(plain).returncode == 0                  # 不写 history 时只看现在的树


def test_history_open_roots_and_still_open_roots_are_skipped(tmp_path):
    old_open_v = GONE_V.replace("gone_core", "old_core").replace("o_gone_col", "o_open_old")
    was_open_v = GONE_V.replace("gone_core", "was_core").replace("o_gone_col", "o_was_open")
    before = {"cbb/old_open/rtl/old_core.v": old_open_v,
              "cbb/cbb_open/rtl/open_core.v": OPEN_V, "cbb/cbb_open/rtl/old.v": was_open_v}
    after = {"flow/a.py": "# o_open_old\n# o_was_open\n"}
    for d in "xy":
        (tmp_path / d).mkdir()
    listed = HIST.replace("  history: true\n", "  history: true\n  history_open_roots: ['cbb/old_open']\n")
    skip = _hist_repo(tmp_path / "x", listed, before, ["cbb/old_open", "cbb/cbb_open/rtl/old.v"], after)
    r = _scan(skip, "--show-terms")
    assert r.returncode == 0, r.stdout + r.stderr       # cbb/old_open 已声明；cbb/cbb_open 现在开源
    flagged = _hist_repo(tmp_path / "y", HIST, before, ["cbb/old_open", "cbb/cbb_open/rtl/old.v"], after)
    shown = _scan(flagged, "--show-terms")
    assert "flow/a.py:1: closed-vocab [block] o_open_old" in shown.stdout, shown.stdout + shown.stderr
    assert "o_was_open" not in shown.stdout


def test_history_rtl_without_names_does_not_fail_but_tokenizer_check_still_applies(tmp_path, monkeypatch):
    import re
    sys.path.insert(0, str(REPO_ROOT / "flow" / "export"))
    import leak_scan
    (tmp_path / "e").mkdir()
    (tmp_path / "t").mkdir()
    empty = _hist_repo(tmp_path / "e", HIST, {"cbb/cbb_gone/rtl/empty.v": "// 只有注释\n"},
                       ["cbb/cbb_gone"], {"flow/a.py": "x = 1\n"})
    r = _scan(empty)
    assert "自检" not in r.stdout and r.returncode == 0, r.stdout + r.stderr
    tok = _hist_repo(tmp_path / "t", HIST, {"cbb/cbb_gone/rtl/gone_core.v": GONE_V},
                     ["cbb/cbb_gone"], {"flow/a.py": "x = 1\n"})
    monkeypatch.setattr(leak_scan, "TOKEN", re.compile(r"[A-Za-z]+"))
    try:
        leak_scan.load_manifest(tok, "HEAD")
    except leak_scan.ManifestError as e:
        assert "自检" in str(e) and "o_gone_col" in str(e)
    else:
        raise AssertionError("历史 RTL 的词切不出来时应当报自检失败")
