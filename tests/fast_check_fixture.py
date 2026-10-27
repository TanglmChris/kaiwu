"""tests/test_fast_check*.py 共用的夹具：最小仓、桩工具、文档模板与跑脚本的辅助函数（内部#336 从 tests/test_fast_check.py 拆出）。

不以 test_ 开头，pytest 不收；各用例文件 `from fast_check_fixture import *`。为什么夹具是独立的最小仓见 tests/test_fast_check.py 的文档串。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "fast_check.sh"

def _good_rtl(mod="FOO", spec="designs/foo/lrs.FOO.md"):
    """一份合乎全部约定的最小 RTL：书写风格（add-rtl-coding-style）要求五字段头注释，
    `Spec` 指向的文件必须在夹具仓库里存在，所以模块名与 spec 路径一起给。"""
    return f"""\
//======================================================================

// File    : {mod.lower()}.v
// Module  : {mod}
// Purpose : fast_check fixture
// Spec    : {spec}
// Language: Verilog-2001
//======================================================================

module {mod} #(parameter DAT_W = 4) (input wire [DAT_W-1:0] i_a, output wire [DAT_W-1:0] o_y);
    assign o_y = i_a;
`ifdef CBB_PARAM_CHK_ON
`endif
endmodule
"""


GOOD_RTL = _good_rtl()
BROKEN_RTL = "module BAD_HELPER; wire w = ; endmodule\n"


def _good_spec(top, extra_in=()):
    """与 GOOD_RTL 同形的 spec 端口表。fast_check 比对 spec 端口表与 RTL
    （guardrail-scope 的「秒级护栏必须检查 spec 端口表与 RTL 一致」），
    所以每个夹具设计根都要带一份对得上的 spec，不然与本用例无关的检查会红。"""
    return (f"# {top}\n\n## 接口\n\n| 信号 | 方向 | 位宽 | 含义 |\n|---|---|---|---|\n"
            + "".join(f"| `{n}` | in | 1 | x |\n" for n in extra_in)
            + "| `i_a` | in | `DAT_W` | 输入 |\n| `o_y` | out | `DAT_W` | 输出 |\n")


# LRS / LLD 的必填节（repo-layout「专用设计的 LRS 与 LLD 必须有必填节与需求追溯」，lrs-lld-docs）。
# 夹具按契约原样列出，契约改了这里跟着改 —— 这正是测试要守的东西。
LRS_SECTIONS = ("文档信息", "概述", "配置与应用场景", "术语与约定", "参数", "接口", "功能描述",
                "异常与 DFX", "性能需求")
# LLD 的必填节（内部#203，lld-restructure D1）；夹具另在「框图与模块划分」后写一个子模块节 `SUB_A`
LLD_SECTIONS = ("文档信息", "设计概述", "框图与模块划分", "DFX 实现", "设计断言")


def _lrs(spec_text, reqs=("R.001",), skip=(), params=("DAT_W",), info=None):
    """把一份只有「## 接口」端口表的 spec 补成完整的 LRS：其余必填节写「不适用」，
    需求定义（加粗的 R 编号）写在「功能描述」里，「参数」一节列出 params（要与 params.yaml
    对得上，flow-guard-feedback D4）。`designs/` 下的设计根用它。"""
    tail = ""
    for sec in LRS_SECTIONS:
        if sec == "接口" or sec in skip:
            continue
        body = "不适用\n"
        if sec == "功能描述":
            body = "".join(f"- **{r}** 需求 {r}\n" for r in reqs)
        elif sec == "参数" and params:
            body = "| 参数 | 取值 | 含义 |\n|---|---|---|\n" + "".join(f"| `{n}` | x | x |\n" for n in params)
        elif sec == "文档信息" and info is not None:
            body = info
        tail += f"\n## {sec}\n\n{body}"
    return spec_text + tail


def _good_lld(trace=("R.001",), skip=(), asserts=None, text=""):
    """完整的 LLD：追溯表在「设计概述」里，「框图与模块划分」的模块表列一个子模块 SUB_A，
    它自己一节；其余必填节写「不适用」。asserts 给出时「设计断言」一节写断言表（flow-guard-feedback D5）；
    text 写在 SUB_A 那一节里。"""
    out = "# LLD\n"
    for sec in LLD_SECTIONS + ("SUB_A",):
        if sec in skip:
            continue
        body = "不适用\n"
        if sec == "设计概述" and trace is not None:
            body = "| 需求 | 实现 |\n|---|---|\n" + "".join(f"| {r} | §4 |\n" for r in trace)
        elif sec == "设计断言" and asserts is not None:
            body = "| 断言 | 性质 | 所在模块 | 对应需求 |\n|---|---|---|---|\n" + "".join(
                f"| {a} | x | `FOO` | R.001 |\n" for a in asserts)
        elif sec == "框图与模块划分":
            body = "| 模块 | 功能 |\n|---|---|\n| `SUB_A` | x |\n"
        elif sec == "SUB_A":
            body = (text or "不适用") + "\n"
        out += f"\n## {sec}\n\n{body}"
    return out


def _write_docs(root, top, spec_text):
    """按根的类型写接口文档：designs/ 写 lrs + lld（lld 已有则不动），cbb/ 写 spec。"""
    if root.parent.name == "designs":
        params = ("DAT_W",)
        if (root / "params.yaml").exists():
            import yaml
            cfg = ((yaml.safe_load((root / "params.yaml").read_text()) or {}).get("tops") or {}).get(top) or {}
            params = tuple(cfg.get("params") or {})
        (root / f"lrs.{top}.md").write_text(_lrs(spec_text, params=params))
        if not (root / f"lld.{top}.md").exists():
            (root / f"lld.{top}.md").write_text(_good_lld())
        for kind in ("param", "ppa", "timing"):      # 内部#203 lld-restructure D4：三份文档，模板原样
            if not (root / f"{kind}.{top}.md").exists():
                (root / f"{kind}.{top}.md").write_text(
                    (REPO_ROOT / "flow" / "templates" / "design-root" / f"{kind}.md").read_text())
    else:
        (root / f"spec.{top}.md").write_text(spec_text)


def _as_tops(params_yaml, top):
    """把一段 `params:` 包成设计根声明的形态：`design_root:` + `tops:` + 顶层。

    2026-09-20 起一个设计根按 `tops:` 声明它的被测顶层，`sim`/`sta`/`params`
    三段都挂在顶层之下（`openspec/specs/repo-layout/spec.md` 的
    「设计根可以声明多个被测顶层」）。用例给的仍然只是 `params:` 那一段 ——
    它们要验的是**组合展开**，不是声明形态，所以包装放在夹具里而不是用例里。
    """
    body = "".join(("    " + ln if ln.strip() else ln) + "\n"
                   for ln in params_yaml.rstrip("\n").split("\n"))
    return f"design_root: {top}\ntops:\n  {top}:\n{body}"


# 夹具仓的记录分支白名单：main 加一个集成分支 cbb_open，用例里的「白名单分支」都指它。
FIXTURE_RECORD_BRANCHES = """\
# 测试夹具的记录分支白名单（tests/fast_check_fixture.py 写入）
branches:
  - main
  - cbb_open
