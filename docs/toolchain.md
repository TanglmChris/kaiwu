# 工具链与 PDK

本机环境事实。**不放契约**（契约在 `openspec/specs/`）、**不放坑**（坑在 `docs/pitfalls.md`）。

**本文件是索引**（内部#336 按主题拆开）：条文在 `docs/toolchain/` 下各文件。原来每一节的标题都在下面，写明在哪个文件；别处写「`docs/toolchain.md`「某节」」的，按节名在这里查。新条文写进对应主题的文件，不写在这里。

## [`docs/toolchain/tools.md`](toolchain/tools.md)：工具路径与最低版本

- 工具路径
  - 工具最低版本（内部#260）

## [`docs/toolchain/pdk.md`](toolchain/pdk.md)：PDK（ASAP7）、合并 liberty、换 PDK

- ASAP7 的几个事实
  - 哪些子模块拉了、哪些没拉
- 合并 liberty
  - 这份合并库是哪一份
  - 判定两份合并库是不是只差排列
  - 其他 Vt/corner 实测过了（2026-09-20）
- 换 PDK 时要一起改的地方

## [`docs/toolchain/equiv.md`](toolchain/equiv.md)：等价证明器的并行度

- 等价证明器的并行度：`-j` 该给多大（2026-09-21 实测）

## [`docs/toolchain/worktree.md`](toolchain/worktree.md)：并行开发：一个模块一个 worktree（建 / 跑 / 合并）

- 并行开发：一个模块一个 worktree
  - 建
  - 跑
  - 合并

## [`docs/toolchain/collaboration.md`](toolchain/collaboration.md)：推送、授权、共享资源与换班（原「设计与验证分属两个 worktree」一节）

- 设计与验证分属两个 worktree（内部#79）
  - 规格评审（内部#114、内部#115）
  - 发布 → 验证 → 交付 → 集成 → 出口（内部#80、内部#300）
  - 需要并行：本会话拉 subagent（内部#418，用户 2026-10-25；取代 10-04 的主会话 / 子会话）
- 集成期的过渡端口表（内部#119）

## [`docs/toolchain/sta-decl.md`](toolchain/sta-decl.md)：STA 的时钟与静态端口声明

- 同周期的第二个时钟（门控时钟，内部#138）
- 静态端口排除在时序分析之外（内部#154）

## [`docs/toolchain/regress.md`](toolchain/regress.md)：回归、扫参组合与逻辑级数

- 自检型 TB 的分层回归（内部#83）
- 扫哪些组合：叉乘、exclude、sweep_points（内部#138、内部#214）
- 不写记录地量逻辑级数（内部#111）

## [`docs/toolchain/external-cli.md`](toolchain/external-cli.md)：调用外部模型 CLI

- 调用外部模型 CLI（自己跑 / codex / dsh，由会话自选）

## [`docs/toolchain/disk.md`](toolchain/disk.md)：磁盘使用

- 磁盘使用（内部#173）

## 不是标题、但别处按名字引用的条目

- 「CPU 预算」→ `docs/toolchain/worktree.md`
- 「推 main 前的硬清单」→ `docs/toolchain/collaboration.md`
- 「两种省法」→ `docs/toolchain/collaboration.md`
- 「推送、授权与共享资源」→ `docs/toolchain/collaboration.md`
- 「常备授权」→ `docs/toolchain/collaboration.md`
- 「阶段整理」→ `docs/toolchain/collaboration.md`
- 「换班」→ `docs/toolchain/collaboration.md`
- 「时序验收」→ `docs/toolchain/regress.md`
