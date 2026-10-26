## 1. 对齐

- [x] 1.1 `experiment-trust` 两条与 `openspec/config.yaml` 的 context 改成「params.yaml 声明、流程施加」
  - Covers:
    - experiment-trust / 功能等价的微架构取值必须产出可区分的网表
    - experiment-trust / 枚举流水深度的设计必须让各取值面对同一份组合切分
  - Touch:
    - openspec/config.yaml
  - Verify:
    - Strategy: evidence-first
    - Reason: 纯文本对齐，没有可先失败的行为；判据是「再也没有权威文本要求把属性写进 RTL」。
    - M1: `grep -rn '(\* keep_hierarchy \*)' openspec/config.yaml openspec/changes/align-stale-keep-hierarchy-copies/specs` 的每一处命中都**不是**「在 RTL 里标注」的要求；`keel openspec validate align-stale-keep-hierarchy-copies` 通过
    - M2 (regression): `./scripts/fast_check.sh` 与 `pytest tests/ -n auto -m 'not flow'` 全绿 —— 不动代码，应当原样绿
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:37e0c39be3dde5c0b03b00585ff4a97ff6bbc72dd82cbd8cd5b992c00de1cfca
    - M1: `grep -rn '(\* keep_hierarchy \*)' openspec/config.yaml openspec/changes/align-stale-keep-hierarchy-copies/specs` 零命中（rc=1）—— 两处要求都改成了「params.yaml 声明、流程施加」并引用 `rtl-structure-authority` / `flow-parameterization` / P-3 / P-15。`keel openspec validate align-stale-keep-hierarchy-copies`：`Change 'align-stale-keep-hierarchy-copies' is valid`。
    - M2: `./scripts/fast_check.sh` rc=0；`pytest tests/ -q -n auto -m 'not flow'` `226 passed in 7.36s`。
    - Review:
      - Status: pass
      - Acceptance check: 契约本身（不 flatten、切分点保住层级、可区分网表的判据）一字未动，只改了「怎么施加」与排查入口；两条都改成**引用**权威出处而不复述（knowledge-placement 的第一条）。
      - Scope check: 产品写入只有 Touch 里的 `openspec/config.yaml`；其余都在本变更目录内。顺带更正了 config context 里两条本机已不成立的环境描述（uv、direnv），属 I3。
      - Findings: none
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "设计 SHALL 通过在关键 building block 上标注 `(* keep_hierarchy *)`" — `openspec/specs/experiment-trust/spec.md` 两条 Requirement。Updated by: 1.1（delta spec，归档时落进主 spec）
- I2: "在关键 building block 模块上标 `(* keep_hierarchy *)`" — `openspec/config.yaml` 的 context 第 2 条。Updated by: 1.1
- I3: "进仓库目录时 direnv 自动 source ~/tools/env.sh 并激活 .venv" / "uv 管理" — `openspec/config.yaml` 的 context。Updated by: 1.1
- I4: "(* keep_hierarchy *)" — `docs/pitfalls.md`（P-3 的 2026-09-08 实测）、`flow/equiv/run_equiv.py` 模块头（冻结件仍可能自带属性）、`openspec/changes/archive/` 里的旧 change。Discard reason: 它们说的是历史或冻结件，不是「现在该怎么写 RTL」的要求。

## Expectation Coverage

- E1: 不再有两份权威文本对「保层级怎么施加」说法相反 Covered by: 1.1
