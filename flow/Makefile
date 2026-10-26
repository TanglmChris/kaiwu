# 流程入口：全部目标都是对 scripts/ 与 flow/ 下 Python 的转调。
# 这里不实现任何仿真/综合/STA 逻辑——一旦 Makefile 里长出流程逻辑，
# 命令行和 Python 两条路径就会各自漂移。
#
#   make -f flow/Makefile exp    DESIGN=CBB_LZD PARAMS="DAT_W=32 MSB_EN=0 SCHEME=0"
#   make -f flow/Makefile sweep  DESIGN=CBB_LZD
#   make -f flow/Makefile report DESIGN=CBB_LZD
#
# PARAMS 是空格分隔的 NAME=VALUE 列表，名字必须在设计的 params.yaml 里声明过。
# 流程侧不认识任何具体设计的参数名。

REPO_ROOT := $(patsubst %/,%,$(dir $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))))
PY        := $(REPO_ROOT)/.venv/bin/python3
LIBERTY   ?= $(HOME)/pdk/asap7_merged/asap7sc7p5t_RVT_TT.lib
# 扫参并行度。默认 1（串行）—— 并行只压墙钟，不换代也不改数字（design.md 的 D7），
# 但默认开会让一台正在干别的活的机器被塞满，所以由调用方显式给。
JOBS      ?= 1

# 字节码缓存必须落在设计根之外。cocotb 把测试台跑在 vvp 内嵌的解释器里，导入
# designs/<name>/tb/*.py 时解释器会就地写 __pycache__ —— 那是设计根下的新增
# 文件，repo-layout 的「每类产物必须归属到明确的一层」不给它开例外
# （scripts/fast_check.sh 的设计根洁净度检查会当场拦住）。
# 子进程继承环境变量，所以在这里 export 一次就覆盖整条流程。
export PYTHONPYCACHEPREFIX := $(REPO_ROOT)/.pycache
SIM       ?= icarus
PERIOD_NS ?= 5.0

# "SCHEME=1 PIPE_STAGES=1" -> "--param SCHEME=1 --param PIPE_STAGES=1"
PARAM_FLAGS = $(foreach kv,$(PARAMS),--param $(kv))

.PHONY: help sim synth sta exp sweep report check clean regress depth iodeps revequiv
.DEFAULT_GOAL := help

help:
	@echo "目标: sim synth sta exp sweep report check clean regress depth iodeps"
	@echo "变量: DESIGN(必填) PARAMS LIBERTY SIM PERIOD_NS RUN JOBS SKIP_EXISTING SKIP_EXISTING_GENERATION KEEP_VCD"
	@echo '例: make -f flow/Makefile exp DESIGN=CBB_LZD PARAMS="DAT_W=32 MSB_EN=0 SCHEME=0"（参数给全；SCHEME 类参数取编号，名字见 params.yaml 的 labels）'

require-design:
	@test -n "$(DESIGN)" || { echo "需要 DESIGN=<设计名>"; exit 2; }

sim: require-design
	$(PY) $(REPO_ROOT)/flow/sim/run_sim.py --design $(DESIGN) $(PARAM_FLAGS) --sim $(SIM)

# 自检型 SV TB 的分层回归（flow/verify/regress.py，内部#83）：读设计根的 tb/regress.<顶层>.yaml。
# TIER=inner（默认，设计侧内循环）或 full（验证侧在发布之后跑，内部#149）。并行度：命令行给了 JOBS 就用它，否则 4
# （不沿用 sweep 的默认 1；同机各会话加起来不超过 6，见 docs/toolchain.md「CPU 预算」，内部#359）。
# 仿真器：命令行给了 SIM 就用它，否则 verilator（不沿用 cocotb 流程的默认 icarus；SIM=icarus 交叉核对）。
TIER ?= inner
regress: require-design
	$(PY) $(REPO_ROOT)/flow/budget.py run --heavy regress -- $(PY) $(REPO_ROOT)/flow/verify/regress.py --design $(DESIGN) --tier $(TIER) \
		-j $(if $(filter-out file default,$(origin JOBS)),$(JOBS),4) \
		--sim $(if $(filter-out file default,$(origin SIM)),$(SIM),verilator)

# 签名逐作业比对（flow/verify/sigeq.py，内部#224）：同 TB、两个提交的 RTL，逐作业比 DONE 行的 sig=；零差异类改动的证据 ①。
# OLD 必填，NEW 默认 HEAD（未提交的改动不在内）；MUTATE='文件::原文::替换' 在新的一侧植入变异体，要被抓到才退出 0。
sigeq: require-design
	@test -n "$(OLD)" || { echo "需要 OLD=<旧 RTL 的提交>"; exit 2; }
	$(PY) $(REPO_ROOT)/flow/verify/sigeq.py --design $(DESIGN) --old $(OLD) $(if $(NEW),--new $(NEW)) --tier $(TIER) \
		-j $(if $(filter-out file default,$(origin JOBS)),$(JOBS),4) \
		--sim $(if $(filter-out file default,$(origin SIM)),$(SIM),verilator) $(if $(MUTATE),--mutate '$(MUTATE)')

