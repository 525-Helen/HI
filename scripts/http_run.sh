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

python ${WORK_DIR}/src/main.py -m http -p $PORT
