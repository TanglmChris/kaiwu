#!/bin/sh
# 全机 CPU 巡检的主机定时任务（内部#359，cpu-watch D6）：launchd 每 5 分钟跑一次 `flow/cpu_watch.py --post <群>`。
#
#   flow/cpu_watch_agent.sh install <群>  # keel chat 群名；在管 CPU 的角色绑定的 worktree 里跑（发消息的角色按工作目录认）
#   flow/cpu_watch_agent.sh uninstall
#   flow/cpu_watch_agent.sh status
#
# 不用会话级定时：会话一结束就停了。日志在 ~/Library/Logs/kaiwu-cpu-watch.log。
set -eu
LABEL=com.kaiwu.cpu-watch
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/kaiwu-cpu-watch.log"
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"

case "${1:-}" in
install)
    GROUP="${2:-}"
    [ -n "$GROUP" ] || { echo "用法：$0 install <keel chat 群名>" >&2; exit 2; }
    KEEL="$(command -v keel)" || { echo "keel 不在 PATH，巡检发不了群消息" >&2; exit 2; }
    [ -x "$ROOT/.venv/bin/python3" ] || { echo "${ROOT}/.venv/bin/python3 不存在" >&2; exit 2; }
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/.venv/bin/python3</string>
    <string>$ROOT/flow/cpu_watch.py</string>
    <string>--post</string>
    <string>$GROUP</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$(dirname "$KEEL"):/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "已装：${PLIST}（每 5 分钟点名到群 ${GROUP}，工作目录 ${ROOT}，日志 ${LOG}）"
    ;;
uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "已卸：${LABEL}"
    ;;
status)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|last exit|runs|path" || echo "${LABEL} 没装"
    [ -f "$LOG" ] && tail -5 "$LOG"
    ;;
*)
    echo "用法：$0 install <群>|uninstall|status" >&2
    exit 2
    ;;
esac
