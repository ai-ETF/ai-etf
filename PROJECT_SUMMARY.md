# AI-ETF 项目架构总结

> 本文档用于快速理解项目结构，避免每次开发时重新阅读整个项目。
> 更新时间：2026-04-01

---

## 一、项目概述

**AI-ETF** 是一个面向投资新手的 ETF 投研辅助系统，使用 LangGraph + Claude + Supabase 构建。

### 核心特点
- **双 Agent 架构**：莱拉（对话）+ 小研（数据收集）
- **渐进式 Skill 系统**：按需加载，支持扩展
- **情绪感知**：检测 FOMO/焦虑/后悔/盲目自信并干预
- **流式输出**：SSE 实时响应

### 技术栈
| 组件 | 技术 |
|------|------|
| 框架 | FastAPI + LangGraph |
| LLM | Claude (claude-sonnet-4-20250514) |
| 向量 | text2vec-base-chinese (768d) |
| 数据库 | Supabase pgvector |
| ETF 数据 | akshare |
| 依赖管理 | Poetry |

---

## 二、目录结构

```
server/
├── app.py                          # FastAPI 入口，注册路由
├── config/
│   └── settings.py                 # 配置管理（环境变量）
│
├── api/                            # API 端点
│   ├── chat.py                     # [主要] SSE 流式对话 API
│   ├── ask.py                      # [旧] 文档问答
│   ├── upload.py                   # [保留] 文档上传
│   └── test.py                     # 健康检查
│
├── graphs/                         # [核心] LangGraph 图定义
│   ├── lyra/                       # 莱拉主控 Agent
│   │   ├── graph.py               # StateGraph 编排 ⭐
│   │   ├── state.py               # LyraState 状态定义 ⭐
│   │   ├── nodes.py               # 节点函数（意图/情绪/输出）
│   │   ├── edges.py               # 条件边（路由逻辑）
│   │   └── prompts.py             # 人设 Prompt + 情绪干预
│   │
│   ├── skills/                     # Skill 子图
│   │   └── buy_decision/          # 买入决策 Skill
│   │       ├── graph.py           # Skill 子图编排
│   │       ├── state.py           # BuyDecisionSkillState
│   │       └── nodes.py           # 追问链/决策框架节点
│   │
│   └── xiaoyan/                    # 小研数据 Agent
│       ├── graph.py               # 数据收集图编排
│       ├── state.py               # XiaoYanState
│       ├── nodes.py               # 数据收集/整合节点
│       └── sources/               # 数据源
│           ├── akshare_client.py  # ETF 行情/估值/资金流向
│           └── rag_client.py      # 投行观点 RAG 检索
│
├── skills/                         # Skill 内容文件（渐进式披露）
│   ├── registry.py                # Skill 注册表 + 相关性匹配
│   ├── loader.py                  # 按需加载器
│   └── buy-decision/              # 买入决策 Skill 内容
│       ├── SKILL.md               # 入口文件（frontmatter + 核心流程）
│       ├── config.yaml            # 数据需求配置
│       └── references/            # 详细话术（按需加载）
│
├── storage/                        # 数据持久化
│   ├── supabase_client.py         # Supabase 客户端（复用）
│   ├── session_repo.py            # 会话状态持久化（新建）
│   ├── embedding_repo.py          # 向量存储（复用）
│   └── document_repo.py           # 文档元数据（复用）
│
├── rag/                            # RAG 系统（复用）
│   ├── embedder.py                # sentence-transformers 嵌入
│   ├── retriever.py               # Supabase 向量检索
│   └── chunker.py                 # 滑动窗口分块
│
├── models/
│   └── schemas.py                 # Pydantic 请求/响应模型
│
├── agents/                         # [已废弃] 旧 Agent 实现
└── services/                       # [已废弃] 旧 Service 层
```

---

## 三、核心组件说明

### 3.1 莱拉（Lyra）- 主控 Agent

