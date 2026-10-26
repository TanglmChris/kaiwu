## Context

**F1** — `fst2vcd` 的 usage 是 `[OPTION]... [FSTFILE]`，其 `-h` 明写
「VCD is emitted to stdout if output filename is unspecified」。
`flow/sim/run_sim.py:97` 把 FST 放在 `-o` 之前，BSD / macOS 的 getopt 因此在第一个
非选项参数处停止解析，`-o <vcd>` 不被识别为选项。
Basis: 2026-09-13 `fst2vcd --help` 输出，加上两种参数顺序的对照实测——
文件在前时退出码 0 且**不生成文件**，`-f` 在前时退出码 0 且生成 16770 字节的 VCD。

**F2** — 故障不在出错点浮现：`run_sim` 返回未核实的 `vcd_path`，
`scripts/run_experiment.py:56` 把它交给 `flow/sim/vcd_stats.py:20` 的 `VCDVCD()`，
用户看到的是 `vcdvcd` 内部的 `FileNotFoundError`。
Basis: 2026-09-13 `make -f flow/Makefile exp DESIGN=adder32 ...` 的实际 traceback。

**F3** — `flow/` 下另外两处调外部工具的地方（`flow/synth/synth.py:91` 的 yosys、
`flow/sta/run_sta.py:101` 的 OpenSTA）**都没有**显式断言产物存在，但两者都在检查
退出码之后**立刻读取**产物（`stats_json.read_text()` / `results_json.read_text()`），
因此缺文件会在使用点当场失败，且它们的 `RuntimeError` 已经带上日志路径。
`flow/equiv/run_equiv.py` 不产出文件。
Basis: 2026-09-13 通读这三个文件的相应段落。

**F4** — 这个缺陷在用户主力机器上**未曾暴露**：`results/experiments.jsonl` 有 392 条
记录，说明那里的 `fst2vcd` 调用是通的。本机装的是 oss-cad-suite 20260913。
Basis: 记录数为实测；主力机器的工具版本无法在此核实。

## Goals / Non-Goals

**Goals:**

- 让 `fst2vcd` 真的产出 VCD。
- 让「产出失败」在**它发生的那一段**失败，带上足以定位参数误解的信息。
- 把「不得报告没有产出的产物」写成契约，使同类问题在别处被写出来时有判据可依。

**Non-Goals:**

- **不给 `synth.py` / `run_sta.py` 加断言**。按 F3，它们当前的行为不构成同一个缺陷；
  铺开去改属于扩大范围，而且会让本变更的验收对象变得模糊。
- 不改 `fst2vcd` 的选择（不换 gtkwave 之外的工具）。
- 不产生任何实验记录。

## Decisions

**D1** — 用 `-f <fst> -o <vcd>` 而不是 `-o <vcd> <fst>`。
Basis: 两种都能让选项先于位置参数，但 `-f` 是 `fst2vcd` 明确提供的输入选项
（`-f specify FST input filename`），全选项形式不依赖「位置参数在末尾」这一约定，
将来即使 usage 变化也更稳。

**D2** — 断言产物存在时，错误信息 MUST 带上 `fst2vcd` 的 stdout/stderr。
Basis: F1 的根因是参数被误解，而那个信息只存在于工具的输出里（VCD 内容本身被
打到了 stdout）。只报「文件不存在」会把读者引向「仿真没产出波形」这个错误方向——
这正是本次实际发生的事。

**D3** — 新 Requirement 挂在 `experiment-trust` 而不是 `guardrail-scope`。
Basis: `guardrail-scope` 管的是**检查**的诚实（退出码与覆盖摘要）；这条管的是
**流程产物**的诚实，与 `experiment-trust` 已有的「缺少必需输入时必须报出真正的原因」
是同一条原则的两端，放在一起才能被一起读到。

**D4** — 回归测试用**桩 `fst2vcd`**，不依赖真实工具。
Basis: 要测的是「工具以 0 退出但没产出文件时，本段是否失败」。用真工具无法构造
这个输入；桩既能构造，又让测试在没装工具链的机器上也能跑
（与 `tests/test_fast_check.py` 的桩 iverilog 同一思路）。

## Hidden Knowledge / Assumptions

**A1** — 假设主力机器上修复后的写法同样有效。`-f <fst> -o <vcd>` 是 `fst2vcd`
文档化的全选项形式，在 getopt 会重排参数的平台上同样成立（重排只影响能否识别，
不影响已经正确排列的参数）。
Basis: F1 的 usage 文本；无法在此实测主力机器。
Owner: 本变更的验收 —— 修复后在本机端到端跑通一次实验即为证据；
主力机器上若有异常会在下次跑扫参时立即暴露（VCD 缺失现在会当场失败）。

## Coupled Iteration Contract

不适用。

## Risks / Trade-offs

| 风险 | 后果 | 缓解 |
|---|---|---|
| 主力机器上 `-f` 形式不被支持 | 那边的流程反而坏掉 | A1 的依据是文档化的选项；且修复后失败是**当场**且带工具输出的，不会再延后误导 |
| 只修一处，另两处留着同样的形状 | 将来在别处重现 | F3 说明另两处不构成同一缺陷；新 Requirement 提供了判据，下次写出来时有依据挡 |
| 断言过严，把正常情况挡住 | 流程跑不动 | 断言的条件只是「约定的产物存在」，与成功路径完全一致 |

## Open Questions

None.
