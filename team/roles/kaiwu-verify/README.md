# 镜像 kaiwu-verify：验证

运行态名 `kaiwu-verify-<ip>`，每个 IP 一个；要并行就自己拉 subagent（`team/pull-team.md`「需要并行：本会话拉 subagent」，内部#418）。组织分工见 `team/README.md`。

## 职责

维护设计根的 `tb/`、`verify.<顶层>.md`、`params.yaml` 的 `tops:<顶层>:sim:` 段与验证产物（覆盖、问题清单）；
按提交验证设计、交付；在 main checkout 本地做集成（先合设计、后合验证）。SVA 的断言内容归验证。

## 输入与输出

- 输入：发布 issue（设计提交）、规格。
- 输出：交付小结（回在发布 issue 里）、问题 issue、集成提交（合进本 IP 的集成分支，交 PM 推）。

## 交接

- 每轮验证先冻结输入（`flow/verify/freeze.py`），结果才指得回一个版本。
- 交付小结写设计提交、TB 提交与 manifest 的 `deliverable`；可出口时写「可出口」并附证据。
- 集成前两边都 `fast_check` 绿，合完把提交号发给推 main 的人。

## 禁区

- 不改 RTL；看到设计问题开 `design` 标签的 issue。
- 空用例、跳过与缺失的结果不算通过（`design-verify-collaboration`）。
- 回归跑着时别改它要读的 TB（用开跑时快照或 `--tb-ref`）。

## 技能与模板

- 冻结与判定：`flow/verify/freeze.py`、`flow.verify.judge`；契约 `openspec/specs/design-verify-collaboration/spec.md`。
- 交付小结格式、出口 tag（`scripts/release_tag.py`）：本文件「发布 → 验证 → 交付 → 集成 → 出口」一节。
- 分层回归：`docs/toolchain.md`「自检型 TB 的分层回归」。

## 经验

由 kaiwu-lead 从各运行态会话收集后写进这里，每条写现象、做法和出处（issue 或提交）。举例只用开源设计。
规则本身以出处里指的权威文件为准，这里只记踩过的坑和判断办法。
下文的「回归驱动」「回归汇总脚本」「交付套件」「单元 TB 集合」指各 IP 验证环境里自己的脚本（公开仓里没有通用版），换成你那个 IP 里做同一件事的脚本；`flow/verify/` 下的 `freeze.py`、`regress.py` 是公开的。
出处只写 issue 号；私有仓的提交号不写。

**1. 回归跑着时改 TB**
- 现象：旧版回归驱动每个运行是新进程，从工作区 import TB。全量回归在后台跑时给 TB 打补丁，后半段用上了未调试的新代码，32 条失败里 29 条是 TB 自己的问题，整轮作废重跑。
- 做法：用带快照的回归驱动：开跑前把 TB 复制到 `<out>/tb`（或 `--tb-ref <提交>` 按提交导出），构建与仿真都读快照，跑着时改工作区不影响本轮。不走回归驱动的入口按它读哪里定；拿不准就先提交，另开 worktree 跑。
- 出处：内部#343。

**2. 放宽 TB 判据后要在全配置上扫，不能只验原失败种子**
- 现象：修「碰撞窗判据太严」时只验了原失败种子加 42 次强制碰撞；放宽还删掉了一个合法候选，最终回归 421/422 才暴露，只好再跑一轮 1.5 小时的全量。
- 做法：放宽一个判据会同时影响别的情形。先用强制该模式的旋钮在全配置上扫（`--configs all --seeds 2 --sva`），再提交、再跑交付回归。对照臂用改前的 TB 文件同种子复跑，分清新旧问题。
- 出处：内部#274。

**3. SVA bind 悬空时回归全绿，断言却在空转**
- 现象：RTL 删改信号后，bind 连到不存在的名字。Verilator 把它静默建成恒 0 的隐式线（单独开 `-Werror-IMPLICIT` 也不报），断言误报或根本不判，回归照样全过。
- 做法：交付前逐条看回归汇总里 `SVA_HIT` 为 0 的断言并解释；冻结时审 bind 改动连到的信号语义有没有变。回归驱动编译前做 bind 连线检查，fast_check 也静态核名字，但它们核不了「接得对不对」。bind 连线与断言内容的分工见 `kaiwu-design` 的「SVA 文件的分工」。
- 出处：内部#194（fast_check 静态核；私有 IP 的回归驱动另加了 bind 连线检查，连到不存在的名字就拒绝编译）。

