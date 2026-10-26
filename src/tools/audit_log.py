"""请求级审计日志与运行指标（V6 产品化收尾）。

能力：
1. 请求级审计：request_id、意图(intent)、工具调用及参数(tool/tool_args)、耗时(duration_ms)、错误类型(error_type)。
2. 运行指标：平均响应时间（工具处理段，按 request_id 聚合）、工具失败率、分工具/分意图统计。
3. 无法获取的指标（Token 消耗 / 调用成本）明确标记为「未接入」：需模型网关计费元数据，当前不在 agents 层采集。

审计事件以结构化 JSON 追加写入主日志文件（与根日志同文件），
每条事件带 audit_type/ts/request_id 字段，便于运营检索与指标回放。
本模块只做追加与只读统计，绝不抛出异常，不阻塞业务。
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger("audit")

# 工具名 -> 意图标签；请求级意图取该请求内首个核心工具。
TOOL_INTENT = {
    "save_meal_record": "save_record",
    "get_daily_intake": "query_history",
    "save_user_profile": "profile_write",
    "delete_user_profile": "profile_delete",
    "get_user_profile": "profile_read",
    "save_diet_plan": "diet_plan",
    "knowledge_search": "knowledge_qa",
    "diet_nutrition_agent": "nutrition_calc",
}

DEFAULT_LOG_FILE = "/app/work/logs/bypass/app.log"


def _get_log_file() -> str:
    override = os.environ.get("COZE_AUDIT_LOG_FILE")
    if override and override.strip():
        return override.strip()
    try:
        import coze_coding_utils.log.node_log as nl
        if getattr(nl, "LOG_FILE", None):
            return nl.LOG_FILE
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_LOG_FILE


def _safe_args(args) -> str:
    """参数序列化为 JSON 字符串，防循环引用与超长。"""
    try:
        s = json.dumps(args, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        try:
            s = str(args)
        except Exception:  # noqa: BLE001
            s = "<unserializable>"
    return s[:800]


def _safe_resp(resp) -> str:
    """工具返回内容摘要化（截断），用于审计原始结果。"""
    try:
        s = str(resp)
    except Exception:  # noqa: BLE001
        s = "<unserializable>"
    return s[:600]


def _emit(ev: dict) -> None:
    """以顶层 JSON 字段写入主日志文件；审计失败绝不阻断业务。

    用 extra= 传入事件字段，使 audit_type/request_id/tool 等成为日志 JSON 的
    顶层键（而非被包进 message），便于 metrics 直接 json.loads 解析。
    """
    ev.setdefault("ts", int(time.time() * 1000))
    try:
        logger.info("AUDIT_EVENT", extra=dict(ev))
    except Exception:  # noqa: BLE001
        pass


def record_tool_call(request_id, tool, args=None, duration_ms=0.0, ok=True, error_type="", response=""):
    """记录一次工具调用（含参数、耗时、错误类型与原始返回摘要）。

    - args：调用入参（含 meal_date 等字段，随 tool 不同而不同）
    - response：工具返回内容摘要；save_meal_record 的响应含 created/duplicate/落库日期，
      可用于统计 save_count 与核对落库日期。
    """
    _emit({
        "audit_type": "tool_call",
        "request_id": str(request_id or ""),
        "intent": TOOL_INTENT.get(tool, "unknown"),
        "tool": tool,
        "tool_args": _safe_args(args),
        "duration_ms": round(float(duration_ms or 0), 2),
        "ok": bool(ok),
        "error_type": str(error_type or ("ok" if ok else "ERROR")),
        "tool_response": _safe_resp(response) if response not in (None, "") else "",
    })


def _load_events(last_lines: int = 3000) -> list:
    """读取主日志尾部，解析出审计事件（tool_call/request）。"""
    path = _get_log_file()
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            tail = f.readlines()[-last_lines:]
    except Exception:  # noqa: BLE001
        return events
    _RE = re.compile(r'^\{.*"audit_type".*\}\s*$')
    for line in tail:
        line = line.strip()
        if '"audit_type"' not in line:
            continue
        if not _RE.match(line):
            # 容错：JSON 行可能被 append 到含前缀的日志中，尝试定位到 '{'
            pos = line.find('{"')
            if pos < 0:
                continue
            line = line[pos:]
        try:
            obj = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if obj.get("audit_type") == "tool_call":
            events.append(obj)
    return events


def compute_metrics(last_lines: int = 3000) -> dict:
    """基于审计日志回放，计算运行指标（只读，不产生副作用）。

    返回：
    - tool_calls_total / tool_calls_failed / tool_failure_rate
    - avg_tool_duration_ms 单次工具调用平均耗时
    - avg_request_duration_ms 每个请求的工具处理段平均耗时
    - by_tool / by_error 分桶
    - usage 说明（Token/调用成本未接入）
    - note 指标体系口径说明
    """
    events = _load_events(last_lines)

    tool_calls_total = len(events)
    failed = [e for e in events if not e.get("ok")]
    tool_calls_failed = len(failed)
    durations = [float(e.get("duration_ms") or 0) for e in events]
    avg_tool_duration_ms = round(sum(durations) / len(durations), 2) if durations else 0.0

    # 按 request_id 聚合为"请求的工具处理段耗时"
    req_agg: dict = {}
    for e in events:
        rid = e.get("request_id") or ""
        agg = req_agg.setdefault(rid, {"sum": 0.0, "n": 0})
        agg["sum"] += float(e.get("duration_ms") or 0)
        agg["n"] += 1
    req_times = [a["sum"] for a in req_agg.values() if a["n"] > 0]
    avg_request_duration_ms = round(sum(req_times) / len(req_times), 2) if req_times else 0.0

    by_tool: dict = {}
    by_error: dict = {}
    # save_count：保存记录（save_meal_record）的调用次数与成功入账(created=true)次数
    save_attempts = 0
    created_saves = 0
    for e in events:
        t = e.get("tool") or "unknown"
        b = by_tool.setdefault(t, {"calls": 0, "failed": 0, "duration_ms": 0.0})
        b["calls"] += 1
        b["duration_ms"] += float(e.get("duration_ms") or 0)
        if not e.get("ok"):
            b["failed"] += 1
            err = e.get("error_type") or "ERROR"
            by_error[err] = by_error.get(err, 0) + 1
        if t == "save_meal_record":
            save_attempts += 1
            if re.search(r'"created"\s*:\s*true', e.get("tool_response") or ""):
                created_saves += 1

    return {
        "tool_calls_total": tool_calls_total,
        "tool_calls_failed": tool_calls_failed,
        "tool_failure_rate": round(tool_calls_failed / tool_calls_total, 4) if tool_calls_total else 0.0,
        "avg_tool_duration_ms": avg_tool_duration_ms,
        "avg_request_duration_ms": avg_request_duration_ms,
        "requests_count": len(req_agg),
        "save_count": {
            "save_attempts": save_attempts,
            "created_saves": created_saves,
            "note": "created_saves 由 save_meal_record 响应中的 created=true 统计，即实际新增入账数；duplicate 属于幂等未新增。",
        },
        "by_tool": by_tool,
        "by_error": by_error,
        "usage": {
            "tokens": None,
            "cost": None,
            "status": "not_connected",
            "note": "Token 消耗与调用成本未接入：需在模型网关层采集计费/UsageMetadata，agents 层当前不采集。",
        },
        "note": "avg_request_duration_ms 为请求内全部工具处理段耗时之和（不含纯 LLM 生成段）。接口级端到端响应时间需网关层计时，当前未接入。meal_date 与落库日期见于 save_meal_record 的 tool_args / tool_response；原始工具结果见各事件 tool_response。",
    }