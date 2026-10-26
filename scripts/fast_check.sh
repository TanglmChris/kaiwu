#!/usr/bin/env bash
# Seconds-scale inner-loop check (keel fast_check).
#
# Deliberately does NOT run simulation/synthesis/STA -- a single sweep is
# minutes, which belongs to `keel gate change-close`, not a pre-push. What
# this catches is the cheap-but-common breakage: RTL that no longer
# elaborates under some parameter combination, and Python that no longer
# imports.
# 退出码 0 的含义是「本脚本声明要做的每一类检查都实际执行了并且通过」——
# 不是「没有检查失败」。两者的区别在于「一个都没跑」：前者不许它返回 0。
# 这与 experiment-trust 的「无法测得的指标必须缺席，不得以合法值代替」同源。
# 契约在 openspec/specs/guardrail-scope/spec.md。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --rev <提交>（内部#344）：在该提交的临时检出里跑它自己的 fast_check（scripts/at_ref.py：detached worktree、软链 .venv、
# 核干净、首行打印完整提交号、跑完删掉）。放在设 trap 之前，exec 之后本进程就是 at_ref。
if [ "${1:-}" = "--rev" ]; then
    [ -n "${2:-}" ] || { printf '%s\n' "用法：scripts/fast_check.sh --rev <提交>" >&2; exit 2; }
    PYR="$REPO_ROOT/.venv/bin/python3"; [ -x "$PYR" ] || PYR=python3
    exec "$PYR" "$REPO_ROOT/scripts/at_ref.py" --ref "$2" -- ./scripts/fast_check.sh
fi

# --docs-only（内部#379，merge-check-reuse D8）：具名开关，不跑 RTL lint，每个顶层的 lint 记「未执行」。只有
# merge_check 的轻量模式（base..head 只改了 designs/ cbb/ docs/ knowledge/ team/ 下的文档）传它：lint 的输入
# 一个没变。elaborate 照跑 —— 端口表比对用它留下的 vvp，而端口表读的正是文档。
DOCS_ONLY=0
NO_CACHE="${FAST_CHECK_NO_CACHE:-0}"   # --no-cache：不复用通过的结果，照样记下（内部#382）
while [ $# -gt 0 ]; do
    case "$1" in
        --docs-only) DOCS_ONLY=1 ;;
        --no-cache) NO_CACHE=1 ;;
        *) break ;;
    esac
    shift
done
DOCS_ONLY_WHY="--docs-only：只改文档，lint 的输入没变"

fail=0
ran=()        # 实际执行并通过的检查
skipped=()    # 没能执行的检查（附原因）
live=()       # 每次都实跑、结果不进缓存的检查（内部#432：「记录与报告」看分支名与 HEAD 提交，缓存键盖不住）
# bash 3.2 下 ${#arr[@]} 对空数组是 0，但 "${arr[@]}" 会触发 set -u；下面统一先判长度。
note() { printf '%s\n' "$*"; }

# 退出码 0 的前提是**跑到了末尾**。bash 中途夭折时不一定把状态传出来：实测
# macOS 自带的 bash 3.2 在 `while ... done <<< "$str"` 里撞上 set -u 的未绑定
# 变量，脚本只打了第一条检查就结束，**退出码却是 0** —— 正是头部那句契约最不能
# 容忍的形态（报告的范围大于实际检查的范围），而且这一次连"报告"都没打出来。
# 哨兵只回答"跑到末尾了没有"，**不读 $?** —— 夭折之后 bash 3.2 连 $? 都取不
# 可靠（trap 里 `rc=$?` 自己会再炸一次 unbound variable，实测）。
finished=0
# 日志落在每次运行自己的临时目录里。以前是固定的 /tmp/fast_check_*.log：两个实例
# 同时跑（pytest -n、两个 worktree、两个会话各自 pre-push）会互相截断对方的
# 报错，失败时 cat 出来的是别人的日志（2026-09-24 在 pytest -n 6 下实撞）。
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/fast_check.XXXXXX")" || { note "FAIL  mktemp -d 失败"; exit 1; }
trap 'rm -rf "${LOGDIR:-/nonexistent}"; [ "${finished:-0}" = 1 ] || { printf "%s\n" "FAIL  fast_check 没跑到末尾就退出了：退出码按 90 报，不要当成通过" >&2; exit 90; }' EXIT

# --- 运行环境：工具链 PATH 与 .venv（内部#107、内部#108）---
# 从没 source 过 ~/tools/env.sh 的 shell 发 push 时工具不在 PATH（P-17），各会话
# 反复被拦。这里先自己 source 一次再查；source 之后仍缺，下面照旧 FAIL ——
# 补 PATH 只是替调用方做了那一步，不是降级。FAST_CHECK_TOOLS_ENV= 置空则不补。
TOOLS_ENV="${FAST_CHECK_TOOLS_ENV-$HOME/tools/env.sh}"
if ! { command -v iverilog && command -v verilator; } > /dev/null 2>&1 \
        && [ -n "$TOOLS_ENV" ] && [ -f "$TOOLS_ENV" ]; then
    set +u   # env.sh 不是为 set -u 写的
    . "$TOOLS_ENV" > /dev/null 2>&1
    set -u
    note "note  工具不在 PATH，已 source ${TOOLS_ENV}"
fi
# app 建的 worktree 没有 .venv，回落到系统 python3 会缺 yaml。主仓有就软链过来
# （与 scripts/new_worktree.sh 做的是同一件事；.venv 在 .gitignore 里）。
if [ ! -e .venv ]; then
    common="$(git rev-parse --path-format=absolute --git-common-dir 2> /dev/null || true)"
    main_root="${common%/.git}"
    if [ -n "$common" ] && [ "$main_root" != "$REPO_ROOT" ] && [ -x "$main_root/.venv/bin/python3" ]; then
        # 相对链接，工作区目录改名后照样能用（用户 10-25）；两端先取真实路径，路径上有软链（/var → /private/var）也不指错
        ln -s "$(python3 -c 'import os, sys; r = os.path.realpath; print(os.path.relpath(os.path.join(r(sys.argv[1]), ".venv"), r(sys.argv[2])))' "$main_root" "$REPO_ROOT")" .venv && note "note  本工作区没有 .venv，已软链到 ${main_root}/.venv"
    fi
fi

# pre-push 钩子靠 core.hooksPath 挂载；agent 会话不一定经过 direnv 的 .envrc，这里也自愈一次（内部#417）。
# 与上面补 .venv 同理：替调用方做那一步，不是降级。
[ ! -x scripts/heal_hooks_path.sh ] || scripts/heal_hooks_path.sh