# 按提交比一个模块的形式等价（flow/equiv/rev_equiv.py，内部#339）：零差异类改动的证据 ②。GOLD 必填，GATE 默认 WORKTREE
# （当前工作区，含未提交改动）；TOP 默认 DESIGN，可以是任一子模块；GATE_TOP 用于模块改名；PARAMS 两侧同样 chparam。
# 退出码 0 等价、1 不等或未证、2 用法错误、3 自检失败（负对照没被抓到 / 证不出 gold ≡ gold）。
revequiv: require-design
	@test -n "$(GOLD)" || { echo "需要 GOLD=<改前的提交>"; exit 2; }
	$(PY) $(REPO_ROOT)/flow/equiv/rev_equiv.py --repo $(REPO_ROOT) --design $(DESIGN) --top $(if $(TOP),$(TOP),$(DESIGN)) \
		--gold-ref '$(GOLD)' $(if $(GATE),--gate-ref '$(GATE)') $(if $(GATE_TOP),--gate-top $(GATE_TOP)) \
		$(foreach p,$(PARAMS),-p $(p)) $(if $(MODE),--mode $(MODE)) $(if $(SEQ),--seq $(SEQ))

# 不写记录地量一个模块的逻辑级数与关键路径（flow/synth/depth.py，内部#111）：MODULE 默认就是 DESIGN，
# 可以是它源文件集合里的任一子模块；PARAMS 是该模块的参数（不给取 RTL 默认值）。产物在 runs/depth/。
# FALSE_FROM="rst_n cfg_*" 给不计时序的输入（默认 *rst_n*，none 关掉）；PATHS=N 列出最深的 N 个终点（内部#154）。
# BUDGET=N 列出全部超过 N 级的终点（按起止模块分组），有超标时退出码 1 —— 时序验收用这个，不用 PATHS（内部#184）。
# 里层显式 REF=：命令行上的 REF 会经 MAKEFLAGS 传给子 make，不清掉就无限递归（内部#397）；at_ref.py 也清 MAKEFLAGS。
depth: require-design
ifneq ($(REF),)
	$(PY) $(REPO_ROOT)/scripts/at_ref.py --ref $(REF) -- make -f flow/Makefile depth REF= DESIGN=$(DESIGN) \
	    $(if $(MODULE),MODULE=$(MODULE)) $(if $(PARAMS),PARAMS="$(PARAMS)") $(if $(POINT),POINT=$(POINT)) \
	    $(if $(FALSE_FROM),FALSE_FROM="$(FALSE_FROM)") $(if $(PATHS),PATHS=$(PATHS)) $(if $(BUDGET),BUDGET=$(BUDGET))
else
	$(PY) $(REPO_ROOT)/flow/disk.py check
	$(PY) $(REPO_ROOT)/flow/synth/depth.py --design $(DESIGN) $(if $(MODULE),--module $(MODULE)) $(PARAM_FLAGS) $(if $(POINT),--point $(POINT)) --liberty $(LIBERTY) \
	    $(foreach f,$(FALSE_FROM),--false-from '$(f)') $(if $(PATHS),--paths $(PATHS)) $(if $(BUDGET),--budget $(BUDGET))
endif

synth: require-design
	$(PY) $(REPO_ROOT)/flow/disk.py check
	$(PY) $(REPO_ROOT)/flow/synth/synth.py --design $(DESIGN) $(PARAM_FLAGS) --liberty $(LIBERTY)

