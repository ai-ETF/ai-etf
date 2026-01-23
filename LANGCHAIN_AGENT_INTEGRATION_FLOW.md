# LangChain Agent 集成后的系统调用流程

## 1. 系统架构概览

```
用户提问
    ↓
规则型Agent (ETFRuleBasedAgent)
    ↓
意图识别与参数提取
    ↓
┌─────────────────────────────────────────────────────────────┐
│                     LangChain Agent                         │
├─────────────────────────────────────────────────────────────┤
│ 工具1: DocumentSearchTool (文档检索)                        │
│ 工具2: CompareETFsTool (ETF比较)                           │
│ 工具3: RiskAssessmentTool (风险评估)                        │
│ 工具4: PortfolioAnalysisTool (投资组合分析)                 │
│ 工具5: MarketDataTool (市场数据)                            │
│ 工具6: HistoryContextTool (历史对话)                        │
│ 工具7: QuestionAnalysisTool (封装QuestionAgent)             │
│ 工具8: OutputFormatAnalysisTool (封装OutputFormatAgent)     │
│ 工具9: DocumentAnalysisTool (封装DocumentAgent)             │
└─────────────────────────────────────────────────────────────┘
    ↓
智谱AI (ZhipuLLM)
    ↓
生成最终回答
```

## 2. 三个原智能体的LangChain封装

### 2.1 QuestionAgent → QuestionAnalysisTool

**原功能**: 分析问题意图和输出格式偏好
```python
class QuestionAnalysisTool(BaseTool):
    """问题意图分析工具 - 封装原有QuestionAgent"""
    name: str = "question_analysis"
    description: str = "分析用户问题的意图和输出格式偏好"
    
    def _run(self, question: str, ...) -> str:
        # 封装原有QuestionAgent的analyze方法
        decision = self.question_agent.analyze(question)
        return str(decision)
```

**封装逻辑**:
- 保留了原有的关键词匹配逻辑
- 支持比较类、摘要类、趋势类等多种意图识别
- 返回结构化的意图分析结果

### 2.2 OutputFormatAgent → OutputFormatAnalysisTool

**原功能**: 分析和决定AI回答的输出格式
```python
class OutputFormatAnalysisTool(BaseTool):
    """输出格式分析工具 - 封装原有OutputFormatAgent"""
    name: str = "output_format_analysis"
    description: str = "分析和决定AI回答的输出格式"
    
    def _run(self, intent: str, question: str, content: str = "", ...) -> str:
        # 封装原有OutputFormatAgent的analyze方法
        format_analysis = self.output_format_agent.analyze(intent=intent, content=content)
        return str(format_analysis)
```

**封装逻辑**:
- 保留了意图到格式的映射逻辑
- 支持表格、要点列表、编号列表、自然文本、时间线等多种格式
- 根据内容和用户偏好动态调整格式

### 2.3 DocumentAgent → DocumentAnalysisTool

**原功能**: 分析文档类型、结构和关键信息
```python
class DocumentAnalysisTool(BaseTool):
    """文档分析工具 - 封装原有DocumentAgent"""
    name: str = "document_analysis"
    description: str = "分析文档类型、结构和关键信息"
    
    def _run(self, content: str, doc_id: str = None, ...) -> str:
        # 封装原有DocumentAgent的analyze方法
        analysis = self.document_agent.analyze(content, doc_id)
        return str(analysis)
```

**封装逻辑**:
- 保留了文档类型识别逻辑（财报、ETF报告、新闻文章、法规文档等）
- 提取关键信息位置
- 分析内容结构（行数、段落数、表格/列表检测等）
- 提供推荐的分块策略

## 3. 完整调用流程

### 3.1 传统RAG流程 (文档查询类问题)
```
用户提问 → ETFRuleBasedAgent (识别为DOCUMENT_QUERY) → 传统RAG流程
    ↓
QuestionAgent → 意图识别
    ↓
OutputFormatAgent → 格式分析  
    ↓
Embedding + Retrieval → 相关文档块
    ↓
PromptBuilder → 构建提示词
    ↓
ZhipuLLM → 生成回答
```

### 3.2 LangChain Agent流程 (非文档查询类问题)
```
用户提问 → ETFRuleBasedAgent (识别为ETF_COMPARISON/RISK_ASSESSMENT等) → LangChain Agent流程
    ↓
选择对应LangChain工具 (如CompareETFsTool)
    ↓
LangChain Agent调度器
    ↓
可能调用QuestionAnalysisTool → 调用封装的QuestionAgent
    ↓
可能调用OutputFormatAnalysisTool → 调用封装的OutputFormatAgent  
    ↓
可能调用DocumentAnalysisTool → 调用封装的DocumentAgent
    ↓
执行业务工具 (如CompareETFsTool)
    ↓
ZhipuLLM → 生成回答
```

## 4. 智能体内部协作流程

当LangChain Agent处理复杂问题时，内部各工具可能相互协作：

```
主问题 → LangChain Agent
    ↓
调用QuestionAnalysisTool (获取问题意图)
    ↓
调用OutputFormatAnalysisTool (确定输出格式)
    ↓
根据需要调用DocumentAnalysisTool (分析相关文档)
    ↓
调用业务工具 (如CompareETFsTool)
    ↓
整合所有信息生成最终答案
```

## 5. 异常处理与降级策略

### 5.1 API密钥缺失处理
- 当ZHIPU_API_KEY未配置时，系统自动切换到备用模式
- 仍可执行基本功能，但不会调用AI生成回答

### 5.2 工具执行失败处理
- 当LangChain Agent执行失败时，自动回退到传统RAG流程
- 当特定工具失败时，使用备用工具或返回错误信息

### 5.3 参数缺失处理
- 当问题缺少必要参数时，系统会要求用户澄清
- 通过ETFRuleBasedAgent的clarification_message返回澄清需求

## 6. 数据流向与状态管理

- **输入**: 用户问题、用户ID、会话ID、文档过滤条件
- **中间状态**: 意图、提取参数、工具调用结果、上下文信息
- **输出**: 最终回答

## 7. 扩展性考虑

1. **工具扩展**: 可以轻松添加新的LangChain工具，只需继承BaseTool类
2. **智能体集成**: 可以继续封装其他原有智能体
3. **模型替换**: 可以通过修改ZhipuLLM适配器来更换底层AI模型
4. **记忆组件**: 可以添加记忆组件以支持多轮对话

这个集成方案在保留原有系统功能的基础上，通过LangChain的工具调用机制增强了系统的灵活性和扩展性。