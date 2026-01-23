from typing import Dict, List, Optional, Any
from langchain.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import BaseModel, Field
from server.rag.retriever import Retriever
from server.storage.embedding_repo import EmbeddingRepo
from server.config.settings import SETTINGS
from server.agents.etf_rule_agent import ETFRuleBasedAgent
from server.agents.question_agent import QuestionAgent
from server.agents.output_format_agent import OutputFormatAgent
from server.agents.document_agent import DocumentAgent
import logging

logger = logging.getLogger(__name__)


class DocumentSearchToolInput(BaseModel):
    query: str = Field(description="搜索查询")
    top_k: int = Field(default=5, description="返回的结果数量")


class DocumentSearchTool(BaseTool):
    """文档搜索工具，用于RAG检索"""
    name: str = "document_search"
    description: str = "搜索相关ETF文档和资料"
    args_schema: type[BaseModel] = DocumentSearchToolInput

    def _run(
        self,
        query: str,
        top_k: int = 5,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> List[Dict[str, Any]]:
        """同步运行工具"""
        # 初始化依赖项
        emb_repo = EmbeddingRepo()
        retriever = Retriever(emb_repo)
        
        from server.rag.embedder import Embedder
        embedder = Embedder(dim=SETTINGS.EMBED_DIM)
        qvec = embedder.embed_text(query)

        # 检索相关文本块
        results = retriever.retrieve(qvec, top_k=top_k)
        
        # 转换为适合工具输出的格式
        formatted_results = []
        for idx, result in enumerate(results):
            formatted_results.append({
                "id": idx,
                "content": result.get("content", ""),
                "score": result.get("similarity", 0),
                "metadata": result.get("metadata", {})
            })
        
        return formatted_results


class CompareETFsToolInput(BaseModel):
    etf_codes: List[str] = Field(description="要比较的ETF代码列表")
    etf_names: Optional[List[str]] = Field(default=None, description="要比较的ETF名称列表")


class CompareETFsTool(BaseTool):
    """ETF比较工具"""
    name: str = "compare_etfs"
    description: str = "比较不同ETF的表现、费用、持仓等信息"
    args_schema: type[BaseModel] = CompareETFsToolInput

    def _run(
        self,
        etf_codes: List[str],
        etf_names: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # NOTE: 这是模拟实现，需要后续连接真实ETF数据源
        # TODO: 实际应用中需要替换为连接真实ETF数据源的实现
        if not etf_codes and not etf_names:
            return "没有提供有效的ETF代码或名称"
        
        etfs_to_compare = etf_codes if etf_codes else etf_names or []
        
        if len(etfs_to_compare) < 2:
            return f"需要至少两个ETF进行比较，当前只有: {etfs_to_compare}"
        
        # 注意：以下是比较详细的数据，这在实际应用中应该从真实数据源获取
        comparison_result = f"比较 {len(etfs_to_compare)} 个ETF: {', '.join(etfs_to_compare)}\n\n"
        
        for etf in etfs_to_compare:
            comparison_result += f"{etf}:\n"
            comparison_result += "- 费用比率: 0.15%\n"
            comparison_result += "- 追踪指数: 相关指数\n"
            comparison_result += "- 成立日期: 2020年\n"
            comparison_result += "- 规模: 大型\n"
            comparison_result += "- 近一年收益率: 8.5%\n"
            comparison_result += "- 波动率: 中等\n"
            comparison_result += "- 风险评级: 中等\n\n"
        
        comparison_result += "综合比较结论: \n"
        comparison_result += f"- 费用比率: {'、'.join(etfs_to_compare)} 费用比率相近\n"
        comparison_result += "- 追踪不同指数，适合不同投资策略\n"
        comparison_result += "- 建议根据投资目标和风险承受能力选择\n"
        
        return comparison_result


class RiskAssessmentToolInput(BaseModel):
    etf_code: Optional[str] = Field(default=None, description="ETF代码")
    etf_name: Optional[str] = Field(default=None, description="ETF名称")


class RiskAssessmentTool(BaseTool):
    """风险评估工具"""
    name: str = "risk_assessment"
    description: str = "评估ETF的风险水平和波动性"
    args_schema: type[BaseModel] = RiskAssessmentToolInput

    def _run(
        self,
        etf_code: Optional[str] = None,
        etf_name: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # NOTE: 这是模拟实现，需要后续连接真实ETF数据源
        # TODO: 实际应用中需要替换为连接真实ETF数据源的实现
        target_etf = etf_code or etf_name
        if not target_etf:
            return "请提供ETF代码或名称"
        
        # 模拟风险评估 - 实际应用中需要从真实数据源获取
        risk_levels = {
            "510300": "中等风险", 
            "510050": "中高等风险",
            "159919": "中等风险",
            "510500": "高等风险"
        }
        
        risk_level = risk_levels.get(target_etf, "中等风险")
        
        assessment = f"ETF {target_etf} 风险评估报告:\n"
        assessment += f"- 风险等级: {risk_level}\n"
        assessment += "- 历史波动率: 中等 (约15%) \n"
        assessment += "- 最大回撤: 通常在-20%至-30%之间\n"
        assessment += "- 夏普比率: 通常在0.5-0.8之间\n"
        assessment += "- Beta系数: 接近1.0 (与市场相关性强)\n"
        assessment += "- 相关性分析: 与基准指数高度相关\n"
        assessment += "- 适合风险承受能力: 稳健型及以上投资者\n"
        assessment += "- 投资建议: 适合长期持有，定期定额投资\n"
        assessment += "- 风险提示: 受市场整体走势影响较大\n"
        
        return assessment


class PortfolioAnalysisToolInput(BaseModel):
    etf_codes: Optional[List[str]] = Field(default=None, description="ETF代码列表")
    allocation: Optional[Dict[str, float]] = Field(default=None, description="持仓比例")


class PortfolioAnalysisTool(BaseTool):
    """投资组合分析工具"""
    name: str = "portfolio_analysis"
    description: str = "分析投资组合的构成、风险和收益特征"
    args_schema: type[BaseModel] = PortfolioAnalysisToolInput

    def _run(
        self,
        etf_codes: Optional[List[str]] = None,
        allocation: Optional[Dict[str, float]] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # NOTE: 这是模拟实现，需要后续连接真实ETF数据源
        # TODO: 实际应用中需要替换为连接真实ETF数据源的实现
        if not etf_codes and not allocation:
            return "请提供ETF代码或持仓比例信息"
        
        analysis = "投资组合分析报告:\n"
        
        if etf_codes:
            analysis += f"- ETF代码: {', '.join(etf_codes)}\n"
        
        if allocation:
            analysis += "- 持仓比例:\n"
            for etf, percent in allocation.items():
                analysis += f"  * {etf}: {percent}%\n"
        else:
            analysis += "- 持仓比例: 未提供，假设平均分配\n"
        
        analysis += "\n风险特征: 中等风险\n"
        analysis += "收益预期: 中等收益 (年化6%-10%)\n"
        analysis += "分散程度: 中等 (依赖于持有的ETF种类)\n"
        analysis += "相关性分析: 各ETF之间可能存在较高相关性\n"
        analysis += "建议: 分散投资，降低单一资产风险\n"
        analysis += "调整策略: 根据市场情况定期调整配置比例\n"
        analysis += "再平衡建议: 每季度或当某资产偏离目标比例超过5%时进行调整\n"
        
        return analysis


class MarketDataToolInput(BaseModel):
    etf_codes: List[str] = Field(description="ETF代码列表")
    time_period: Optional[str] = Field(default="1M", description="时间周期")


class MarketDataTool(BaseTool):
    """市场数据工具"""
    name: str = "market_data"
    description: str = "获取ETF的实时价格、成交量等市场数据"
    args_schema: type[BaseModel] = MarketDataToolInput

    def _run(
        self,
        etf_codes: List[str],
        time_period: Optional[str] = "1M",
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # NOTE: 这是模拟实现，需要后续连接真实市场数据API
        # TODO: 实际应用中需要替换为连接真实市场数据源的实现
        if not etf_codes:
            return "请提供ETF代码"
        
        data = f"市场数据 (周期: {time_period}):\n"
        
        for code in etf_codes:
            data += f"\n{code}:\n"
            data += "- 当前价格: ¥1.23\n"
            data += "- 涨跌幅: +0.50%\n"
            data += "- 成交量: 1,234,567手\n"
            data += f"- {time_period}回报: +2.34%\n"
            data += f"- {time_period}波动率: 3.2%\n"
            data += "- 净值: ¥1.22\n"
            data += "- 折溢价: +0.8%\n"
            data += f"- 年化收益率: 8.5%\n"
        
        return data


class HistoryContextToolInput(BaseModel):
    user_id: str = Field(description="用户ID")
    chat_id: str = Field(description="会话ID")
    limit: Optional[int] = Field(default=3, description="返回的历史消息数量")


class HistoryContextTool(BaseTool):
    """历史对话上下文工具"""
    name: str = "history_context"
    description: str = "获取历史对话上下文，了解之前的交流内容"
    args_schema: type[BaseModel] = HistoryContextToolInput

    def _run(
        self,
        user_id: str,
        chat_id: str,
        limit: Optional[int] = 3,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # NOTE: 这是模拟实现，需要后续连接真实数据库
        # TODO: 实际应用中需要替换为从数据库获取历史记录的实现
        try:
            # 模拟返回一些历史信息
            history = f"用户 {user_id} 在会话 {chat_id} 中的最近 {limit} 条消息:\n\n"
            history += "1. 用户: 沪深300ETF和中证500ETF哪个更好?\n"
            history += "2. AI: 这两个ETF追踪不同指数，适合不同投资策略...\n"
            history += "3. 用户: 那它们的风险如何?\n"
        except Exception as e:
            logger.error(f"获取历史消息失败: {str(e)}")
            history = f"获取历史消息时出现错误: {str(e)}"
        
        return history


class QuestionAnalysisToolInput(BaseModel):
    question: str = Field(description="待分析的问题")


class QuestionAnalysisTool(BaseTool):
    """问题意图分析工具 - 封装原有QuestionAgent"""
    name: str = "question_analysis"
    description: str = "分析用户问题的意图和输出格式偏好"
    args_schema: type[BaseModel] = QuestionAnalysisToolInput

    def _run(
        self,
        question: str,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # 初始化QuestionAgent并分析问题
        question_agent = QuestionAgent()
        decision = question_agent.analyze(question)
        
        result = {
            "intent": decision.intent,
            "output_format": decision.output_format,
            "top_k": decision.top_k,
            "doc_filter": decision.doc_filter
        }
        
        return str(result)


class OutputFormatAnalysisToolInput(BaseModel):
    intent: str = Field(description="问题意图")
    question: str = Field(description="用户问题")
    content: Optional[str] = Field(default="", description="上下文内容")


class OutputFormatAnalysisTool(BaseTool):
    """输出格式分析工具 - 封装原有OutputFormatAgent"""
    name: str = "output_format_analysis"
    description: str = "分析和决定AI回答的输出格式"
    args_schema: type[BaseModel] = OutputFormatAnalysisToolInput

    def _run(
        self,
        intent: str,
        question: str,
        content: Optional[str] = "",
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # 初始化OutputFormatAgent并分析格式
        output_format_agent = OutputFormatAgent()
        format_analysis = output_format_agent.analyze(
            intent=intent,
            content=content,
            user_preference=None  # 可以扩展为接收用户偏好
        )
        
        return str(format_analysis)


class DocumentAnalysisToolInput(BaseModel):
    content: str = Field(description="待分析的文档内容")
    doc_id: Optional[str] = Field(default=None, description="文档ID")


class DocumentAnalysisTool(BaseTool):
    """文档分析工具 - 封装原有DocumentAgent"""
    name: str = "document_analysis"
    description: str = "分析文档类型、结构和关键信息"
    args_schema: type[BaseModel] = DocumentAnalysisToolInput

    def _run(
        self,
        content: str,
        doc_id: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """同步运行工具"""
        # 初始化DocumentAgent并分析文档
        document_agent = DocumentAgent()
        analysis = document_agent.analyze(content, doc_id)
        
        return str(analysis)


def get_all_tools():
    """获取所有工具列表"""
    return [
        DocumentSearchTool(),
        CompareETFsTool(),
        RiskAssessmentTool(),
        PortfolioAnalysisTool(),
        MarketDataTool(),
        HistoryContextTool(),
        QuestionAnalysisTool(),
        OutputFormatAnalysisTool(),
        DocumentAnalysisTool()
    ]


def create_langchain_agent(zhipu_llm):
    """
    创建LangChain Agent，使用智谱AI作为LLM
    """
    from langchain.agents import create_tool_calling_agent, AgentExecutor
    from langchain_core.prompts import ChatPromptTemplate
    
    tools = get_all_tools()
    
    # 创建提示模板
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个专业的ETF投资顾问。你可以使用以下工具来回答用户的问题：{tools}。请根据用户问题选择合适的工具。"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    
    # 创建工具调用代理
    agent = create_tool_calling_agent(
        llm=zhipu_llm,
        tools=tools,
        prompt=prompt
    )
    
    # 创建执行器
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True
    )
    
    return agent_executor


def map_rule_agent_decision_to_tool(agent_decision: Any):
    """
    将规则型Agent的决策映射到对应的工具
    """
    tool_map = {
        "document_search": DocumentSearchTool(),
        "compare_etfs": CompareETFsTool(),
        "risk_assessment": RiskAssessmentTool(),
        "portfolio_analysis": PortfolioAnalysisTool(),
        "market_data": MarketDataTool(),
        "history_context": HistoryContextTool(),
        "general_chat": DocumentSearchTool()  # 默认使用文档搜索
    }
    
    tool_name = agent_decision.selected_tool
    if tool_name in tool_map:
        return tool_map[tool_name]
    
    # 如果找不到对应的工具，返回默认工具
    return tool_map["general_chat"]