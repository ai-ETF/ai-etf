"""API 层测试 conftest：用空替身预填充超慢的重依赖模块。

本环境 `langchain_anthropic` 导入 >60s；`server.services.document_service`
（→ rag.embedder / graphs → torch / langgraph）同样极重。二者都会在
`import server.api`（父包 __init__ 会 import secure_chat / upload）时被连带加载，
拖垮所有 API 测试。此处用空替身预填充 sys.modules，使 import 变轻量。

- langchain：`server.llm` 只把 langchain 类当类型提示，运行时（astream_text 是
  纯逻辑、get_llm 惰性）不依赖真实 ChatAnthropic，故用空类替身即可让 server.llm
  以真实代码加载。
- document_service：upload 路由依赖，M 类不测 upload，直接替换为 DocumentService 空类。

被测路由所需的业务服务在各自测试文件里另行 monkeypatch。
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