**4. 吞吐配对比：先核激励相同，再比拍数**
- 现象：随机激励与时序共用一个随机源，同种子换时序后激励就漂移，吞吐 ±10% 的噪声判不了 0.5% 的差异。
- 做法：把随时序变化的随机抽取挪到独立随机源，结果里记命令序列摘要（`stim`）。A / B 两个构建跑同一种子，先核 `stim` 相同再比 `cycles`；拆分前后的结果不能混着比。拆分后 A/A 的噪声底是 0 拍。
- 出处：内部#199（要判的 0.5%）、内部#268。

**5. 模块级验随路字段：采集再回放**
- 现象：要验随路字段（如读 user）的取法，手写覆盖多种排布、拆分读、压缩区的激励太费。
- 做法：① 临时写一个 bind 到被测子模块的采集 SVA，negedge 把全部输入加控制输出每拍 `$fwrite` 成一行 hex，每行 `$fflush`（否则尾部丢失），用完删掉不提交。② 用回归驱动带上 SVA、指定设计提交跑几组配置；同一构建并发运行会互相截断文件，只有几十拍的那份当无效。③ iverilog 回放：先补复位，数据字节换成握手序号，逐拍核 `user == f(首个数据字节)`；复位释放后控制输出必须与采集一致，否则回放无效。④ 基线 RTL 必须报错，并逐处做变异体。
- 出处：内部#249。

**6. 大 TB 文件按功能拆小，拆分用零差异证明**
- 现象：约束随机环境长到 2000 多行，各项功能都改同一个文件。多会话并行时互相冲突，审查与合并成本高。
- 做法：新功能不往大文件里堆，按功能建独立文件。已有大文件按「只搬方法、不改行为」拆，用同种子回归结果逐字段零差异来证明。派工时按文件划分边界。
- 出处：私有 IP 验证环境的一次零差异重构（随机环境按功能拆成子模块）。

**7. 默认 shell 的 PATH 里没有 EDA 工具，pytest 会静默跳过一批用例**
- 现象：不带工具 PATH 跑 `pytest tests/ -m 'not flow'` 报 455 passed / 135 skipped，看着是绿的；补上 PATH 是 589 passed，并暴露一条失败用例。单元 TB 集合和回归驱动则直接报找不到 iverilog / verilator。
- 做法：跑集成或交付检查前先 `export PATH="$HOME/tools/oss-cad-suite/bin:$HOME/tools/OpenSTA-src/build:$PATH"`，并看 skipped 是否为 0（只补第一个目录仍会跳 25 条）。skipped 不算通过；贴结果时写明带没带 PATH、skipped 数。pre-push 里同类问题见 `docs/pitfalls.md` P-17。
- 出处：内部#270。

**8. 判成败用退出码，不用 `grep … && 提交`**
- 现象：`<回归驱动> … | grep -E "FAIL|结果" && git commit`：grep 匹配到 FAIL 行也返回 0，带着失败提交并推送。同类：`keel gate … | grep Status && 勾选 && git commit`，把 `Status: fail` 当成通过，失败的门被勾选。
- 做法：回归结果先用回归汇总脚本的退出码判，只有新失败才非 0，看过再单独提交，不和回归串在一条命令里。keel gate 写成 `keel gate … > log; rc=$?; [ $rc = 0 ] && …`。管道会把退出码换成最后一个命令的。
- 出处：内部#291（一次被误勾选的完成门，事后补正）。

**9. 集成合并后逐字节核对，基线前进了就重新核**
- 现象：集成时 `tb/` 冲突，或等批准期间 `origin/main` 又前进，合并结果与交付的两个提交不再逐字节对应，交付证据指不回去。
- 做法：`tb/` 冲突取验证分支版本；合完核 `rtl/` 与设计提交逐字节相同，再跑 fast_check 和 inner pytest；推送前 `origin/main` 又动了，先合再核，并按新提交号重新取得批准。`params.yaml` 有改动时必须跑 inner pytest（见 `kaiwu-design` 经验 3）。
- 出处：一次集成合并漏了「按新提交号重新批准」；内部#206（inner pytest 挡下）。

