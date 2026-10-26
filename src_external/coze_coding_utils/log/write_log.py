"""外部主机(非 Coze 环境)使用的兼容实现 —— log / write_log。

提供 request_context(ContextVar 对象, 具备 .get()/.set())，
供工具层以 request_context.get() 读取当前请求上下文。
"""
from contextvars import ContextVar as _CV

# 请求上下文对象（跨调用透传）。真实库也可能提供相同语义。
request_context = _CV("request_context", default=None)


def setup_logging(*args, **kwargs):
    """空实现：外部环境使用标准 logging，无需 Coze 日志框架。"""
    pass


def get_request_context():
    return request_context.get()