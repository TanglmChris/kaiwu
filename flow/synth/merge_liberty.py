"""ASAP7 ships one liberty file per cell family (AO/OA/INVBUF/SEQ/SIMPLE/...)
per Vt/corner. Yosys's dfflibmap/abc and OpenSTA's read_liberty each expect a
single file, so merge the per-family cell definitions into one liberty file
under a single `library (...) { ... }` block, borrowing the first file's
header/attributes.

    python flow/synth/merge_liberty.py -o merged.lib file1.lib file2.lib ...

ORDER MATTERS. Liberty is parsed top-down: a lookup-table template must be
defined before the first cell that references it by name. Getting this wrong
does NOT make the parser stop -- it warns once ("table template ... not found",
"no table models found in timing group") and drops that timing group, so the
cell loses that arc's delay model entirely. An earlier version of this script
appended every borrowed block at the end, which put the SEQ family's
`delay_template_7x7` 38k lines AFTER the flip-flops that use it: OpenSTA then
had no CLK->Q arc at all, so no timing path could START at a flop, and every
pipelined design reported "input -> first flop" as its critical path with no
error anywhere. Sequential internal power came out as a flat zero for the same
reason. Hence: all templates first, then all cells.
"""
import argparse
import hashlib
import re
import sys


# Block types that vary per cell family and must be unioned across files.
# (Templates are referenced by name from cell timing/power tables -- if a
# cell's family file isn't the one that "owns" a template, dropping it left
# OpenSTA unable to find e.g. passive_power_template_7x1.)
TEMPLATE_BLOCK_TYPES = ("lu_table_template", "power_lut_template")
MERGE_BLOCK_TYPES = ("cell",) + TEMPLATE_BLOCK_TYPES


def _blank_noncode(text):
    """同长度的副本，字符串字面量与 `/* */` 注释里的字符全换成空格（换行保留）。

    块边界只能按 liberty 的词法结构来判：`function : "A { not a brace"` 里的
    花括号不是块的开始，注释里写着 `cell (FOO)` 也不是一个块。逐字符数花括号
    会把两者都算进去 —— 实测结果是 `cell (BUF)` 的块吞掉紧随其后的整个
    `cell (INV)` 和 `library` 的收尾花括号，而没有任何一步报错。

    做成「挖空副本」而不是边扫边判，是为了让偏移量保持不变：正则与花括号计数都
    在副本上跑，切出来的片段仍然从**原文**取，块内容因此逐字保留。

    只认双引号字符串（转义只认反斜杠）与 `/* */` 注释 —— liberty 的字符串就是
    双引号，注释就是 C 风格。`//` 在 liberty 里不是注释，当成注释会吃掉合法内容。
    """
    out = list(text)
    n = len(text)
    i = 0
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                out[i] = " "
                out[i + 1] = "\n" if text[i + 1] == "\n" else " "
                i += 2
                continue
            out[i] = "\n" if ch == "\n" else " "
            if ch == '"':
                in_string = False
            i += 1
        elif ch == '"':
            in_string = True
            out[i] = " "
            i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for k in range(i, end):
                out[k] = "\n" if text[k] == "\n" else " "
            i = end
        else:
            i += 1
    return "".join(out)


def _block_spans(text, block_type):
    """Return [(name, start, end_exclusive), ...] for top-level `block_type (name) { ... }`.

    块头的定位与花括号的配对都在 `_blank_noncode` 的副本上进行，偏移量因此与原文
    一一对应。返回**偏移**而不是切片，是因为调用方有两类需求：一类要块的内容
    （`_extract_blocks`），另一类要块**之外**的内容（`_skeleton`）。后者没法从
    切片反推位置 —— `text.index(块内容)` 在两个块内容逐字相同时会指向同一处。
    """
    code = _blank_noncode(text)
    spans = []
    for m in re.finditer(r"\n(\s*" + block_type + r"\s*\(([^)]*)\))", code):
        start = m.start(1)
        name = m.group(2).strip()
        brace_start = code.index("{", start)
        depth = 0
        i = brace_start
        while i < len(code):
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        spans.append((name, start, i + 1))
    return spans


def _extract_blocks(text, block_type):
    """Return [(name, raw_block_text), ...] for top-level `block_type (name) { ... }` blocks."""
    return [(name, text[start:end]) for name, start, end in _block_spans(text, block_type)]