**职责**：
- 人设维持（温和、专业、不替用户做决定）
- 意图识别 → 路由到对应 Skill
- 情绪检测 → 三步干预
- 统一输出（流式）

**图结构**：
```
entry → check_emotion → [emotion_intervention?] → classify_intent
    → route_by_intent → [buy_decision_skill] → output → save_state → END
```

**关键文件**：
- `graphs/lyra/graph.py` - 图编排，`build_lyra_graph()` 函数
- `graphs/lyra/state.py` - `LyraState` TypedDict
- `graphs/lyra/prompts.py` - `get_system_prompt()` 人设

### 3.2 小研（XiaoYan）- 数据 Agent

**职责**：
- 异步收集 ETF 数据（估值、资金流向、成分股）
- RAG 检索投行观点
- 生成简要/详细数据报告

**数据源**：
| 数据类型 | 来源 | 文件 |
|----------|------|------|
| 估值/行情/资金流向 | akshare | `xiaoyan/sources/akshare_client.py` |
| 投行观点 | RAG | `xiaoyan/sources/rag_client.py` |

**关键函数**：
- `AkshareClient.get_etf_valuation(symbol)`
- `AkshareClient.get_etf_fund_flow(symbol, days)`
- `RAGClient.query_institution_views(targets)`

### 3.3 买入决策 Skill

**流程**：
```
quick_response → intent_routing
    ├─ simple → output_brief → END
    └─ deep → output_brief → inquiry_chain(6步) → output_detail
              → decision_framework → generate_exec_plan → END
```

**6 步追问链**：
1. 投资目标（为什么想买）
2. 投资期限（打算投多久）
3. 标的理解（直接给，不追问）
4. 风险认知（浮亏20%怎么办）
5. 自我匹配（结合数据判断）
6. 四条纪律（买入后规则）

**关键文件**：
- `skills/buy-decision/SKILL.md` - Skill 入口
- `skills/buy-decision/references/inquiry.md` - 追问话术
- `skills/buy-decision/references/four_rules.md` - 四条纪律

---

## 四、API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 同步对话 |
| `/api/chat/stream` | POST | **SSE 流式对话** ⭐ |
| `/api/chat/{id}/data-status` | GET | 数据收集状态轮询 |
| `/api/chat/{id}/history` | GET | 对话历史 |
| `/api/upload` | POST | 文档上传（保留） |
| `/api/ask` | POST | 文档问答（旧，保留） |

**SSE 事件类型**：
- `start` - 会话开始
- `response` - 响应片段
- `data_status` - 数据进度
- `end` - 会话结束
- `error` - 错误

---

## 五、状态定义

### LyraState（主状态）
```python
class LyraState(TypedDict):
    session_id: str
    user_id: str
    messages: Annotated[List[BaseMessage], add]
    current_input: str
    intent: Optional[str]              # buy_decision / unknown
    current_skill: Optional[str]
    skill_state: SkillState
    data_status: DataStatus            # brief_ready / detail_ready
    brief_data: Optional[dict]
    detail_data: Optional[dict]
    emotion_flags: List[str]           # fomo / anxiety / regret
    emotion_intervened: bool
    response: Optional[str]
    should_end: bool
    waiting_for_user: bool
```

### BuyDecisionSkillState
```python
class BuyDecisionSkillState(TypedDict):
    targets: List[str]                 # ["消费50", "消费80"]
    intent_route: str                  # simple / deep
    inquiry_step: int                  # 0-6
    inquiry_answers: InquiryAnswers
    post_buy_rules: PostBuyRules       # 四条纪律
    selected_target: Optional[str]
    position_size: Optional[str]
```

---

## 六、配置

### 环境变量（.env）
```
SUPABASE_URL=xxx
SUPABASE_SERVICE_ROLE_KEY=xxx
ANTHROPIC_API_KEY=xxx          # Claude API
LYRA_MODEL=claude-sonnet-4-20250514
LYRA_MAX_TOKENS=4096
XIAOYAN_CACHE_TTL=86400        # 数据缓存 1 天
```

