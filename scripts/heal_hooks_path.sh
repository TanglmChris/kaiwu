#!/usr/bin/env bash
# core.hooksPath 自愈（内部#254、内部#417）：.githooks/pre-push 只在 core.hooksPath 指向 .githooks 时才会运行，
# 挂不上时 git 静默跳过钩子，与「钩子跑过并通过」在外部看来完全一样（guardrail-scope「护栏的挂载状态
# 必须是自愈的或可见的」）。
#
# 值只认相对的 .githooks：git 对相对值按各工作副本的根解析，每个 worktree 用自己检出的钩子；绝对路径
# 在工作区改名后就悬空（10-25 工作区目录改名时实撞，内部#417）。要改的有两处：公共 .git/config，
# 以及开了 extensions.worktreeConfig 时各 worktree 自己的 config.worktree —— 后者优先于前者，只改
# 公共配置盖不住它。
#
# 用法：scripts/heal_hooks_path.sh [仓库内任一目录]。仓库里没有可执行的 .githooks/pre-push 时什么也不做
# （夹具仓、别的仓）。值已经对时不写、不打印；改了就打印一行 note。.envrc、new_worktree.sh、fast_check.sh
# 都调它。
set -u
dir="${1:-.}"
root=$(git -C "$dir" rev-parse --show-toplevel 2> /dev/null) || exit 0
[ -x "$root/.githooks/pre-push" ] || exit 0
common=$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2> /dev/null) || exit 0

fixed=()
if [ "$(git -C "$dir" config --local core.hooksPath 2> /dev/null)" != ".githooks" ]; then
    git -C "$dir" config --local core.hooksPath .githooks && fixed+=("${common}/config")
fi
for f in "$common"/config.worktree "$common"/worktrees/*/config.worktree; do
    [ -f "$f" ] || continue
    v=$(git config -f "$f" core.hooksPath 2> /dev/null) || continue
    if [ "$v" != ".githooks" ]; then
        git config -f "$f" core.hooksPath .githooks && fixed+=("$f")
    fi
done
if [ "${#fixed[@]}" -gt 0 ]; then
    for f in "${fixed[@]}"; do printf '%s\n' "note  core.hooksPath 已自愈为 .githooks：${f}"; done
fi
exit 0