# --- Python: syntax/compile of the flow + driver scripts ---
if [ -x .venv/bin/python3 ]; then
    PY=.venv/bin/python3
else
    PY=python3
fi
# --- 同一份内容只检查一次（内部#382，budget-renew-fast-check-load D4 / D5）---
# 工作区干净时按 HEAD 树、merge-base、参数、工具与 Python 环境记下通过的结果（git 公共目录，所有 worktree 共用）；
# 同一组输入再跑就打印「复用」与当时的覆盖摘要，不等负载、不跑检查。不可复用时 key 打印原因、不记。
# 例外是「记录与报告」那几项（内部#432）：它们看当前分支名与 HEAD 提交本身，而键只有树与 merge-base —— 白名单分支
# 推过的同一棵树快进进一个不在白名单里的分支，复用就等于跳过了它们。它们是秒级的，命中时照样实跑，结论以本次为准。
FC_KEY=""
if [ -f flow/check/fc_cache.py ]; then
    FC_KEY="$("$PY" flow/check/fc_cache.py key $([ "$DOCS_ONLY" = 1 ] && echo --docs-only) 2> /dev/null)" || FC_KEY=""
    if [ -n "$FC_KEY" ] && [ "$NO_CACHE" != 1 ] && "$PY" flow/check/fc_cache.py get "$FC_KEY"; then
        rb_rc=0
        "$PY" -m flow.check.fc_record_branches > "$LOGDIR/records.log" 2>&1 || rb_rc=$?
        note "本次实跑（不复用，#432）"
        while IFS= read -r line; do
            case "$line" in "ok    "*) note "  已执行  ${line#ok    }" ;; *) note "$line" ;; esac
        done < "$LOGDIR/records.log"
        finished=1
        [ "$rb_rc" = 0 ] || exit 1
        exit 0
    fi
fi
# --- 开跑前等负载（内部#382，budget-renew-fast-check-load D3）---
# 几个会话同时推送时 pre-push 的 fast_check 会叠起来（10-20 到过负载 79）。只等负载、不拿 cpu-heavy，最多等 10 分钟后照跑；
# 在大活里（KAIWU_HEAVY_HELD=1，如 merge_check）或 FAST_CHECK_NO_LOAD_WAIT=1 时不等。夹具仓里没有 budget.py 就不等。
if [ -f flow/budget.py ]; then
    "$PY" flow/budget.py wait-load fast_check || note "note  flow/budget.py wait-load 出错，不等负载照跑"
fi
# 按文件定位违规的检查段失败时走这里（内部#254，fast-check-waivers）：违规全部落在 flow/check_waivers.yaml
# 登记的豁免内就打 WAIVED、不让退出码变红，否则照旧 FAIL。段名取日志名，见 flow/check/check_waivers.py。
_check_fail() {   # $1 = 段名（$LOGDIR/<段名>.log）  $2 = 标题
    local rc=0
    "$PY" flow/check/check_waivers.py apply "$1" "$2" "$LOGDIR/$1.log" "$LOGDIR/waivers.used" \
        > "$LOGDIR/$1.waived" 2>&1 || rc=$?
    if [ "$rc" = 0 ]; then
        cat "$LOGDIR/$1.waived"
        ran+=("$2（有豁免）")
        return
    fi
    if [ "$rc" = 1 ]; then
        cat "$LOGDIR/$1.waived"
    else   # 判定脚本自己坏了：照旧报这一段的失败与原始日志，再附上它的报错
        note "FAIL  $2"
        cat "$LOGDIR/$1.log"
        note "      （失败豁免判定没能运行，退出码 ${rc}：$(tail -n 1 "$LOGDIR/$1.waived")）"
    fi
    fail=1
}
if ! "$PY" -m compileall -q flow scripts > "$LOGDIR/py.log" 2>&1; then
    note "FAIL  python compileall"
    cat "$LOGDIR/py.log"
    fail=1
else
    note "ok    python compileall (flow/, scripts/)"
    ran+=("python compileall (flow/, scripts/)")
fi

# 顶层名 -> 下标。macOS 自带的 /bin/bash 是 3.2，**没有关联数组**，所以逐顶层
# 的统计用三条平行的下标数组加线性查找（顶层数是个位数，代价可以忽略）。
#
# ⚠️ 结果放全局 $ti 回传，**不能**写成 `ti=$(_top_slot ...)`：命令替换是子 shell，
# 在里面新开的格子出了子 shell 就没了，而且那种丢失是静默的。
_top_slot() {
    ti=0
    while [ "$ti" -lt "${#top_names[@]}" ]; do
        if [ "${top_names[$ti]}" = "$1" ]; then return 0; fi
        ti=$(( ti + 1 ))
    done
    top_names+=("$1"); top_n+=(0); top_fail+=(0); top_lfail+=(0); top_files+=(""); top_bad+=(0); top_excl+=(0); top_pts+=(0)
}

# --- 设计根可解析（guardrail-scope，flow-batch-2026-10 的 1.1，内部#74）---
# 用流程自己的入口（flow/paths.py::_top_index）对全部设计根建一次顶层索引。护栏下面
# 的各项按 params.yaml 遍历，看不到「会让流程解析报错」的根：2026-09-28 一个只放了
# 规格的根让内循环 5 → 62 个失败，而护栏报的是通过。规格先行的根（既无 params.yaml
# 也无 rtl/）被索引跳过，这里单独计数。
if ! resolve_out="$("$PY" -m flow.check.fc_resolve 2>"$LOGDIR/resolve.log")"; then
    note "FAIL  设计根可解析"
    cat "$LOGDIR/resolve.log"
    fail=1
else
    note "ok    设计根可解析（${resolve_out}）"
    ran+=("设计根可解析（${resolve_out}）")
fi

# --- RTL: elaborate（iverilog）+ lint（verilator），每个参数组合各跑一次 ---
# 两个工具都定义 CBB_PARAM_CHK_ON：RTL 自带的参数检查（`ifdef 里的 $error）只有定义了才生效，
# 不定义时 params.yaml 声明出的非法组合照样 elaborate 通过、进扫参（内部#165：一组 RTL 判为非法的参数组合）。
# 只在这里打开，不进综合 / 仿真：那些在 METRIC_MODULES 里，打开就全仓换代；本检查展开全部组合
# （含 sweep: false），能进扫参的组合都先过这一道。
# 两个工具各自判缺失：缺了哪个，哪一项就 FAIL（或具名降级），另一项照跑。
# 静默跳过是本仓的头号失效模式（报告的范围大于实际检查的范围）。
# 降级必须由调用方具名声明，不能是默认行为。
_missing_tool() {   # $1 = 工具名  $2 = 检查项名
    if [ "${FAST_CHECK_ALLOW_MISSING_TOOLS:-}" = "1" ]; then
        note "DEGRADED  $1 不在 PATH —— 本次运行没有做 $2"
    else
        note "FAIL  $1 不在 PATH：$2 一个组合都没能检查"
        note "      修复：source ~/tools/env.sh"
        note "      或显式降级：FAST_CHECK_ALLOW_MISSING_TOOLS=1 $0"
        note "      不要用 git push --no-verify 绕过（#254）：确实要先推，在 flow/check_waivers.yaml 登记豁免"
        fail=1
    fi
    skipped+=("$2（$1 不在 PATH）")
}
HAVE_IV=1; command -v iverilog  > /dev/null 2>&1 || { HAVE_IV=0; _missing_tool iverilog "RTL elaborate"; }
if [ "$DOCS_ONLY" = 1 ]; then
    HAVE_VL=0
    note "note  ${DOCS_ONLY_WHY}，本次不跑 RTL lint"
