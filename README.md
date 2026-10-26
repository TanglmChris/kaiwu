# kaiwu

> An open reference implementation of [Keel](https://github.com/TanglmChris/keel) for hardware: parameterised RTL, a
> simulation → synthesis → STA / power flow on open-source tools (Yosys, Verilator, Icarus, OpenSTA, ASAP7), and an
> agent team that develops IP blocks through specs, reviews and gated hand-offs. Documentation is in Chinese.

kaiwu（开物，取自《天工开物》）是一个 RTL 设计与 PPA 实验的仓库，也是 [Keel](https://github.com/TanglmChris/keel)
在硬件方向的参考实现。它想回答一个问题：几个 AI 会话分工做一块 IP，怎样做到「跑通了，而且数字可信」。

## 里面有什么

| 目录 | 内容 |
|---|---|
| `flow/`、`scripts/` | 全链路流程：仿真（cocotb，Icarus / Verilator）→ 综合（Yosys + ABC）→ STA 与功耗（OpenSTA，VCD 反标），结果结构化写进每个设计根的记录文件 `results/<设计根>/experiments.jsonl`；`scripts/fast_check.sh` 是秒级门禁 |
| `designs/adder32/` | 一个完整的示例设计：LRS 需求规格、LLD 详细设计、参数、TB、验证计划 |
| `cbb/` | 四个通用构件（CBB）：`cbb_lzd`、`cbb_bin2onehot`、`cbb_onehot2bin`、`cbb_fifo`，各带规格与覆盖全部参数组合的 cocotb TB |
| `team/` | agent 组织：组织角色、每个 IP 一个 PM、能力镜像（规格 / 设计 / 验证 / 评审 / 报告）、拉 team 的书面流程 |
| `openspec/specs/` | 契约：仓库布局、实验记录 schema、打分、可信度、组织分工等 |
| `knowledge/` | 架构知识资料卡（运算、优先级编码、存储与流控、架构技巧） |
| `docs/` | 命令全集、踩坑清单（症状 + 判据命令 + 修复）、规格写作规范、工具链、数据可信度的读法 |

## 几条底线

这个项目最容易翻车的不是「跑不通」，而是「跑通了但数字不可信」，门禁查不出来。所以：

1. 报任何 PPA 数字之前，过一遍 `docs/pitfalls.md` 的判据列；
2. 实验记录（`results/<设计根>/experiments.jsonl`）只增字段，不改名、不删、不重写历史行；
3. 记录实验前先提交，记录里的 `git_commit` 才是真的；
4. 流程指纹不同的记录不能横向比较；
5. 动态功耗必须由 VCD 反标算出。

## 从哪开始

- 装环境、跑通第一个设计：[`docs/quickstart.md`](docs/quickstart.md)
- 命令全集：[`docs/commands.md`](docs/commands.md)
- agent team 怎么组织：[`team/README.md`](team/README.md)、[`team/pull-team.md`](team/pull-team.md)
- 执行纪律（Keel）：[`AGENTS.md`](AGENTS.md)

## 说明

- 这是一个私有仓的开源导出：只含流程、平台、agent team 与示例设计，私有 IP 与 PPA 记录不在其中。正文里的
  「内部#N」指私有仓的 issue，这里查不到。
- `cbb/` 各构件下的 `REPORT.*.md` 是用私有仓里的实验记录生成的报告快照，生成它们的记录文件不在公开仓；
  照 [`docs/quickstart.md`](docs/quickstart.md) 第 5 步在本地跑实验，就能用自己的记录重新生成。
- 日常在 macOS 上开发和验证；`requirements.txt` 是在 Linux + Python 3.11 上锁定的，整条流程没有在 Linux 上完整跑过。

## 许可

[Apache License 2.0](LICENSE)。
