"""工具最低版本门禁（内部#260）：fast_check 与验证侧回归脚本开跑前都调这一处，最低版本只写在这里。

低版本工具造成的红和代码红长得一模一样（PR 内部#245 / 内部#246：Verilator 5.020 不认 waivers.vlt，lint 全红），
所以不达标时直接报「环境不合格」，不让它表现成一堆用例失败。表与依据见 docs/toolchain.md「工具最低版本」。

    python3 flow/check/tool_versions.py [--sim verilator|icarus]     # 不达标打 FAIL 行并退出 1
    python3 flow/check/tool_versions.py --print-verilator-min        # 给 fast_check.sh 取数
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERILATOR_MIN = "5.036"     # cocotb 2.1 要求；5.020 不认 waivers.vlt


def _key(v):
    return tuple(int(x) for x in v.split("."))


def verilator_version():
    """`verilator --version` 的 主.次 版本；没装或认不出返回 None。"""
    try:
        out = subprocess.run(["verilator", "--version"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"^Verilator (\d+\.\d+)", out, re.M)
    return m.group(1) if m else None


def requirements_pin(name):
    """requirements.txt 里 `name==X` 锁定的版本；没锁返回 None。"""
    for line in (REPO / "requirements.txt").read_text().splitlines():
        m = re.match(rf"\s*{re.escape(name)}\s*==\s*([^\s#;]+)", line, re.I)
        if m:
            return m.group(1)
    return None


def installed_version(name):
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version(name)
    except PackageNotFoundError:
        return None


def problems(sim="verilator"):
    """不达标的项，每项一行（已带「FAIL  环境：」前缀）。认不出 verilator 版本号只当没装，交给调用方报。"""
    out = []
    if sim == "verilator":
        v = verilator_version()
        if v and _key(v) < _key(VERILATOR_MIN):
            out.append(f"FAIL  环境：verilator {v} < {VERILATOR_MIN}（低版本不认 waivers.vlt，结果不可信）")
    pin, got = requirements_pin("cocotb"), installed_version("cocotb")
    if pin and got and got != pin:
        out.append(f"FAIL  环境：cocotb {got} != {pin}（requirements.txt 锁定；cocotb 进 flow 指纹）")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim", choices=("verilator", "icarus"), default="verilator")
    ap.add_argument("--print-verilator-min", action="store_true")
    a = ap.parse_args(argv)
    if a.print_verilator_min:
        print(VERILATOR_MIN)
        return 0
    probs = problems(a.sim)
    for p in probs:
        print(p)
    if probs:
        print("      最低版本表见 docs/toolchain.md「工具最低版本」；修环境后重跑，不要当成代码红放过")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
