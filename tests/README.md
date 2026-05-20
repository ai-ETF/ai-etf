# 测试文件说明

## 运行方式

```bash
# 运行全部测试
poetry run pytest tests/ -v

# 运行单个文件
poetry run pytest tests/test_classify_intent.py -v

# 运行单个测试
poetry run pytest tests/test_classify_intent.py::TestClassifyIntentNode::test_keyword_fast_path -v

# 只看失败的详细信息
poetry run pytest tests/ -v --tb=long
```

所有测试都 mock 了 LLM 调用，不需要 API key，不需要网络。

> -v 是 pytest 的 verbose（详细模式），效果是显示每个测试的名字和结果，不是必须的。

---

## 文件一览

| 文件 | 测试数 | 测试对象 |
|------|--------|----------|
| `conftest.py` | — | 共享 fixtures（状态构造、LLM mock） |
| `test_classify_intent.py` | 5 | 意图识别节点（关键词快速通道 + tool calling） |
| `test_detect_emotion.py` | 12 | 情绪关键词检测 |
| `test_edges.py` | 11 | 路由函数（情绪干预、意图路由、结束判断） |
| `test_inquiry_interrupt.py` | 4 | 追问链 interrupt 模式（多轮问答） |
| `test_llm_service.py` | 4 | LLM 单例服务 |
| `test_node_messages.py` | 6 | 消息去重（entry_node / output_node） |
| `test_run_lyra.py` | 5 | run_lyra 入口函数（interrupt/resume） |
| `test_tools.py` | 9 | tool 定义和映射 |

---

## 各文件详细说明

### conftest.py — 共享 Fixtures

提供所有测试共用的 fixtures：

- `sample_lyra_state` — 最小可用的 LyraState，包含所有必需字段的默认值
- `sample_buy_decision_state` — 带 buy_decision skill 状态的 LyraState，模拟已进入买入决策流程
- `mock_llm_response` — 工厂函数，构造模拟的 LLM 文本响应
- `mock_tool_call_response` — 工厂函数，构造模拟的 tool calling 响应

### test_classify_intent.py — 意图识别节点

测试 `classify_intent_node()` 的两层路由机制：

- **关键词快速通道**：`SkillRegistry.select_skill` 命中时直接返回，不调用 LLM
- **Tool calling 路径**：关键词未命中时，通过 `bind_tools` 让 LLM 选择意图工具
- **降级处理**：LLM 无 tool_calls 时降级为 unknown；LLM 异常时降级为 unknown
- **全量映射**：验证每个 tool name 都能正确映射到 intent

Mock 策略：patch `get_skill_registry`（关键词匹配）和 `get_llm_with_tools`（LLM tool calling）。

### test_detect_emotion.py — 情绪检测

测试 `detect_emotion()` 关键词匹配函数：

- 四种情绪：fomo（踏空）、anxiety（焦虑）、regret（后悔）、overconfidence（过度自信）
- 多情绪同时检测
- 正常输入无情绪、空字符串、部分匹配不触发

### test_edges.py — 路由函数

测试三个路由函数：

- `should_intervene_emotion` — 是否进行情绪干预（检测到情绪 + 未干预过）
- `route_by_intent` — 根据 intent 和 confidence 路由到不同 skill
- `should_end` — 判断对话是否结束

### test_inquiry_interrupt.py — 追问链 Interrupt

测试 `inquiry_chain_node()` 的 LangGraph interrupt 机制：

- 首次进入（step=1）：生成问题，不调用 interrupt
- 后续步骤（step>1）：调用 `interrupt()` 获取用户回答，记录到 inquiry_answers
- 跳过追问：`skip_remaining_inquiry=True` 时直接跳到详细报告
- 返回值不含 `waiting_for_user`（已改用 interrupt 模式）

Mock 策略：patch `interrupt` 函数返回模拟的用户回答。

### test_llm_service.py — LLM 单例服务

测试 `server/llm.py`：

- `get_llm()` 单例模式 — 多次调用返回同一实例，ChatAnthropic 只构造一次
- `get_llm()` 配置参数 — 使用 SETTINGS 中的 model 和 max_tokens
- `get_llm_with_tools()` — 调用 base_llm.bind_tools(tools)
- `get_llm_with_tools()` 不缓存 — 每次返回新的绑定实例

每个测试前重置 `_llm_instance = None` 避免测试间干扰。

### test_node_messages.py — 消息去重

测试 `entry_node` 和 `output_node` 的消息去重逻辑：

- entry_node：首次输入添加 HumanMessage；重复输入不添加；不同输入正常添加
- output_node：首次响应添加 AIMessage；重复响应不追加；response=None 生成默认回复

### test_run_lyra.py — 入口函数

测试 `run_lyra()` 的调度逻辑（mock 了整个 graph 对象）：

- 正常模式：无 pending interrupt 时创建初始状态并调用 ainvoke
- 恢复模式：有 pending interrupt 时用 `Command(resume=user_input)` 调用 ainvoke
- 返回 `_interrupted` 和 `_waiting_for_input` 标志
- config 中 thread_id 等于 session_id

### test_tools.py — Tool 定义

测试 `server/graphs/lyra/tools.py`：

- 5 个 tool 函数都可调用
- INTENT_TOOLS 列表长度为 5
- TOOL_NAME_TO_INTENT 映射完整（每个 tool 都有对应 intent）
- tool name 与 mapping keys 一致
- 每个 tool 都有非空 docstring

---

## 添加新测试

1. 在对应文件中添加测试方法，或新建 `test_xxx.py`
2. 使用 `conftest.py` 中的 fixtures 构造状态和 mock
3. 对 LLM 调用用 `unittest.mock.patch` mock，不要调用真实 API
4. 测试函数加 `@pytest.mark.asyncio`（异步函数）或不加（同步函数）
5. 用 `print(f"[DEBUG] ...")` 输出调试信息，pytest `-v` 模式会显示
