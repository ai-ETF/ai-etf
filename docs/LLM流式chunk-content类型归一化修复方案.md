# LLM 流式 chunk.content 类型归一化修复方案

> 版本：v1.1
> 日期：2026-09-04
> 状态：已实现
> 前置依赖：`server/llm.py`（统一 LLM 单例）

---

## 一、概述

### 1.1 背景与问题现象

线上 `/api/secure-chat`（以及 `/api/simple-chat`）调用 LLM 进行 SSE 流式对话。服务端日志出现：

```
POST /api/secure-chat HTTP/1.1" 200 OK          # HTTP 已 200（SSE 流已建立）
...
HTTP Response: POST https://api.deepseek.com/anthropic/v1/messages "200 OK"   # LLM 请求本身成功
ERROR:server.api.secure_chat:LLM 调用失败: can only concatenate str (not "list") to str
```

关键特征：**请求成功、上游 200，但应用在消费流式返回时崩溃**。客户端收到 SSE `error` 事件（而非正常文本），但 HTTP 层面仍是 200。

### 1.2 根因

崩溃点在 `server/api/secure_chat.py:217`：

```python
full_response += chunk.content     # str += chunk.content
```

`chunk` 是 langchain 流式产出的 `AIMessageChunk`，其 `.content` 类型为 **`Union[str, list]`**：

- 纯文本场景 → `str`（如 `"你"`）；
- **内容块场景 → `list`**，例如 `[{type: 'text'|'thinking', text/thinking: '...', index: 0}]`。

当某个 chunk 的 `.content` 是 `list` 时，`"" + [...]` 触发 `TypeError`。

**为什么会收到 list？** 依赖 `langchain-anthropic`（锁定 `0.3.22`，见 poetry.lock）。该包内部按请求是否含 tools / thinking / 带引用的 document 决定文本增量用 `str` 还是 `list` 表达（`chat_models.py:1645-1649`）；而**推理增量（`thinking_delta` / `signature_delta`）是无条件按 `list` 包装的**（`chat_models.py:2528-2532`）：

```python
elif event.delta.type in {"thinking_delta", "signature_delta"}:
    content_block = event.delta.model_dump()
    content_block["type"] = "thinking"
    message_chunk = AIMessageChunk(content=[content_block])   # 恒为 list
```

`deepseek-v4-flash` 是**带推理能力（reasoning）的模型**，其 Anthropic 兼容网关把推理过程以 `thinking` 事件形式流式吐回 → 首个非空 chunk 即为 `list` → `full_response += chunk.content` 立即抛错。这与「HTTP 200 之后立刻报错」的日志完全吻合。

> 该隐患对所有模型通用：只要调用携带 tools、开启 thinking，`coerce_content_to_string` 变为 False，普通文本增量也会包成 list（`chat_models.py:2513-2525`）。本次只是 secure-chat 首个暴露。

### 1.3 目标

1. 流式对话对 `AIMessageChunk.content`（str 或 list）**统一归一为纯文本**，不再崩溃。
2. **一处实现、多处复用**：同时修复 `secure-chat` 与 `simple-chat` 两个流式端点，避免同 bug 二次出现。
3. 默认策略：**仅取 `text` 块，丢弃 `thinking`**（推理内容不回显用户、不入库），与改造前纯文本模型行为一致。

---

## 二、影响范围

| 文件 | 现状 | 问题 |
|---|---|---|
| `server/api/secure_chat.py:204-236` | `async for chunk in llm.astream(...)` 内 `full_response += chunk.content` | str+=list 崩溃；文本无法落库 |
| `server/api/simple_chat.py:31-54` | `async for chunk in llm.astream(...)` 内 `yield format_sse_event("token", {"content": chunk.content})` | 不崩，但会把 list 原样发给前端 |

两条路径共用同一 `get_llm()` 单例与同一 reasoning 模型，一次全中。因此**单点修复不够**，需公共归一化。

类图/`LangGraph` 内部走 `graph.invoke()`（LCEL 自行累积 chunk），不手工拼 `.content`，不受影响，无需改动。

---

## 三、核心设计决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 归一化位置 | 新增 helper `astream_text()` 放 **`server/llm.py`** | LLM 实例统一出口，流式取文本逻辑集中一处，覆盖全部流式点，策略只写一次 |
| helper 形态 | **异步生成器，产出纯文本片段** `AsyncIterator[str]` | 端到端消费干净；落库端自行拼 `str`，回显端直接转发 |
| `content` 归一规则 | `str` → 原样；`list` → 仅取 `type == "text"` 块的 `text` | `thinking` 等非文本块不进正文 |
| thinking 内容 | **默认丢弃** | 推理过程通常不应回显用户 / 入库；需保留另见 §8 |
| 是否从 Provider 关推理 | 否（不依赖） | langchain-anthropic 0.3.22 无构造参数强制 content 为 str（coerce 按请求自动判定）；DeepSeek 兼容网关是否支持关闭 reasoning 未见文档——不赌供应商行为，侧归一最稳 |

> **备选方案（不采用）**：在各调用点各写一份 `isinstance(chunk.content, list)` 判断 → 逻辑重复、策略易漂移，且漏掉 simple-chat 类只转发不拼接的路径。

---

## 四、代码修改

### 4.1 `server/llm.py`：新增 `astream_text`

在文件末尾追加：

