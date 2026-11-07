#!/bin/bash

set -e
# 导出环境变量

WORK_DIR="${COZE_WORKSPACE_PATH:-.}"
# 平台部署将应用监听端口固定为 :80（端口不可在控制台修改）。
# 因此部署启动脚本默认绑定 80 以匹配平台代理；可用 -p 覆盖。
PORT="${HTTP_RUN_PORT:-80}"

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

# 防端口冲突（自愈 + 防复发）：
# 启动前清理占用目标端口的【本项目 main.py 残留服务】。
# 仅对本项目(main.py)的残留进程下手，绝不影响 9000 系统服务等其它进程。
clean_port() {
  local port="$1" pid cmdline
  for pid in $(ss -ltnp 2>/dev/null | grep -E ":[0-9]+ " | grep -E ":${port}[^0-9]" | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); do
    cmdline=$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)
    if echo "$cmdline" | grep -q "main.py"; then
      echo "[http_run] 检测到端口 ${port} 上本项目残留服务 (PID ${pid})，正在清理..."
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
}

clean_port "$PORT"

echo "[http_run] 启动 Agent HTTP 服务 (port ${PORT})"
python ${WORK_DIR}/src/main.py -m http -p $PORT