from server.agents.question_agent import QuestionAgent
from server.rag.embedder import Embedder
from server.rag.retriever import Retriever
from server.rag.prompt_builder import build_prompt
from server.storage.embedding_repo import EmbeddingRepo
from server.models.decision import DecisionResult
from server.config.settings import SETTINGS
import logging


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class QAService:
    """
    问答服务类
    负责处理用户问题，包括意图分析、向量检索和提示词构建
    """
    
    def __init__(self):
        """
        初始化问答服务
        创建问题分析智能体、嵌入器、检索器和嵌入存储实例
        """
        logger.debug("初始化问答服务")
        self.agent = QuestionAgent()
        self.embedder = Embedder(dim=SETTINGS.EMBED_DIM)
        self.emb_repo = EmbeddingRepo()
        self.retriever = Retriever(self.emb_repo)
        logger.debug(f"问答服务初始化完成，嵌入维度: {SETTINGS.EMBED_DIM}")

    def handle_question(self, question: str, doc_id: str = None):
        """
        处理用户问题
        
        参数:
            question: 用户的问题
            doc_id: 限制搜索范围的文档ID（可选）
            
        返回:
            包含提示词、决策结果和相关文本块的字典
        """
        logger.debug(f"开始处理问题: {question}")
        logger.debug(f"文档ID过滤: {doc_id}")
        
        # 分析问题意图和输出格式
        logger.debug("开始分析问题意图")
        decision: DecisionResult = self.agent.analyze(question)
        logger.debug(f"问题分析完成，结果: {decision}")
        
        # 生成问题的嵌入向量
        logger.debug("生成问题嵌入向量")
        qvec = self.embedder.embed_text(question)
        logger.debug(f"问题嵌入向量生成完成，维度: {len(qvec)}")
        
        # 检索相关文本块
        logger.debug(f"开始检索相关文本块，top_k: {decision.top_k}")
        top = self.retriever.retrieve(qvec, top_k=decision.top_k, doc_id=doc_id)
        logger.debug(f"检索完成，返回 {len(top)} 个文本块")
        
        # 构建完整提示词
        logger.debug("开始构建提示词")
        prompt = build_prompt(question, decision.__dict__, top)
        logger.debug(f"提示词构建完成，长度: {len(prompt)}")
        
        result = {"prompt": prompt, "decision": decision.__dict__, "top_chunks": top}
        logger.debug("问答处理完成")
        return result