from server.agents.question_agent import QuestionAgent
from server.agents.document_agent import DocumentAgent
from server.agents.output_format_agent import OutputFormatAgent
from server.agents.etf_rule_agent import ETFRuleBasedAgent
from server.rag.embedder import Embedder
from server.rag.retriever import Retriever
from server.rag.prompt_builder import build_prompt
from server.storage.embedding_repo import EmbeddingRepo
from server.config.settings import SETTINGS
from server.storage.supabase_client import get_supabase
import logging
import time

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
        logger.debug("🚀 初始化问答服务")
        self.agent = QuestionAgent()
        self.document_agent = DocumentAgent()
        self.output_format_agent = OutputFormatAgent()
        self.rule_agent = ETFRuleBasedAgent()  # 新增规则型Agent
        self.embedder = Embedder(dim=SETTINGS.EMBED_DIM)
        self.emb_repo = EmbeddingRepo()
        self.retriever = Retriever(self.emb_repo)
        
        # 初始化Supabase客户端用于AI请求
        self.supabase = get_supabase()
        
        logger.debug(f"✅ 问答服务初始化完成，嵌入维度: {SETTINGS.EMBED_DIM}")

    def handle_question(self, question: str, doc_id: str = None):
        """
        处理用户问题，通过智能体决策、向量检索、生成完整Prompt并发送到Supabase进行AI处理
        """
        logger.info(f"❓ 开始处理用户问题: {question}")
        
        # 使用规则型智能体进行意图识别
        logger.debug("🧠 使用规则型智能体进行意图识别...")
        agent_decision = self.rule_agent.decide_intent(question)
        logger.info(f"🎯 意图识别结果: {agent_decision.intent}")
        
        # 统一处理：所有意图均走 RAG + Supabase AI 流程
        logger.debug("📝 开始统一RAG流程处理...")
        
        # 使用QuestionAgent分析问题
        logger.debug("🧠 使用QuestionAgent分析问题...")
        decision = self.agent.analyze(question)
        logger.info(f"📋 问题分析结果 - 意图: {decision.intent}, 格式: {decision.output_format}")
        
        # 使用OutputFormatAgent分析输出格式
        logger.debug("🎨 使用OutputFormatAgent分析输出格式...")
        format_result = self.output_format_agent.analyze(
            intent=decision.intent,
            content=question
        )
        logger.info(f"📝 输出格式分析: {format_result['primary_format']}")
        
        # 生成查询向量
        logger.debug("🧮 生成查询向量...")
        qvec = self.embedder.embed_text(question)
        
        # 执行向量检索
        logger.debug(f"🔍 执行向量检索，Top-K: {decision.top_k}...")
        results = self.retriever.retrieve(qvec, top_k=decision.top_k, doc_id=doc_id)
        logger.info(f"✅ 检索完成，获得 {len(results)} 个相关文档块")
        
        # 将results转换为chunks格式，用于构建提示词
        chunks = []
        for result in results:
            chunks.append({
                "text": result["text"],
                "score": result.get("similarity", 0)
            })
        
        # 构建决策字典
        decision_dict = {
            "intent": decision.intent,
            "output_format": decision.output_format
        }
        
        # 构建完整提示词
        logger.debug("💬 构建完整回答提示词...")
        full_prompt = build_prompt(
            question=question,
            decision=decision_dict,
            chunks=chunks,
            format_analysis=format_result
        )
        logger.debug(f"📋 构建的完整提示词: {full_prompt[:200]}...")  # 只显示前200字符
        
        # 将完整Prompt发送到Supabase，由Supabase转发给AI处理
        logger.info("🔄 将完整Prompt发送到Supabase进行AI处理...")
        ai_response = self._send_prompt_to_supabase_and_get_response(full_prompt)

        # 返回结果
        result = {
            "prompt": full_prompt,
            "decision": decision,
            "top_chunks": results,
            "ai_response": ai_response
        }
        
        logger.info("✅ 问题处理完成")
        return result


        
    def _send_prompt_to_supabase_and_get_response(self, prompt: str):
        """
        将完整Prompt发送到Supabase，由Supabase转发给AI处理并返回响应
        """
        if not self.supabase:
            logger.error("❌ Supabase客户端未初始化，无法发送AI请求")
            return "抱歉，AI服务暂时不可用"
        
        try:
            # 将Prompt发送到Supabase的AI请求表
            ai_request_data = {
                "prompt": prompt,
                "status": "pending",
                "created_at": "now()"
            }
            
            logger.debug("🔄 向Supabase提交AI处理请求")
            response = self.supabase.table("ai_requests").insert(ai_request_data).execute()
            
            # 获取请求ID
            request_id = response.data[0]['id']
            logger.debug(f"🆔 AI请求已提交，请求ID: {request_id}")
            
            # 等待AI处理完成（轮询状态）
            max_attempts = 60  # 最多等待60次（30秒）
            attempt = 0
            
            while attempt < max_attempts:
                # 查询处理状态
                result = (self.supabase
                         .table("ai_requests")
                         .select("status,response")
                         .eq("id", request_id)
                         .execute())
                
                if result.data and len(result.data) > 0:
                    req_data = result.data[0]
                    
                    if req_data['status'] == 'completed':
                        logger.debug(f"✅ AI处理完成，请求ID: {request_id}")
                        return req_data.get('response', '')
                    elif req_data['status'] == 'failed':
                        logger.error(f"❌ AI处理失败，请求ID: {request_id}")
                        return "AI处理请求时发生错误"
                
                time.sleep(0.5)  # 等待0.5秒后重试
                attempt += 1
            
            logger.error(f"⏰ AI处理超时，请求ID: {request_id}")
            return "AI处理请求超时"
            
        except Exception as e:
            logger.error(f"❌ 发送Prompt到Supabase时发生错误: {str(e)}")
            return f"发送请求时发生错误: {str(e)}"

def format_prompt_for_log(prompt: str) -> str:
    if len(prompt) <= 600:
        return prompt
    return f"{prompt[:500]}...{prompt[-100:]}"
