# 测试说明

## 测试规范

### 基本规则

- **新功能必须带测试**：功能代码和测试文件一起提交
- **命名对应**：`server/api/login.py` → `tests/test_login.py`，好找
- **不调真实 API**：所有 LLM 调用用 Mock 模拟，不需要 API key、不需要网络
- **改代码跑测试**：改了某个模块 → 跑对应测试 → 通过再提交

### 提交前检查

```bash
# 1. 跑你改动的部分
pytest tests/test_detect_emotion.py -v

# 2. 跑全部（防止改坏别人的代码）
pytest tests/ -v

```

---

## 如何运行

```bash
# 运行全部测试
pytest tests/ -v

# 运行单个文件
pytest tests/test_detect_emotion.py -v

# 运行单个测试（精确到函数）
pytest tests/test_detect_emotion.py::TestDetectEmotion::test_detect_fomo_踏空 -v

# 屏蔽第三方库的废弃警告，输出更干净
pytest tests/ -v -W ignore::DeprecationWarning

# 手动交互测试（会调真实 LLM，需要 API key）
poetry run python tests/manual_test_chat.py
```

> `-v` 是 verbose 模式，显示每个测试的名字和结果，不加也行但看不到细节。

---

## 文件一览

| 文件 | 测试数 | 测试对象 | 难度 |
|------|--------|----------|------|
| `conftest.py` | — | 共享测试道具（状态构造、LLM mock） | — |
| `test_detect_emotion.py` | 12 | 情绪关键词检测 | 简单 |
| `test_edges.py` | 11 | 路由函数（情绪干预、意图路由、结束判断） | 简单 |
| `test_tools.py` | 9 | 意图 tool 定义和映射 | 简单 |
| `test_node_messages.py` | 6 | 消息去重（entry_node / output_node） | 中等 |
| `test_classify_intent.py` | 5 | 意图识别节点（关键词快速通道 + tool calling） | 中等 |
| `test_llm_service.py` | 4 | LLM 单例服务 | 中等 |
| `test_inquiry_interrupt.py` | 4 | 追问链 interrupt 模式（多轮问答） | 较难 |
| `test_run_lyra.py` | 5 | run_lyra 入口函数（interrupt/resume） | 较难 |

建议阅读顺序：从上到下，先看简单的建立感觉。

---

## 各文件详细说明

### conftest.py — 共享测试道具

不是测试文件，是所有测试共用的"道具箱"，提供：

- `sample_lyra_state` — 预造好的测试状态，包含所有必需字段的默认值
- `sample_buy_decision_state` — 模拟已进入买入决策流程的状态
- `mock_llm_response` — 造假的 LLM 文本响应
- `mock_tool_call_response` — 造假的 LLM tool calling 响应

用法：测试函数参数里写 fixture 名字就能直接用，不用自己构造：

```python
async def test_xxx(self, sample_lyra_state):  # 自动注入
    state = dict(sample_lyra_state)
    state["current_input"] = "我想买沪深300"
    ...
```

### test_detect_emotion.py — 情绪检测（12 个测试）

测试 `detect_emotion()` 关键词匹配函数。

最简单的测试文件，直接调函数看返回值，不需要 Mock：

```
输入 "我踏空了好后悔" → detect_emotion() → ["fomo", "regret"]
输入 "沪深300怎么样" → detect_emotion() → []
输入 ""              → detect_emotion() → []
```

覆盖四种情绪：fomo（踏空）、anxiety（焦虑）、regret（后悔）、overconfidence（过度自信），以及多情绪同时检测、正常输入无情绪、空字符串、部分匹配不触发。

### test_edges.py — 路由函数（11 个测试）

测试图里的"岔路口"决策函数，同样是纯函数，不需要 Mock：

- `should_intervene_emotion` — 有情绪且没干预过 → 走干预路径；其他 → 跳过
- `route_by_intent` — buy_decision + 高置信度 → 走 skill；低置信度 → 兜底
- `should_end` — should_end=True → 结束；False/缺失 → 继续

### test_tools.py — Tool 定义（9 个测试）

测试 5 个意图 tool（buy_decision、position_manage、stop_loss、knowledge_qa、market_analysis）：

- 每个 tool 能正常调用
- `TOOL_NAME_TO_INTENT` 映射完整，tool name 和映射 key 一致
- 每个 tool 的 description 不为空（LLM 靠它选择 tool）

### test_node_messages.py — 消息去重（6 个测试）

测试 `entry_node` 和 `output_node` 的去重逻辑：

- entry_node：首次输入添加 HumanMessage；重复输入不添加；不同输入正常添加
- output_node：首次响应添加 AIMessage；重复响应不追加；response=None 生成默认回复

背景：多轮对话时图会循环，如果 current_input 不变（interrupt 场景），不应重复添加消息。

### test_classify_intent.py — 意图识别（5 个测试）

测试 `classify_intent_node()` 的两层路由机制：

1. **关键词快速通道**：`SkillRegistry.select_skill` 命中 → 直接返回，不调 LLM
2. **Tool calling 路径**：关键词未命中 → 通过 `bind_tools` 让 LLM 选择意图
3. **降级处理**：LLM 无 tool_calls → unknown；LLM 异常 → unknown
4. **全量映射**：每个 tool name 都能正确映射到 intent

Mock 策略：patch `get_skill_registry` 和 `get_llm_with_tools`。

### test_llm_service.py — LLM 服务（4 个测试）

测试 `server/llm.py` 的单例模式：

- `get_llm()` 多次调用返回同一实例（ChatAnthropic 只构造一次）
- 构造参数使用 SETTINGS 中的配置
- `get_llm_with_tools()` 调用 `bind_tools` 绑定工具
- `get_llm_with_tools()` 不缓存，每次返回新实例

每个测试前重置 `_llm_instance = None` 避免测试间干扰。

### test_inquiry_interrupt.py — 追问链（4 个测试）

测试买入决策的追问机制——莱拉问用户问题，用户回答后继续追问：

- 首次进入（step=1）：生成问题，不调 interrupt
- 后续步骤（step>1）：调 `interrupt()` 暂停，用户回答后恢复
- 跳过追问：`skip_remaining_inquiry=True` 时直接到详细报告
- 返回值不含 `waiting_for_user`（已改用 interrupt 模式）

Mock 策略：patch `interrupt` 函数返回模拟的用户回答。

### test_run_lyra.py — 入口函数（5 个测试）

测试 `run_lyra()` 的调度逻辑（mock 了整个 graph 对象）：

- 正常模式：无 pending interrupt → 创建初始状态 → ainvoke
- 恢复模式：有 pending interrupt → `Command(resume=user_input)` → ainvoke
- 返回值包含 `_interrupted` 和 `_waiting_for_input` 标志
- config 中 thread_id 等于 session_id

### manual_test_chat.py — 手动交互测试

不在 pytest 体系里，单独运行。会调用真实 LLM，用于验证完整流程：

```bash
poetry run python tests/manual_test_chat.py
```

终端交互，输入"我想买沪深300"看莱拉怎么回复，输入 q 退出。

---

## 添加新测试

1. 在 `tests/` 下新建 `test_xxx.py`，测试类用 `class TestXxx`
2. 用 `conftest.py` 中的 fixtures 构造状态（参数名写 fixture 名即可）
3. LLM 调用用 `unittest.mock.patch` mock，不要调真实 API
4. 异步函数加 `@pytest.mark.asyncio`，同步函数不用加
5. 调试输出用 `print(f"[DEBUG] ...")`
