#!/usr/bin/env bash
# ============================================================
# AI个性化饮食管理 Agent — 国内 VPS 一键部署脚本
# 用法: bash scripts/deploy_vps.sh
# 前置: 已安装 Docker，且已 clone 本项目到服务器
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

APP_NAME="ai-diet-agent"
IMAGE_NAME="ai-diet-agent:1.0"
HOST_PORT="${APP_PORT:-7860}"          # 宿主机端口，默认 7860，可按需改
CONTAINER_PORT="7860"

# 构建镜像（使用 Dockerfile.external；国内环境建议配置 pip 加速，见文档）
echo "==> [1/4] 构建镜像 ${IMAGE_NAME} ..."
docker build -f Dockerfile.external -t "${IMAGE_NAME}" .

# 停止并移除旧容器（若存在）
echo "==> [2/4] 清理旧容器（如有）..."
docker rm -f "${APP_NAME}" >/dev/null 2>&1 || true

# 运行容器
echo "==> [3/4] 启动容器 ${APP_NAME} (端口 ${HOST_PORT}) ..."
docker run -d --name "${APP_NAME}" \
  --restart unless-stopped \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  -e EXTERNAL_MODE=1 \
  -e EXTERNAL_OPENAI_BASE_URL="${EXTERNAL_OPENAI_BASE_URL:-https://llmapi.paratera.com/v1}" \
  -e EXTERNAL_OPENAI_API_KEY="${EXTERNAL_OPENAI_API_KEY:?需要设置 EXTERNAL_OPENAI_API_KEY}" \
  -e EXTERNAL_OPENAI_MODEL="${EXTERNAL_OPENAI_MODEL:-DeepSeek-V4-Pro-0813}" \
  -e EXTERNAL_KNOWLEDGE_DISABLED=1 \
  -e COZE_SUPABASE_URL="${COZE_SUPABASE_URL}" \
  -e COZE_SUPABASE_ANON_KEY="${COZE_SUPABASE_ANON_KEY}" \
  -e COZE_SUPABASE_SERVICE_ROLE_KEY="${COZE_SUPABASE_SERVICE_ROLE_KEY}" \
  -e EXTERNAL_CORS_ORIGINS="${EXTERNAL_CORS_ORIGINS:-*}" \
  "${IMAGE_NAME}"

echo "==> [4/4] 等待健康检查..."
sleep 6
echo "健康检查:"
curl -fsS "http://127.0.0.1:${HOST_PORT}/health" && echo " <- /health OK" || { echo "健康检查失败，查看日志:"; docker logs --tail 50 "${APP_NAME}"; exit 1; }

echo ""
echo "✅ 部署成功！"
echo "   访问地址: http://<你的服务器公网IP>:${HOST_PORT}"
echo "   健康检查: http://<你的服务器公网IP>:${HOST_PORT}/health"
echo "   查看日志: docker logs -f ${APP_NAME}"