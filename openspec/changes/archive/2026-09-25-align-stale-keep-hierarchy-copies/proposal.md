## Why

保层级的意图 2026-09-21 从 RTL 搬进了流程（`move-keep-hierarchy-from-rtl-into-the-synthesis-flow`，内部#46 的 2.2）：
RTL **不许**带 `(* keep_hierarchy *)`，意图由 `params.yaml` 的 `tops:<顶层>:synth:keep_hierarchy:` 声明、
由综合流程施加。那次变更改了 `rtl-structure-authority` 与 `flow-parameterization`，但
**`experiment-trust` 的两条 Requirement 仍然要求「在 building block 上标注 `(* keep_hierarchy *)`」**，
`openspec/config.yaml` 的 context 也还这么写 —— 两份权威文本现在互相矛盾，照着旧的那份做会被
`fast_check` 当场拦下。这是 内部#58 的 B1（同一个坑写 5–6 份）真实造成的损害：副本没跟上。

## What Changes

- `experiment-trust` 的两条 Requirement 把「标注 `(* keep_hierarchy *)`」改成「由该顶层 `params.yaml` 声明、
  由综合流程施加」，并**引用** `flow-parameterization` 那条而不复述它；排查入口同步改。
  顺带去掉指向已不存在的 `CLAUDE.md`「综合坑」一节的引用，改指 `docs/pitfalls.md` 的 P-3。
- `openspec/config.yaml` 的 context 同步改，并更正两条本机已不成立的环境描述（direnv 自动 source、uv 管理）。

## Capabilities

### New Capabilities

### Modified Capabilities
- `experiment-trust`: 「功能等价的微架构取值必须产出可区分的网表」与「枚举流水深度的设计必须让各取值面对同一份组合切分」
  两条里保层级的**施加方式**（契约本身——不 flatten、切分点保住层级——不变）。

## Impact

纯文本对齐，不动代码、不动 RTL、不换代、不碰 `results/experiments.jsonl`。