else
    HAVE_VL=1; command -v verilator > /dev/null 2>&1 || { HAVE_VL=0; _missing_tool verilator "RTL lint"; }
fi
# 工具最低版本（内部#260，表在 docs/toolchain.md「工具最低版本」）：低版本的 verilator 不认 waivers.vlt
# 里的写法，每个组合都报 lint FAIL，看起来像代码红，实际是环境不合格 —— 真的红项混在里面被
# 习惯性放过（内部#246）。不达标就报一行环境 FAIL，lint 记「未执行」，不再跑出几十组 lint FAIL。
# 认不出版本号（测试里的桩）只提示不拦：真的 verilator 总会打印版本。
VERILATOR_MIN="$("$PY" flow/check/tool_versions.py --print-verilator-min)"   # 最低版本只写在 tool_versions.py（验证侧回归脚本也用它）
if [ "$HAVE_VL" = 1 ]; then
    vl_ver="$(verilator --version 2> /dev/null | sed -n 's/^Verilator \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1)"
    if [ -z "$vl_ver" ]; then
        note "note  认不出 verilator 的版本号（verilator --version），跳过最低版本检查"
    elif [ "$(printf '%s\n%s\n' "$VERILATOR_MIN" "$vl_ver" | sort -t. -k1,1n -k2,2n | head -n 1)" != "$VERILATOR_MIN" ]; then
        HAVE_VL=0
        fail=1
        note "FAIL  环境：verilator ${vl_ver} < ${VERILATOR_MIN}（$(command -v verilator)）"
        note "      低版本不认 waivers.vlt，lint 结果不可信，本次不跑 RTL lint；最低版本表见 docs/toolchain.md「工具最低版本」"
        skipped+=("RTL lint（环境不合格：verilator ${vl_ver} < ${VERILATOR_MIN}）")
    fi
fi
# 设计树名单只有一处权威：flow/paths.py 的 DESIGN_TREES（designs/、cbb/，kaiwu-layout-decouple D4，
# kaiwu-layout-in-place，内部#305）。下面 bash 里的循环由它派生；内嵌的 Python 用
# flow.paths 的 tree_glob / is_cbb_path / local_cbb_copies，不再各写一份 designs/*、cbb/*。
read -r -a DESIGN_TREES <<< "$("$PY" -c 'from flow.paths import DESIGN_TREES; print(*DESIGN_TREES)')"
DESIGN_PARAMS=()
for t in "${DESIGN_TREES[@]}"; do
    for f in "$t"/*/params.yaml; do
        [ -e "$f" ] && DESIGN_PARAMS+=("$f")
    done
done
# lint 的豁免逐条登记，每条带文件与具体标识符（见文件头）：通用的在 flow/lint/waivers.vlt，
# 设计根自己的在 <设计根>/waivers.vlt（内部#109，flow-guard-feedback D1）。一份都没有就是零豁免。
VLT=()
for f in flow/lint/waivers.vlt; do
    [ -f "$f" ] && VLT+=("$f")
done
for t in "${DESIGN_TREES[@]}"; do
    for f in "$t"/*/waivers.vlt; do
        [ -f "$f" ] && VLT+=("$f")
    done
done
n_waivers=0
[ "${#VLT[@]}" -gt 0 ] && n_waivers="$(cat "${VLT[@]}" | grep -c '^lint_off')"
if [ "$HAVE_IV" = 1 ] || [ "$HAVE_VL" = 1 ]; then
    # 并发默认 4，KAIWU_JOBS 可调；不按核数满开（内部#359：多个会话同时满开把 10 核的机器压到负载 94）
    NJOBS="$("$PY" flow/budget.py jobs)" || { note "FAIL  flow/budget.py jobs（KAIWU_JOBS 写错？）"; exit 1; }
    # 每个组合同时起 iverilog 与 verilator 两个进程：两个都在时一次只跑一半组合，进程总数不超过 KAIWU_JOBS
    # （10-19 实测按组合数算时 4 个组合 = 8 个进程、峰值 6.7 核，内部#359 漏算）
    [ "$HAVE_IV" = 1 ] && [ "$HAVE_VL" = 1 ] && NJOBS=$(( NJOBS > 1 ? NJOBS / 2 : 1 ))
    # 各设计树（flow/paths.py 的 DESIGN_TREES）布局一致，同一套检查逻辑遍历全部
    for params in "${DESIGN_PARAMS[@]}"; do
        [ -e "$params" ] || continue   # 某棵树为空时 glob 不展开
        design_root="$(dirname "$params")"
        design="$(basename "$design_root")"
        rtl_dir="$design_root/rtl"
        [ -d "$rtl_dir" ] || continue

        # 组合展开失败必须是 FAIL。展开不出组合时，下面的循环会拿空参数跑一次
        # iverilog —— 那测的是 RTL 的默认参数，却会打印"all param combos"。
        if ! combos="$("$PY" -m flow.check.fc_combos "$params" 2>"$LOGDIR/combos.log")"; then
            note "FAIL  展开参数组合 $design ($params)"
            cat "$LOGDIR/combos.log"
            fail=1
            continue
        fi
        if [ -z "$combos" ]; then
            note "FAIL  展开参数组合 $design ($params): 一个组合都没有"
            fail=1
            continue
        fi
        # 逐**顶层**统计，不是逐设计根：一个根可以挂多个被测顶层，
        # 其中一个全过、另一个全挂时，按根统计会打出一句自相矛盾的摘要。
        # bash 3.2 没有 `declare -A`。它在 3.2 上不是当场报错退出，而是打一句
        # 「declare: -A: invalid option」继续跑，下一行 ${top_fail[$top]} 把顶层名
        # 当算术展开、撞上 set -u 才夭折 —— 那条路径的退出码是 0（见上面的哨兵）。
        top_names=(); top_n=(); top_fail=(); top_lfail=(); top_files=(); top_bad=(); top_excl=(); top_pts=()
        job_ti=(); job_desc=(); job_top=(); job_kv=(); nj=0
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            old_ifs="$IFS"; IFS=$'\t'
            # 第一个字段是顶层名，其余是 k=v
            set -- $line
            IFS="$old_ifs"
            if [ "$1" = "#EXCLUDE" ]; then
                _top_slot "$2"; top_excl[$ti]="$3"; top_pts[$ti]="${4:-0}"
                continue
            fi
            top="$1"; shift
            _top_slot "$top"
            top_n[$ti]=$(( ${top_n[$ti]} + 1 ))
            # 读哪些文件由 flow/paths.py::rtl_candidates 决定：本根 rtl/*.v 加上 params.yaml
            # 里 deps 声明的 cbb 构件根的 rtl/*.v（add-design-cbb-deps 的 D3）。与综合 /
            # 仿真的 source_files 用同一个函数，不在这里另写一遍 —— 两份就是两条口径。
            # 每个顶层只解析一次；解析失败（deps 拼错、指向 designs/、成环）整个顶层 FAIL。
            # 参数片段的 include 目录（rtl/inc/，内部#76）由 flow/paths.py::include_dirs 给出，
            # 与综合 / 仿真同口径；和候选文件一起取，Tab 隔开。
            if [ "${top_bad[$ti]}" = 0 ] && [ -z "${top_files[$ti]}" ]; then
                if ! top_raw="$("$PY" -c 'import os, sys
