"""server 包。

应用实例 app 通过惰性 __getattr__ 按需加载：import server 时不再触发
server.app 及其全部依赖（FastAPI 路由 → sentence-transformers/torch）的
导入，从而让单元测试导入保持轻量；只有真正访问 server.app 时才加载。
"""

__all__ = ["app"]


def __getattr__(name):
    if name == "app":
        from .app import app
        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
