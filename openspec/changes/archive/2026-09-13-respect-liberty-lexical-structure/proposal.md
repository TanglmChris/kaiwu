## Why

`flow/synth/merge_liberty.py` 的 `_extract_blocks` 是「正则定位块头 + 手工数花括号」，
数花括号时**不认识 liberty 的词法结构** —— 字符串字面量里的 `{` 和 `/* */` 注释里的
`{` 一样被计入深度。

2026-09-13 实测（`<scratchpad>/i19/probe.py`）：

```
cell (BUF) {
  pin (Y) { function : "A { not a brace"; direction : output; }
}
cell (INV) { area : 2.0; }
```

`_extract_blocks(text, "cell")` 对 `BUF` 返回的块**吞掉了整个 `cell (INV)` 和
`library` 的收尾花括号**，而 `INV` 又被单独抽出来一次。合并产物里于是会出现
重复的 cell 和多余的花括号。

**失效方式是本仓库的标准形状**：`_extract_blocks` 不报错，`merge_liberty` 不报错，
产出一个语法坏掉或内容重复的 liberty；下游 `read_liberty` 对坏块的处理历来是
**警告一句、丢掉、继续** —— 而 2026-09-09 那次翻车（`delay_template_7x7` 定义在
引用之后，OpenSTA 丢掉全部 `CLK→Q` 弧）证明了这条路径上丢东西有多难发现。

ASAP7 里目前没有这种写法（引自 内部#19，
本机无 `~/pdk`，无法复核）。换 PDK 就可能踩到。

## What Changes

- **`_extract_blocks` 改用一个尊重 liberty 词法结构的扫描器**：数花括号时跳过
  双引号字符串（含 `\` 转义）与 `/* */` 注释。
- **块头的定位同样走这个扫描器**：正则 `\n(\s*cell\s*\(...\))` 会匹配注释里或
  字符串里的 `cell (...)`，那是同一个病的另一面。
- **加回归测试**：字符串里的 `{`、注释里的 `{`、以及注释里伪装成块头的 `cell (...)`。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `experiment-trust`: 「合并出来的 liberty 必须自洽」新增一条关于**块边界识别**的
  要求与 Scenario —— 合并工具切出来的块边界必须与 liberty 的词法结构一致。

## Impact

| 文件 | 动作 |
|---|---|
| `flow/synth/merge_liberty.py` | `_extract_blocks` 重写为词法感知的扫描 |
| `tests/test_merge_liberty.py` | 新增三个回归用例 |

**不受影响**：`results/experiments.jsonl`、已经生成的合并库（本变更不重新生成，
本机也没有 `~/pdk`）、`flow/sim`、`flow/sta`。

**为什么走 Full**：改的是合成综合库的那一步。综合库是 `flow` 指纹里的一项事实，
它坏了会让**全部**数字整体挪位，而坏法是静默的 —— 正是 `keel/lenses/hardware.md`
说的「a wrong number is the more likely failure than a wrong circuit」。