"""


def _fixture_repo(tmp_path, params_yaml, extra_rtl=None):
    """搭一个最小仓库：flow/ 与 scripts/ 要存在（compileall 会走到），加一个设计根。"""
    for d in ("flow", "scripts", "cbb"):
        (tmp_path / d).mkdir()
    rtl = tmp_path / "designs" / "foo" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "foo.v").write_text(GOOD_RTL)
    if extra_rtl is not None:
        (rtl / "bad.v").write_text(extra_rtl)
    (tmp_path / "designs" / "foo" / "params.yaml").write_text(
        _as_tops(params_yaml, "FOO"))
    _write_docs(tmp_path / "designs" / "foo", "FOO", _good_spec("FOO"))
    shutil.copy(SCRIPT, tmp_path / "scripts" / "fast_check.sh")
    # fast_check 读哪些文件由 flow/paths.py::rtl_candidates 决定（add-design-cbb-deps D3），
    # 夹具仓库要带上这一份 —— 拷的是本仓的真文件，不是替身。
    _copy_paths_py(tmp_path)
    return tmp_path / "scripts" / "fast_check.sh"


def _style_exempt(root, *paths):
    """把夹具里**故意**不合书写风格的文件列进豁免清单（add-rtl-coding-style D15）。

    这些用例测的是别的检查项（一个文件两个模块时的模块名检查、注释里出现关键字时
    的扫描、同名文件一致性……），夹具 RTL 的形状就是被测对象，改成合规会改掉用例本意。
    清单的语义正好对得上：列出的文件 MUST 仍然不合规，合规了检查会要求移出。"""
    lst = root / "flow" / "lint" / "style_legacy.txt"
    lst.parent.mkdir(parents=True, exist_ok=True)
    old = lst.read_text() if lst.exists() else ""
    lst.write_text(old + "".join(p + "\n" for p in paths))


def _copy_paths_py(root):
    (root / "flow").mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "flow" / "paths.py", root / "flow" / "paths.py")
    shutil.copy(REPO_ROOT / "flow" / "param_exclude.py", root / "flow" / "param_exclude.py")
    shutil.copy(REPO_ROOT / "flow" / "budget.py", root / "flow" / "budget.py")  # 并发取自这里（内部#359）
    (root / "flow" / "check").mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "flow" / "check" / "check_waivers.py", root / "flow" / "check" / "check_waivers.py")
    shutil.copy(REPO_ROOT / "flow" / "check" / "tool_versions.py", root / "flow" / "check" / "tool_versions.py")
    # fast_check 的各段检查器（内部#336 从脚本里迁出）；fc_cache.py 不拷：夹具里同一份内容第二次跑会被复用，
    # 复用由 tests/test_fast_check_reuse.py 专门测
    for checker in (REPO_ROOT / "flow" / "check").glob("fc_*.py"):
        if checker.name != "fc_cache.py":
            shutil.copy(checker, root / "flow" / "check" / checker.name)
    shutil.copy(REPO_ROOT / "requirements.txt", root / "requirements.txt")
    # 记录分支白名单（内部#422）：fc_record_branches 读它，读不到按契约失败。夹具自己声明一份，不拷本仓的真文件：
    # 真文件的分支表会变，开源导出里它还被换成只有 main 的版本，用例假定的集成分支就不在了（内部#409 Q2）。
    (root / "flow" / "record_branches.yaml").write_text(FIXTURE_RECORD_BRANCHES)
    # 「开源集合泄漏不增」（内部#365）：扫描脚本照拷，清单与基线用最小的一份（真清单的 block 规则是闭源名字表）
    (root / "flow" / "export").mkdir(exist_ok=True)
    for name in ("leak_scan.py", "leak_ratchet.py"):
        shutil.copy(REPO_ROOT / "flow" / "export" / name, root / "flow" / "export" / name)
    (root / "flow" / "export" / "manifest.yaml").write_text("include:\n  - flow/**\nrules:\n  block: []\n  warn: []\n")
    (root / "flow" / "export" / "leak_baseline.txt").write_text("0\n")


_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(root, *args):
    import os
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True,
                          env=dict(os.environ, **_GIT_ENV)).stdout


def _ensure_git(script, branch="main"):
    """夹具仓还不是 git 仓时，就地 `git init` 并把当前内容提交一次。

    fast_check 的「记录与报告的来源」等几项要从 `main` 算 merge-base，
    不在 git 仓里只能记为未执行（parallel-worktree spec，内部#443）。所以夹具默认就是
    一个停在 main 上、工作区干净的 git 仓；已经是 git 仓的（用例自己搭的
    分支形态）原样不动。"""
    root = script.parent.parent
    if (root / ".git").exists():
        return
    subprocess.run(["git", "init", "-q", "-b", branch, str(root)], check=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")


def _run(script):
    """跑脚本。夹具仓库里没有 .venv，fast_check.sh 会回落到 PATH 上的 python3，
    而参数组合展开需要 yaml——所以必须把本仓 .venv/bin 接进 PATH。

    不这么做时，这些用例只在「direnv 已激活 .venv 的 shell」里通过，换个环境就
    红在 ModuleNotFoundError 上，而那是夹具坏了、不是被测行为坏了。2026-09-13
    装上 iverilog 之前这两个用例一直被 @needs_iverilog 跳过，这层环境敏感性
    因此从未暴露过。"""
    import os
    env = dict(os.environ)
    env["PATH"] = f"{REPO_ROOT / '.venv' / 'bin'}:{env['PATH']}"
    _ensure_git(script)
    return (subprocess.run([str(script)], capture_output=True, text=True, env=env))


needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog 不在 PATH")

GOOD_PARAMS = "params:\n  DAT_W:\n    values: [4, 8]\n"
# 桩 iverilog 不检查 RTL，但 fast_check 要从它的 -o 产物（vvp）里读顶层端口，
# 所以按夹具 GOOD_RTL 的形状写一份最小的 vvp：端口 i_a / o_y，位宽取 -P <顶层>.DAT_W
# （缺省 4），参数值按真 iverilog 的 `+C4<二进制>` 格式写。
_STUB_VVP = r"""
out=; top=; w=4
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift ;;
    -s) top=$2; shift ;;
    -P*.DAT_W=*) w=${1##*=} ;;
  esac
  shift
done
if [ -n "$out" ] && [ "$out" != /dev/null ]; then
  n=$w; bits=
  while [ "$n" -gt 0 ]; do bits=$((n % 2))$bits; n=$((n / 2)); done
  printf '.scope module, "%s" "%s" 2 3;\n' "$top" "$top" > "$out"
  printf '    .port_info 0 /INPUT %s "i_a";\n    .port_info 1 /OUTPUT %s "o_y";\n' "$w" "$w" >> "$out"
  printf 'P_0 .param/l "DAT_W" 0 1 1, +C4<%s>;\n' "${bits:-0}" >> "$out"
fi
"""
STUB_OK = "#!/bin/sh\n" + _STUB_VVP + "exit 0\n"


# 夹具仓库里没有 .venv，脚本会回落到 PATH 上的 python3；组合展开需要 yaml，
# 所以把本仓 .venv/bin 放进 PATH。不这么做的话红会是 ModuleNotFoundError，
# 那是夹具坏了，不是被测行为坏了。
_VENV_BIN = REPO_ROOT / ".venv" / "bin"


def _run_with_path(script, stub=None, env_extra=None, args=(), verilator="#!/bin/sh\nexit 0\n"):
    """跑脚本。stub 非空时把一个假 iverilog 放进 PATH 最前；为空则保证 PATH 上没有它。

    PATH 必须仍然解析得到 bash（脚本的 shebang 是 /usr/bin/env bash）与一个带
    yaml 的 python3——否则失败原因会是夹具而不是被测行为。
    """
    import os
    env = dict(os.environ)
    bindir = script.parent.parent / "stubbin"
    bindir.mkdir(exist_ok=True)
    base = f"{bindir}:{_VENV_BIN}:/usr/bin:/bin:/usr/sbin:/sbin"
    if stub is not None:
        p = bindir / "iverilog"
        p.write_text(stub)
        p.chmod(0o755)
        # lint 一项要 verilator。这些用例测的是 elaborate 那一侧的判定，所以给一个
        # 永远通过的桩：两个工具要么都在、要么都不在，不让 lint 的缺失混进来。
        v = bindir / "verilator"
        v.write_text(verilator)
        v.chmod(0o755)
    env["PATH"] = base
    env.update(env_extra or {})
    _ensure_git(script)
    return (subprocess.run([str(script), *args], capture_output=True, text=True, env=env))
STYLE = "RTL 书写风格"

STYLE_OK = """\
//======================================================================

// File    : sty.v
// Module  : STY
// Purpose : style fixture with every mechanically checked convention
// Spec    : designs/foo/lrs.FOO.md
// Language: Verilog-2001
//======================================================================

module STY #(
     parameter DAT_W = 4
)(
     input  wire             clk
    ,input  wire             rst_n
    ,input  wire [DAT_W-1:0] i_a
    ,output wire [DAT_W-1:0] o_y
    ,output wire [1:0]       o_cnt
);

