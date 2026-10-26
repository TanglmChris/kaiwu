#!/bin/sh
# 为并行开发建一个 worktree：一个模块一个 worktree、一个会话，main 只用来合并。
# 流程与约定见 docs/toolchain.md 的「并行开发：一个模块一个 worktree」。
#
#   scripts/new_worktree.sh [--base <ref>] <名字>
#   scripts/new_worktree.sh --detach <提交> <名字>     # 一次性：不建分支（内部#229）
#
# 建在 <主仓>/.claude/worktrees/<名字>，分支 worktree-<名字>，新分支从 --base 建
# （默认本地 main；验证 worktree 用设计分支的提交，见 docs/toolchain.md「设计与验证
# 分属两个 worktree」）。与 Claude Code 的 worktree 功能同一位置、同一命名。幂等：
# worktree 已存在（比如由 Claude Code 建的）且检出的正是 worktree-<名字> 时只补 .venv
# 软链。在主仓或任何 worktree 里运行都行。
#
# 不符一律报错、不动现场（内部#80）：分支已在别的工作区检出、同名 worktree 检出的是别的
# 分支、已有分支又给了 --base（不重置已有分支）、--base 解析不到提交。设计与验证分属
# 两条分支以后，任何一边的工作区都可能留着对方不知道的未提交成果。
#
# 退出前检查主工作区与该 worktree 的 `git status --porcelain`：任何条目都会让
# run_experiment.py 的脏树守卫拒绝写记录（红线 3），所以这里非空就以非零退出。
# 契约在 openspec/specs/parallel-worktree/spec.md。
#
# --detach <提交>（内部#229）：评审、外部 agent（G18 的 dsh_review_rN）、按某个提交跑 fast_check 用的一次性
# worktree。分离 HEAD 检出该提交，不建分支；同样软链 .venv、查两边干净；路径已存在就报错（不复用）。
# 用完删掉（toolchain 常备授权第 3 条，只删自己建的）：脚本最后打印删除命令。
set -eu

die() { printf '%s\n' "new_worktree: $*" >&2; exit 1; }

usage="用法：scripts/new_worktree.sh [--base <ref>] <名字>  或  scripts/new_worktree.sh --detach <提交> <名字>"
base=""
detach=""
case "${1:-}" in
    -h|--help) echo "${usage}"; echo "（新分支默认基于本地 main；--base、--detach 见文件头）"; exit 0 ;;
