#!/bin/bash

set -e

WORK_DIR="${COZE_WORKSPACE_PATH:-.}"

# 端口优先级（不硬编码 80）：
#  1) 平台提供 DEPLOY_RUN_PORT（本环境为 5000）
#  2) 显式环境变量 HTTP_RUN_PORT
#  3) 兜底 5000（与平台/keep_alive.sh 一致）
# 说明：系统服务固定占用 9000（_FAAS_RUNTIME_PORT），此处绝不触碰该端口。
PORT="${DEPLOY_RUN_PORT:-${HTTP_RUN_PORT:-5000}}"

usage() {
  echo "用法: $0 -p <端口>"
}

while getopts "p:h" opt; do
  case "$opt" in
    p)
      PORT="$OPTARG"
      ;;
    h)
      usage
      exit 0
      ;;
    \?)
      echo "无效选项: -$OPTARG"
      usage
      exit 1
      ;;
  esac
done

# 激活 .venv（devbox 环境），deploy 无 .venv 则跳过
if [ -f "${WORK_DIR}/.venv/bin/activate" ]; then
  source "${WORK_DIR}/.venv/bin/activate"
fi

# 单实例守卫：清理占用目标端口的【本项目 main.py 残留服务】后启动，
# 保证同一时刻只存在一个 Agent HTTP 实例；明确排除 9000 系统服务等其它进程。
clean_project_on_port() {
  local port="$1" pid cmdline
  for pid in $(ss -ltnp 2>/dev/null | grep -E ":${port}[^0-9]" | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); do
    cmdline=$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)
    if echo "$cmdline" | grep -q "main.py"; then
      echo "[http_run] 清理端口 ${port} 上本项目残留服务 (PID ${pid})"
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
}

clean_project_on_port "$PORT"

echo "[http_run] 端口来源: DEPLOY_RUN_PORT=${DEPLOY_RUN_PORT:-未设置}，本次监听端口=${PORT}"
echo "[http_run] 启动 Agent HTTP 服务 ..."
# exec 使 uvicorn 成为主进程；启动失败时它会在日志中直接输出实际监听地址/端口与原因(如 [Errno 98] Address already in use)
exec python ${WORK_DIR}/src/main.py -m http -p "$PORT"