sys.path.insert(0, ".")
from flow.paths import include_dirs, rtl_candidates
print(" ".join(os.path.relpath(p) for p in rtl_candidates(sys.argv[1])) + chr(9)
      + " ".join("-I" + os.path.relpath(d) for d in include_dirs(sys.argv[1])))' "$top" \
                        2>"$LOGDIR/cand.log" < /dev/null)"; then
                    note "FAIL  解析 $top 的候选源文件（params.yaml 的 deps）"
                    tail -3 "$LOGDIR/cand.log"
                    fail=1; top_bad[$ti]=1; top_fail[$ti]=1; top_lfail[$ti]=1
                else
                    top_files[$ti]="${top_raw%%$'\t'*}"
                    top_incs[$ti]="${top_raw#*$'\t'}"
                fi
            fi
            [ "${top_bad[$ti]}" = 0 ] || continue
            srcs="${top_files[$ti]}"
            incs="${top_incs[$ti]}"
            # 参数名直接来自 params.yaml，流程侧不认识任何具体设计的参数
            pflags=(); gflags=()
            for kv in "$@"; do
                [ -n "$kv" ] || continue
                k="${kv%%=*}"; v="${kv#*=}"
                case "$v" in
                    ''|*[!0-9-]*) pflags+=("-P$top.$k=\"$v\""); gflags+=("-G$k=\"$v\"") ;;  # 字符串参数要带引号
                    *)            pflags+=("-P$top.$k=$v");     gflags+=("-G$k=$v") ;;
                esac
            done
            # 各组合互不依赖，后台并行跑；判定放到全部跑完之后、按原顺序做，
            # 所以输出与串行时逐字相同。攒满 $NJOBS 个就整批 wait（bash 3.2 没有 wait -n）。
            job_ti[$nj]=$ti; job_desc[$nj]="$top ${*}"; job_top[$nj]=$top; job_kv[$nj]="${*}"
            # vvp 不丢：「spec 端口表与 RTL 一致」一项从里面读顶层端口与参数实际值，
            # 不为那一项再调一次工具（guardrail-scope）
            vvp="$LOGDIR/rtl.$design.$nj.vvp"
            if [ "$HAVE_IV" = 1 ]; then
            ( iverilog -g2012 -DCBB_PARAM_CHK_ON -o "$vvp" -s "$top" \
                    "${pflags[@]}" $incs \
                    $srcs > "$LOGDIR/rtl.$nj.log" 2>&1
              echo $? > "$LOGDIR/rtl.$nj.rc" ) &
            fi
            # lint 走同一个组合：warning 与参数有关（PIPE_STAGES=0 时 clk 空挂、位宽随
            # 位宽参数变），只 lint 默认参数会漏掉大半。-Wall 下任何未豁免的 warning 都是非 0。
            if [ "$HAVE_VL" = 1 ]; then
            ( verilator --lint-only -Wall -Wno-DECLFILENAME -DCBB_PARAM_CHK_ON --top-module "$top" \
                    ${gflags[@]+"${gflags[@]}"} ${VLT[@]+"${VLT[@]}"} $incs \
                    $srcs > "$LOGDIR/lint.$nj.log" 2>&1
              echo $? > "$LOGDIR/lint.$nj.rc" ) &
            fi
            nj=$(( nj + 1 ))
            [ $(( nj % NJOBS )) -eq 0 ] && wait
        done <<< "$combos"
        wait
        k=0
        while [ "$HAVE_IV" = 1 ] && [ "$k" -lt "$nj" ]; do
            # 端口比对的清单：设计根、顶层、vvp、elaborate 退出码、参数（空格分隔的 k=v）
            printf '%s\t%s\t%s\t%s\t%s\n' "$design_root" "${job_top[$k]}" \
                "$LOGDIR/rtl.$design.$k.vvp" "$(cat "$LOGDIR/rtl.$k.rc" 2>/dev/null || echo missing)" \
                "${job_kv[$k]}" >> "$LOGDIR/ports.manifest"
            k=$(( k + 1 ))
        done
        k=0
        while [ "$k" -lt "$nj" ]; do
            # rc 文件缺失（子 shell 没跑完）按失败算，不按通过算
            if [ "$HAVE_IV" = 1 ] && [ "$(cat "$LOGDIR/rtl.$k.rc" 2>/dev/null)" != 0 ]; then
                note "FAIL  elaborate ${job_desc[$k]}"
                cat "$LOGDIR/rtl.$k.log"
                fail=1
                top_fail[${job_ti[$k]}]=1
            fi
            if [ "$HAVE_VL" = 1 ] && [ "$(cat "$LOGDIR/lint.$k.rc" 2>/dev/null)" != 0 ]; then
                note "FAIL  lint ${job_desc[$k]}"
                grep -E '^%(Warning|Error)' "$LOGDIR/lint.$k.log" || cat "$LOGDIR/lint.$k.log"
                note "      有意的写法就在设计根的 waivers.vlt（通用的在 flow/lint/waivers.vlt）登记一条（带 -file 与 -match，写理由），不要改成整文件关"
                fail=1
                top_lfail[${job_ti[$k]}]=1
            fi
            k=$(( k + 1 ))
        done
        # 这一行只在该**顶层全部**组合都过时才打印。无条件打印的话，
        # 一份日志里会同时出现若干 FAIL 和一句"all param combos"。
        ti=0
        while [ "$ti" -lt "${#top_names[@]}" ]; do
            if [ "$HAVE_IV" = 1 ] && [ "${top_fail[$ti]}" -eq 0 ]; then
                note "ok    elaborate ${top_names[$ti]} (all param combos)"
                excl_desc=""
                [ "${top_excl[$ti]}" -gt 0 ] && excl_desc="，exclude 排除 ${top_excl[$ti]} 个"
                [ "${top_pts[$ti]}" -gt 0 ] && excl_desc="${excl_desc}，含 sweep_points ${top_pts[$ti]} 个"
                ran+=("RTL elaborate ${top_names[$ti]}（${top_n[$ti]} 个参数组合${excl_desc}）")
            fi
            if [ "$HAVE_VL" = 1 ] && [ "${top_lfail[$ti]}" -eq 0 ]; then
                note "ok    lint ${top_names[$ti]} (all param combos)"
                excl_desc=""
                [ "${top_excl[$ti]}" -gt 0 ] && excl_desc="，exclude 排除 ${top_excl[$ti]} 个"
                [ "${top_pts[$ti]}" -gt 0 ] && excl_desc="${excl_desc}，含 sweep_points ${top_pts[$ti]} 个"
                ran+=("RTL lint ${top_names[$ti]}（${top_n[$ti]} 个参数组合${excl_desc}，verilator -Wall，豁免 ${n_waivers} 条）")
            elif [ "$DOCS_ONLY" = 1 ]; then
                skipped+=("RTL lint ${top_names[$ti]}（${DOCS_ONLY_WHY}）")
            fi
            ti=$(( ti + 1 ))
        done
    done