```python
from typing import AsyncIterator, Sequence
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage


async def astream_text(
    llm: BaseChatModel,
    messages: Sequence[BaseMessage],
) -> AsyncIterator[str]:
    """
    流式调用 LLM，逐段产出纯文本。

    归一 AIMessageChunk.content（str 或 content-block 列表）：
    - str → 原样产出
    - list → 仅取 type == "text" 的块（thinking 等非文本块丢弃）

    典型用法：
        async for text in astream_text(llm, [HumanMessage(content=question)]):
            ...   # 落库端自行拼接，回显端直接转发
    """
    async for chunk in llm.astream(messages):
        content = chunk.content
        if isinstance(content, str):
            if content:
                yield content
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    yield text
```

> 导入需在 `get_llm()`/`get_llm_with_tools()` 之后按需放置，避免循环导入（`BaseChatModel`/`BaseMessage` 均来自 langchain_core，安全）。

### 4.2 `server/api/secure_chat.py`：`stream_with_save` 改用 helper

`server/api/secure_chat.py:204-236` 的 `stream_with_save` 改为：

```python
from server.llm import get_llm, astream_text          # 顶部 import 增加 astream_text

async def stream_with_save(question: str, chat_id: str, user_id: str):
    from langchain_core.messages import HumanMessage

    llm = get_llm()
    repo = get_chat_repo()
    full_response = ""

    try:
        async for text in astream_text(llm, [HumanMessage(content=question)]):
            full_response += text                       # 此时必为 str，安全拼接
            yield format_sse_event("token", {"content": text})

        # 流式完成，保存 assistant 消息（全文本落库）
        assistant_msg = repo.save_message(
            chat_id=chat_id,
            role="assistant",
            content=full_response,
            user_id=user_id,
        )
        if assistant_msg:
            logger.debug(f"assistant 消息已保存: id={assistant_msg['id']}")
        else:
            logger.warning("assistant 消息保存失败")

        yield format_sse_event("done", {"chat_id": chat_id})

    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        yield format_sse_event("error", {"message": str(e)})
```

### 4.3 `server/api/simple_chat.py`：改用 helper

`server/api/simple_chat.py:31-54` 改为：

```python
from server.llm import get_llm, astream_text          # 顶部 import 增加 astream_text

async def stream_simple_chat(question: str):
    from langchain_core.messages import HumanMessage

    llm = get_llm()

    try:
        async for text in astream_text(llm, [HumanMessage(content=question)]):
            yield format_sse_event("token", {"content": text})

        yield format_sse_event("done", {})

    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        yield format_sse_event("error", {"message": str(e)})
```

### 4.4 新增/修改文件结构

```
server/
├── llm.py                     # 修改：新增 astream_text() 归一化生成器
└── api/
    ├── secure_chat.py         # 修改：stream_with_save 改用 astream_text（保拼接 + 落库）
    └── simple_chat.py         # 修改：stream_simple_chat 改用 astream_text（直接转发文本）
```

---

## 五、行为对照（改造前后）

| 场景 | 改造前 | 改造后 |
|---|---|---|
| 普通文本模型（content 恒为 str） | 正常 | 正常（透传 str） |
| reasoning 模型（deepseek-v4-flash，首块为 thinking list） | secure-chat：`TypeError` 崩溃；simple-chat：list 透传前端 | 两端均正常；thinking 被丢弃，仅 text 流出 |
| 携带 tools 的流式调用（潜在） | 文本增量可能为 list → 同崩 | 稳定归一 |

---

## 六、测试命令

```bash
# 本地起服务后（默认 http://localhost:8000）

# 1) secure-chat：应能完整收到 token 流并以 done 收尾，不再报 TypeError
curl -N -X POST http://localhost:8000/api/secure-chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question":"你是谁"}' \
  | head -n 5

# 2) simple-chat：同样应收到纯文本 token 事件
curl -N -X POST http://localhost:8000/api/simple-chat \
  -H "Content-Type: application/json" \
  -d '{"question":"你是谁"}' \
  | head -n 5

# 3) 服务端日志确认无 ERROR: ... LLM 调用失败
```

验证要点：
- 收到的事件 `content` 字段**必须是字符串**（非数组）。
- secure-chat 结束后数据库 `messages` 表中该 assistant 消息为完整纯文本。
- 日志不再出现 `can only concatenate str (not "list") to str`。

---

## 七、错误处理与兼容性

1. **不改变错误处理结构**：异常仍走既有 `except` → SSE `error` 事件；helper 内不吞异常，归一化失败同样向上抛出。
2. **兼容所有 content 形态**：str / 空串 / 空 list / 混合块均安全（空内容跳过）。
3. **thinking 丢弃的影响**：仅影响展示/入库内容；不改变 LLM 生成能力。

---

## 八、待确认事项

| 事项 | 说明 | 状态 |
|---|---|---|
| thinking 内容去留 | **丢弃**（不回显、不入库），已确认采用。若后续需把 DeepSeek 推理也流给前端/入库：把 helper 改为同时取 `type == "thinking"` 的 `thinking` 字段（注意与正文分段/排序的边界） | ✅ 已确认丢弃 |
| 是否需要统一加到 graphs 流式 | 当前 LangGraph 走 `graph.invoke()` 不手工拼 chunk；若后续改 LCEL 手动流式，同样优先复用 `astream_text` | 观察后续需求 |

---

## 九、参考

- `server/api/secure_chat.py:204-236`（`stream_with_save`，含 `full_response += chunk.content` 崩溃点）
- `server/api/simple_chat.py:31-54`（`stream_simple_chat`，list 透传隐患点）
- `server/llm.py`（统一 LLM 单例，helper 落点）
- langchain-anthropic 0.3.22：`chat_models.py:1645-1649`（`coerce_content_to_string` 判定）、`chat_models.py:2528-2532`（`thinking_delta` 无条件 list 化）