**10. 清进程只杀自己的，不用 `pkill -f` 按命令模式**
- 现象：停掉自己的回归后，用 `pkill -f '<回归驱动> --design-ref <提交>'` 清残留，把另一个会话在它自己 worktree 里跑的、同一设计提交的性能回归也杀了，只好通知它重跑。
- 做法：多个会话共用一台机器，同一设计提交的命令行几乎一样。停后台任务用 TaskStop；要清子进程先 `pgrep -f` 看清楚，只杀命令行里带自己输出目录（`--out runs/<回归目录>/<我的目录>`）或属于自己 PID 子树的；拿不准就不杀，等它自己结束。
- 出处：内部#360（2026-10-04 实撞）。放在验证镜像是因为多路并发的回归主要是验证会话在跑。

**11. scratchpad 里的一次性脚本不用裸模块名**
- 现象：scratchpad 里上次会话留下的 `py.py`，被 `flow/sim/run_sim.py` → cocotb → pytest → `import py` 当模块执行，把「补注释」的补丁又写进 `designs/adder32/params.yaml` 两遍。pytest 报 `module 'py' has no attribute 'path'`，而真正的后果是一个已提交的产品文件被静默改了，`git status` 之前没人看（2026-09-13）。
- 做法：从 scratchpad 目录运行 Python 时 `sys.path[0]` 就是该目录，所以一次性脚本一律命名 `sp_<名字>.py`，或放进按任务命名的子目录；仓库文件的副本命名 `stale_copy_<名字>.py.txt`，让它不可 import。脚本只做检查，不写成 import 即生效的副作用。跑完看一眼 `git status --short`，确认写入范围等于任务的 Touch。
- 出处：内部#360。放在验证镜像是因为一次性检查脚本主要由验证会话写。

**12. SVA 汇总里的「从没触发」是没激励到，不是没失败**
- 现象：回归汇总打印「N 条断言，从没触发 M 条」，M 是前件一次都没被激励的断言条数，是覆盖缺口。评论里把「从没触发 0 条」写成了「N 条断言从没触发」，意思正好反了。
- 做法：报 SVA 结果时写成「N 条全部被激励、无失败」或「M 条没激励到：<名单>」；断言失败会让用例失败，另看失败数与通过数。M 不为 0 时，按经验 3 逐条解释。
- 出处：内部#390（10-24 原地更正）。

**13. 证据不打包进仓；验证空间大时用等效划分加约束随机多种子**
- 现象：一轮验证把波形、trace、日志打包，算哈希、分批传 Release（三批共约 1.9 GB），每轮还全量重跑旧版本，十几个小时大半花在搬证据上；GitHub 也放不下这么大的文件。
- 做法：仓里只留能复现的命令、种子和结果汇总，结论写进交付小结。地址、参数组合这类大空间先做等效划分，再用约束随机多种子去冲，不靠遍历堆用例数。交给外部模型跑大矩阵时，给边界清楚的任务和预期产物，结果自己核过再提交。
- 出处：用户 2026-10-04 定（验证由 Claude 会话主导，codex 只当工具）。

## 发布 → 验证 → 交付 → 集成 → 出口（内部#80、内部#300）

设计版本**只认 git 提交**：验证按提交取设计，结果才指得回一个版本、设计方与集成方才能
在同一个提交上复查。按工作区路径取设计只作开发运行，结果标为不可交付。

| 步 | 谁 | 在哪 | 留下什么 |
|---|---|---|---|
| 1. 发布 | 设计 | 设计分支 | `git push` 之后单开一个发布 issue（下面的模板），主线 issue 的索引里关联它 |
| 2. 同步 | 验证 | 验证分支 | `git fetch` 之后二选一：`git merge origin/worktree-<设计>`（两边文件不重叠，不会冲突）；或不 merge，冻结时直接 `--design-ref` 指向发布的提交 |
| 3. 交付 | 验证 | 验证分支 | `git push` 之后在发布 issue 里回一条交付小结，写明设计提交、TB 提交与 manifest 的 `deliverable` |
| 4. 集成 | 验证（用户 2026-10-05 定，内部#213） | 本 IP 的集成分支（`team/README.md`「IP 集成分支」；没设的 IP 在 main checkout 本地） | 读发布 issue 里的交付小结；先合设计分支、后合验证分支；合之前两边都 `fast_check` 绿；合完把提交号发 PM，由 PM 推集成分支，关键节点再向 kaiwu-chief 提合入 main。流程只答疑 |
| 5. 出口（可选，逐版问） | 验证判可出口；kaiwu-chief 问用户打不打 tag、打了推 | 发布 issue；main checkout | 验证在交付小结里写「可出口」并附证据。kaiwu-chief 在推 main 的批准里**逐版问用户是否打 tag**（用户 2026-10-13 定，内部#300：不自动每版都打）；打的话见下面「出口 tag」 |

