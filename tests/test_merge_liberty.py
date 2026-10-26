"""merge_liberty.py 的合并产物必须满足「模板定义先于引用」。

为什么值得有这个测试：liberty 是自上而下解析的，模板在引用之后才定义时
**解析器不会报错退出**，只会警告一句并把那个时序组丢弃。丢的是那条弧的延时模型，
后果是整类路径从 STA 里消失（时序单元的 CLK→Q 弧一没，所有以触发器为起点的路径
就都不存在了），而工具照常给出一个看上去正常的 slack。2026-09-09 就是这么翻的车：
`~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib` 里 `delay_template_7x7` 的定义在
第 943009 行，而第一次引用在第 905363 行。

`check_definition_before_use` 用**独立的正则**扫产物，不复用 merge_liberty 自己的
`_extract_blocks` —— 用被测代码的解析函数去验证被测代码，测不出解析本身的偏差。
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MERGE_SCRIPT = REPO_ROOT / "flow" / "synth" / "merge_liberty.py"

sys.path.insert(0, str(MERGE_SCRIPT.parent))
from merge_liberty import merge_liberty  # noqa: E402

TEMPLATE_DEF = re.compile(
    r"^[ \t]*(?:lu_table_template|power_lut_template)[ \t]*\([ \t]*([A-Za-z0-9_]+)[ \t]*\)",
    re.M,
)


def check_definition_before_use(text):
    """返回 [(模板名, 首次引用位置, 定义位置), ...]；为空表示产物自洽。

    「引用」= 文本里任何一处 `(<模板名>)`，除了定义自己那一处。名字两侧要求紧邻
    括号，所以 `(delay_template_7x7_x1)` 不会被算成 `delay_template_7x7` 的引用。
    """
    defs = {}
    for m in TEMPLATE_DEF.finditer(text):
        defs.setdefault(m.group(1), m.start())

    problems = []
    for name, def_pos in sorted(defs.items()):
        pattern = re.compile(r"\([ \t]*" + re.escape(name) + r"[ \t]*\)")
        for m in pattern.finditer(text):
            if m.start() < def_pos:
                problems.append((name, m.start(), def_pos))
                break
    return problems


def _write(path, text):
    path.write_text(text)
    return str(path)


BASE_LIB = """\
library (base_lib) {
  delay_model : table_lookup;
  time_unit : "1ps";

  lu_table_template (t_shared) {
    variable_1 : input_net_transition;
    index_1 ("1, 2");
    marker_from_base_lib : 1;
  }

  cell (SHARED_CELL) {
    marker_from_base_lib : 1;
    pin (Y) {
      timing () {
        cell_rise (t_shared) {
          values ("1, 2");
        }
      }
    }
  }
}
"""

# 第二个库：cell 在前、它引用的模板在后 —— 正是 ASAP7 的 SEQ 库那种形态
SEQ_LIB = """\
library (seq_lib) {
  delay_model : table_lookup;

  cell (SEQ_CELL) {
    pin (QN) {
      timing () {
        related_pin : "CLK";
        cell_rise (t_seq_only) {
          values ("3, 4");
        }
        rise_power (p_seq_only) {
          values ("5, 6");
        }
      }
    }
  }

  cell (SHARED_CELL) {
    marker_from_seq_lib : 1;
  }

  lu_table_template (t_shared) {
    marker_from_seq_lib : 1;
  }

  lu_table_template (t_seq_only) {
    variable_1 : input_net_transition;
    index_1 ("1, 2");
  }

  power_lut_template (p_seq_only) {
    variable_1 : input_net_transition;
    index_1 ("1, 2");
  }
}
"""


def _merge(tmp_path):
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    out = tmp_path / "merged.lib"
    subprocess.run(
        [sys.executable, str(MERGE_SCRIPT), "-o", str(out), "--base", base, seq],
        check=True, capture_output=True,
    )
    return out.read_text()


def test_templates_are_defined_before_first_use(tmp_path):
    """本 bug 的直接判据。"""
    merged = _merge(tmp_path)
    problems = check_definition_before_use(merged)
    assert not problems, (
        "合并产物里有模板在定义之前就被引用了（liberty 自上而下解析，"
        "解析器只会警告不会报错，丢掉的是整条时序弧）：\n"
        + "\n".join(
            f"  {name}: 首次引用在 offset {use}，定义在 offset {dfn}"
            for name, use, dfn in problems
        )
    )


def test_dedup_rule_unchanged(tmp_path):
    """本变更只改块的排列，不改取舍：同名块仍然只保留首个源文件里的那一份。"""
    merged = _merge(tmp_path)

    assert merged.count("cell (SHARED_CELL)") == 1
    assert merged.count("lu_table_template (t_shared)") == 1
    # 保留的必须是 base 那一份 —— seq 里的同名块带了不同的 marker
    assert "marker_from_seq_lib" not in merged
    assert merged.count("marker_from_base_lib") == 2   # 模板一次、cell 一次

    # 第二个库独有的块要被带进来
    assert merged.count("cell (SEQ_CELL)") == 1
    assert merged.count("lu_table_template (t_seq_only)") == 1
    assert merged.count("power_lut_template (p_seq_only)") == 1


def test_merged_library_is_a_single_library_block(tmp_path):
    """合并的意义就是产出一个 library{}；顺序重排不能把它拆开或漏掉收尾。"""
    merged = _merge(tmp_path)
    assert merged.count("\nlibrary (") + merged.startswith("library (") == 1
    assert merged.rstrip().endswith("}")
    assert merged.count("{") == merged.count("}")


if __name__ == "__main__":
    # 也可以直接拿来查一份真实的合并库：
    #   python tests/test_merge_liberty.py ~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib
    target = Path(sys.argv[1]).expanduser()
    found = check_definition_before_use(target.read_text())
    if found:
        print(f"{target}: {len(found)} 个模板在定义之前就被引用：")
        for name, use, dfn in found:
            print(f"  {name}: 首次引用 offset {use} < 定义 offset {dfn}")
        sys.exit(1)
    print(f"{target}: 所有被引用的模板都先于引用被定义")


# --- 块边界必须与 liberty 的词法结构一致 -------------------------------------

LEXICAL_LIB = """\
library (lexical_lib) {
  delay_model : table_lookup;

  lu_table_template (t_shared) {
    variable_1 : input_net_transition;
    index_1 ("1, 2");
  }

  cell (BUF) {
    area : 1.0;
    /* 这段注释里有个花括号 {，下一行是一个伪装成块头的行：
    cell (GHOST) {
       注释没结束，上面那行不是块头 */
    pin (Y) {
      function : "A { not a brace";
      direction : output;
    }
  }

  cell (INV) {
    area : 2.0;
  }
}
"""


def _cells(text):
    from flow.synth.merge_liberty import _extract_blocks
    return {name: body for name, body in _extract_blocks(text, "cell")}


def test_brace_in_string_literal_does_not_extend_the_block():
    """字符串里的 `{` 曾让 cell (BUF) 的块吞掉后面整个 cell (INV)。"""
    cells = _cells(LEXICAL_LIB)
    assert "cell (INV)" not in cells["BUF"], (
        "BUF 的块吞掉了后面的 cell —— 字符串里的花括号被算进了块深度")
    assert cells["BUF"].rstrip().endswith("}")
    assert 'function : "A { not a brace";' in cells["BUF"], "块内容必须逐字保留"


def test_brace_in_comment_does_not_extend_the_block():
    """`/* … { … */` 里的花括号同样不该算进深度。"""
    cells = _cells(LEXICAL_LIB)
    assert "cell (INV)" not in cells["BUF"]
    assert cells["INV"].strip().startswith("cell (INV)")
    assert "area : 2.0;" in cells["INV"]


def test_block_header_inside_a_comment_is_not_a_block():
    """注释里写着 `cell (GHOST)`，它不是一个块。"""
    assert "GHOST" not in _cells(LEXICAL_LIB)


# --- 产物不得依赖源文件的给出顺序 ---------------------------------------------
#
# 为什么值得有这个测试：合并库的**内容哈希**是流程指纹的一项事实
# （`flow/flow_fingerprint.py` 的 `liberty_sha256`）。顺序敏感意味着同一批源文件
# 能产出两份哈希不同的库，把语义上同一个库判成两个不可比的流程代 —— 一次假分代。
# 2026-09-14 从 Mac 交接到 Linux 时就撞上了：两份 `asap7sc7p5t_RVT_TT.lib`
# 字节数逐字节相同（46152868）、sha256 不同。

# 第三个库：与 base/seq 都没有同名块，用来打乱顺序
AUX_LIB = """\
library (aux_lib) {
  delay_model : table_lookup;

  cell (AUX_CELL) {
    marker_from_aux_lib : 1;
    pin (Y) {
      timing () {
        cell_rise (t_aux_only) {
          values ("7, 8");
        }
      }
    }
  }

  lu_table_template (t_aux_only) {
    variable_1 : input_net_transition;
    index_1 ("1, 2");
  }

  power_lut_template (p_aux_only) {
    variable_1 : input_net_transition;
    index_1 ("1, 2");
  }
}
"""


def test_merge_is_independent_of_source_order(tmp_path):
    """同一个基文件 + 同一批其余源文件，换个给出顺序，产物必须逐字节相同。"""
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    aux = _write(tmp_path / "aux.lib", AUX_LIB)

    forward = merge_liberty([base, seq, aux])
    reverse = merge_liberty([base, aux, seq])

    assert forward == reverse, (
        "换一个入参顺序就换一份产物 —— 合并库的内容哈希是流程指纹的一项事实，"
        "这会把语义上同一个库判成两个不可比的流程代"
    )
    # 顺序无关不能是"两边都漏了同一批块"换来的
    for marker in ("SEQ_CELL", "AUX_CELL", "t_seq_only", "t_aux_only",
                   "p_seq_only", "p_aux_only"):
        assert forward.count(marker) >= 1, f"{marker} 没被带进产物"


def test_source_order_independence_survives_the_p2_rule(tmp_path):
    """排序不得破坏「全部模板在前、全部 cell 在后」—— 那是 P-2。"""
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    aux = _write(tmp_path / "aux.lib", AUX_LIB)

    for paths in ([base, seq, aux], [base, aux, seq]):
        merged = merge_liberty(paths)
        problems = check_definition_before_use(merged)
        assert not problems, (
            f"入参顺序 {[Path(p).name for p in paths]} 下产物有模板在定义前被引用："
            + ", ".join(name for name, _u, _d in problems)
        )


def test_conflicting_duplicate_blocks_are_refused(tmp_path):
    """同名块内容不同时必须报错 —— 静默挑一份就等于把顺序敏感藏起来。

    去重是「首个出现的胜出」，而谁先出现由入参顺序决定。内容相同时这无所谓
    （ASAP7 的 5 个 RVT/TT 源文件里 6 个跨文件同名块内容全都逐字节相同）；
    内容不同时，静默挑一份就让上面那条「顺序无关」变成假的。

    只针对 `paths[1:]` 之间的冲突。基文件与其余文件的同名块由基文件胜出，
    那与顺序无关（基文件永远是 `paths[0]`），是 test_dedup_rule_unchanged
    锁住的既有取舍。
    """
    conflicting = SEQ_LIB.replace('values ("3, 4");', 'values ("9, 9");')
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    other = _write(tmp_path / "other.lib", conflicting)

    with pytest.raises(ValueError) as exc:
        merge_liberty([base, seq, other])
    # 报错必须说清是哪个块，否则拿着一份几十 MB 的库没法查
    assert "SEQ_CELL" in str(exc.value)
    # 换个顺序同样要报 —— 否则"报不报错"本身就成了顺序敏感的
    with pytest.raises(ValueError):
        merge_liberty([base, other, seq])


def test_base_file_wins_over_a_conflicting_borrowed_block(tmp_path):
    """基文件与其余文件的同名冲突不报错：基文件永远是 paths[0]，胜出与顺序无关。"""
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)

    merged = merge_liberty([base, seq])
    assert "marker_from_seq_lib" not in merged
    assert merged.count("marker_from_base_lib") == 2


def test_identical_duplicate_blocks_are_still_deduped(tmp_path):
    """内容逐字相同的同名块不算冲突 —— ASAP7 的实际形态就是这样。"""
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    same = _write(tmp_path / "same.lib", SEQ_LIB)

    merged = merge_liberty([base, seq, same])
    assert merged.count("cell (SEQ_CELL)") == 1


# --- 与块顺序无关的内容摘要 ---------------------------------------------------
#
# 为什么值得有这个测试：两份合并库的内容哈希不同时，唯一能问的问题是"不相等"，
# 而那答不了"是不是只差块的排列"。2026-09-14 Mac 与 Linux 那两份
# `asap7sc7p5t_RVT_TT.lib` 字节数逐字节相同、sha256 不同，就卡在这个问题上。
#
# 它是**比较两份文件**的工具，MUST NOT 当作 P-2 的判据：它复用被测代码的
# `_extract_blocks`，用被测代码的解析函数去验证被测代码测不出解析本身的偏差。
# 比较两份文件时那个偏差在两边抵消，所以这个用法是成立的。

def _canonical(path):
    """跑 `--canonical-hash`，返回 {'canonical': ..., 'header': ...}。"""
    out = subprocess.run(
        [sys.executable, str(MERGE_SCRIPT), "--canonical-hash", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return dict(
        line.split(None, 1) for line in
        (l.strip() for l in out.splitlines()) if line and len(line.split()) == 2
    )


# 同一批块、两种排列。手写而不是把一份产物重排：1.1 之后 merge_liberty 已经
# 顺序无关，没法再靠它造出"只差排列"的两份，而在测试里复用被测代码的切块函数去
# 重排，等于用被测代码验证被测代码。
_HEADER = """\
library (order_lib) {
  delay_model : table_lookup;
  time_unit : "1ps";
"""

_BLOCK_T = """
  lu_table_template (t_a) {
    variable_1 : input_net_transition;
    index_1 ("1, 2");
  }
"""

_BLOCK_C1 = """
  cell (C_ONE) {
    area : 1.0;
    pin (Y) {
      timing () {
        cell_rise (t_a) {
          values ("3, 4");
        }
      }
    }
  }
"""

_BLOCK_C2 = """
  cell (C_TWO) {
    area : 2.0;
  }
"""

ORDER_LIB_A = _HEADER + _BLOCK_T + _BLOCK_C1 + _BLOCK_C2 + "}\n"
ORDER_LIB_B = _HEADER + _BLOCK_T + _BLOCK_C2 + _BLOCK_C1 + "}\n"


def test_canonical_hash_ignores_block_order(tmp_path):
    """同一批块换个排列，canonical 相同。"""
    one = _write(tmp_path / "one.lib", ORDER_LIB_A)
    two = _write(tmp_path / "two.lib", ORDER_LIB_B)
    assert ORDER_LIB_A != ORDER_LIB_B, "夹具的两份必须真的不同字节"

    a, b = _canonical(one), _canonical(two)
    assert a["canonical"] == b["canonical"], (
        "只差块排列的两份库，canonical 摘要必须相同 —— 否则它答不了假分代"
    )
    assert a["header"] == b["header"], "两份的头部逐字相同，header 也该相同"


def test_canonical_hash_changes_when_a_block_changes(tmp_path):
    """摘要不能对内容改动免疫，否则它什么也证明不了。"""
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    one = _write(tmp_path / "one.lib", merge_liberty([base, seq]))
    two = _write(tmp_path / "two.lib",
                 merge_liberty([base, seq]).replace('values ("3, 4")',
                                                    'values ("9, 9")'))
    assert _canonical(one)["canonical"] != _canonical(two)["canonical"]


def test_header_hash_is_reported_separately(tmp_path):
    """只改首块之前的头部时，canonical 不变而 header 变 —— 两项各管一段。

    头部带着 delay_model、单位声明、operating_conditions —— 那些同样改变测量
    结果，只哈希块会把它们漏掉。分两项输出是为了能一眼看出差异落在哪一边。
    """
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    merged = merge_liberty([base, seq])
    assert 'time_unit : "1ps";' in merged

    one = _write(tmp_path / "one.lib", merged)
    two = _write(tmp_path / "two.lib",
                 merged.replace('time_unit : "1ps";', 'time_unit : "1ns";'))

    a, b = _canonical(one), _canonical(two)
    assert a["canonical"] == b["canonical"], "改头部不该动 canonical"
    assert a["header"] != b["header"], "改头部必须动 header"


# --- 基文件必须显式给出，且产物要能自证用了哪一份 ------------------------------
#
# 为什么值得有这个测试：基文件的正文整段原样进入产物，它还带着 delay_model、
# 单位声明、operating_conditions —— 换一个基文件就是另一份 liberty_sha256，
# 也就是另一代记录（红线 4）。而这件事**不会报错**：合并照常成功，产物照常可用，
# 只是与此前全部记录不可横向比较。
#
# 2026-09-15 之前唯一的约束是 docs/toolchain.md 里一句「SIMPLE 放第一个」——
# 排错了不报错。本仓 内部#29。

def _run_merge(args, check=True):
    return subprocess.run(
        [sys.executable, str(MERGE_SCRIPT), *args],
        check=check, capture_output=True, text=True)


def test_merging_without_a_base_is_refused(tmp_path):
    """不给 `--base` 时必须失败，且不能从位置参数里挑一个顶上。"""
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    out = tmp_path / "merged.lib"

    r = _run_merge(["-o", str(out), str(base), str(seq)], check=False)

    assert r.returncode != 0, (
        "没给基文件却合并成功了 —— 那意味着它从位置参数里挑了一个，"
        "而选谁决定了产物的 liberty_sha256，也就是这批记录属于哪一代")
    assert "base" in (r.stderr + r.stdout).lower()
    assert not out.exists(), "失败了却写出了产物"


def test_canonical_hash_tells_which_base_was_used(tmp_path):
    """只换基文件：`base` 项必须不同，而 `canonical` 项相同（块集合没变）。"""
    a = _write(tmp_path / "a.lib", BASE_LIB)
    b = _write(tmp_path / "b.lib", BASE_LIB.replace("order_lib", "order_lib")
               .replace('time_unit : "1ps";', 'time_unit : "1ps";\n  // 只差一行注释'))
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)

    out_a = tmp_path / "ma.lib"
    out_b = tmp_path / "mb.lib"
    _run_merge(["-o", str(out_a), "--base", str(a), str(seq)])
    _run_merge(["-o", str(out_b), "--base", str(b), str(seq)])

    ha, hb = _canonical(out_a), _canonical(out_b)
    assert "base" in ha, f"摘要里没有 base 项：{ha}"
    assert ha["base"] != hb["base"], (
        "换了基文件而 base 项没变 —— 那这一项就证明不了任何东西")
    assert ha["canonical"] == hb["canonical"], (
        "块集合没变，canonical 却变了 —— 这一项的定义被破坏了")


def test_source_order_still_does_not_matter_with_an_explicit_base(tmp_path):
    """基文件相同、其余源库顺序不同：产物逐字节相同，摘要三项全同。"""
    base = _write(tmp_path / "base.lib", BASE_LIB)
    seq = _write(tmp_path / "seq.lib", SEQ_LIB)
    aux = _write(tmp_path / "aux.lib", AUX_LIB)

    fwd = tmp_path / "fwd.lib"
    rev = tmp_path / "rev.lib"
    _run_merge(["-o", str(fwd), "--base", str(base), str(seq), str(aux)])
    _run_merge(["-o", str(rev), "--base", str(base), str(aux), str(seq)])

    assert fwd.read_bytes() == rev.read_bytes()
    assert _canonical(fwd) == _canonical(rev)
