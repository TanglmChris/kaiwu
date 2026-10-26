# 工具链：工具路径与最低版本

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

## 工具路径

- 开源工具链（yosys / verilator / iverilog）：`~/tools/oss-cad-suite`
  - yosys 还兼作形式化等价证明的求解器：
    `.venv/bin/python3 flow/equiv/run_equiv.py --design <设计>`。
    zc 两对是秒级，addr expand 三个 DAT_W 约 3 分 44 秒。它**不进** `fast_check.sh`
    （那是秒级内循环），属于 `keel gate change-close` 那一档。
- OpenSTA（时序 + 功耗，源码编译）：`~/tools/OpenSTA-src/build/sta`
- 统一环境变量脚本：`~/tools/env.sh`（把上面两个工具的 bin 加进 PATH，还有 nvm/uv）
- 本仓库备了一份 `.envrc`（direnv）：进入仓库目录自动 `source ~/tools/env.sh`、
  激活 `.venv`，并把 `core.hooksPath` 自愈到 `.githooks`；离开目录自动还原，
  不影响其他项目的 python3
- ⚠️ **2026-09-24 这台 mac mini 上没装 direnv**（`command -v direnv` 是空的），
  仓库的位置与名字也都换过（工作区目录、仓库名先后改名）。也就是说 `.envrc` 那三件事一件都没自动
  发生，**每个新 shell 都要自己 `source ~/tools/env.sh`** —— P-17 与 P-18 两条坑
  都是从这儿来的。`core.hooksPath` 的自愈不只靠 `.envrc`：`scripts/heal_hooks_path.sh` 也由
  `fast_check.sh` 与 `new_worktree.sh` 调用，连各 worktree 的 `config.worktree` 一起改回相对的 `.githooks`
  （10-25 工作区改名后绝对值悬空、钩子静默跳过，内部#417）。
- Python 环境：仓库内 `.venv`（uv 管理）。版本锁在 `requirements.txt`（含传递依赖），
  重建：`uv pip install -r requirements.txt --python .venv/bin/python3`。
  里面 **cocotb / vcdvcd / pyyaml 三个包在测量路径上**。cocotb 自 2026-09-14 起
  已进 `flow` 指纹的 `sim` 那项（换版本会分代）；**vcdvcd 与 pyyaml 仍然不进** ——
  换它们的版本能改数字而指纹不变（内部#27 的缺口 3 只解决了 cocotb 那一层）。
- PDK：`~/pdk/asap7`（ASAP7 7nm FinFET 预测性 PDK）
- 综合用的合并 liberty：`~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib`

### 工具最低版本（内部#260）

低版本工具造成的红，看起来和代码红一模一样，真的红项会混在里面被放过（PR 内部#245 / 内部#246：云端 apt 装的
Verilator 5.020 让每个分支的 lint 都红）。所以有依据的最低版本由门禁直接拦，报成「环境不合格」：

| 工具 | 最低版本 | 依据 | 谁拦 | 本机已验证（2026-10-12） |
|---|---|---|---|---|
| Verilator | 5.036 | cocotb 2.1 要求；5.020 不认 `waivers.vlt`，lint 全红 | `flow/check/tool_versions.py`：`fast_check.sh` 报 `FAIL  环境：verilator <版本> < 5.036`、RTL lint 记「未执行」；验证侧回归脚本用 verilator 开跑前报同一行并退出 2 | 5.053 devel |
| Icarus Verilog | 未定 | 尚无版本引起的问题 | — | 14.0 devel |
| Yosys | 未定 | 同上 | — | 0.69+24 |
| OpenSTA | 未定 | 同上 | — | 3.1.0 |
| Python 包 | 按 `requirements.txt` 逐个锁定 | cocotb / vcdvcd / pyyaml 在测量路径上 | cocotb：`tool_versions.py` 核装的版本等于锁定版本，不等报 `FAIL  环境：cocotb <装的> != <锁定>`（验证侧回归脚本开跑前拦；fast_check 不跑 cocotb，不查）；其余包只靠锁定 | cocotb 2.1.0 |

- 改最低版本：改 `flow/check/tool_versions.py` 的 `VERILATOR_MIN` 与这张表；fast_check 与验证侧回归脚本都从它取，不另写一份（内部#260）。表里写「未定」的，等真出现版本问题再定，
  不要凭猜测填数。
- 云端或新机器：apt 装的 Verilator 一般太旧。装 YosysHQ 的 oss-cad-suite 发布包，解到 `~/tools/oss-cad-suite`，
  `source ~/tools/env.sh` 后用 `verilator --version` 核一遍。下载受限、装不上合格版本时，fast_check 报环境
  FAIL 是预期的：照实写进回报，**不能当成代码红放过，也不能当成通过**；仿真可以用 `SIM=icarus` 跑。
