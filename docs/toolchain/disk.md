# 工具链：磁盘使用

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

## 磁盘使用（内部#173）

2026-10-05 Data 卷（228 GB）写满，只剩 164 MB，所有会话的 shell 都失败，正在跑的回归、试跑、depth 全部作废。
占用大头是验证侧的 Verilator 构建缓存（约 28 GB，每次回归留一份、从不清）、大设计试跑的门级 VCD（每个组合
几 GB）、设计侧 `runs/regress`（6.5 GB）和已结束的 codex worktree 的 `runs/`。用户定下面七条：

1. **VCD 算完功耗就删**：`make sweep` 每个组合成功后删掉 `runs/<id>/{sim,sim_gate}/*.vcd`（内部#172），
   测量值不变、不换代；`KEEP_VCD=1` 保留。单条 `make exp` 成功后同样删（内部#222，`scripts/exp.py`），失败的留着排查。读法见 data-credibility 的 D-36。
2. **构建产物只留最近几份**：`flow/verify/regress.py` 开跑前按时间戳只留 `runs/regress/<顶层>/` 下最近
   `KEEP_BUILDS`（3）份，含本次。其他脚本自己攒构建的（比如验证侧回归脚本的构建缓存），调用
   `flow.disk.prune_old(<目录>, keep=…)` 做同样的事。还有进程开着的目录跳过不删。
3. **开跑前查剩余空间**：`flow/disk.py`，阈值 20 GB（环境变量 `RTL_PPA_MIN_FREE_GB` 可改）。
   `make exp / synth / depth` 开跑前、`make regress` 开跑前、`make sweep` **每个组合**开跑前都查，不够就拒绝。
   扫参不按「组合数 × 峰值」事先估：并行的组合一开始就全部提交，只在开头估一次挡不住中途写满；逐个组合查
   更准。空间不够的组合按测量失败记下、结尾列出，清理后用 `SKIP_EXISTING=1` 续跑。
   单独查：`.venv/bin/python3 flow/disk.py check [--need <GB>]`。
4. **任务结束就清**：codex / dsh 任务、临时 detached worktree（变异体、基线；建用 `new_worktree.sh --detach`，内部#229）、试跑 worktree，验收完、结果记下后
   就删它们的 `runs/`。
5. **能删和不能删的边界**：`runs/` 下都是可重建的中间产物（与 `make clean` 的约定一致）；
   实验记录（`results/<设计根>/experiments.jsonl`）、各次交付的 `results.jsonl`、证据文件不删。
6. **谁来删**：各会话只删自己产生的产物，删之前用 `lsof +D <目录>` 确认没有进程在用（看输出有没有行，
   本机 lsof 找到了也可能退出 1）。本会话自己产生的中间产物按 `docs/toolchain/collaboration.md`「常备授权」第 3 条直接删，不用问（用户 2026-10-06 定，内部#218）；其余删除（别人的产物、记录、证据、分支）要该会话里的用户本人批准，别的会话转达的批准不算。
7. **磁盘满期间的结果一律作废**：回归、签名比对、depth、综合，空间恢复后在最终提交上重跑。

峰值按「并行路数 × 单组合峰值」估；各设计的实测见设计根 `doc/process.<顶层>.md`。逐组合开跑前的 20 GB 阈值不受影响。