def _skeleton(text):
    """块外的全部文本 —— 头部、块与块之间的属性/注释、收尾的 `}`。

    合并产物里这一整段**只来自基文件**：借来的块是整块拼进去的，块外只多出
    固定的换行分隔符。所以它就是「这份库拿谁当的基」的可验证答案，而且不需要
    往产物里塞任何标记 —— 塞标记会改变合并库的字节，当前这一代的
    `liberty_sha256` 就不再能由源文件复现了。
    """
    spans = []
    for block_type in MERGE_BLOCK_TYPES:
        spans.extend((start, end) for _n, start, end in _block_spans(text, block_type))
    spans.sort()
    out = []
    cursor = 0
    for start, end in spans:
        if start >= cursor:              # 顶层块互不嵌套，正常走这一支
            out.append(text[cursor:start])
            cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _first_block_offset(text):
    """Offset of the base file's first template/cell block.

    Borrowed templates are spliced in here rather than right after
    `library (...) {`, so the base file's own header attributes (delay_model,
    technology, the unit declarations, operating_conditions) all stay ahead of
    them -- no need to bet on how tolerant the parser is about those.
    """
    offsets = [start
               for block_type in MERGE_BLOCK_TYPES
               for _name, start, _end in _block_spans(text, block_type)]
    if not offsets:
        raise ValueError("base liberty has no cell or template block")
    return min(offsets)


def merge_liberty(paths):
    """产物 MUST NOT 依赖 `paths[1:]` 的给出顺序。

    合并库的**内容哈希**是流程指纹的一项事实（`flow/flow_fingerprint.py` 的
    `liberty_sha256`）。顺序敏感意味着同一批源文件能产出两份哈希不同的库，
    把语义上同一个库判成两个不可比的流程代 —— 一次假分代，而分代机制的价值
    恰恰在于"不同代"这句话是可信的。2026-09-14 从 Mac 交接到 Linux 时撞上过：
    两份 `asap7sc7p5t_RVT_TT.lib` 字节数逐字节相同、sha256 不同。

    顺序自由度有两处，两处都要堵：

    1. **借来的块的拼接顺序** —— 按 `(块类型, 块名)` 排序。排序只发生在
       templates / cells 两个桶**内部**，「全部模板在前、全部 cell 在后」不动
       （那是 P-2）。liberty 里 cell 不引用 cell、模板不引用模板，桶内重排安全。
    2. **`paths[1:]` 之间同名块谁胜出** —— 去重是"首个出现的胜出"，而谁先出现
       由入参顺序决定。内容逐字相同时这无所谓（ASAP7 的 5 个 RVT/TT 源文件里
       6 个跨文件同名块内容全都相同）；**内容不同时当场报错**，不静默挑一份。
       按内容哈希取最小者之类的"确定性挑选"同样能让产物顺序无关，
       但"选了哪一份"对人不可见 —— 这个仓库防的正是静默错数。

       **基文件与其余文件之间的同名冲突不在此列**：基文件永远是 `paths[0]`，
       它胜出与 `paths[1:]` 怎么排无关，是确定的。这条既有取舍不动
       （`tests/test_merge_liberty.py::test_dedup_rule_unchanged`）。

    **基文件（`paths[0]`）自己的块保持原位逐字不动。** 它们留在 `body` 里，
    块与块之间还夹着属性与注释；重排就要把这些非块文本拆开重拼，那是 P-2 那一类
    的静默损坏风险，而假分代的来源只在借来的那部分。所以产物对 `paths[1:]` 的
    顺序免疫，对**基文件选谁**仍然敏感 —— 见 `docs/toolchain.md`「合并 liberty」（`--base` 给 SIMPLE 那份）。
    """
    base_text = open(paths[0]).read()
    last_brace = base_text.rindex("}")
    body = base_text[:last_brace]
    splice_at = _first_block_offset(body)

    # Dedup key is (block type, name), first occurrence wins. Content is kept
    # alongside so a later file redefining the same key with DIFFERENT content
    # can be refused instead of silently losing to whoever was passed first.
    seen = {}
    for block_type in MERGE_BLOCK_TYPES:
        for name, _block in _extract_blocks(base_text, block_type):
            seen[(block_type, name)] = None      # None = 基文件占用，确定性胜出

    borrowed = []
    for path in paths[1:]:
        text = open(path).read()
        for block_type in MERGE_BLOCK_TYPES:
            for name, block in _extract_blocks(text, block_type):
                key = (block_type, name)
                if key in seen:
                    incumbent = seen[key]
                    if incumbent is None:
                        continue             # 基文件胜出，与顺序无关
                    first_path, first_block = incumbent
                    if block != first_block:
                        raise ValueError(
                            f"{block_type} ({name}) 在 {first_path} 与 {path} 里"
                            f"内容不同。这两个都不是基文件，保留哪一份取决于给出"
                            f"顺序，产物会随入参顺序变化 —— 那会让同一批源文件"
                            f"产出两个不可比的流程代。合并前先确定该用哪一份。")
                    continue
                seen[key] = (path, block)
                borrowed.append((block_type, name, block))

    type_rank = {bt: i for i, bt in enumerate(MERGE_BLOCK_TYPES)}
    borrowed.sort(key=lambda item: (type_rank[item[0]], item[1]))

    borrowed_templates = [b for bt, _n, b in borrowed
                          if bt in TEMPLATE_BLOCK_TYPES]
    borrowed_cells = [b for bt, _n, b in borrowed
                      if bt not in TEMPLATE_BLOCK_TYPES]

    def joined(blocks):
        return "".join("\n" + b + "\n" for b in blocks)

    # templates ahead of every cell, cells appended after the base file's own
    merged = body[:splice_at] + joined(borrowed_templates) + body[splice_at:]
    merged += joined(borrowed_cells)
    merged += "\n}\n"
    return merged


