"""一日三餐卡路里记录 Agent。

用户描述当日进食内容后，Agent 估算每餐热量并持久化到数据库，
同时支持查询指定日期三餐记录与总热量汇总。
"""
import os
import json
import time
from typing import Annotated

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
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


class AuditLogMiddleware(AgentMiddleware):
    """请求级审计中间件：记录每次工具调用（工具名、参数、耗时、错误类型）。

    同时实现同步 wrap_tool_call 与异步 awrap_tool_call，故在 invoke 与 ainvoke
    （含 HTTP /run、/stream_run）两条路径都可用。仅在外围追加结构化审计，
    工具成功时原样返回结果；失败时返回带错误的 ToolMessage，不阻断 agent 循环，
    也不改变业务规则。
    """

    @staticmethod
    def _content(res) -> str:
        if res is None:
            return ""
        c = getattr(res, "content", "")
        if c is None:
            return ""
        return c if isinstance(c, str) else str(c)

    def _log(self, request, ok, dur_ms, err_type="", response=""):
        try:
            tc = getattr(request, "tool_call", None) or {}
            name = _tc_field(tc, "name", "")
            args = _tc_field(tc, "args", {})
            rid = get_or_create_request_id()
            record_tool_call(rid, name, args, duration_ms=dur_ms, ok=ok,
                             error_type=err_type, response=response[:600])
        except Exception:  # 审计绝不能影响业务
            pass

    def _apply(self, request, handler, resp_factory):
        start = time.time()
        try:
            res = handler(request)
            self._log(request, True, (time.time() - start) * 1000, response=self._content(res))
            return res
        except Exception as e:  # noqa: BLE001
            self._log(request, False, (time.time() - start) * 1000,
                      err_type=type(e).__name__)
            return resp_factory(str(e))

    def wrap_tool_call(self, request, handler):
        return self._apply(request, handler, lambda msg: ToolMessage(
            content=f"Tool execute error: ({msg})",
            tool_call_id=_tc_field(getattr(request, "tool_call", None) or {}, "id", ""),
        ))

    async def awrap_tool_call(self, request, handler):
        start = time.time()
        try:
            res = await handler(request)
            self._log(request, True, (time.time() - start) * 1000, response=self._content(res))
            return res
        except Exception as e:  # noqa: BLE001
            self._log(request, False, (time.time() - start) * 1000, err_type=type(e).__name__)
            return ToolMessage(
                content=f"Tool execute error: ({str(e)})",
                tool_call_id=_tc_field(getattr(request, "tool_call", None) or {}, "id", ""),
            )


def _resolve_llm(cfg: dict):
    """解析模型调用配置。

    优先使用外部可访问的 LLM（供自包含外部部署），并兼容 Coze 内网接入点：
    - 设置 EXTERNAL_OPENAI_BASE_URL + EXTERNAL_OPENAI_API_KEY + EXTERNAL_OPENAI_MODEL
      时，走外部 OpenAI 兼容端点（如 llmapi.paratera.com），仅当三者同时满足才切换。
    - 否则回退到 Coze 内网接入点（integration.coze.cn + workload identity）。
    返回 (llm_kwargs, is_external)。
    """
    ext_base = os.getenv("EXTERNAL_OPENAI_BASE_URL")
    ext_key = os.getenv("EXTERNAL_OPENAI_API_KEY")
    ext_model = os.getenv("EXTERNAL_OPENAI_MODEL")
    if ext_base and ext_key and ext_model:
        return {
            "model": ext_model,
            "api_key": ext_key,
            "base_url": ext_base,
            "temperature": float(cfg["config"].get("temperature", 0.6)),
            "streaming": True,
            "timeout": int(cfg["config"].get("timeout", 600)),
            # 外部端点多数非 DeepSeek thinking，不传 extra_body，避免 400
        }, True
    return {
        "model": cfg["config"].get("model"),
        "api_key": os.getenv("COZE_WORKLOAD_IDENTITY_API_KEY"),
        "base_url": os.getenv("COZE_INTEGRATION_MODEL_BASE_URL"),
        "temperature": float(cfg["config"].get("temperature", 0.6)),
        "streaming": True,
        "timeout": int(cfg["config"].get("timeout", 600)),
        "extra_body": {
            "thinking": {
                "type": cfg["config"].get("thinking", "disabled")
            }
        },
    }, False


def build_agent(ctx=None, checkpointer=None):
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
    config_path = os.path.join(workspace_path, LLM_CONFIG)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    llm_kwargs, is_external = _resolve_llm(cfg)
    if not is_external:
        llm_kwargs["default_headers"] = default_headers(ctx) if ctx else {}

    llm = ChatOpenAI(**llm_kwargs)

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

    # 外部主机部署可用内存 checkpointer（外部入口传入），避免 PostgresSaver 事件循环绑定问题
    cp = checkpointer if checkpointer is not None else get_memory_saver()

    return create_agent(
        model=llm,
        system_prompt=cfg.get("sp"),
        tools=tools,
        middleware=[AuditLogMiddleware()],
        checkpointer=cp,
        state_schema=AgentState,
    )