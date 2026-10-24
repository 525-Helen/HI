"""自包含外部常驻主机入口（路线 B）。

用于在无 Coze 运行环境的外部常驻主机（Render / 云主机 / Docker）上，以
「完整 Agent 能力」稳定提供服务。与平台版相比的差异与取舍：
- 模型接入点：改用外部 OpenAI 兼容端点（EXTERNAL_OPENAI_BASE_URL / API_KEY / MODEL），
  不再依赖 Coze 内网 integration.coze.cn。Agent 逻辑零改动（见 agents/agent.py 的 _resolve_llm）。
- 会话记忆：使用内存 MemorySaver（无需外部建 Postgres 记忆表）。注意重启即清空会话，
  数据持久化（档案/饮食记录）仍走 Supabase，不受影响。
- 营养知识问答：外部无 Coze 托管知识库时，knowledge_search 降级为「通用营养常识」回答
  （EXTERNAL_KNOWLEDGE_DISABLED=1 时生效，见 tools/intake_tools.py）。
- 接口协议：与平台版 /run 保持一致（请求体 {messages:[...]}，响应 {messages:[...], run_id}），
  前端 assets/frontend/index.html 用相对路径 /run 调用，开箱即用。

启动：uvicorn src.external_main:app --host 0.0.0.0 --port ${PORT:-7860}
"""
import json
import logging
import os
import uuid

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver

from agents.agent import build_agent
from tools.request_id import set_request_id, set_current_user
from tools.request_date import reset_request_date

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HEADER_X_RUN_ID = "x-run-id"
PROJECT_ID = os.getenv("EXTERNAL_PROJECT_ID", "ai-diet-agent-external")

app = FastAPI(title="AI Diet Agent (External)")

# CORS：允许外部接入方（含自定义前端）跨域调用
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("EXTERNAL_CORS_ORIGINS", "*").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局单例 checkpointer：外部使用内存持久（进程内有效，数据表落库不影响）
_checkpointer = MemorySaver()


def _new_run_id() -> str:
    return str(uuid.uuid4())


def _extract_user_text(messages: Any) -> str:
    """从平台 /run 请求体 messages 中提取最新一条用户文本（支持 str 与 {content:text} 形态）。"""
    if not messages:
        return ""
    if not isinstance(messages, list):
        messages = [messages]
    text_parts: List[str] = []
    for m in messages:
        if isinstance(m, str):
            text_parts.append(m)
        elif isinstance(m, dict):
            content = m.get("content")
            role = m.get("role")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, dict):
                text_parts.append(str(content.get("text", "")))
            elif isinstance(content, list):
                for seg in content:
                    if isinstance(seg, dict) and seg.get("type") == "text":
                        text_parts.append(str(seg.get("content", {}).get("text", "") if isinstance(seg.get("content"), dict) else seg.get("content", "")))
                    elif isinstance(seg, dict) and seg.get("content"):
                        text_parts.append(str(seg.get("content")))
    return "\n".join([p for p in text_parts if p])


def _build_payload(user_query: str, run_id: str, headers) -> Dict[str, Any]:
    """构造传给 Agent（LangChain create_agent）的标准消息负载。"""
    run_config = {"configurable": {"thread_id": run_id}}
    return {
        "messages": [{"role": "user", "content": user_query}],
        "run_id": run_id,
        "canvas_input": {"messages": [{"role": "user", "content": user_query}]},
    }, run_config


def _extract_ai_reply(result: Any) -> str:
    """从 Agent 运行结果中提取最终的 AI 回复文本。"""
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            for m in reversed(messages):
                msg_type = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else None)
                if msg_type in ("ai", "AIMessage", "assistant"):
                    content = getattr(m, "content", None)
                    if isinstance(m, dict):
                        content = m.get("content")
                    if content:
                        if isinstance(content, list):
                            return "".join(str(s.get("text", "")) for s in content if isinstance(s, dict) and s.get("text"))
                        return str(content)
        # 兼容 {output: "..."} 形态（create_agent 返回）
        for key in ("output", "final_output"):
            if result.get(key):
                return str(result[key])
    return ""


@app.on_event("startup")
def _startup():
    try:
        from storage.database.db import get_session  # noqa: F401 触发 env 加载检查（可忽略）
    except Exception:  # noqa: BLE001
        pass
    logger.info("External agent entry loaded.")


@app.get("/", include_in_schema=False)
@app.get("/ui", include_in_schema=False)
async def serve_ui():
    """提供「AI个性化饮食管理 Agent」移动端前端。"""
    workspace = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
    ui_path = os.path.join(workspace, "assets", "frontend", "index.html")
    try:
        with open(ui_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        html = "<h2>前端页面缺失</h2>"
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Service is running"}


@app.post("/run")
async def http_run(request: Request) -> Dict[str, Any]:
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    run_id = request.headers.get(HEADER_X_RUN_ID) or payload.get("run_id") or _new_run_id()
    user_id = request.headers.get("x-user-id", "") or payload.get("user_id", "")

    # 请求级上下文
    set_request_id(str(uuid.uuid4()))
    reset_request_date()
    set_current_user(user_id or "")

    user_query = _extract_user_text(payload.get("messages"))
    if not user_query:
        return {
            "run_id": run_id,
            "messages": [{"type": "ai", "content": "请描述您的饮食情况，例如：'午饭吃了200g米饭和150g鸡胸肉'。"}],
        }

    agent = build_agent(checkpointer=_checkpointer)
    _, run_config = _build_payload(user_query, run_id, request.headers)

    try:
        # 同步构建一个包含单条用户消息 + 会话 thread 的完整消息数组
        from langchain_core.messages import HumanMessage, AIMessage
        msgs = []
        # 若前端传了多轮 history，重组为 LangChain 消息（支持上下文延续）
        hist = payload.get("messages") or []
        for m in hist:
            if isinstance(m, dict):
                role = m.get("role")
                content = m.get("content")
                if isinstance(content, dict):
                    content = content.get("text", "")
                elif isinstance(content, list):
                    _parts = []
                    for seg in content:
                        if isinstance(seg, dict) and seg.get("type") == "text":
                            _parts.append(str(seg.get("content", {}).get("text", "") if isinstance(seg.get("content"), dict) else seg.get("content", "")))
                    content = "".join(_parts)
                if not content:
                    continue
                if role in ("user", "human"):
                    msgs.append(HumanMessage(content=str(content)))
                else:
                    msgs.append(AIMessage(content=str(content)))
        if not msgs:
            msgs = [HumanMessage(content=user_query)]

        result = await agent.ainvoke(
            {"messages": msgs},
            config=run_config,
        )
        reply = _extract_ai_reply(result)
        return {
            "run_id": run_id,
            "messages": [
                {"type": "human", "content": user_query},
                {"type": "ai", "content": reply},
            ],
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("External /run failed")
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {e}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)