# 国内 VPS（自有主机）稳定部署指南

> 目标：把「AI个性化饮食管理 Agent」部署到国内常驻主机，获得国内访问快、稳定、可写进简历的网址。
> 复用当前 Docker 配置（`Dockerfile.external`），与 Render 上部署的是同一套代码，只是运行环境换成国内 VPS。

---

## 一、前置条件
- 一台**国内云服务器**（阿里云 / 腾讯云 / 华为云轻量均可，建议 2C2G 起，Ubuntu 22.04 或 CentOS 7+）。
- 已安装 **Docker**（含 `docker compose` 可不用）。
- 已把本项目代码放到服务器上（`git clone` 或上传）。
- 准备好环境变量值（LLM key、Supabase 凭据——与 Render 用的那套一致即可）。

---

## 二、在服务器上装 Docker（若未装）
```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录使生效
```

---

## 三、拿到代码
在服务器上执行（或直接用你本地已 clone 的目录上传）：
```bash
cd ~ && git clone <你的仓库地址> ai-diet-agent && cd ai-diet-agent
```
> 如果你不想用 git，也可以把本地项目目录整个 `scp`/上传到服务器，只要包含 `Dockerfile.external`、`src/`、`src_external/`、`assets/`、`config/` 等即可。

---

## 四、配置环境变量并一键部署

### 方式 1：命令行直接传环境变量（推荐，最直接）
```bash
cd ~/ai-diet-agent

EXTERNAL_OPENAI_API_KEY="sk-你的key" \
EXTERNAL_OPENAI_BASE_URL="https://llmapi.paratera.com/v1" \
EXTERNAL_OPENAI_MODEL="DeepSeek-V4-Pro-0813" \
COZE_SUPABASE_URL="https://你的supabase项目域名" \
COZE_SUPABASE_ANON_KEY="你的anon key" \
COZE_SUPABASE_SERVICE_ROLE_KEY="你的service_role key" \
APP_PORT=7860 \
bash scripts/deploy_vps.sh
```

### 方式 2：用 env 文件
```bash
cp .env.vps.example .env.vps.prod
# 编辑 .env.vps.prod，填好各变量
set -a && source .env.vps.prod && set +a
bash scripts/deploy_vps.sh
```

脚本会自动：构建镜像（清华 pip 源加速）→ 启动容器（`--restart unless-stopped` 开机自启）→ 健康检查 `/health`。

---

## 五、开放端口
- 云服务器控制台**安全组**放行端口 `7860`（或你改的 APP_PORT）。
- 本机防火墙（如有）放行：`sudo ufw allow 7860` 或 `firewall-cmd --add-port=7860/tcp`。

---

## 六、访问验证
- 应用地址：`http://<服务器公网IP>:7860`
- 健康检查：`http://<服务器公网IP>:7860/health` → 返回 `{"status":"ok"}`
- 打开页面 → 建档 → 记录一餐 → 验证热量计算。

---

## 七、常用运维命令
```bash
docker logs -f ai-diet-agent      # 看日志
docker restart ai-diet-agent      # 重启容器
docker stop ai-diet-agent && docker rm ai-diet-agent   # 停止并删除（再跑 deploy_vps.sh 重新部署）
```

---

## 八、让网址更"正式"（进阶，可选）
若希望用 80/443 端口 + 域名（才能用 HTTPS、更好写简历）：
1. 把 `APP_PORT` 改为 `80`（或配 Nginx 反代 7860→80）。
2. 域名解析到服务器 IP，配 SSL（可用 acme.sh / certbot 免费证书）。
3. 得到 `https://你的域名` 正式地址。

---

## 九、重要提示
- **关键优势**：主机与国内 LLM 同区域 → 建模/记录快而稳，不再被跨洋超时卡住。
- **数据**：Supabase 复用现有外部库则无需处理；新开库按 `docs/EXTERNAL_SCHEMA.sql` 建表。
- **会话**：使用进程内 MemorySaver；容器重启会清空进行中会话（档案/饮食记录已落库，不丢）。
- **安全**：不要把 `.env.vps.prod`、真实 key 提交到公开仓库。