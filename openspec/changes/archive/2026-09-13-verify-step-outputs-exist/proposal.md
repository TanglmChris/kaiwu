## Why

`flow/sim/run_sim.py:97` 调 `fst2vcd` 时把 FST 文件名放在了选项之前：

```python
subprocess.run([fst2vcd, str(fst_path), "-o", str(vcd_path)], check=True, capture_output=True)
```

`fst2vcd` 的 usage 是 `[OPTION]... [FSTFILE]`，**选项必须在文件名之前**。
BSD / macOS 的 getopt 遇到第一个非选项参数就停止解析，于是 `-o <vcd>` 被当成多余的
位置参数，VCD 按其默认行为**打到 stdout** —— 而 `capture_output=True` 把它吞掉了。

2026-09-13 实测：

| 写法 | 退出码 | 生成文件 |
|---|---|---|
| `fst2vcd <fst> -o <vcd>`（现状） | 0 | **否** |
| `fst2vcd -f <fst> -o <vcd>` | 0 | 是（16770 字节） |

**失效方式是本仓库的标准形状**：`check=True` 因退出码 0 而放行，`run_sim` 返回一个
指向不存在文件的 `vcd_path`，故障延后到另一个模块才爆成
`FileNotFoundError: ... adder32.vcd`（`vcdvcd` 的内部错误）。读的人会以为仿真没产出
波形，而真正的原因是参数顺序。

这直接违反 `experiment-trust` 已有的「缺少必需输入时必须报出真正的原因」——
那条要求「MUST NOT 把缺失值传给外部工具并让用户面对该工具的内部错误」。
现在缺的更靠前一步：**某一段报告了它没有产出的产物**。

## What Changes

- **修 `flow/sim/run_sim.py` 的参数顺序**：`fst2vcd -f <fst> -o <vcd>`。
- **产出后断言文件真的存在**，不存在就报出「哪一段没产出什么」，并附上
  `fst2vcd` 的实际输出——而不是返回一个没核实过的路径。
- **新增一条 Requirement**：流程的某一段 MUST NOT 报告它没有产出的产物。
  这比「缺输入时报对原因」更靠前：前者管消费侧，这条管生产侧。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `experiment-trust`: 新增一条 Requirement，禁止流程的某一段在产物实际不存在时
  仍把它作为结果返回。

## Impact

| 文件 | 动作 |
|---|---|
| `flow/sim/run_sim.py` | 参数顺序 + 产出断言 |
| `tests/test_run_sim.py` | 新增：回归测试 |

**不受影响**：`results/experiments.jsonl`（本变更不产生记录）、`flow/synth`、
`flow/sta`、`flow/equiv`。

**风险**：低。`synth.py` 与 `run_sta.py` 虽然也没有显式断言产物存在，但它们**产出后
立刻读**（`stats_json.read_text()` / `results_json.read_text()`），缺文件会在使用点
当场失败且有日志路径可循。本变更**只修 `run_sim.py`** —— 它是唯一一个「返回未核实
的路径、让故障在别的模块爆发」的。把断言铺到另外两处属于扩大范围，且它们当前的
行为不构成同一个缺陷。

**为什么走 Full**：触及 `flow/**`，按 `keel/lenses/hardware.md` 的路由属于
「a wrong number is the more likely failure than a wrong circuit」的范围 ——
这个 bug 正是让流程在缺少功耗反标输入时给出令人误判的错误。
