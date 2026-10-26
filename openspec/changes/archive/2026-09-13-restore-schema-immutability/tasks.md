## 1. 让红线 2 在规格层完整落地

- [x] 1.1 在 `experiment-record` 补上「字段集合只能单调增长」，并从 `flow-parameterization` 移除那条惰性 Requirement
  - Covers:
    - experiment-record / 实验记录的字段集合只能单调增长
    - experiment-record / 实验记录的字段集合只能单调增长 / 一次变更给记录加了新字段
    - experiment-record / 实验记录的字段集合只能单调增长 / 一次变更试图给已有字段改名
    - experiment-record / 实验记录的字段集合只能单调增长 / 一次变更试图删除已有字段
    - D1（落点是 experiment-record，非 experiment-trust）
    - D2（只说单调性，不复述「不回填、不改写」）
    - D3（删除而非改写惰性条文）
    - F1（那条 Requirement 当前不禁止任何事）
    - F2（红线 2 的四项里，规格层只落地了后两项）
  - Touch:
    - openspec/specs/experiment-record/spec.md
    - openspec/specs/flow-parameterization/spec.md
  - Verify:
    - Strategy: evidence-first
    - Reason: 产出是两份规格文本的增删。规格不执行，没有任何行为能先失败；正确性由「红线 2 四项逐项可追溯到 Requirement」与「无重复表述」两个可检索的事实建立，而不是由红绿循环建立。
    - M1: 把 `CLAUDE.md` 红线 2 的四项（只增字段 / 不改名 / 不删 / 不回填不重写历史行）逐项在 `openspec/specs/` 中定位到承载它的 Requirement，四项全部有着落，零缺口
    - M2: `flow-parameterization` 的 Requirement 数由 6 降为 5，且其中不再出现 `results/experiments.jsonl` 字样；`experiment-record` 由 6 升为 7
    - M3: 新 Requirement 未复述 `experiment-record`「已有记录必须保持可读」的内容——全仓检索「不得被回填或改写」类表述，权威出处仍只有一处
    - M4: `keel openspec validate --specs --strict` 全部通过，且 `results/experiments.jsonl` 逐字节未变
  - Evidence:
    - Contract: keel-task-capsule/v1 sha256:bba6857df8e403af2fec1d6a5d5959a86edf5283f27fcb6d16a11a5a9148c536
    - M1: 红线 2 四项逐项定位，四项全部有着落且**同在一份 spec 内**——「只增字段」→ `experiment-record` 的「任何变更 MAY 新增字段」；「不改名」→「MUST NOT 被改名」；「不删」→「MUST NOT 被删除」；「不回填不重写历史行」→「已有记录 MUST NOT 被回填或改写」。四条 grep 全部只命中 `openspec/specs/experiment-record/spec.md`，缺口 0。
    - M2: `flow-parameterization` 的 Requirement 由 6 降为 5，`experiment-record` 由 6 升为 7。**该检查的第三个条件在授权时写错了**：原文要求 `flow-parameterization` 中「不再出现 `results/experiments.jsonl` 字样」，但该 capability 讲自己的主题时本就要引用这个文件（「参数取值必须原样落进实验记录」第 56 行、`sweep: false` 的动机第 95 行），两处均与 schema 保护无关。按真实判据复核：剩余 5 条 Requirement 标题全部是参数主题（params.yaml 驱动 / 取值落记录 / 仿真配置由设计声明 / 不参与扫参 / 省略取值），无一条是 schema 保护，惰性条款已完全移除。
    - M3: 全仓检索「MUST NOT 被回填或改写」，`openspec/specs/` 下命中 1 处（`experiment-record/spec.md:54`），权威出处仍唯一。新 Requirement 在需要提及回填时写的是「回填本身已被『已有记录必须保持可读』禁止」，是引用而非复述，符合 D2 与 knowledge-placement 第一条。
    - M4: `keel openspec validate --specs --strict` → `Totals: 7 passed, 0 failed`（余一条 INFO 是 knowledge-placement 首条 Requirement 超 500 字符，与本变更无关）。`results/experiments.jsonl` 的 md5 为 `4dead2d29e5db9bf462571634578ed3c`，与任务开始前的基线逐字相同，`git diff --numstat` 对该文件输出 0 行。
    - Review:
      - Status: pass
      - Acceptance check: M1 证明 E1（红线 2 四项在规格层完整落地）且四项同处一份 spec，读者不会只看到半条；M3 证明 E2（不产生重复表述）；新 Requirement 的第一个 Scenario 要求「新增字段被允许」，证明 E3（约束没写过紧）；M4 证明 E4（记录一行未动）。
      - Scope check: 仅修改 Touch 列出的 2 份 spec。`results/experiments.jsonl` 的 md5 未变，未触碰任何流程代码。
      - Findings: M2 的第三个条件在授权时被我写成了不可满足的形式——要求一个以「参数取值必须原样落进实验记录」为己任的 capability 完全不提 `results/experiments.jsonl`。已按真实判据（无 schema 保护类 Requirement 残留）复核通过，并在 M2 的证据里写明原措辞错在哪，而不是悄悄换一个标准。Resolved here: M2 —— 该检查的证据里写明了原措辞、错因与替代判据，并逐条列出剩余 5 条 Requirement 的标题供复核。
    - Blocker: none
    - Reauthorizations: none

## Invalidates

- I1: "本次变更 MUST NOT 新增、改名或删除 `results/experiments.jsonl` 中的任何字段，也 MUST NOT 改写任何已有记录。" — `openspec/specs/flow-parameterization/spec.md` 的「实验记录的 schema 在本次变更中不得改变」。Updated by: 1.1
- I2: "`results/experiments.jsonl` 中原有的 10 行内容逐字节不变" — 同一条 Requirement 的 Scenario；该文件现有 392 行。Updated by: 1.1
- I3: "改成无时态的表述（比如「任何变更」），或者把它整条挪到 `experiment-trust` spec 下 —— 那里才是这条约束的归属。" — issue 内部#10（内部#10） 正文；该建议源自 `FOLLOWUP.md` 第 10 条（内容截至 2026-09-04），当时 `experiment-record` 尚不存在（F3），落点结论已按 D1 改为 `experiment-record`。Durable owner: 内部#10
- I4: "| 待办 10 | `flow-parameterization` 的措辞失效 | [内部#10](…) |" — `docs/data-credibility.md` 的迁移对照表。Discard reason: 该行陈述的是「待办 10 去了 内部#10」这一迁移事实，本变更不改变它；内部#10 本身的开闭状态由其自身承载。

## Expectation Coverage

- E1: `CLAUDE.md` 红线 2 的四项在 `openspec/specs/` 中逐项有对应 Requirement Covered by: 1.1
- E2: 不产生重复表述——「不回填、不改写」的权威出处仍唯一（D2 与 knowledge-placement 第一条） Covered by: 1.1
- E3: 新增字段仍然被允许，约束没有写过紧（A1） Covered by: 1.1
- E4: `results/experiments.jsonl` 一行不动 Covered by: 1.1
- E5: 这条约束是否要变成可执行门禁（Q1）——本变更明确不做 Durable owner: 内部#16
