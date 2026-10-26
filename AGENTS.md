<!-- keel:start version=5.203.0 -->
## Keel Bootstrap

- Start every session with `keel context`; OpenSpec artifacts and Git are the durable authority, and memory or transcripts may only inform.
- Memory: write only what the next session would get wrong without it and the repository cannot answer, never a one-off slip; one fact per entry. Recheck it after a fix, at a release, and at a shift change.
- Obey the selected task capsule: `keel gate task-start` before implementing, `--record` its fingerprint to Evidence `Contract`, which `task-complete` requires, before checking complete. Touch bounds product writes; the change's own dir is exempt. On Claude a passing `task-start` guards it by default (`--no-guard` opts out).
- Work through an approved `tasks.md` in order, each task through its own gates. A subagent is the model's choice and is treated as the main agent is. No commit, push, sync, or archive unless the task, the owner, or `keel/config.yaml` authorizes it.
- Route Full (the OpenSpec flow) for new features, interface or protocol changes, cross-module work, or over ~3 files / 100 lines; Lite for local fixes with no interface change. No gate checks routing; a project corrects the size bar with `full_mode_paths:` in `keel/config.yaml`, which `keel context` reports.
- SessionStart projections are disposable views, never authority; without the plugin, run the commands by hand.
- Keel skills and hooks come from the `keel` native plugin (`codex plugin add` / `claude plugin install`); `keel --init` owns only the OpenSpec schema, overlays, and this bootstrap.
<!-- keel:end -->

## 项目路由政策

Claude（经 `CLAUDE.md` 的 `@AGENTS.md`）与 Codex 读的是这同一节。它是项目特例：与上面 Keel 通用规则冲突时以本节为准，本节没写到的按通用规则。细则与例子在 `docs/commands.md`「路由、零差异任务、设计内部改动」。

1. **默认 Lite。** 必走 Full 的只有两类：改实验记录（`results/<设计根>/experiments.jsonl`）的 schema（只增字段，见 `CLAUDE.md` 红线 2），与改测量口径（任何会换代的改动）。能按路径认出的已列在 `keel/config.yaml` 的 `full_mode_paths:`，认不出的要自己认（内部#16）。
2. **设计内部的改动不开 OpenSpec change**：只动 `designs/<根>/` 或 `cbb/<目录>/` 下的 RTL、TB、设计文档，不改 flow、不改记录口径的，改文档 + commit 即可（内部#58）。交付证据照样要能找到：规格基线（定稿提交号）、改动范围、验证结果、交付提交，写进该设计的 issue 与 `doc/track.<顶层>.md`。
3. **OpenSpec change 留给** flow、记录 schema、测量口径与仓库契约（内部#58）。
4. **零差异类任务**（重构、搬家、声称不改数字的换代）用 `Strategy: equivalence`，判据是 `scripts/pair_generations.py` 逐设计退出 0（内部#59）。