fi

# --- spec 端口表与 RTL 一致 ---
# 设计内部改动不走 OpenSpec（内部#58），`spec.<顶层>.md` 是接口契约唯一的权威。
# 2026-09-27 首次全量比对，6 个顶层里 2 个的 spec 已悄悄过时（一个把 `32*LANE_NUM`
# 写成 512，一个把 `CNT_W` 写成 2），之前没有
# 任何东西失败。逐顶层 × 逐参数组合比对端口名、方向、位宽。实际端口与参数值
# （含由别的参数算出的 parameter）取自上面 elaborate 留下的 vvp，不另调工具、
# 不在这里重推参数 —— 重推等于把 RTL 的参数逻辑再写一份，两份会漂移。
# 契约：guardrail-scope「秒级护栏必须检查 spec 端口表与 RTL 一致」，
# repo-layout「spec 的端口表必须能被机械地读出」。
PORT_CHECK="spec 端口表与 RTL 一致"
if [ "$HAVE_IV" != 1 ]; then
    skipped+=("${PORT_CHECK}（iverilog 不在 PATH，拿不到 elaborate 的端口）")
elif [ ! -s "$LOGDIR/ports.manifest" ]; then
    note "FAIL  ${PORT_CHECK}：没有任何组合可比（elaborate 一个组合都没跑）"
    fail=1
elif ! port_out="$("$PY" -m flow.check.fc_ports "$LOGDIR/ports.manifest" 2>"$LOGDIR/ports.log")"; then
    _check_fail ports "spec 端口表与 RTL 不一致"
else
    port_tops="${port_out%% *}"; port_combos="${port_out##* }"
    port_desc="${port_tops} 个顶层，${port_combos} 个参数组合"
    port_doc="$(cat "$LOGDIR/portdoc.txt" 2>/dev/null)"
    [ -n "$port_doc" ] && port_desc="${port_desc}；集成期 ${port_doc}"
    note "ok    ${PORT_CHECK}（${port_desc}）"
    ran+=("${PORT_CHECK}（${port_desc}）")
fi

# --- lint 豁免没有过时（内部#109，flow-guard-feedback D2）---
# 豁免指向的文件或信号不在了，放行就没有对象；留着它，下一次有人写出同名信号时会静默放过真问题。
# 判据：-file 的通配在 designs/*/rtl、cbb/*/rtl 下要匹配到文件；-match 里引号括起的标识符要在
# 匹配到的文件里按单词边界出现。
if [ "${#VLT[@]}" -gt 0 ]; then
    if "$PY" -m flow.check.fc_lint_waivers "${VLT[@]}" > "$LOGDIR/waiver.log" 2>&1
    then
        note "ok    lint 豁免没有过时（${#VLT[@]} 份豁免文件，${n_waivers} 条）"
        ran+=("lint 豁免没有过时（${#VLT[@]} 份豁免文件，${n_waivers} 条）")
    else
        note "FAIL  lint 豁免过时：指向的文件或信号已不存在，删掉这几行"
        sed 's/^/      /' "$LOGDIR/waiver.log"
        fail=1
    fi
fi

# --- LRS 与 LLD 的结构与需求追溯（lrs-lld-docs）---
# 专用设计（designs/）的需求写在 LRS 里、以加粗的 R.00X 定义，实现写在 LLD 里、由追溯表
# 指回需求。没有这一项时，「漏了一整节」「同一个编号定义两次」「有需求没人实现」「LLD 说
# 实现了一条不存在的需求」都不会让任何东西失败。只查能机械判定的：节名、编号、追溯的并集。
# 契约：repo-layout「专用设计的 LRS 与 LLD 必须有必填节与需求追溯」，guardrail-scope「秒级
# 护栏必须检查 LRS 与 LLD 的结构与需求追溯」。旧格式 spec / design 已退役，没有过渡清单（内部#134）。
DOC_CHECK="LRS 与 LLD 的结构与需求追溯"
if ! doc_out="$("$PY" -m flow.check.fc_docs 2>"$LOGDIR/doc.log")"; then
    _check_fail doc "${DOC_CHECK}"
else
    IFS=$'\t' read -r doc_tops doc_reqs <<< "$doc_out"
    doc_desc="${doc_tops} 个顶层，${doc_reqs} 条需求"
    note "ok    ${DOC_CHECK}（${doc_desc}）"
    [ -s "$LOGDIR/doc.log" ] && cat "$LOGDIR/doc.log"     # 只剩提示（不致命）
    ran+=("${DOC_CHECK}（${doc_desc}）")
fi

