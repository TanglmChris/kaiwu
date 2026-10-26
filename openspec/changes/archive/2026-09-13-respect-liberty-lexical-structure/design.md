## Context

**F1** — 实测复现。对

```
cell (BUF) {
  pin (Y) { function : "A { not a brace"; direction : output; }
}
cell (INV) { area : 2.0; }
```

`_extract_blocks(text, "cell")` 给 `BUF` 返回的块长 137 字符，**吞掉了整个
`cell (INV)` 与 `library` 的收尾花括号**；`INV` 随后又被单独抽出一次。
Basis: 2026-09-13 `<scratchpad>/i19/probe.py` 的输出。

**F2** — 同一个病的另外两面，源码里同样没有防护：
(a) `/* … { … */` 注释里的花括号一样被计入深度（`merge_liberty.py:44-47` 只看
字符本身）；(b) 块头用正则 `\n(\s*<type>\s*\(([^)]*)\))` 定位
（`merge_liberty.py:37`），注释里或字符串里出现 `cell (FOO)` 就会被当成块头。
Basis: 通读 `flow/synth/merge_liberty.py:34-52`。

**F3** — ASAP7 当前不触发。
Basis: 引自 内部#19，
**本机无法复核**（`~/pdk` 不存在）。

**F4** — 后果是静默的。`_extract_blocks` 的块被 `merge_liberty` 原样拼进产物，
边界错了就是重复的 cell 加多余的花括号；而 liberty 解析器对坏块的历来做法是
警告一句、丢掉、继续 —— 2026-09-09 那次 `delay_template_7x7` 的事故
（OpenSTA 丢掉全部 `CLK→Q` 弧、每个流水设计都把「输入→第一级触发器」报成关键路径）
就是这条路径上的先例。
Basis: `merge_liberty.py` 的模块 docstring 与 `docs/data-credibility.md` 的 D-2。

**F5** — `tests/test_merge_liberty.py` 的校验函数 `check_definition_before_use`
刻意**不复用** `_extract_blocks`，用独立正则扫产物。所以本次改 `_extract_blocks`
不会让既有断言跟着一起错 —— 它们仍是独立的第二双眼睛。
Basis: 该文件的模块 docstring 与实现。

## Goals / Non-Goals

**Goals:**

- 块边界与 liberty 的词法结构一致：字符串与注释里的花括号不算数。
- 块头不会在注释或字符串里被误认。
- 上述两点由回归测试覆盖，而不是靠"ASAP7 里没有这种写法"。

**Non-Goals:**

- **不写完整的 liberty 解析器**。只处理决定块边界的两件事：双引号字符串与
  `/* */` 注释。liberty 的其余语法（属性、复合值、`define`）与块边界无关。
- 不重新生成任何合并库（本机没有 `~/pdk`，且重新生成会改 `liberty_sha256`、
  让全部新记录换代 —— 那是独立决策）。
- 不改 `_first_block_offset` 用 `text.index(块文本)` 反查偏移的写法（可读性尚可，
  且块内容现在是逐字正确的，反查唯一的风险是重复块，而重复块正是本变更消除的）。

## Decisions

**D1** — 用一个扫描器同时处理三件事：数花括号、跳过字符串、跳过注释；块头的定位
也走它，而不是继续用正则在原文里搜。
Basis: F2 —— 三者是同一个词法问题的三个面。分开修会留下"引号防住了、注释没防住"
这种半成品，而半成品在这里等于没修：产物照样坏，照样静默。

**D2** — 字符串只认双引号，转义只认 `\`。
Basis: liberty 的字符串就是双引号包起来的，`function : "A & B"` 是最常见的形态。
不去猜单引号或其他转义规则 —— 猜出来的规则没有依据，且会让扫描器对合法输入
产生新的错判。

**D3** — 只认 `/* */`，不认 `//`。
Basis: liberty 的注释是 C 风格的 `/* */`。`//` 在 liberty 里不是注释，
把它当注释会把合法内容整行吃掉。

**D4** — 回归测试用**合成的最小 liberty**，不依赖 ASAP7。
Basis: F3 —— ASAP7 里根本没有这种写法，拿它当输入测不出任何东西；而本机也没有
`~/pdk`。要测的输入必须专门构造。

## Hidden Knowledge / Assumptions

**A1** — 假设 liberty 里不会出现未闭合的字符串或注释。真出现时扫描器会一路扫到
文件末尾，块边界依然是错的，只是错法不同。
Basis: 未验证。
Owner: 不为它加防护 —— 未闭合的字符串是源文件本身坏了，那时任何解析器都会出错，
而本变更的目标是"合法输入不被算错"，不是"非法输入也要救回来"。

## Coupled Iteration Contract

不适用。

## Risks / Trade-offs

| 风险 | 后果 | 缓解 |
|---|---|---|
| 新扫描器对 ASAP7 的行为与旧的不同 | 已生成的合并库与将来生成的不一致 | 既有三个用例（模板顺序、去重规则、单一 library 块）都跑在合成 liberty 上并保持绿；ASAP7 本身不含触发条件（F3），行为应当逐字相同，但**本机无法复核** |
| 只处理字符串与注释，不是完整解析器 | 还有别的词法结构能骗过它 | Non-Goal 已写明范围；liberty 里能影响花括号配对的就这两样 |
| A1（未闭合的字符串/注释） | 块边界仍然错 | 那是源文件坏了；不为它加防护，理由记在 A1 |
