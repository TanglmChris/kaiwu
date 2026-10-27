"""跑测试时把 Python 字节码缓存挪出设计根。

为什么值得有这个文件：`tests/test_run_sim.py` 真跑仿真，cocotb 会导入
`designs/<name>/tb/*.py`，解释器就地写 `__pycache__/`。那是**设计根下的新增
文件**，而 `repo-layout` 的「每类产物必须归属到明确的一层」判据是目录内容、
不是 `git status` —— 被 `.gitignore` 挡住不作数，`scripts/fast_check.sh` 的
设计根洁净度检查会当场拦住。

实测（2026-09-15）那些 `.pyc` 的文件名带 `cpython-311-pytest-9.1.1` 标记，
说明写它们的是**带 pytest 断言重写的导入**，所以落点必须在 pytest 这一侧，
而不只是 `flow/Makefile`。

`os.environ` 这一份同时管两件事：本进程后续的编译（`sys.pycache_prefix`），
以及 cocotb 拉起的子进程（环境变量被继承）。两者都要，缺一处就会漏。

不给 `__pycache__` 开白名单：一旦开了，判据就从「目录里有没有别的东西」退化成
「有没有**我认得的**别的东西」，而下一个漏进来的产物恰恰是没人认得的那个。
"""
import os
import sys
from pathlib import Path

_PREFIX = Path(__file__).resolve().parents[1] / ".pycache"
os.environ.setdefault("PYTHONPYCACHEPREFIX", str(_PREFIX))
sys.pycache_prefix = os.environ["PYTHONPYCACHEPREFIX"]

# fast_check 缺工具时会自己 source ~/tools/env.sh（内部#107）。测试里跑的 fast_check
# 要看到的是用例自己摆的 PATH（缺工具的用例靠它），所以默认关掉；要测这条行为的
# 用例显式传 FAST_CHECK_TOOLS_ENV。
os.environ["FAST_CHECK_TOOLS_ENV"] = ""

# 仿真子进程（Verilator 的 makefile 调的 python3 脚本）用跑 pytest 的这个解释器，不激活 venv 也能跑（内部#442，
# flow-parameterization「仿真子进程必须用跑流程的那个解释器」）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flow.sim.python_path import prefer_this_python  # noqa: E402

prefer_this_python()

# 测试里拉起的 merge_check / review_prep / make sweep 都会经 flow/budget.py 拿全机锁
# `cpu-heavy`（内部#359）。测试不该去占真锁、也不该在 xdist 的几个 worker 之间互相排队；
# 整轮 pytest 算一件大活（由 merge_check 或跑的人自己排），里面一律当已持有。
# 锁本身的行为由 tests/test_budget.py 用桩 keel 测，那里显式删掉这个变量。
os.environ["KAIWU_HEAVY_HELD"] = "1"
# 同理，测试里拉起的 fast_check 不等负载（内部#382）；等负载本身在 tests/test_budget.py 里测。
os.environ["FAST_CHECK_NO_LOAD_WAIT"] = "1"


def pytest_configure(config):
    # 真跑 EDA 工具（yosys / OpenSTA / 等价证明 / 整条实验流程）的用例标 `flow`。
    # 它们占全量耗时的八成以上：内循环用 `-m "not flow"`，全量留给 change-close。
    config.addinivalue_line(
        "markers", "flow: 真跑 EDA 工具的用例（慢）；内循环用 -m 'not flow' 排除")
    _warm_source_sets(config)


def _warm_source_sets(config):
    """`pytest -n` 时，先在主进程里把每个顶层的读入集合缓存算好。

    `flow/synth/synth.py` 的 `source_files()` 把结果缓存在 `runs/.source_sets/`，
    写法是直接 `write_text` —— 不是原子的。缓存失效时两个 worker 同时算同一个
    顶层，一个在写、一个在读，读到空文件就是 `JSONDecodeError`（2026-09-24 在
    `-n 6` 下实撞）。修它要动 `synth.py`，而它在 `METRIC_MODULES` 里、改了就换代，
    所以先在测试侧绕开：worker 起来之前缓存已经是热的，之后只有读。
    跟踪：本仓 内部#57。
    """
    if not getattr(config.option, "numprocesses", None):
        return  # 串行，没有竞争
    if hasattr(config, "workerinput"):
        return  # xdist 的 worker；只在主进程做一次
    import shutil
    if shutil.which("yosys") is None:
        return  # 需要 yosys 的用例反正会被 skip
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from flow.paths import _top_index
    from flow.synth.synth import source_files
    for top in _top_index():
        source_files(top)


# --- 夹具设计根（trim-design-roots 的 D2）------------------------------------------
#
# 有些用例测的是某种结构性质（慢一个量级的组合链……），仓里保留的设计提供不了。
# 这些夹具设计放在 tests/fixtures/designs/<根>/，不在 designs/ 与 cbb/ 下 —— 流程与
# fast_check 平时看不到它们；用例请求 `fixture_designs` 时，把它们并进流程的顶层索引，
# 流程的每个入口（resolve_design_root、rtl_candidates、validate_params……）都经同一个
# `_top_index`，于是按名字就能找到，不需要逐个函数打补丁。
FIXTURE_DESIGNS = Path(__file__).resolve().parent / "fixtures" / "designs"


import pytest  # noqa: E402


@pytest.fixture
def fixture_designs(monkeypatch):
    import flow.paths as fp

    orig = fp._top_index

    def with_fixtures(repo_root=fp.REPO_ROOT):
        index = orig(repo_root)
        for root in sorted(p for p in FIXTURE_DESIGNS.iterdir() if p.is_dir()):
            for top, cfg in fp._declared_tops(root).items():
                index.setdefault(top, (root, cfg or {}))
        return index

    monkeypatch.setattr(fp, "_top_index", with_fixtures)
    return FIXTURE_DESIGNS