# --- 跨设计根的同名源文件必须逐字节相同 ---
# 设计根按 repo-layout 各自自带 rtl/ 与 tb/，所以一个文件被两个设计根同时需要时
# 只能各留一份拷贝，而拷贝的失效方式是**漂移**。
# （曾经的实例：一个组合子块既是自己的顶层，又是它所属地址流水那份
# 交叉比对 SV TB 的被测件，两个根下各一份。2026-09-20 收根之后两个顶层同住一个
# 设计根，本仓当前 0 组 —— 这项检查守的是下一次又出现拷贝的时候。）
# 逃生口是把它搬进 cbb/ —— 那棵树就是为"被多方需要的构件"准备的。
#
# 两层各自的失效形态不同，而 tb/ 那层更隐蔽：
#   rtl/ 漂移 -> 两个设计根测的是两个不同的电路，记录里看不出来，
#                但至少 PPA 数字会对不上。
#   tb/  漂移 -> 两个 TB 拿着两份不同的黄金参考各自全绿，**连数字都不产生**。
#                没有任何下游指标会暴露它。
# 契约条款：openspec/specs/repo-layout/spec.md 的
# 「跨设计根复制的源文件必须逐字节相同」。
if ! dup_out="$("$PY" -m flow.check.fc_dup 2>"$LOGDIR/dup.log")"; then
    _check_fail dup "同名源文件在不同设计根下内容不同"
else
    note "ok    同名源文件逐字节相同（${dup_out} 组）"
    ran+=("同名源文件一致性（${dup_out} 组）")
fi

# --- 设计根下只许有契约声明的那几种源 ---
# repo-layout 的「单次原始产物 MUST NOT 写入设计根目录内部」把观察量都写死了：
#   「MUST 以该目录下有没有新增文件为观察量，MUST NOT 以 git status 是否干净为
#    观察量。被 .gitignore 挡住的产物同样是写进了设计根。」
# 2026-09-15 之前没有任何东西在执行它，于是它预言的失效方式真的发生了：两个
# 设计根的 tb/ 下各躺着一份残留 results.xml，五个设计根下都有 __pycache__，
# 全部被 .gitignore 挡住 —— `git ls-files designs/*/tb/` 一个都看不见。
#
# 用**白名单**（只许这几种）而不是黑名单（禁止这几种）：黑名单的失效方式正是这条
# 契约要防的那一种 —— 下一个漏进来的产物一定是黑名单上没有的那个。白名单需要维护，
# 但它的失效方式是当场 FAIL，人会看见。
#
# `__pycache__` 同样不放行。它不是「单次原始产物」，但它是设计根下的新增文件；
# 开了这个白名单，判据就从「目录里有没有别的东西」退化成「有没有我认得的别的
# 东西」。正确的处置是让调用方把它重定向出去（PYTHONPYCACHEPREFIX，见
# flow/Makefile 与 tests/conftest.py），不是豁免它。
if ! clean_out="$("$PY" -m flow.check.fc_clean 2>"$LOGDIR/clean.log")"; then
    _check_fail clean "设计根下有非源文件"
else
    note "ok    设计根下只有源文件（${clean_out} 个设计根）"
    ran+=("设计根洁净度（${clean_out} 个设计根）")
fi

# --- 可综合 RTL 里不许有仿真专用构造 ---
# `$random` / `$fwrite` / `#n` 延时 / `initial` 块进了可综合 RTL，会让**仿真看到的
# 电路与综合出的电路当场分家，而两边都不报错** —— 仿真照常全绿，综合照常出网表，
# 只是两者测的不是同一个东西。这是本仓头号失效模式（「跑通了但数字不可信」）在
# RTL 层的形态。口径借鉴 MoonshotAI/nano-kpu 的 harness/audit.py（R1 扫描）。
#
# 只扫 rtl/，不扫 tb/：TB 里 initial、#n、$dumpvars 全都是**正当**的，
# 一起扫只会逼出一堆豁免。
#
# 匹配前先把注释与字符串字面量挖空 —— 注释里写「这里不许用 $random」不是违规。
# 护栏一旦开始产生噪音，人就会给它加豁免，而豁免会长期存在。
# 挖空而不是删除：偏移与行号保持不变，报错才能指到原文的那一行。
# ⚠️ Verilog 的词法与 liberty **不同**：`//` 在 Verilog 里是注释，
# 所以不能复用 flow/synth/merge_liberty.py 的 _blank_noncode。
if ! escape_out="$("$PY" -m flow.check.fc_escape 2>"$LOGDIR/escape.log")"; then
    _check_fail escape "可综合 RTL 里有仿真专用构造"
else
    note "ok    RTL 无仿真专用构造（${escape_out} 个 RTL 文件）"
    ran+=("RTL 仿真逃生口（${escape_out} 个 RTL 文件）")
fi

# --- RTL 模块名必须全大写 ---
# 2026-09-21 把 30 个模块名一次性改成大写（本仓 内部#46 的 2.1）。这条命名约定与本仓
# 其它约定不同的地方在于：**没有任何东西会让它的违反失败** —— 小写模块名照样
# elaborate、照样综合、照样仿真、照样产生记录。规范没有护栏就是建议，而下一个
# 新写模块的人不会记得它。所以约定落地的同一天就要有这道检查，否则它会慢慢漏回来。
#
# 范围按契约写死的那个：`designs/**/*.v` 与 `cbb/**/*.v`，**递归**，不是只扫 rtl/。
# 上面「仿真逃生口」那一项只扫 rtl/ 是因为 TB 里 initial/#n 是正当的；这一条不同 ——
# 命名约定对 tb/ 下的 `.v` 同样成立，而契约就是这么写的。`.sv` 的 TB（`tb_*`）不在
# 范围内：它们不是被测件，契约的措辞是 `*.v`。
#
# 注释里的 `module 旧名字` 不算声明 —— 同样是为了不让护栏产生噪音。
# 计数按**模块数**，不是文件数：一个文件可以声明多个模块，报文件数会让摘要
# 听起来查得比实际多（guardrail-scope 的「说出自己实际覆盖了什么」）。
if ! case_out="$("$PY" -m flow.check.fc_case 2>"$LOGDIR/case.log")"; then
    _check_fail case "RTL 模块名不符合大小写约定"
else
    note "ok    RTL 模块命名（${case_out} 个模块；本地 CBB 副本按名单（flow/lint/local_cbb.txt 与设计根的 local_cbb.txt）小写，其余全大写）"
    ran+=("RTL 模块命名（${case_out} 个模块）")
fi

