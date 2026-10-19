"""一日三餐卡路里记录 Agent。

用户描述当日进食内容后，Agent 估算每餐热量并持久化到数据库，
同时支持查询指定日期三餐记录与总热量汇总。
"""
import os
import json
import time
from typing import Annotated

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage, ToolMessage
from coze_coding_utils.runtime_ctx.context import default_headers

from storage.memory.memory_saver import get_memory_saver
from tools.meal_tools import save_meal_record, get_daily_intake
from tools.profile_tools import save_user_profile, get_user_profile, save_diet_plan, delete_user_profile
from tools.intake_tools import knowledge_search, diet_nutrition_agent
from tools.audit_log import record_tool_call
from tools.request_id import get_or_create_request_id

LLM_CONFIG = "config/agent_llm_config.json"

# 默认保留最近 20 轮对话 (40 条消息)
MAX_MESSAGES = 40


def _windowed_messages(old, new):
    """滑动窗口: 只保留最近 MAX_MESSAGES 条消息"""
    return add_messages(old, new)[-MAX_MESSAGES:]  # type: ignore


class AgentState(MessagesState):
    messages: Annotated[list[AnyMessage], _windowed_messages]


def _tc_field(tc, key, default=None):
    """兼容地从 tool_call 读取字段（dict 或对象）。"""
    if isinstance(tc, dict):
        return tc.get(key, default)
    return getattr(tc, key, default)


@wrap_tool_call
def audit_tool_calls(request, handler):
    """请求级审计中间件：记录每次工具调用（工具名、参数、耗时、错误类型）。

    仅在代理的工具执行外围追加结构化审计，绝不影响工具返回值与业务逻辑。
    """
    tc = getattr(request, "tool_call", None) or {}
    tool_name = _tc_field(tc, "name", "")
    tool_args = _tc_field(tc, "args", {})
    rid = get_or_create_request_id()
    start = time.time()
    try:
        res = handler(request)
        record_tool_call(rid, tool_name, tool_args,
                         duration_ms=(time.time() - start) * 1000, ok=True)
        return res
    except Exception as e:  # noqa: BLE001
        record_tool_call(rid, tool_name, tool_args,
                         duration_ms=(time.time() - start) * 1000, ok=False,
                         error_type=type(e).__name__)
        return ToolMessage(
            content=f"Tool execute error: ({str(e)})",
            tool_call_id=_tc_field(tc, "id", ""),
        )


def build_agent(ctx=None):
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
    config_path = os.path.join(workspace_path, LLM_CONFIG)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    api_key = os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY")
    base_url = os.getenv("COZE_INTEGRATION_MODEL_BASE_URL")

    llm = ChatOpenAI(
        model=cfg["config"].get("model"),
        api_key=api_key,
        base_url=base_url,
        temperature=cfg["config"].get("temperature", 0.6),
        streaming=True,
        timeout=cfg["config"].get("timeout", 600),
        extra_body={
            "thinking": {
                "type": cfg["config"].get("thinking", "disabled")
            }
        },
        default_headers=default_headers(ctx) if ctx else {},
    )

    tools = [
        save_meal_record,
        get_daily_intake,
        save_user_profile,
        get_user_profile,
        save_diet_plan,
        delete_user_profile,
        knowledge_search,
        diet_nutrition_agent,
    ]

    return create_agent(
        model=llm,
        system_prompt=cfg.get("sp"),
        tools=tools,
        middleware=[audit_tool_calls],
        checkpointer=get_memory_saver(),
        state_schema=AgentState,
    )