#!/usr/bin/env bash
# 自定义 UI 服务守护：确保 src/main.py -m http -p 5000 在崩溃/被杀后自动拉起。
# 用于 DEV 预览域名场景的进程级自愈（容器休眠/重启场景不在此脚本能力内）。
# 用法：bash scripts/keep_alive.sh &
set -u
WORK_DIR="${COZE_WORKSPACE_PATH:-.}"
PORT="${KAKA_UI_PORT:-5000}"
LOG="${KAKA_UI_LOG:-/tmp/kaka_keepalive.log}"
while true; do
  if ! pgrep -f "main.py -m http -p ${PORT}" >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] restarting ui on :${PORT}" >> "$LOG"
    ( cd "$WORK_DIR" && nohup python src/main.py -m http -p "$PORT" >> /tmp/kaka5000.log 2>&1 & )
  fi
  sleep 15
done