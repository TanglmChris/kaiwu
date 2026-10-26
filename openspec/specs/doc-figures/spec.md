# doc-figures Specification

## Purpose
TBD - created by archiving change drawio-figlib. Update Purpose after archive.

## Requirements

### Requirement: draw.io 图有进仓的作图库

仓库 MUST 提供 `flow/doc/figlib.py` 的作图类 `Fig`：方框、菱形、文字、连线与标题，配色与线型取 `docs/spec-writing.md` §6 的全仓约定，产出未压缩、`html=0` 的 `.drawio`。

理由：作图类原来放在会话 scratchpad，丢了（内部#227，用户 10-21 定由 kaiwu-flow 重写）。

#### Scenario: 画一张数据通路图

- **WHEN** 用 `Fig` 画一个 `kind="data"` 的方框并保存
- **THEN** 文件能被 XML 解析读回，方框填充色是 §6 的数据蓝

### Requirement: draw.io 导出带超时，挂住时杀整个进程组

`flow/doc/drawio_export.py <图.drawio> [<图.svg>]` MUST 用 draw.io 本体 `--no-sandbox` 导出 svg，在新进程组里跑；超时 MUST 杀掉整个进程组并以非 0 退出、写明挂住；导出后 svg 不存在或为空 MUST 失败。

理由：`drawio -x` 在 Claude Code 的 Bash 沙箱里会挂住，`perl alarm` 停不掉，因为 Electron 的子进程还占着管道（内部#227，spec 10-18）。

#### Scenario: 导出挂住

- **WHEN** draw.io 在超时内没有退出
- **THEN** `drawio_export.py` 杀掉整个进程组、以非 0 退出，写明挂住

### Requirement: draw.io 图有图元重叠检查

`flow/doc/drawio_overlap.py <图.drawio>…` MUST 报出同一页里部分相交的图元：形状与形状部分相交、文字与文字的字迹相交、文字的字迹跨在形状边上。形状完全包含另一个图元（容器）MUST NOT 报；style 带 `kaiwuOverlap=ok` 的图元 MUST NOT 报。有报出时 MUST 以非 0 退出，逐条列出页名与两个图元的文字。

理由：图元有没有压在一起，以前只能靠人眼看 png（内部#227）。

#### Scenario: 两个方框压在一起

- **WHEN** 一页里两个方框部分相交
- **THEN** `drawio_overlap.py` 以非 0 退出，点名这两个方框的文字

#### Scenario: 容器与故意的重叠

- **WHEN** 一个方框完整地画在另一个方框里，或跨边的标签带 `kaiwuOverlap=ok`
- **THEN** `drawio_overlap.py` 不报