**版本编号**（用户 2026-10-14 定，内部#303）：

- 新版本号由项目经理提议、用户确认后才用；没确认的编号不写进发布单、提交说明与 tag。
- 正式版 `R<三位序号>`，如 `R009`；对某一版的修订用 `R<三位序号>.<n>`，n 从 1 起，如 `R009.1`。
- 发布单标题、验证交付标题、tag 名里的 `R<三位序号>` 都可以是修订版号。

**出口 tag**（内部#300，用户 2026-10-13 定）：

- 名字 `<被测顶层小写>-<版本号>`，如 `<顶层小写>-R009`、`<顶层小写>-R009.1`；`git tag -l '<顶层小写>-*'` 一次列全。`cbb/` 下不走 R00x 发布的通用构件不打。各设计已有的 tag 与补打记录见设计根 `doc/process.<顶层>.md`。
- 打在**进 main 后的集成提交**上（设计与 TB 都在里面，`git checkout <tag>` 就能复跑），附注 tag，正文四行必填：可出口结论、设计 / 验证 / 规格提交与规格基线、出口判据、发布单与可出口结论的链接。
- 用 `scripts/release_tag.py` 生成名字与正文：默认只打印；`--create` 在本地打。它核对名字格式、必填项、集成提交在 `origin/main` 上、设计 / 验证 / 规格提交都包含在集成提交里、同名 tag 本地与远端都不存在。
  ```
  .venv/bin/python3 scripts/release_tag.py <顶层> R009 --commit <集成提交> --design <设计提交> --verify <验证提交> \
      --spec <规格提交> --spec-base "LRS v<…> / LLD v<…>" --exit "<交付套件各套件 通过/总数，fast_check rc=0，iodeps PASS n/n>" \
      --issue <发布单> --exit-link <可出口结论的评论链接>
  ```
- 推送：keel 推送守卫把 `git push origin <tag>`、`refs/tags/…`、`--tags` 都当成推不在表里的分支而拒（2026-10-13 实测，内部#300）。kaiwu-chief 在推 main 时用 `git push --follow-tags origin main`，tag 和 main 同一次批准推出去。`--follow-tags` 会带上本地**所有**指向 main 上提交、远端还没有的附注 tag，先 `git push --dry-run --follow-tags origin main` 看清单，只该有这一版的 tag。

各方**只在自己的分支提交**。验证 worktree 第一次建时从设计的发布提交起：

```bash
git fetch origin
scripts/new_worktree.sh --base origin/worktree-<设计> <设计>_verify
```

脚本在分支已被别处检出（会点名那个工作区，包括 `.claude/worktrees/` 之外的）、同名
worktree 检出的是别的分支、已有分支又给了 `--base`、`--base` 解析不到时报错，什么都不动。

**每轮验证先冻结输入**（`flow/verify/freeze.py`，契约在
`openspec/specs/design-verify-collaboration/spec.md`）：

```bash
.venv/bin/python3 flow/verify/freeze.py --top <顶层> \
    --design-ref origin/worktree-<设计> [--tb-ref <提交>] --out runs/verify_<顶层>_<时间>
```

- `<out>/tree/` 按仓库布局放这一轮读的全部输入，**只读**：
  - `designs/` 与 `cbb/` 取自设计提交；
  - 设计根下的 `tb/` 与 `verify.<顶层>.md` 取自验证侧（不给 `--tb-ref` 时取本工作区）；
  - `params.yaml` 的 `sim:` 段取自验证侧。

  运行中设计侧再怎么改都不影响这一轮。
- `<out>/manifest.json` 记设计 / TB / 流程三侧的提交（或工作区与是否有未提交改动）、
  逐文件 sha256 与来源侧，以及 `deliverable`。只有设计与 TB 都来自提交、流程侧干净时
  才是 `true`，否则 `not_deliverable_because` 写明原因。
- runner 以 `tree` 为 `repo_root` 取源文件：`flow.paths.rtl_candidates(<顶层>, repo_root=tree)`。
  结果用 `flow.verify.judge.judge([...results.xml])` 判：缺文件、零个用例、任何
  skipped / failure / error 都不算通过。
