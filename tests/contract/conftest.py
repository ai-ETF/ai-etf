"""契约测试 conftest：复制 tests/unit/server/api/conftest.py 的轻量导入垫片。

为什么需要：契约测试要读 `server.app` 的真实路由表，而 `import server.app`
会连带 `server.api`（其 `__init__` 里 import 了 secure_chat 与 upload）：

- `secure_chat` → `server.llm` → `langchain_anthropic`（本机导入 >60s）
- `upload` → `server.services.document_service` → `rag` → torch / langgraph（更重）

用空替身预填充 sys.modules 可让 import 变轻量。**注意这不影响被测对象**：
路由是 `APIRouter` 上的真实对象，替身只替换了运行时才需要的第三方类。

与 `tests/unit/server/api/conftest.py` 的差异：本目录只需要「能 import 出 app」，
不需要 `client` 之类的 fixture，所以只保留 `_install` 部分。
"""
import sys
import types


def _install(name, **attrs):
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# 1) langchain 替身（server.llm 依赖）
_install("langchain_anthropic", ChatAnthropic=type("ChatAnthropic", (), {}))
_install("langchain_core")
_install("langchain_core.language_models")
_install("langchain_core.language_models.chat_models", BaseChatModel=type("BaseChatModel", (), {}))
_install("langchain_core.messages", BaseMessage=type("BaseMessage", (), {}))

# 2) document_service 替身（upload 依赖）
_install("server.services.document_service", DocumentService=type("DocumentService", (), {}))