### Supabase 表
| 表名 | 用途 |
|------|------|
| `document_chunks` | RAG 向量存储 |
| `documents` | 文档元数据 |
| `conversation_sessions` | 会话状态持久化 |

**建表 SQL**（session_repo.py 注释中）：
```sql
CREATE TABLE conversation_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 七、关键函数速查

### 启动对话
```python
from server.graphs.lyra.graph import run_lyra

result = await run_lyra(
    user_id="user_123",
    session_id="session_abc",
    user_input="消费50和消费80哪个更适合定投？"
)
```

### 获取 ETF 数据
```python
from server.graphs.xiaoyan.sources.akshare_client import get_akshare_client

client = get_akshare_client()
valuation = await client.get_etf_valuation("510150")
fund_flow = await client.get_etf_fund_flow("510150", days=30)
```

### RAG 检索
```python
from server.graphs.xiaoyan.sources.rag_client import get_rag_client

client = get_rag_client()
views = await client.query_institution_views(["消费50", "消费"])
```

### Skill 匹配
```python
from server.skills.registry import get_skill_registry

registry = get_skill_registry()
skill = registry.select_skill("消费50和消费80哪个适合定投？")
# → BuyDecisionSkillMetadata
```

---

## 八、废弃组件

以下文件已废弃，保留仅为兼容性：

| 文件 | 替代 |
|------|------|
| `server/agents/question_agent.py` | `graphs/lyra/nodes.py` 的意图分类 |
| `server/agents/document_agent.py` | 文档处理服务（上传流程保留） |
| `server/agents/output_format_agent.py` | Skill 内置格式化 |
| `server/services/qa_service.py` | LangGraph 图执行 |

---

## 九、设计文档

`设计资料/` 目录包含完整的产品设计文档：

| 文档 | 内容 |
|------|------|
| `技术对接文档.md` | API 格式、数据结构、开发优先级 |
| `Lyra人设文档.md` | 人设核心、投资主张、面对质疑 |
| `莱拉工作流.md` | 莱拉职责、状态管理、意图分类 |
| `小研工作流.md` | 数据源架构、缓存策略、降级处理 |
| `Skill设计规范.md` | 渐进式披露、YAML 格式、加载流程 |
| `数据报告设计.md` | 简要/详细报告模板 |
| `技能设计/buy-decision/` | 买入决策 Skill 完整设计 |

---

## 十、部署工作流

**重要**：本地无运行环境，代码通过 GitHub 推送到阿里云服务器运行。

```
本地写代码 → git commit → git push → GitHub
                                        ↓
                              阿里云 git pull
                                        ↓
                              poetry install
                                        ↓
                              启动服务测试
```

**分支**：
- `main`：主分支
- `sing`：开发分支（当前使用）

**本地开发注意**：
- 本地不要尝试 `poetry install` 或启动服务
- 写完代码直接 commit + push
- 测试在阿里云上进行

---

## 十一、开发注意事项

1. **依赖安装**：`poetry install`（会安装 akshare、langchain-anthropic）
2. **API Key**：必须在 `.env` 中配置 `ANTHROPIC_API_KEY`
3. **Supabase**：需要创建 `conversation_sessions` 表
4. **小研异步化**：当前小研是同步收集，需要改为 `asyncio.create_task()` 真正异步
5. **测试端点**：`curl -N http://localhost:8000/api/chat/stream -d '{"user_id":"test","message":"消费50和消费80哪个适合定投？"}'`

---

## 十二、待完成项

- [ ] 小研真正异步化（`asyncio.create_task`）
- [ ] 莱拉与买入决策子图集成（替换占位节点）
- [ ] 执行计划文档保存到 Supabase Storage
- [ ] 持仓管理 Skill
- [ ] 知识问答 Skill
- [ ] 联网搜索数据源（Tavily/Serper）
