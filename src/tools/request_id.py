"""请求级 request_id 上下文。

request_id 在整条用户请求进入工作流时生成一次，存入本模块的 ContextVar，
贯穿意图识别、份量澄清、营养计算、保存与所有重试流程：
- 同一请求（同一工作流 run）内，diet_nutrition_agent / save_meal_record 重试时复用同一 request_id；
- 用户补充克数或修改份量触发新的工作流 run 时，生成新的 request_id（不同记录）；
- save_meal_record 的 idempotency_key 默认取当前 request_id，保证同请求重试不重复落库，

并发兜底由 meal_records.request_id 的部分唯一索引 uq_meal_request_id 保证。
"""
import uuid
from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("biz_request_id", default="")

# 当前交互用户（来自网页前端显式上传的 x-user-id，用于多用户数据隔离）。
# 为空表示未显式声明用户（如平台 test_run / 历史调用），此时保持原全局行为。
_user_var: ContextVar[str] = ContextVar("biz_current_user", default="")


def set_current_user(user_id: str) -> None:
    """设置当前交互用户（请求入口根据前端 x-user-id 设置一次）。"""
    _user_var.set(user_id or "")


def get_current_user() -> str:
    """读取当前交互用户；为空表示未显式声明用户（保持全局行为）。"""
    return _user_var.get()


def set_request_id(request_id: str) -> None:
    """设置当前请求的 request_id（在工作流入口调用一次）。"""
    _request_id_var.set(request_id)


def get_request_id() -> str:
    """读取当前请求的 request_id。"""
    return _request_id_var.get()


def get_or_create_request_id() -> str:
    """返回当前请求的 request_id；若尚未生成（如单元测试直接调用工具），则生成并写入。"""
    rid = _request_id_var.get()
    if not rid:
        rid = str(uuid.uuid4())
        _request_id_var.set(rid)
    return rid