# sta 单独跑要有前一步的网表与 VCD。给 RUN=<experiment_id> 就从 runs/<id>/synth/ 找网表，
# VCD 先找 sim_gate/（门级，gate-level-activity 起记录的功耗出自它），没有再找 sim/
# （那一代之前的 runs 只有 RTL VCD）；NETLIST=/VCD= 仍可显式覆盖。完整链路用 exp。
# 只重跑 TT：记录里的 sta.corners（SS/FF）由 exp 写，这里不刷新 —— 它不写记录，不会造出不一致的行。
STA_RUN_DIR = $(REPO_ROOT)/runs/$(RUN)
sta_netlist = $(if $(NETLIST),$(NETLIST),$(firstword $(wildcard $(STA_RUN_DIR)/synth/*_netlist.v)))
sta_vcd     = $(if $(VCD),$(VCD),$(firstword $(wildcard $(STA_RUN_DIR)/sim_gate/*.vcd) $(wildcard $(STA_RUN_DIR)/sim/*.vcd)))

sta: require-design
	@test -n "$(RUN)$(NETLIST)" || { echo "需要 RUN=<experiment_id>，或显式给 NETLIST= 与 VCD="; exit 2; }
	@test -n "$(sta_netlist)" || { echo "在 $(STA_RUN_DIR)/synth/ 下找不到网表（*_netlist.v）"; exit 2; }
	@test -n "$(sta_vcd)" || { echo "在 $(STA_RUN_DIR)/sim_gate/ 与 sim/ 下都找不到 VCD（*.vcd）；exp / sweep 算完功耗就删 VCD（#172、#222），重跑功耗要重跑这个组合，或带 KEEP_VCD=1 跑"; exit 2; }
	$(PY) $(REPO_ROOT)/flow/sta/run_sta.py --design $(DESIGN) --netlist $(sta_netlist) \
		--liberty $(LIBERTY) --vcd $(sta_vcd) --period-ns $(PERIOD_NS) \
		$(if $(RUN),--out-dir $(STA_RUN_DIR)/sta,)

# REFERENCE=1：另量参考口径（按唯一适用场景的 case 接常数、跨层次优化），写进同一条记录的 reference（内部#202）。
# 多一次综合、三个角的 STA、一次 depth、一次网表等价；只给目标配置用，sweep 不开。
# 成功后删这次的 VCD（内部#222，与 sweep 同口径；KEEP_VCD=1 保留），失败的留着排查。删在 scripts/exp.py：run_experiment 在 METRIC_MODULES 里。
# TRIAL=1 试跑：记录写到 runs/trial/<时间>/trial.jsonl，不进 results/，不要求工作区干净；不能当正式数据用（内部#222）。
exp: require-design
	$(PY) $(REPO_ROOT)/flow/disk.py check
	$(PY) $(REPO_ROOT)/scripts/exp.py --design $(DESIGN) $(PARAM_FLAGS) $(if $(POINT),--point $(POINT)) \
		--liberty $(LIBERTY) --sim $(SIM) --period-ns $(PERIOD_NS) $(if $(REFERENCE),--reference) \
		$(if $(KEEP_VCD),--keep-vcd,) $(if $(TRIAL),--trial,)

# 两个跳过开关，口径不同，不要混用：
#   SKIP_EXISTING=1             按 (design, params, synth.sources_sha256) 匹配 ——
#                               任何一代、同一份 RTL 跑过就算已有。用于续跑中断的**同一轮**扫参。
#   SKIP_EXISTING_GENERATION=1  按 (design, params, flow.fingerprint, synth.sources_sha256)
#                               匹配 —— 本代、同一份 RTL 跑过才算已有。用于**换代重跑**的断点续跑。
# 两者都按当前 RTL 的摘要匹配，所以改了 RTL 之后续跑不会跳过改过的顶层。
# 两个都给时这里不拦，由 scripts/sweep.py 报错 —— 拦截逻辑只写一份
# （本文件开头：Makefile 里不长流程逻辑）。
# 每个组合算完功耗就删它的 VCD（内部#172；大设计每个组合的 VCD 可达约 9 GB），KEEP_VCD=1 保留。单条 exp 同样删（内部#222）。
sweep: require-design
	$(PY) $(REPO_ROOT)/flow/budget.py run --heavy sweep -- $(PY) $(REPO_ROOT)/scripts/sweep.py --design $(DESIGN) \
		--liberty $(LIBERTY) --sim $(SIM) --period-ns $(PERIOD_NS) \
		--jobs $(JOBS) \
		$(if $(SKIP_EXISTING),--skip-existing,) \
		$(if $(SKIP_EXISTING_GENERATION),--skip-existing-generation,) \
		$(if $(KEEP_VCD),--keep-vcd,) $(if $(POINTS),--points "$(POINTS)")

# 磁盘护栏（内部#173）：exp / synth / depth 开跑前查剩余空间（flow/disk.py，阈值 20 GB，RTL_PPA_MIN_FREE_GB 可改）；
# sweep 与 regress 在脚本里逐组合 / 开跑前自己查。
# 端口组合依赖检查（io-comb-deps，内部#266）：按 params.yaml 的 iodeps_configs 逐组跑，与 LRS「接口组合依赖」表比对，
# 任一组 FAIL 退出 1。发布前必跑（docs/toolchain.md），不进 fast_check（大设计每组约 70 秒、峰值约 5.8 GB）。
# CONFIG="a b" 只跑这几组；JOBS 默认 1，按内存定（每组峰值见上）。产物在 runs/iodeps/<顶层>/<组>/。
# iodeps / regress / sweep 是全机大活（内部#359）：经 flow/budget.py 等负载与内存、拿 keel 租约 cpu-heavy 排队，跑完释放。
iodeps: require-design
	$(PY) $(REPO_ROOT)/flow/disk.py check
	$(PY) $(REPO_ROOT)/flow/budget.py run --heavy iodeps -- $(PY) $(REPO_ROOT)/flow/check/io_comb_deps.py --design $(DESIGN) --jobs $(JOBS) $(foreach c,$(CONFIG),--config $(c))

# 报告刷新是独立命令，绝不挂在 exp/sweep 后面（见 design.md D4）
report: require-design
	$(PY) $(REPO_ROOT)/scripts/gen_report.py --design $(DESIGN)

check:
	$(REPO_ROOT)/scripts/fast_check.sh

# 只删 runs/：里面全是 gitignored 的单次原始产物，可由记录+代码重新生成。
# 不碰 results/ 下的实验记录与各设计的 REPORT.md —— 那是 durable 的部分。
clean:
	rm -rf $(REPO_ROOT)/runs
	@echo "已删除 runs/（experiments.jsonl 与 REPORT.md 未动）"
