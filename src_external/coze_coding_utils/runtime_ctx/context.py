"""外部主机(非 Coze 环境)使用的兼容实现 —— runtime_ctx / context。

仅当运行在外部主机(设置了 EXTERNAL_MODE=1 且无 coze_coding_utils 真实库)时，
通过 PYTHONPATH 将本目录优先于真实库加载。
提供 new_context / default_headers 的最小等价实现，足够支撑工具层引用。
"""
from contextvars import ContextVar


def _current_user() -> str:
    # 与 storage/tools/request_id 的当前用户做轻量透传（避免循环导入，延迟读取）
    try:
        from tools.request_id import get_current_user
        return get_current_user() or ""
    except Exception:  # pragma: no cover
        return ""


class Context:
    """外部环境的最小上下文对象，等价于真实 Context 的可用子集。"""

    def __init__(self, method: str = ""):
        self.method = method

    def get_user_id(self) -> str:
        return _current_user()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExternalContext method={self.method}>"


def new_context(method: str = "external", **kwargs) -> Context:
    """创建新的外部请求上下文。"""
    return Context(method=method)


def default_headers(ctx=None) -> dict:
    """返回透传给 HTTP 客户端的默认请求头（外部环境无需额外头）。"""
    if ctx is None:
        return {}
    uid = getattr(ctx, "get_user_id", lambda: "")()
    headers = {"Content-Type": "application/json"}
    if uid:
        headers["X-User-Id"] = uid
    return headers