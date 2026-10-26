"""在几个 ABC 延时目标上各综合一次，取最好的那一个。

**目标是按设计自己的可达延时 `d0` 推出来的，不是一组写死的绝对值。** 这不是风格
问题：2026-09-13 的全量重跑就栽在这上面 —— 绝对阶梯 `(300, 150, 100, 90)` 是在
`ADDER32`（路径 180–2000 ps）上调的，放到 `d0 = 1381 ps` 的一个地址流水设计上
整组比可达值紧 4 倍以上，ABC 够不着就退回"放到最大"，四档产出的网表与不加压
逐字节相同，护栏触发，那个设计 9 个组合一条记录都没写成。

换成相对坐标之后规律很干净（6 个组合 × 12 个比例的细扫）：

- 响应几乎是**阶跃**。从 `1.5 × d0` 到 `0.5 × d0`，六个组合返回**完全相同**的
  结果（延时、面积、网表哈希都一样）。有梯度的只有 `0.3–0.5` 那一小段。
- **在细扫过的那 6 个组合上，死区是一个固定比例**，在 `0.2–0.25 × d0`
  （4 个组合在 `0.2 × d0` 处产出与不加压逐字节相同的网表）。早先记成"设计相关的
  绝对阈值（70 ps / 85 ps）"是坐标系选错造成的假象：70/308 = 0.23、85/380 = 0.22，
  换成相对坐标是同一个数。详见 `docs/data-credibility.md` 的 D-7。

  ⚠️ **这条不能往更浅的设计上推广。** 那 6 个组合的 `d0` 在 180–1400 ps；
  2026-09-14 在一个组合地址子块（`d0 = 126 ps`）上实测，死区一直延伸到
  **`1.0 × d0`**，而有响应的区间在 `d0` 的**上方**。说得通：不加压等于"延时目标 0，
  能多快多快"，任何**紧于** `d0` 的目标都够不着；只有**宽松于** `d0` 的目标才让
  ABC 松手降尺寸换面积（那个设计上 `1.5 × d0`：面积 −3.3%、延时 +31%）。
- 所以不需要密采样，也不需要二分。二分本来也不成立 —— 延时对 `-D` 非单调
  （`CLA` 与另外两个设计每一档都比不加压更差）。

`(1.0, 0.5, 0.3)` 这三个比例在全部 6 个细扫组合上都命中了该组的最优值，而且三个
都是"活的"（产出的网表都与不加压不同），护栏因此总有比对物。

`1.5` 是 2026-09-14 补的，为的是**浅设计**：`d0` 低到百皮秒量级时，≤ 1.0 的档
全部够不着，整组失效，护栏（正确地）拦住 —— 那个设计一条记录也写不成。
一个宽松于 `d0` 的档保证护栏总有比对物。它**不改变既有设计的胜出者**：细扫记录
说从 `1.5 × d0` 到 `0.5 × d0` 六个组合返回完全相同的结果，网表逐字节相同 →
延时与面积相同 → `pick_best` 的第三项兜底选不加压那档。

比例是**流程的一部分，不是每次调用的自由参数**，所以它进 `synth_recipe_sha256`
（见 `flow/flow_fingerprint.py`）。进去的是**比例**而不是推出来的皮秒值：
皮秒值是每个设计各自的，两个设计跑同一套流程必须落在同一代里。
`ratios=` 参数只给测试用。
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from flow.sta.run_sta import run_sta
from flow.synth.synth import run_synth

# 延时目标 = 这几个比例各乘以设计自己的 d0（不加压那一档的关键路径）。
# 不加压那一档总是要跑的，所以它不在这个元组里 —— 它既是候选，也是 d0 的来源。
# 改这个元组会改变 synth_recipe_sha256，因而给记录分代 —— 那是对的。
DELAY_TARGET_RATIOS = (1.5, 1.0, 0.5, 0.3)


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pick_best(candidates):
    """延时最小 → 平手取面积小 → 再平手取不加压。

    平手真的会发生：`BRENT_KUNG W=32` 在 `D=300` 与 `D=80` 延时同为 0.284901，
    面积却是 23.69250 vs 23.77998。最后一项让结果不依赖遍历顺序 ——
    换个阶梯写法就换个赢家的话，这个量就不是可复现的。
    """
    return min(candidates, key=lambda c: (c["sta"]["critical_path_delay_ns"],
                                          c["synth"]["area_um2"],
                                          0 if c["delay_target_ps"] is None else 1))


def delay_targets(d0_ps, ratios=DELAY_TARGET_RATIOS):
    """把比例换算成绝对皮秒。`abc -D` 只吃整数。"""
    return [round(r * d0_ps) for r in ratios]


def search_fmax(design, params, liberty, vcd=None, period_ns=5.0, out_dir=None,
                ratios=DELAY_TARGET_RATIOS):
    """先跑不加压那一档量出 d0，再按比例推目标各跑一次，返回胜出的那一档的产物。

    不加压那一档**不是可选的**：它既是候选之一，又是 `d0` 的唯一来源，还是护栏的
    比对物。所以它写死在流程里而不是放进那组可配的比例 —— 少了它护栏会永远通过。

    `out_dir` 是这次实验的**根目录**（`runs/<experiment_id>/`）。每一档落在
    `search/<档名>/{synth,sta}/`，胜出的那一档再**原样复制**到 `synth/` 与 `sta/` ——
    这两个位置是既有约定：`make sta RUN=<id>` 就是从 `runs/<id>/synth/*_netlist.v`
    找网表的。复制而不是只留一个指针，是为了让"这条记录描述的是哪一份网表"这件事
    在目录结构上就能看出来，不必先读 JSON 再去某个子目录里找。

    `synth` 与 `sta` 两段都来自**同一个**胜出网表 —— 面积、功耗、延时必须同源，
    否则记录里的几个数描述的是不同的电路。
    """
    out_dir = Path(out_dir) if out_dir else None

    def run_one(target):
        tag = "base" if target is None else f"D{target}"
        sub = (out_dir / "search" / tag) if out_dir else None
        synth_result = run_synth(design, params, liberty,
                                 out_dir=(sub / "synth") if sub else None,
                                 delay_target_ps=target)
        sta_result = run_sta(design, synth_result["netlist_path"], liberty,
                             vcd=vcd, period_ns=period_ns,
                             out_dir=(sub / "sta") if sub else None)
        return {
            "delay_target_ps": target,
            "dir": sub,
            "netlist_sha256": _sha256_file(synth_result["netlist_path"]),
            "synth": synth_result,
            "sta": sta_result,
        }

    base = run_one(None)
    d0_ps = round(base["sta"]["critical_path_delay_ns"] * 1000)
    targets = delay_targets(d0_ps, ratios)
    candidates = [base] + [run_one(t) for t in targets]

    effective = _the_targets_did_something(candidates)
    # 整组无效（内部#85）：取不加压那一档。那份网表就是 base 本身，fmax 是它的关键路径倒数
    # —— 按 experiment-record 的定义正是 "analytic"；记成 search:abc-D 就是冒充搜过。
    winner = pick_best(candidates) if effective else base
    synth_result, sta_result = winner["synth"], winner["sta"]
    if winner["dir"] is not None:
        synth_result = _promote(synth_result, winner["dir"] / "synth", out_dir / "synth")
        sta_result = _promote(sta_result, winner["dir"] / "sta", out_dir / "sta")
    # fmax 现在是"在这组目标里能拿到的最好值"，不再是"没加压时恰好是多少"。
    # 换了取得方式就要换 fmax_method —— 复用 "analytic" 会让两种量混在一起比。
    sta_result = {**sta_result, "fmax_method": "search:abc-D" if effective else "analytic"}
    return {
        "delay_target_ps": winner["delay_target_ps"],
        # 至少一档目标改变了网表。False 时上面的 fmax 不是搜出来的（内部#85，D-31）
        "search_effective": effective,
        "synth": synth_result,
        "sta": sta_result,
        "candidates": [
            {"delay_target_ps": c["delay_target_ps"],
             "netlist_sha256": c["netlist_sha256"],
             "area_um2": c["synth"]["area_um2"],
             "critical_path_delay_ns": c["sta"]["critical_path_delay_ns"]}
            for c in candidates
        ],
    }


def _promote(result, src_dir, dst_dir):
    """把胜出那一档的产物复制到实验根下的既有位置，并让返回的路径指向副本。

    返回的路径必须跟着改：一个指向 `search/D90/synth/` 的 `netlist_path` 配上
    `runs/<id>/synth/` 里的同名文件，读者没法知道哪一个才是记录描述的那份。
    """
    shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir)
    src, dst = str(src_dir), str(dst_dir)
    return {k: (dst + v[len(src):] if isinstance(v, str) and v.startswith(src) else v)
            for k, v in result.items()}


def _the_targets_did_something(candidates):
    """至少一档目标产出了与不加压不同的网表时为 True。

    死区是静默的，而"整组失效"与"搜过了，base 恰好最好"在结果上完全一样。
    2026-10-03 之前整组失效时直接报错、不写记录（这条守卫 2026-09-13 真的触发过：
    绝对皮秒阶梯对 `d0 = 1381 ps` 的设计整组紧了 4 倍以上）。但关键路径只有百皮秒
    量级的浅组合（d0 = 1–123 ps）每一档都改不动网表，一条记录都写不出（内部#85）。
    用户 2026-10-03 定：放行，由记录自己说明 —— `synth.search_effective = false`、
    `fmax_method = "analytic"`。比例为空（一档加压都没跑）同样算无效。
    """
    base_sha = candidates[0]["netlist_sha256"]
    return any(c["netlist_sha256"] != base_sha for c in candidates[1:])


if __name__ == "__main__":
    import argparse
    from flow.paths import cli_params

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design", required=True)
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--period-ns", type=float, default=5.0)
    args = ap.parse_args()

    result = search_fmax(args.design, cli_params(args.param), args.liberty,
                         period_ns=args.period_ns)
    print(json.dumps({"delay_target_ps": result["delay_target_ps"],
                      "candidates": result["candidates"]},
                     indent=2, ensure_ascii=False))
