# 从零跑起来

按顺序做完，能在本机跑通门禁、一个设计的全链路实验和报告。下面的路径（`~/tools`、`~/pdk`）是流程默认读的位置；
放在别处的话，按每步后面写的变量改。

## 1. 克隆，建 Python 环境

前提：**Python ≥ 3.11**（`requirements.txt` 锁定的 `contourpy==1.3.3` 只支持 3.11 起；macOS 自带的 `python3` 是 3.9，
照锁文件装会报 `No matching distribution`）。推荐用 [uv](https://docs.astral.sh/uv/)，第 3 步解压 PDK 也用它。

```bash
git clone https://github.com/TanglmChris/kaiwu.git
cd kaiwu
uv venv --python 3.11 .venv
uv pip install -r requirements.txt --python .venv/bin/python3
```

没有 uv 时，用 3.11 的解释器建环境、再装依赖：

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

然后激活环境（每开一个新 shell 都要激活一次）：

```bash
source .venv/bin/activate
```

- **跑测试和实验前必须激活**：仿真时 Verilator / cocotb 会从 `PATH` 里找 `python3`，不激活就会用到系统自带的那个
  （macOS 上是 3.9），和 `.venv` 的 3.11 对不上，`tests/test_sim_verilator.py` 里的用例会失败。
  只写 `.venv/bin/python3 -m pytest` 不够，子进程看的是 `PATH`。

- `.venv` 必须建在仓库根：`scripts/fast_check.sh`、`scripts/merge_check.py`、`scripts/review_prep.py` 都按这个位置找解释器，
  缺了它有一批测试会失败。
- `requirements.txt` 是含传递依赖的完整锁定。其中 cocotb、vcdvcd、pyyaml 在测量路径上，**不要改它们的版本**：
  换了会改数字（原因写在文件头）。

## 2. 装 EDA 工具

| 工具 | 来源 | 默认位置 |
|---|---|---|
| Yosys、Verilator、Icarus | [YosysHQ oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build) 发布包 | `~/tools/oss-cad-suite` |
| OpenSTA | [parallaxsw/OpenSTA](https://github.com/parallaxsw/OpenSTA) 源码编译 | `~/tools/OpenSTA-src/build/sta` |

- Verilator 至少 5.036（门禁会拦，报「环境不合格」）。发行版 apt 装的一般太旧，用 oss-cad-suite 的。
- 写一个环境脚本，每个新 shell 先 `source` 它：

```bash
# ~/tools/env.sh
export PATH="$HOME/tools/oss-cad-suite/bin:$PATH"
[ -x "$HOME/tools/OpenSTA-src/build/sta" ] && export PATH="$HOME/tools/OpenSTA-src/build:$PATH"
```

- 不带这些工具跑 pytest，依赖它们的用例会**静默跳过**，看起来是绿的，不算通过。

## 3. 准备 ASAP7 PDK

流程用 ASAP7（7nm 预测性 PDK）的 7.5-track 单元库：

```bash
mkdir -p ~/pdk/asap7 && cd ~/pdk/asap7
git clone --filter=blob:none --sparse https://github.com/The-OpenROAD-Project/asap7sc7p5t_28.git
cd asap7sc7p5t_28
git sparse-checkout set LIB/NLDM Verilog    # 时序库 + 门级仿真用的单元模型
```

综合要一份合并后的 liberty：把 RVT / TT 下 AO、OA、INVBUF、SEQ、SIMPLE 五份 `.lib.7z` 解压，再用
`flow/synth/merge_liberty.py` 合并，**基文件用 SIMPLE 那份，并且必须用 `--base` 显式给出**：

```bash
cd ~/pdk/asap7/asap7sc7p5t_28
mkdir -p ~/pdk/asap7_merged/extracted
for f in AO OA INVBUF SEQ SIMPLE; do
  uvx py7zr x LIB/NLDM/asap7sc7p5t_${f}_RVT_TT_nldm_*.lib.7z ~/pdk/asap7_merged/extracted
done
<仓库>/.venv/bin/python3 <仓库>/flow/synth/merge_liberty.py \
  -o ~/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib \
  --base <解压出的 SIMPLE 那份 .lib> \
  <另外 4 份 .lib>
```

- 没有 uv：另建一个只装解压工具的环境，**不要装进仓库的 `.venv`**（那是测量用的锁定环境），再把上面的 `uvx py7zr` 换成它：

  ```bash
  python3.11 -m venv ~/pdk/.py7zr && ~/pdk/.py7zr/bin/pip install py7zr
  # 循环里改成：~/pdk/.py7zr/bin/py7zr x LIB/NLDM/…lib.7z ~/pdk/asap7_merged/extracted
  ```
- 通配符在个别组合上会匹配到两个文件，挑哪个取决于 shell 排序。动手前先看一眼展开结果，细节见
  [`docs/toolchain/pdk.md`](toolchain/pdk.md)「合并 liberty」。
- 合并库的位置由 `flow/Makefile` 的 `LIBERTY` 变量决定，放在别处就 `make … LIBERTY=<路径>`。
- 基文件不同、合并工具版本不同，都会得到另一份 `liberty_sha256`，记录也就进了另一代；新机器上的数字不要和别人的直接比。

## 4. 跑门禁和测试

```bash
source ~/tools/env.sh
source .venv/bin/activate                                      # 新 shell 要重新激活，见第 1 步
./scripts/fast_check.sh                                        # 秒级：elaborate + lint + 文档与结构检查
.venv/bin/python3 -m pytest tests/ -q -n 4 -m 'not flow'       # 内循环
```

两条都应该通过。pytest 允许跳过的只有读私有文件的那几条（PPA 记录不在开源集合里），跳过原因里写着；
其余的跳过多半是工具没进 PATH。fast_check 报「环境」类 FAIL 时先回第 2 步查工具版本，不要当成代码问题放过，也不要当成通过。

## 5. 跑一个设计

```bash
make -f flow/Makefile exp    DESIGN=CBB_LZD PARAMS="<参数给全>"   # 参数名与取值见 cbb/cbb_lzd/params.yaml
make -f flow/Makefile sweep  DESIGN=CBB_LZD                       # 扫 params.yaml 里的全部组合，JOBS 默认 1
make -f flow/Makefile report DESIGN=CBB_LZD                       # 从记录生成 REPORT
```

- 实验前先提交：记录里的 `git_commit` 取自 `HEAD`，工作区脏着跑，记录的出处就是错的（门禁会拒写）。
- 只想试一下、不写正式记录：加 `TRIAL=1`，结果写到 `runs/trial/` 下。
- 全部命令与开关的口径：[`docs/commands.md`](commands.md)；出数字之前过一遍 [`docs/pitfalls.md`](pitfalls.md)。

## 6. 用 agent team 干活（可选）

kaiwu 的协作纪律来自 [Keel](https://github.com/TanglmChris/keel)：

```bash
npm install -g @christang/keel     # Node.js 的版本要求见 keel 的 README
keel --doctor                      # 体检：配置、授权、路由
keel context                       # 现在该做什么
```

- 执行纪律在 [`AGENTS.md`](../AGENTS.md)，Claude Code 与 Codex 读同一份。
- 组织与分工在 [`team/README.md`](../team/README.md)：组织角色、每个 IP 一个 PM、能力镜像在 `team/roles/`。
  PM 拉一组会话干活按 [`team/pull-team.md`](../team/pull-team.md) 的五步走。
- 新建一个设计：专用设计用 `flow/templates/design-root/`（LRS、LLD、验证计划），通用构件用 `flow/templates/cbb-root/`；
  规格怎么写见 [`docs/spec-writing.md`](spec-writing.md)。
