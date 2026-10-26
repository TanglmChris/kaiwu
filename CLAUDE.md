@AGENTS.md

# kaiwu

RTL 设计 + PPA 优化实验项目：每个设计参数化实现，跑通 仿真 → 综合 → STA/功耗 全链路，
结果结构化记录进每个设计根的 `results/<设计根>/experiments.jsonl`（本仓从空记录起步，跑第一条实验时生成），
攒够后做「本地开源工具流 vs 外部参考工具流」的偏差分析。

**本文件只是索引。** 除了下面那五条红线，不要往这里写知识 —— 各有归属，见下表。

## 去哪里找

| 要找的东西 | 在哪 |
|---|---|
| 执行纪律、gate、任务契约、Full/Lite 路由 | `AGENTS.md`（keel 权威 + 项目路由政策）+ `keel/lenses/hardware.md` |
| 从零跑起来 | `docs/quickstart.md` |
| **命令全集、跳过开关的完整口径、路由与零差异任务细则** | `docs/commands.md` |
| 契约：仓库布局 / 记录 schema / 打分 / 可信度 | `openspec/specs/*/spec.md`，`keel openspec list --specs` |
| **踩坑清单**（症状 + 判据命令 + 修复） | `docs/pitfalls.md` |
| 工具路径、PDK、合并 liberty、多模块并行开发、调用外部模型 CLI | `docs/toolchain.md`（索引）与 `docs/toolchain/` |
| **组织与分工**：角色、命名 `kaiwu-<能力>-<ip>`、协作规则、找负责人拍板 | `team/README.md` |
| 能力镜像（规格 / 设计 / 验证 / 评审 / 报告的职责、交接、禁区） | `team/roles/kaiwu-<能力>/README.md` |
| PM 拉 team（开 issue → 建 worktree 绑角色 → 冷启动 → 回收） | `team/pull-team.md` |
| **读记录的口径**（【降级】哪批不可用、【读法】怎么跨分界读） | `docs/data-credibility.md` |
| RTL 结构选型的资料卡 | `knowledge/README.md`，写作约定 `knowledge/CLAUDE.md` |
| **规格怎么写**（黑盒原则、位序、接口规则、LRS 各节、draw.io 图） | `docs/spec-writing.md` |
| 某个设计的需求、方案、验证 | 专用设计 `designs/<根>/{lrs,lld,verify}.<顶层>.md`（模板 `flow/templates/design-root/`）；通用构件 `cbb/<目录>/{spec,verify}.<顶层>.md`（模板 `flow/templates/cbb-root/`）—— 根名小写、顶层名大写 |

## 五条红线

这个项目最容易翻车的不是「跑不通」，是**「跑通了但数字不可信」** —— 门禁查不出来。

1. **报任何 PPA 数字之前，过一遍 `docs/pitfalls.md` 的判据列。** 换库 / 换 PDK /
   改 flow 之后尤其必须。
2. **实验记录 `results/<设计根>/experiments.jsonl` 只增字段**，不改名、不删、不回填、不重写历史行 ——
   契约在 `openspec/specs/experiment-record/spec.md` 的「实验记录的字段集合只能单调
   增长」与「已有记录必须保持可读」。**改它必须走 Full 模式** —— 由 `keel/config.yaml`
   的 `full_mode_paths:` 声明，`keel --doctor` 的「Full/Lite routing」一节可查。
3. **记录实验前先提交** —— 记录里的 `git_commit` 来自 `git rev-parse HEAD`，
   工作区脏着跑出来的 provenance 是错的（P-7）。
4. **指纹不同的记录不能横向比较**，跨代差异可以到数量级（P-8）。
5. **动态功耗必须由 VCD/SAIF 反标算出**，不接受无活动率的静态估算（P-5）。

## 常用命令（全集见 `docs/commands.md`）

```
keel context          # 现在该做什么（扛 /clear 和 compaction）
keel --doctor         # 体检
./scripts/fast_check.sh   # ~10 s：elaborate + lint + Python 编译
.venv/bin/python3 -m pytest tests/ -q -n 4 -m 'not flow'   # 内循环；不用 -n auto
make -f flow/Makefile exp    DESIGN=CBB_FIFO PARAMS="…"     # 参数给全；或 POINT=<点名>
make -f flow/Makefile sweep  DESIGN=CBB_FIFO                # JOBS 默认 1（有意的）
make -f flow/Makefile report DESIGN=CBB_FIFO                # 独立命令，绝不是实验的副作用
```

## 容易误用的开关

- **`SKIP_EXISTING` 与 `SKIP_EXISTING_GENERATION` 口径不同，同时给会报错。** 前者不含流程版本，
  用于续跑**中断的同一轮**扫参；后者只认本代，用于**换代重跑**被打断后接着补。两者都按当前 RTL
  摘要匹配、只看记录在不在不看 `sim.passed`。完整口径见 `docs/commands.md`。
- **扫参维度必须给全**，缺一个就报错（P-6）；唯一例外是 `params.yaml` 里标了 `sweep: false` 的参数。

## 约束 / 习惯

- 不用 Docker，工具都装在本机 `~/tools`（安装见 `docs/quickstart.md`）。
- **路由**（默认 Lite、必走 Full 的两类、设计内部不开 change、零差异任务）：见 `AGENTS.md`「项目路由政策」，Claude 与 Codex 读同一份。
- 脚本不做过度设计：能跑、能读、能改就行。
- 遇到需要做判断的事，先问，不要自己替负责人决定。
- `REPORT.md` 由记录生成，**不要手工编辑**，靠 `make report` 刷新。
- **常备授权**在 `keel/config.yaml` 的 `authorize:`；没列的动作每次都要问负责人。