esac
if [ "${1:-}" = "--detach" ]; then
    [ $# -eq 3 ] || die "${usage}"
    detach=$2
    name=$3
elif [ "${1:-}" = "--base" ]; then
    [ $# -eq 3 ] || die "${usage}"
    base=$2
    name=$3
else
    [ $# -eq 1 ] || die "${usage}"
    name=$1
fi
# 与 Claude Code 的 worktree 名字规则一致，且不许 `..` 逃出 .claude/worktrees/
case "${name}" in
    ''|*[!A-Za-z0-9._-]*|.*|-*) die "名字只能含字母、数字、. _ -，且不以 . 或 - 开头：'${name}'" ;;
esac

# 主仓 = 公共 .git 目录的上一级。从某个 worktree 里运行时 --show-toplevel 给的是
# 那个 worktree，不是主仓。
here=$(cd "$(dirname "$0")" && pwd)
common=$(cd "${here}" && git rev-parse --path-format=absolute --git-common-dir) \
    || die "不在 git 仓库里：${here}"
main=$(dirname "${common}")
wt="${main}/.claude/worktrees/${name}"
branch="worktree-${name}"

[ -x "${main}/.venv/bin/python3" ] || die "主仓没有可用的 .venv（${main}/.venv/bin/python3）；先按 docs/toolchain.md 建好"

# 检出了该分支的工作区（可能在 .claude/worktrees/ 之外，比如 codex 的工作区）。
# 所有判断都在改动之前做完。
holder=$(git -C "${main}" worktree list --porcelain | awk -v b="branch refs/heads/${branch}" '
    /^worktree /{p=substr($0,10)} $0==b{print p}')

if [ -n "${detach}" ]; then
    [ ! -e "${wt}" ] || die "${wt} 已存在；--detach 只建新的一次性 worktree，换个名字，或先删掉旧的"
    sha=$(git -C "${main}" rev-parse --verify --quiet "${detach}^{commit}") \
        || die "提交 '${detach}' 解析不到；别的分支的提交要先在那边 git push、这边 git fetch，再用 origin/<分支>"
    git -C "${main}" worktree add -q --detach "${wt}" "${sha}"
    echo "已建：${wt}（分离 HEAD，${detach} $(git -C "${main}" rev-parse --short "${sha}")，不建分支）"
elif [ -e "${wt}" ]; then
    git -C "${main}" worktree list --porcelain | grep -qx "worktree ${wt}" \
        || die "${wt} 已存在但不是本仓登记的 worktree"
    cur=$(git -C "${wt}" branch --show-current)
    [ "${cur}" = "${branch}" ] \
        || die "${wt} 已存在，但检出的是 ${cur:-（分离 HEAD）}，不是 ${branch}；不补 .venv、不切换分支。换个名字，或先在那个工作区里处理好它的成果"
    [ -z "${base}" ] \
        || die "${wt} 已存在（${branch}），--base 不生效；不给 --base 即沿用它"
    echo "已存在：${wt}（${cur}），只补 .venv"
elif git -C "${main}" show-ref --verify --quiet "refs/heads/${branch}"; then
    [ -z "${base}" ] \
        || die "分支 ${branch} 已存在（$(git -C "${main}" rev-parse --short "${branch}")），不会重置到 --base ${base}；不给 --base 即沿用已有分支"
    [ -z "${holder}" ] \
        || die "分支 ${branch} 已在工作区 ${holder} 检出；同一条分支不能检出到两个工作区（一边的提交会被另一边过期的索引覆盖）"
    git -C "${main}" worktree add -q "${wt}" "${branch}"
    echo "已建：${wt}（沿用已有分支 ${branch}）"
else
    base_ref=${base:-main}
    sha=$(git -C "${main}" rev-parse --verify --quiet "${base_ref}^{commit}") \
        || die "基线 '${base_ref}' 解析不到提交；别的分支的提交要先在那边 git push、这边 git fetch，再用 origin/<分支>"
    git -C "${main}" worktree add -q -b "${branch}" "${wt}" "${sha}"
    echo "已建：${wt}（新分支 ${branch}，基于 ${base_ref} $(git -C "${main}" rev-parse --short "${sha}")）"
fi

if [ -L "${wt}/.venv" ] || [ -e "${wt}/.venv" ]; then
    echo ".venv 已存在，不动：${wt}/.venv"
else
    # 相对链接：wt 固定在 <主仓>/.claude/worktrees/<名>（名字不含 /），工作区目录改名后照样能用（用户 10-25）
    ln -s "../../../.venv" "${wt}/.venv"
    echo ".venv → ../../../.venv（${main}/.venv）"
fi

dirty=0
for repo in "${main}" "${wt}"; do
    st=$(git -C "${repo}" status --porcelain)
    if [ -n "${st}" ]; then
        printf '%s\n' "FAIL  工作区不干净：${repo}" "${st}" | sed '2,$s/^/        /' >&2
        dirty=1
    fi
done
if [ "$dirty" -ne 0 ]; then
    die "上面的条目会让脏树守卫拒绝写实验记录（红线 3、P-7）；提交或清掉再跑实验"
fi

# pre-push 钩子（跑 fast_check）靠 core.hooksPath 挂载；没挂上时推送不做任何检查，看起来却和「检查过了」
# 一样（guardrail-scope「护栏的挂载状态必须是自愈的或可见的」，内部#254）。先自愈，再核生效值；只认相对的
# .githooks —— 绝对路径在工作区改名后悬空（内部#417）。
[ ! -x "${main}/scripts/heal_hooks_path.sh" ] || "${main}/scripts/heal_hooks_path.sh" "${main}"
hooks=$(git -C "${wt}" config core.hooksPath || true)
case "${hooks}" in
    .githooks) ;;
    *) die "core.hooksPath 是「${hooks:-未设置}」，pre-push 钩子没有挂上；在主仓执行 git config core.hooksPath .githooks 后再推送" ;;
esac

if [ -n "${detach}" ]; then
    cat <<EOF
ok    主工作区与 worktree 都干净
下一步：
  cd ${wt} && source ~/tools/env.sh && ./scripts/fast_check.sh
用完删掉（只删自己建的，toolchain 常备授权第 3 条）：
  git worktree remove ${wt}
EOF
    exit 0
fi
cat <<EOF
ok    主工作区与 worktree 都干净
下一步：
  cd ${wt}
  source ~/tools/env.sh     # 本机没装 direnv，每个新 shell 都要自己来
  分支上跑的实验记录只做开发验证，不随分支提交；合入 main 后在 main 上跑正式记录
EOF
