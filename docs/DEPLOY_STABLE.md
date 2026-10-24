# 外部常驻主机稳定部署指南（路线 B：完整自包含）

> 目标：在一个**始终在线**的外部主机（推荐 Render）上部署，获得稳定的 HTTPS 入口
> `https://<服务名>.onrender.com`，供简历展示与长期使用。
>
> 与平台版（Coze 内网）的差异：仅替换「模型接入点」为你的外部 LLM，并让营养知识问答
> 退回通用常识；**建档 / 饮食记录 / 精确计算 / 画像修改 / 过敏拦截 / 多用户隔离 / 多轮上下文
> 全部保留**（已验证）。

---

## 1. 前置条件（你需要准备的）

| 项 | 说明 | 本项目的现成值/建议 |
|---|---|---|
| GitHub 账号 | 用于把仓库推上去，Render 从仓库部署 | 无 |
| Render 账号 | 免费注册，GitHub 登录即可 | https://render.com |
| **外部 OpenAI 兼容 LLM Key** | 决定能否在外部主机调用模型 | 你已提供 `llmapi.paratera.com`，模型 `DeepSeek-V4-Pro-0813`（已验证可用） |
| Supabase（Postgres） | 存档案/饮食记录 | 你已提供（`...supabase2.aidap-global.cn-beijing.volces.com`），需确认外部可达 |

> ⚠️ **Supabase 外部可达性**：当前库托管在火山引擎 `volces.com` 公网域名，大概率外部可直连；
> 部署后在 Render 上验证一次 `/run` 建档即可确证。若不可达，另开一个 [Supabase](https://supabase.com)
> 新项目（免费），用 `docs/EXTERNAL_SCHEMA.sql` 建表，把 URL/anon/service_role 填进环境变量即可。

---

## 2. 环境变量清单

见 [.env.example](../.env.example)（本地用）与 [render.yaml](../render.yaml)（Render 用）。

| 变量 | 必填 | 说明 |
|---|---|---|
| `EXTERNAL_OPENAI_BASE_URL` | ✅ | 外部 LLM Base URL，以 `/v1` 结尾 |
| `EXTERNAL_OPENAI_API_KEY` | ✅ | 你的外部 LLM Key（服务端 Secret） |
| `EXTERNAL_OPENAI_MODEL` | ✅ | 模型名，如 `DeepSeek-V4-Pro-0813` |
| `COZE_SUPABASE_URL` | ✅ | Supabase 项目 URL |
| `COZE_SUPABASE_ANON_KEY` | ✅ | Supabase anon key（Secret） |
| `COZE_SUPABASE_SERVICE_ROLE_KEY` | 建议 | service_role key（写档案/删记录用） |
| `EXTERNAL_KNOWLEDGE_DISABLED` | ✅ | 外部环境必须设 `1`（见第 4 节） |
| `PORT` | 自动 | Render 自动注入；本地默认 7860 |
| `EXTERNAL_CORS_ORIGINS` | 可选 | 跨域来源，默认 `*` |

---

## 3. 首次部署到 Render（约 5 分钟）

### 方式 A：Blueprint（推荐，最省事）
1. 把本项目推到你的 GitHub 私有仓库。
2. Render → **New → Blueprint**，选择该仓库。
3. Render 读取根目录 `render.yaml`，自动创建 Web Service。
4. 创建时补填 `sync: false` 的三个 Secret：
   `EXTERNAL_OPENAI_API_KEY`、`COZE_SUPABASE_ANON_KEY`、`COZE_SUPABASE_SERVICE_ROLE_KEY`。
5. Deploy。完成后顶部即显示你的稳定地址：`https://ai-diet-agent.onrender.com`。

### 方式 B：手动 Web Service
1. Render → **New → Web Service** → 连接你的 GitHub 仓库。
2. Runtime 选 **Docker**，Dockerfile 填 `Dockerfile.external`。
3. 添加上述全部环境变量。
4. Deploy。

### 部署后检查
- 浏览器打开 `https://<服务名>.onrender.com/` → 应看到「AI个性化饮食管理 Agent」移动端首页（无需登录）。
- `https://<服务名>.onrender.com/health` → `{"status":"ok",...}`。
- 在首页填写档案 → 保存成功；对话页发「午饭吃了200g米饭和150g鸡胸肉」→ 应返回 ~480 kcal 精确计算。

---

## 4. 关于「营养知识问答」的降级说明（务必知晓）

- 平台版用 **Coze 托管的向量知识库**（按 `doc_id` 检索），无法搬出到外部主机。
- 外部部署设置了 `EXTERNAL_KNOWLEDGE_DISABLED=1` 后，`knowledge_search` **不会调用任何外部知识库**，
  而是返回一条提示，让 Agent 凭**通用营养常识**回答（并如实说明非权威来源）。
- 影响范围：仅「营养知识百科问答」这一类；**记录 / 热量 / 隔离 / 上下文 不受影响**。

> 如果你希望外部也具备强引用的营养知识，可后续把营养知识整理成文本，接入 Supabase
> `pgvector` + 任意 embedding，做本地 RAG——需要时我再帮你加。

---

## 5. 会话记忆与数据说明（如实告知）

| 能力 | 机制 | 备注 |
|---|---|---|
| 用户档案 / 饮食记录 | Supabase（Postgres）持久化 | 重启不丢 |
| 多轮会话上下文 | 内存 MemorySaver（进程级） | 外部主机为避免建 Postgres 记忆表，用内存实现；**进程重启会清空当前会话上下文**（历史饮食/档案不受影响）。免费计划的冷启动会重置。 |
| 多用户隔离 | `user_id` 过滤 | 已验证 A/B 用户互不可见 |

> 若需要「重启也不丢会话上下文」，可改用 Postgres 版 checkpointer（`render.yaml` 加一个 Postgres 服务），
> 这属于后续优化项。

---

## 6. 稳定性与简历呈现建议

- Render **免费计划**有冷启动（闲置后首次请求慢 10~30s），简历演示 / 面试现场可能稍慢。
  建议升级到 **Starter（$7/月）** 获得持续常驻，规避冷启动。
- 得到稳定地址后，简历上可写：
  > 独立开发并部署「AI 饮食管理 Agent」至公网（`https://ai-diet-agent.onrender.com`），
  > 支持自然语言饮食记录、热量/营养精确计算、用户画像与过敏拦截、多用户数据隔离、多轮上下文，
  > 后端基于 Agent 编排（LangChain + 工具调用）+ Supabase 持久化。

---

## 7. 本地/沙箱自测命令

```bash
# 用外部 LLM 跑精简入口（需先设置上述外部 env，或复制 .env.example 为 .env）
export COZE_WORKSPACE_PATH="$PWD"
export PYTHONPATH="$PWD/src"
export EXTERNAL_OPENAI_BASE_URL="https://llmapi.paratera.com/v1"
export EXTERNAL_OPENAI_API_KEY="<你的key>"
export EXTERNAL_OPENAI_MODEL="DeepSeek-V4-Pro-0813"
export EXTERNAL_KNOWLEDGE_DISABLED=1
# 再 export COZE_SUPABASE_URL / _ANON_KEY / _SERVICE_ROLE_KEY

python src/external_main.py          # 8086 监听，http://localhost:8086/
```

端到端验证脚本（已在沙箱真实跑通）：`PYTHONPATH=src python scripts/verify_e2e_external.py`