"""Cheap sim-side activity stats from a VCD: total bit toggles + clock cycle count.

This is NOT how dynamic power is computed (OpenSTA does that directly from the
VCD via read_power_activities) -- this is just a sanity/activity number for
the experiment record.

clock_signal=None means the design declared it has no clock: cycles comes back
None. A name that is not in the VCD is an error, never cycles=0 -- a plausible
looking zero in the experiment records (results/<root>/experiments.jsonl) cannot be told apart afterwards from
a real measurement.
"""
from vcdvcd import VCDVCD


class ClockSignalNotFound(Exception):
    pass


def vcd_stats(vcd_path, clock_signal):
    vcd = VCDVCD(str(vcd_path))

    total_toggles = 0
    for sig in vcd.data.values():
        prev = None
        for _, val in sig.tv:
            if prev is not None and len(prev) == len(val):
                total_toggles += sum(1 for a, b in zip(prev, val) if a != b)
            prev = val

    if clock_signal is None:
        return {"total_toggles": total_toggles, "cycles": None}

    sig_id = vcd.references_to_ids.get(clock_signal)
    if sig_id is None:
        raise ClockSignalNotFound(
            f"VCD 中找不到时钟信号 {clock_signal!r}（{vcd_path}）。"
            f"在设计的 params.yaml 里用 `sim: {{clock_signal: <端口名>}}` 声明正确的名字，"
            f"纯组合设计写 `clock_signal: null`。VCD 中实际存在的顶层信号："
            + _sample_refs(vcd)
        )

    cycles = 0
    prev = None
    for _, val in vcd.data[sig_id].tv:
        if prev == "0" and val == "1":
            cycles += 1
        prev = val

    return {"total_toggles": total_toggles, "cycles": cycles}


def _sample_refs(vcd, limit=12):
    """列出 VCD 里的顶层信号，帮用户对照出该声明什么。信号可能上千个，只取前若干。"""
    refs = sorted(r for r in vcd.references_to_ids if r.count(".") == 1)
    shown = refs[:limit]
    tail = f" …（共 {len(refs)} 个）" if len(refs) > limit else ""
    return ", ".join(shown) + tail