# --- RTL 命名约定（rtl-structure-authority，2026-09-27 unify-rtl-naming）---
# 用户 2026-09-27 定：模块接口与参数一律统一命名。与「模块名全大写」同一个理由 ——
# 不合约定的名字照样 elaborate、综合、出数，没有任何东西会让它失败，所以约定落地的
# 同一天就要有这道检查。
#
# 只查**能机械判定**的条款（design.md 的 D9）：
#   参数（parameter / localparam / params.yaml 的键）：全大写、不单字母、不许 WIDTH、
#     以 W 结尾就必须以 _W 结尾。
#   端口：除 clk / rst_n（与多时钟的 <域>_clk / <域>_rst_n 输入）外 i_ / o_ 前缀且与方向一致、
#     其余部分小写、不许 inout、
#     按 _ 切开后不许出现 valid / ready / data / din / dout / count。
# 「个数用 _N」「开关用 _EN」「结构枚举叫 SCHEME」是语义约定，名字里看不出一个参数
# 是不是个数 —— 检查不猜，靠评审。
#
# IP 设计根（params.yaml 顶层 `role: ip`，D19，内部#77）里的全部模块改按 IP 级约定（D17 / D18）：
#   端口全小写、不许 inout、禁用词照查；s_ / m_ 通道口不论方向都放行（s_cmd_rdy 是输出），
#   边带口不加前缀，用了 i_ / o_ 就必须与方向一致。参数只查全大写、不单字母。
#   `role` 只许取 ip —— 拼错不当成非 IP 静默放过。
# function / task 体在扫端口之前整段抹掉：它们的 input 不是模块端口。
#
# 范围与「模块名大写」相同：designs/**/*.v 与 cbb/**/*.v，递归。flow/equiv/frozen/
# 不在这两棵树下，天然不扫（冻结件不适用书写约定，经 wrappers/ 下的包装件对接）。
if ! naming_out="$("$PY" -m flow.check.fc_naming 2>"$LOGDIR/naming.log")"; then
    _check_fail naming "RTL 命名约定"
else
    note "ok    RTL 命名约定（${naming_out}）"
    ran+=("RTL 命名约定（${naming_out}）")
fi

# --- RTL 结构枚举（rtl-structure-authority / flow-parameterization，unify-rtl-naming 1.3）---
# 用户 2026-09-29 定：结构枚举（SCHEME / *_SCHEME）取整数，名字只写在 params.yaml 的
# labels 里给人读（D12、D14）。字符串取值照样 elaborate、综合、出数；labels 少一个编号，
# 报告里那个结构就没有名字 —— 都不会有东西失败，所以要有这道检查。
#   RTL：SCHEME / *_SCHEME 的 parameter / localparam 默认值 MUST 是整数字面量。
#   params.yaml：SCHEME / *_SCHEME MUST 带 labels，键集合与 values 相同、名字大写且互不相同。
# 「分派链对每个合法取值写显式判断」不靠文本匹配猜，由 2.5 / 2.6 的非法取值用例守。
# 范围与命名约定相同；flow/equiv/frozen/ 天然不扫。
if ! enum_out="$("$PY" -m flow.check.fc_enum 2>"$LOGDIR/enum.log")"; then
    _check_fail enum "RTL 结构枚举"
else
    note "ok    RTL 结构枚举（${enum_out}）"
    ran+=("RTL 结构枚举（${enum_out}）")
fi

# --- RTL 书写风格（rtl-structure-authority，add-rtl-coding-style D15、D16）---
# 用户 2026-09-29 / 30 定的书写风格里能机械判定的十项，加书写约定的四条 MUST（内部#101）。不合风格的 RTL 照样 elaborate、
# 综合、出数，照抄旧文件写新代码的人（或 agent）不会被任何东西拦下 —— 所以要有这道检查。
#   1 tab  2 非 ASCII  3 五字段头注释（File / Module / Spec 与事实一致）
#   4 一个文件一个模块、文件名是模块名的小写  5 casex / casez  6 case 缺 default
#   7 时序块里 <= 的目标以 _r 或 _<n>ff 结尾  8 always 块与其中 for 的块名（BLK_ / BLK_FOR）
#   9 generate 条件块与 for 的块名（GEN_ / GEN_FOR）  10 例化名 U_<当前模块>_<功能>_<被例化模块>
#  11 `default_nettype  12 wire / reg 定义带赋值  13 localparam integer  14 generate 内 localparam
# 除第 2 项外先剥掉注释与字符串再匹配。范围：designs/*/rtl/*.v、cbb/*/rtl/*.v、
# flow/templates/*.v。
# 2026-09-29 之前的 47 个文件曾列在 flow/lint/style_legacy.txt（D15）；2026-10-02 随设计根删除
# 后清单已空（内部#75）。清单只减不增，
# 列出的文件不存在或已经十项全过，这一项就失败，要求移出。
if ! style_out="$("$PY" -m flow.check.fc_style 2>"$LOGDIR/style.log")"; then
    _check_fail style "RTL 书写风格"
else
    note "ok    RTL 书写风格（${style_out}）"
    ran+=("RTL 书写风格（${style_out}）")
fi

# --- 可综合 RTL 里不许有综合指令属性 ---
# `(* keep_hierarchy *)` 这类属性是**给综合工具的指令**，不是电路描述。
# 2026-09-21 把 18 处从 RTL 搬进了综合流程（声明在该顶层的 params.yaml，
# `flow/synth/synth.py` 施加），本仓 内部#46 的 2.2。搬完之后**没有任何东西**会让
# 一个漏网的属性失败 —— 它照样 elaborate、照样综合、照样出数；而属性留在 RTL 里
# 时同一个意图有两个来源，两边漂移了也不会有人发现。
#
# 扫一个**明确的三名单**。加名字的判据：它是给综合工具的指令，不是电路描述。
# 代价不对称 —— 多扫两个从未用过的名字成本是两行常量，漏扫一个的代价是
# 护栏在该响的时候不响，而「护栏不响」这件事本身不会被任何东西发现。
#
# 注释里提到属性名不算：搬家那段历史就写在 `prefix_node.v` 的注释里。
# 挖空注释的写法与上面「仿真逃生口」那一项同源（Verilog 的 `//` 是注释，
# 不能复用 merge_liberty.py 的 liberty 词法）。
if ! directive_out="$("$PY" -m flow.check.fc_directive 2>"$LOGDIR/directive.log")"; then
    _check_fail directive "可综合 RTL 里有综合指令属性"
else
    note "ok    RTL 无综合指令（${directive_out} 个 RTL 文件）"
    ran+=("RTL 无综合指令（${directive_out} 个 RTL 文件）")
fi

