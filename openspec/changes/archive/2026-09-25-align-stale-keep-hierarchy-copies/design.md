## Context

`move-keep-hierarchy-from-rtl-into-the-synthesis-flow`（2026-09-21）把保层级从 RTL 搬进流程，
改了 `rtl-structure-authority` 与 `flow-parameterization`，没有改 `experiment-trust` 与
`openspec/config.yaml` —— 于是两份权威文本说法相反。

## Decisions

- D1: 只改施加方式与排查入口，**不改契约**（不 flatten、切分点保住层级、可区分网表的判据）。
  Basis: 契约本身没有变过，变的只是意图写在哪。
- D2: 两条 Requirement 改成**引用** `flow-parameterization` / `rtl-structure-authority` / P-3 / P-15，
  不复述施加细节。Basis: `knowledge-placement` 的第一条 Requirement；复述正是这次失效的成因（内部#58 的 B1）。

## Risks

无代码与测量影响：不动 `METRIC_MODULES`、不换代、不碰 `results/experiments.jsonl`。