- 开发中要测设计侧还没提交的 RTL：`--design-worktree <路径>` 代替 `--design-ref`，
  结果不可交付。
- 叠加（内部#341），不用再手拼临时提交，两个选项都可重复，按给出顺序生效：
  - **组合被测**：`--overlay <提交>:cbb/<目录>` 把设计树下这个路径换成另一个提交里的，结果仍可交付。
  - **RTL 变异体做失败臂**：`--overlay-local <变异体.v>:designs/<根>/rtl/<文件>.v` 换成本地文件，结果不可交付。

  叠加不许越出 `designs/`、`cbb/`，也不许碰被测设计根的 `tb/` 与 `verify.*.md`。
  manifest 的 `overlays` 记每个叠加的出处，叠进来的文件 `side` 为 `overlay`。

**给旧版本打补丁：失败臂与交付**（内部#340；内部#282 给应用的 R006 补丁是这样做的，当时全靠手工）

应用手里是一个旧版本（例如 R006），问题在新版本里已修好或要新修，只给旧版本出 RTL 补丁。

1. **建补丁分支**：从应用的基线提交 B（旧版本的发布提交或 tag）拉出，提交顺序固定为：
   - 先提交 **RTL 修复**，可以分几个提交；最后一个修复提交记为 F。只有这部分交付。
   - 最后提交 **TB / 激励的移植**，记为 T，例如把新版本的逐拍 user 激励搬到旧 TB 上；它不交付。
   - 修复放在 TB 前面，补丁才能直接打在 B 上。TB 移植可以手工挑段，但只能出现在 T 这一个提交里。
2. **红**：新 TB 跑旧 RTL，必须失败。设计取 B、TB 取 T：

   ```bash
   .venv/bin/python3 flow/verify/freeze.py --top <顶层> --design-ref B --tb-ref T --out runs/patch_red
   ```

   不失败，就说明新 TB 测不到这个问题，先改激励，修复不算数。
3. **绿**：同一份 TB 跑修复后的 RTL，必须通过：`freeze.py --top <顶层> --design-ref T --tb-ref T --out runs/patch_green`。
4. **每处修复都必要**：有几处修复，就做几个「只退回这一处」的变体。
   - 每个变体用 `--overlay-local <退回后的文件>:designs/<根>/rtl/<文件>.v` 叠到绿的那棵树上，必须失败。
   - 变体对应的排布或配置也要写上（内部#282 是混合、行尾两种排布，各自只在对应排布下失败）。
5. **交付**：只导出 RTL 修复，在干净的 B 上自证能还原出 F：

   ```bash
   .venv/bin/python3 scripts/patch_deliver.py --base B --head F --out runs/patch_<issue>
   ```

   - `<out>` 里是补丁文件和 `DELIVERY.txt`：base、head、两个树哈希、每个补丁的 sha256。
   - 退出 0 才交给应用；交付评论里贴 `DELIVERY.txt` 的内容。
   - 范围里有合并提交时，报告会提示：合并时解冲突或另改的内容不在补丁里，还原不出就退出 1。
6. 补丁分支**按设计不进 main**。应用确认之后打 tag（`<设计根>-R00x-patch<issue>`），再删分支。

发布单开 issue：用模板 `.github/ISSUE_TEMPLATE/release.md`（内部#337；`gh issue create --template "设计发布（R00x）"`，或在网页上选这个模板），
标题 `<顶层>-R<三位序号> · 发布（<提交>）…`，标签 `verify` + 设计根标签；验证交付回在这个发布 issue 里。
模板里的字段：提交、要点、规格基线、时序、端口组合依赖、流程仿真、合入、应用问题、不验收的组合与已知缺口、接口变化、设计侧测试。

发布清单（G6，内部#157、内部#209）：模板里每一项都要有，缺了不发布。

```markdown
### <顶层>-R<三位序号> · 验证交付 · <通过|不通过>
- 设计：`<设计提交>`（R<序号>）；TB：`worktree-<设计>-verify` @ `<提交>`
- 冻结：`flow/verify/freeze.py --design-ref … --tb-ref …`，deliverable=<true|false>
- 结果：<套件与用例数，如 basic 19/19>；不通过的用例与对应的问题 issue
- 出口：<可出口|不可出口>；tag：<待用户定 / `<顶层小写>-R<序号>` / 不打>（第 5 步，内部#300）
```
