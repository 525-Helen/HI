# 生产 API 安全后端集成指南（路线 A）

> 本页面向**后端/服务端**集成说明如何使用扣子正式部署的「智能体 API」渠道。
> 重要：**API Token 只允许出现在后端环境变量中，严禁写入前端页面、浏览器 JS、日志或提交到 Git。**

## 1. 两种入口（角色区分）

| 用途 | 地址 | 鉴权 | 适用对象 |
|---|---|---|---|
| **产品网页应用**（自定义响应式 UI，多用户隔离） | `https://949a3887-2c31-47e1-8fe2-c4dfdabc17db.dev.coze.site` | 无 | 直接给普通用户使用（浏览器直接打开） |
| **正式 Agent API**（官方部署，后端集成用） | `https://chat416wszbd.coze.site/run` | `Authorization: Bearer <API Token>` | 你自己的后端/服务端程序调用 |

## 2. 正式 Agent API 调用方式（后端）

### 请求
```
POST https://chat416wszbd.coze.site/run
Content-Type: application/json
Authorization: Bearer <API_TOKEN>     # 从后端环境变量读取，绝不打进前端
```

请求体（与平台「执行智能体」接口一致）：
```json
{
  "content": {
    "query": [
      { "type": "text", "content": { "text": "今天午餐吃了200克鸡胸肉" } }
    ]
  },
  "type": "query",
  "session_id": "yours-backend-managed-session-id",
  "project_id": 7685654374525288463
}
```

### 响应（同步 JSON，已实测）
```json
{
  "run_id": "...",
  "messages": [
    { "type": "ai",   "content": "...最终回答..." },
    ...
  ]
}
```
> 本接口为**同步**执行；另有流式 `POST /stream_run`（SSE，`text/event-stream`）与异步执行、查询异步任务等端点。

## 3. 后端安全用法示例（Python，读取环境变量）

```python
import os, requests

TOKEN = os.environ["KAKA_CHANNEL_TOKEN"]   # 由后端运维注入环境变量

def call_agent(text: str, session_id: str) -> str:
    resp = requests.post(
        "https://chat416wszbd.coze.site/run",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "content": {"query": [{"type": "text", "content": {"text": text}}]},
            "type": "query",
            "session_id": session_id,
            "project_id": 7685654374525288463,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    # 取最后一条 type=="ai" 且非空的 content 作为最终回复
    for m in reversed(data.get("messages", [])):
        if m.get("type") == "ai" and isinstance(m.get("content"), str) and m["content"].strip():
            return m["content"]
    return ""
```

## 4. ⚠️ 必须知晓的信道特性（避免误用）

1. **无会话记忆（按调用无状态）**：`session_id` 不保留多轮上下文。若你的后端需要多轮对话，请**自行累积对话历史，并在每次请求的 `text` 中拼接完整上下文**。
2. **无按用户隔离**：该信道不接收 `x-user-id`，Agent 内部数据库操作会落到共享默认档案。**不适合做多租户/多用户数据隔离**——这正是我们保留自建网页应用作为普通用户入口的原因。
3. **Agent 行为与自建引擎可能存在差异**（实测同一句"200克鸡胸肉+150克米饭"在信道上有被误判为"面"的情况）。关键业务（过敏拦截、精确热量、隔离）请优先走自建网页应用引擎。

## 5. 安全红线（务必遵守）
- Token 仅存在于后端**环境变量**（如 `export KAKA_CHANNEL_TOKEN="..."`），不在代码仓库、不在前端、不写日志。
- 前端若需调用，应经由你自己的后端转发（后端持有 Token），而不是把 Token 发给浏览器。
- 发布/回滚时注意不要误把 Token 打进构建产物。

## 6. 常见问题
- **403 invalid token**：请确认用的确实是本项目渠道 `API Token`（在部署页「API Token」生成），并确认真有效。
- **`/stream_run` 长时间无数据**：属正常（SSE 长连接等待 Agent 产出）；非流式 `POST /run` 更易集成。
- **跨域/CORS**：供浏览器直连时需在后端对本域名显式放行（本自建服务已放行 `https://.*\.coze\.site` 与 `goodhare128.chatgpt.site`）。