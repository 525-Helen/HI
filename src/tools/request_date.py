"""请求级用餐日期上下文。

相对日期（昨天/前天/上周三/N天前等）只在计算端（diet_nutrition_agent）解析一次，
生成权威的具体 YYYY-MM-DD 存入本模块的 ContextVar，保存端（save_meal_record）与
所有重试流程全程复用，禁止在保存端二次解析相对日期，从而避免"计算端与落库日期不一致"。

同时记录"日期是否指代不明"（如"那天/某天/之前那次"）：此时不允许臆测具体日期，
必须向用户追问，确认前禁止保存。
"""
from contextvars import ContextVar

_resolved_date_var: ContextVar = ContextVar("biz_resolved_date", default=None)
_ambiguous_var: ContextVar = ContextVar("biz_date_ambiguous", default=False)


def reset_request_date() -> None:
    """重置当前请求的日期上下文（在请求入口调用一次）。"""
    _resolved_date_var.set(None)
    _ambiguous_var.set(False)


def set_resolved_date(resolved_date) -> None:
    """写入本次请求解析出的权威用餐日期（YYYY-MM-DD 字符串；不明日期为 None）。"""
    _resolved_date_var.set(resolved_date)


def get_resolved_date():
    """读取本次请求的权威用餐日期（None 表示未解析出具体日期）。"""
    return _resolved_date_var.get()


def set_ambiguous(flag: bool) -> None:
    """标记本次请求的日期是否指代不明（如"那天/某天"）。"""
    _ambiguous_var.set(bool(flag))


def is_ambiguous() -> bool:
    """当前请求的日期是否指代不明（此时不得臆测/不得保存）。"""
    return _ambiguous_var.get() or False