def canonical_digest(text):
    """与块顺序无关的内容摘要：`(canonical, header, base)`。

    两份合并库的 sha256 不同时，唯一能问的问题是"不相等"，而那答不了
    **"是不是只差块的排列"**。2026-09-14 Mac 与 Linux 上那两份
    `asap7sc7p5t_RVT_TT.lib` 字节数逐字节相同、sha256 不同，就卡在这个问题上：
    liberty 的内容哈希是流程指纹的一项事实，判错了就是把同一个库拆成两个
    不可比的流程代，或者反过来把两个不同的库当成一个。

    分三项而不是一项，每一项回答一个不同的问题：

    - `canonical` —— 「块集合一样吗」。覆盖全部块（按 `(块类型, 块名)` 排序后
      逐块喂进哈希），与块在文件里的排列无关。
    - `header` —— 「头一样吗」。覆盖第一个块之前的那段：`delay_model`、单位
      声明、`operating_conditions` 都在那里，同样改变测量结果，只哈希块会漏掉。
    - `base` —— 「拿谁当的基文件」。覆盖块**之外**的全部文本（`header` 是它的
      前缀，再加上块与块之间的属性/注释和收尾）。合并时基文件的正文整段原样进
      产物，借来的块只贡献固定的换行分隔符，所以这一段只来自基文件。ASAP7 的五
      个家族文件各自带着自己的 `library (...)` 名（实测合并库里是
      `asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120`），这一项因此能把基文件认出来。

    ⚠️ `base` **不覆盖基文件自己的块** —— 在产物里基文件的块与借来的块无法区分。
    要区分就得往产物里塞标记，而那会改变合并库的字节：当前这一代的
    `liberty_sha256` 就不再能由源文件重新合并复现。基文件的块由 `canonical`
    覆盖，两项合起来仍然覆盖产物的每一个字节。

    ⚠️ **MUST NOT 当作 P-2 的判据。** 它复用 `_extract_blocks`，而用被测代码的
    解析函数去验证被测代码，测不出解析本身的偏差 —— 那是
    `tests/test_merge_liberty.py` 用独立正则的原因。这里的用法是**比较两份
    文件**：同一份解析器的偏差在两边抵消。"定义先于引用"仍由那个独立检查负责。
    """
    h = hashlib.sha256()
    for block_type in MERGE_BLOCK_TYPES:
        for name, block in sorted(_extract_blocks(text, block_type)):
            for part in (block_type, name, block):
                h.update(part.encode())
                h.update(b"\0")
    header = text[:_first_block_offset(text)]
    return (h.hexdigest(),
            hashlib.sha256(header.encode()).hexdigest(),
            hashlib.sha256(_skeleton(text).encode()).hexdigest())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output",
                    help="合并产物的输出路径（与 --canonical-hash 二选一）")
    ap.add_argument("--base", metavar="LIB",
                    help="基文件：它的正文整段原样进入产物（头部、delay_model、"
                         "单位声明、operating_conditions 都来自它）。必须显式给出")
    ap.add_argument("--canonical-hash", metavar="LIB",
                    help="打印这份 liberty 的与块顺序无关的内容摘要，不做合并")
    ap.add_argument("libs", nargs="*", help="其余源 liberty，给出顺序不影响产物")
    args = ap.parse_args()

    if args.canonical_hash:
        if args.output or args.base or args.libs:
            ap.error("--canonical-hash 只读一份库，不接受 -o / --base 或其他位置参数")
        canonical, header, base = canonical_digest(open(args.canonical_hash).read())
        print(f"canonical {canonical}")
        print(f"header    {header}")
        print(f"base      {base}")
        sys.exit(0)

    if not args.output:
        ap.error("合并需要 -o <输出>")
    if not args.base:
        # 位置参数里挑一个顶上会静默换一代记录：基文件决定产物的头部与
        # liberty_sha256，而挑错不会报错。所以这里宁可失败。
        ap.error("合并需要 --base <lib> 显式指定基文件。它的正文整段进入产物，"
                 "换一份就是另一个 liberty_sha256、另一代记录，而这件事不会报错 —— "
                 "所以不从位置参数里挑一个顶上")

    merged = merge_liberty([args.base] + args.libs)
    with open(args.output, "w") as f:
        f.write(merged)
    print(f"wrote {args.output}", file=sys.stderr)
