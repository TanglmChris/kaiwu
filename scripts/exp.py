"""单条实验（make exp）：跑 run_experiment，成功后删掉这次的 VCD（内部#222 ②，用户 2026-10-13 定）。

功耗算完之后 VCD 不再被读；大设计一个组合最多约 9 GB，REFERENCE 4 个点约 36 GB。删在这一层而不是
run_experiment：后者在 METRIC_MODULES 里，改它全仓换代，而删 VCD 不改任何测量值（与 sweep 同理，内部#172）。
失败的实验不删，留着排查；KEEP_VCD=1（--keep-vcd）保留。RTL 仿真失败时 run_experiment 停在仿真、写失败记录，这里退出 1（内部#334）。删掉之后 `make sta RUN=<id>` 找不到 VCD 会报错，
不会静默退回无活动率的估算（红线 5）。

正式运行的记录写到本设计根的记录文件 results/<设计根>/experiments.jsonl（内部#422，flow/records.py）。

TRIAL=1（--trial，内部#222 ①）：试跑。记录写到 runs/trial/<时间>/trial.jsonl，不进 results/，
也不要求工作区干净（旁边存一份当时的 git status）；验证状态的检查照旧。只临时换掉 run_experiment 模块里的
记录路径与脏树守卫，跑完恢复，不改 run_experiment.py 本身（它在 METRIC_MODULES 里）。试跑记录不能当正式数据用。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from flow import records  # noqa: E402
from flow.param_exclude import point_params  # noqa: E402
from flow.paths import cli_params  # noqa: E402
from scripts import run_experiment as rx  # noqa: E402
from scripts.run_experiment import run_experiment  # noqa: E402
from scripts.sweep import prune_vcd  # noqa: E402

TRIAL_ROOT = REPO_ROOT / "runs" / "trial"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design", required=True)
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--point", help="按 params.yaml 的 sweep_points 点名取全部参数（#332），与 --param 二选一")
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--sim", default="icarus", choices=["icarus", "verilator"])
    ap.add_argument("--period-ns", type=float, default=5.0)
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--keep-vcd", action="store_true", help="保留 sim / sim_gate 下的 VCD（默认算完功耗就删）")
    ap.add_argument("--trial", action="store_true", help="试跑：记录不进 results/，不要求工作区干净")
    a = ap.parse_args(argv)
    if a.point and a.param:
        ap.error("--point 与 --param 不能同时给：--point 已经给全了全部参数")
    params = point_params(a.design, a.point) if a.point else cli_params(a.param)
    if a.trial:
        tdir = TRIAL_ROOT / time.strftime("%Y%m%d-%H%M%S")
        tdir.mkdir(parents=True, exist_ok=True)
        st = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True)
        (tdir / "git_status.txt").write_text(st.stdout)
        saved = (rx.EXPERIMENTS_LOG, rx._assert_clean_worktree)
        rx.EXPERIMENTS_LOG, rx._assert_clean_worktree = tdir / "trial.jsonl", lambda porcelain: None
        print(f"# 试跑（TRIAL=1）：记录写到 {tdir / 'trial.jsonl'}，不进 results/，不当正式数据用")
        try:
            record = run_experiment(a.design, params, a.liberty, a.sim, a.period_ns, reference=a.reference)
        finally:
            rx.EXPERIMENTS_LOG, rx._assert_clean_worktree = saved
    else:
        # 正式记录追加到本设计根的记录文件（内部#422）；run_experiment.py 在 METRIC_MODULES 里，不改它，在这层换目标
        with records.redirect(rx, records.log_path(a.design)):
            record = run_experiment(a.design, params, a.liberty, a.sim, a.period_ns, reference=a.reference)
    print(json.dumps(record, indent=2))
    if (record.get("sim") or {}).get("passed") is False:
        # RTL 仿真失败（内部#334）：run_experiment 已停在仿真、写了失败记录；VCD 留着排查，退出 1
        print(f"# RTL 仿真失败：流程停在仿真，没有综合与 STA；已写失败记录 {record['experiment_id']}，"
              f"VCD 留在 runs/{record['experiment_id']}/sim/ 排查")
        return 1
    if not a.keep_vcd:
        freed = prune_vcd(record["experiment_id"])
        print(f"# 功耗已算完，删了 VCD {freed / 1e9:.2f} GB（runs/{record['experiment_id']}/sim*/；KEEP_VCD=1 保留）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