# --- SVA bind 连接的名字必须在被绑模块里存在（内部#194）---
# `bind <模块> <SVA> #(...) u (.x(x), ...)` 把 SVA 挂到 RTL 模块里。RTL 把某个信号改名或删掉之后，
# Verilator 不报错：bind 里的名字被当成隐式线接进来（悬空、读到 0），断言静默失效 —— 误报或恒不触发。
# 2026-10-05 一个大设计一天实撞三处（A17_11、A83/A34、A58）；`-Werror-IMPLICIT` 也不报（verify 实测）。
# inner / full 回归又不编 SVA，改名之后回归是绿的。所以这里静态查：连接表达式里的每个标识符
# （含 `#(...)` 参数表达式）都要在被绑模块的代码里出现（注释挖空、按单词边界）。`.*` 连接按 SVA 模块的
# 端口名查。被绑模块在 designs/ 与 cbb/ 的 RTL 里按 `module <名>` 找；找不到也报错。
# 验证分支上工作区的 RTL 不是被测 RTL（被测设计还在设计分支，要等验证交付后才集成进 main，内部#211）：
# 给 `SVA_BIND_DESIGN_REF=<被测设计提交>` 时被绑模块按那个提交的 RTL 找（git show），tb/ 下的 SVA 仍读工作区。
# 例：SVA_BIND_DESIGN_REF=1b64e8c git push。不给就按工作区，与以前一样。
if ! bind_out="$("$PY" -m flow.check.fc_bind 2>"$LOGDIR/bind.log")"; then
    _check_fail bind "SVA bind 连接的名字在被绑模块里不存在"
else
    note "ok    SVA bind 连接的名字都在被绑模块里（${bind_out}）"
    ran+=("SVA bind 连接名（${bind_out}）")
fi

# --- 记录与报告：白名单分支、来源、历史行、provenance（内部#422，parallel-worktree / experiment-record）---
# 记录按设计根分文件 results/<设计根>/experiments.jsonl。只有 flow/record_branches.yaml 白名单里的分支（main、
# 各 PM 集成分支、report 分支）自己的提交可以新增记录行、改 REPORT；其余分支的开发记录留在工作区不提交。原来
# 「只许 main」的两条理由各有一项机械检查：git_commit 必须可达 HEAD（rebase / squash 合并会断 provenance），
# 合并后已有记录行原样保留（手工解冲突最容易丢行改行，红线 2）。另拦旧单文件残留。逻辑在
# flow/check/fc_record_branches.py；只看已提交的状态。契约在 openspec/specs/parallel-worktree/spec.md。
"$PY" -m flow.check.fc_record_branches > "$LOGDIR/records.log" 2>&1
rb_rc=$?
cat "$LOGDIR/records.log"
while IFS= read -r line; do
    case "$line" in "ok    "*) live+=("${line#ok    }") ;; esac
done < "$LOGDIR/records.log"
[ "$rb_rc" = 0 ] || fail=1

# --- 开源集合泄漏不增（内部#365，leak-ratchet）---
# 开源白名单里的 block 命中数不得超过 flow/export/leak_baseline.txt 的基线，基线只许调低。扫的是 HEAD 提交，
# 没提交的改动看不到；推送前钩子与 merge_check 都在提交上跑本脚本，新增的在那里拦住。基线就是放行额度，
# 不走按文件的失败豁免。夹具仓里没有扫描脚本、清单或基线时记为未执行（D5）。
LEAK_CHECK="开源集合泄漏不增"
if [ ! -f flow/export/leak_ratchet.py ]; then
    skipped+=("${LEAK_CHECK}（flow/export/leak_ratchet.py 不在）")
else
    lrc=0
    "$PY" flow/export/leak_ratchet.py > "$LOGDIR/leak.log" 2>&1 || lrc=$?
    if [ "$lrc" = 0 ]; then
        note "ok    ${LEAK_CHECK}（$(head -n 1 "$LOGDIR/leak.log")）"
        tail -n +2 "$LOGDIR/leak.log"
        ran+=("${LEAK_CHECK}（$(head -n 1 "$LOGDIR/leak.log")）")
    elif [ "$lrc" = 2 ]; then
        skipped+=("${LEAK_CHECK}（$(tail -n 1 "$LOGDIR/leak.log")）")
    else
        note "FAIL  ${LEAK_CHECK}"
        sed 's/^/      /' "$LOGDIR/leak.log"
        fail=1
    fi
fi

# --- 失败豁免没有过时（内部#254，fast-check-waivers）---
# 某条豁免本次没放行任何违规（已修好或写错）算过时；还在放行违规而挂的 issue 已关只提示（内部#291）。
wrc=0
"$PY" flow/check/check_waivers.py final "$LOGDIR/waivers.used" "$LOGDIR/waivers.active" || wrc=$?
if [ "$wrc" != 0 ]; then
    [ "$wrc" = 1 ] || note "FAIL  失败豁免没能核对（flow/check/check_waivers.py 退出码 ${wrc}）"
    fail=1
else
    ran+=("失败豁免没有过时（flow/check_waivers.yaml）")
fi

# --- 覆盖摘要：通过与失败两条路径都打印 ---
# 只在失败时说明范围是不够的——成功路径才是没人细看的那条，而「报告的范围大于
# 实际检查的范围」正是在成功路径上造成伤害。
# macOS 自带 bash 3.2：set -u 下展开空数组会报 unbound variable，故先判长度。
# 记进缓存的那份不带 live 的几项：复用时它们实跑、另行打印（内部#432），这里的「当前分支」到别的分支上就是错的。
_summary() {   # $1 = 1 时带上 live 的几项
    note ""
    note "覆盖摘要"
    if [ "${#ran[@]}" -gt 0 ]; then
        for item in "${ran[@]}"; do note "  已执行  $item"; done
    elif [ "$1" != 1 ] || [ "${#live[@]}" = 0 ]; then
        note "  已执行  （无）"
    fi
    if [ "${#skipped[@]}" -gt 0 ]; then
        for item in "${skipped[@]}"; do note "  未执行  $item"; done
    fi
    if [ "$1" = 1 ] && [ "${#live[@]}" -gt 0 ]; then
        for item in "${live[@]}"; do note "  已执行  $item"; done
    fi

    if [ -s "$LOGDIR/waivers.active" ]; then
        note "生效的豁免（flow/check_waivers.yaml）"
        cat "$LOGDIR/waivers.active"
    fi
}
_summary 1 > "$LOGDIR/summary.txt"
_summary 0 > "$LOGDIR/summary.cached.txt"
cat "$LOGDIR/summary.txt"
# 只记通过的（D5）；记不下来不影响本次结论
if [ "$fail" = 0 ] && [ -n "$FC_KEY" ]; then
    "$PY" flow/check/fc_cache.py put "$FC_KEY" "$LOGDIR/summary.cached.txt" || note "note  通过结果没记下来（flow/check/fc_cache.py put 出错），不影响本次结论"
fi

finished=1
exit $fail