//---- signal declaration
reg  [DAT_W-1:0] dat_r;
reg  [DAT_W-1:0] dat_1ff;
reg  [DAT_W-1:0] rev_r;
reg  [1:0]       st_r;
reg  [1:0]       st_pre;
wire [DAT_W-1:0] sum;
integer          bi;

//---- data path
always@(posedge clk) begin : BLK_DAT
    dat_r[DAT_W-1:0] <= i_a;
    {dat_1ff} <= dat_r;
end

always@(posedge clk) begin : BLK_REV
    for(bi = 0; bi < DAT_W; bi = bi + 1) begin : BLK_FOR
        rev_r[bi] <= i_a[DAT_W-1-bi];
    end
end

//---- state machine: casez in a comment does not count
always@(posedge clk,negedge rst_n) begin : BLK_ST
    if(rst_n == 1'b0) begin
        st_r <= 2'd0;
    end else if(st_r <= 2'd2) begin
        st_r <= st_pre;
    end
end

always@(*) begin : BLK_ST_PRE
    st_pre = st_r;
    case(st_r)
        2'd0: begin
            st_pre = 2'd1;
        end
        default: begin
            st_pre = 2'd0;
        end
    endcase
end

genvar gi;
generate
    for(gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR
        assign sum[gi] = dat_1ff[gi] ^ rev_r[gi];
    end
    if(DAT_W > 2) begin : GEN_WIDE
        CBB_LZD #(.DAT_W(DAT_W)) U_STY_IDLE_CBB_LZD (.i_dat(sum), .o_enc(o_cnt), .o_dec(), .o_zero());
    end else begin : GEN_NARROW
        assign o_cnt = 2'd0;
    end
endgenerate

assign o_y = sum;

endmodule
"""


def _style_repo(tmp_path, files, legacy=None):
    """夹具仓库加若干文件（{相对 designs/foo/rtl 的文件名: 内容}）与可选的豁免清单。"""
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    for name, text in files.items():
        (tmp_path / "designs" / "foo" / "rtl" / name).write_text(text)
    if legacy is not None:
        (tmp_path / "flow" / "lint").mkdir(parents=True, exist_ok=True)
        (tmp_path / "flow" / "lint" / "style_legacy.txt").write_text(legacy)
    return script


def _style_out(script):
    r = _run(script)
    out = r.stdout + r.stderr
    block = out.split(f"FAIL  {STYLE}", 1)[1].split("\n\n", 1)[0] if f"FAIL  {STYLE}" in out else ""
    return out, block
needs_verilator = pytest.mark.skipif(
    shutil.which("verilator") is None or shutil.which("iverilog") is None,
    reason="verilator / iverilog 不在 PATH")

UNUSED_CLK_RTL = """\
module FOO #(parameter DAT_W = 4) (input wire clk, input wire [DAT_W-1:0] i_a, output wire [DAT_W-1:0] o_y);
  assign o_y = i_a;
endmodule
"""
CLK_WAIVER = """`verilator_config
lint_off -rule UNUSEDSIGNAL -file "*/foo.v" -match "*'clk'"
"""
PORT_CHECK = "spec 端口表与 RTL 一致"
PORT_FAIL = "spec 端口表与 RTL 不一致"


def _port_run(script):
    r = _run(script)
    return r, r.stdout + r.stderr


def _doc_run(tmp_path, lrs=None, lld=None):
    script = _fixture_repo(tmp_path, GOOD_PARAMS)
    root = tmp_path / "designs" / "foo"
    if lrs is not None:
        (root / "lrs.FOO.md").write_text(lrs)
    if lld is not None:
        (root / "lld.FOO.md").write_text(lld)
    r = _run_with_path(script, stub=STUB_OK)
    return r, r.stdout + r.stderr
COMMON_ROWS = ("握手保持", "valid 不依赖 ready", "汇聚口屏蔽", "活性", "写数据不等命令", "功能不依赖打拍配置")


def _verify_md(rows=COMMON_ROWS, cover="覆盖", table=True):
    body = "# FOO 验证方案\n\n验证状态：未验证\n\n"
    if table:
        body += "| 通用规范 | 验什么 | 覆盖 |\n|---|---|---|\n"
        body += "".join(f"| {r} | x | {cover if r != rows[-1] else '不适用（没有握手）'} |\n" for r in rows)
    return body


def _write_waivers(repo, body):
    (repo / "flow" / "check_waivers.yaml").write_text(body)

_NO_NET = {"FAST_CHECK_WAIVER_ISSUE_CHECK": "0"}


# 下划线开头的辅助函数也要给 import * 带出去
__all__ = [n for n in dir() if not n.startswith("__")]
