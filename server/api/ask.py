from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from server.models.schemas import AskRequest, AskResponse
from server.services.qa_service import QAService
import logging
import json
import uuid

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    """
    传统问答端点，返回完整响应
    """
    logger.debug(f"收到问答请求，问题: {req.question}, 文档ID: {req.doc_id}")
    svc = QAService()
    
    try:
        logger.debug("开始处理问答请求")
        result = svc.handle_question(req.question, doc_id=req.doc_id, user_id="default_user", chat_id="default_chat")
        logger.debug("问答处理完成")
    except Exception as e:
        logger.error(f"处理问答请求时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
        
    response = AskResponse(
        prompt=result["prompt"], 
        decision=result.get("decision"), 
        top_chunks=result.get("top_chunks")
    )
    logger.debug(f"返回响应")
    return response


@router.post("/ask-stream")
async def ask_stream(req: AskRequest):
    """
    流式问答端点，通过SSE返回结果
    此端点会将完整Prompt发送到Supabase，由Supabase转发给AI处理
    """
    logger.debug(f"收到流式问答请求，问题: {req.question}, 文档ID: {req.doc_id}")
    
    svc = QAService()
    
    async def event_generator():
        try:
            # 使用规则型智能体进行意图识别
            logger.debug("🧠 使用规则型智能体进行意图识别...")
            agent_decision = svc.rule_agent.decide_intent(req.question, "default_user", "default_chat")
            logger.info(f"🎯 意图识别结果: {agent_decision.intent}")
            
            # 发送意图识别结果
            yield f"data: {json.dumps({'type': 'analysis', 'content': str(agent_decision.intent)})}\n\n"
            
            # 使用QuestionAgent分析问题
            logger.debug("🧠 使用QuestionAgent分析问题...")
            decision = svc.agent.analyze(req.question)
            logger.info(f"📋 问题分析结果 - 意图: {decision.intent}, 格式: {decision.output_format}")
            
            # 发送问题分析结果
            yield f"data: {json.dumps({'type': 'question_analysis', 'content': str(decision)})}\n\n"
            
            # 使用OutputFormatAgent分析输出格式
            logger.debug("🎨 使用OutputFormatAgent分析输出格式...")
            format_result = svc.output_format_agent.analyze(
                intent=decision.intent,
                content:req.question
            )
            logger.info(f"📝 输出格式分析: {format_result['primary_format']}")
            
            # 发送格式分析结果
            yield f"data: {json.dumps({'type': 'format_analysis', 'content': format_result['primary_format']})}\n\n"
            
            # 生成查询向量
            logger.debug("🧮 生成查询向量...")
            qvec = svc.embedder.embed_text(req.question)
            
            # 执行向量检索
            logger.debug(f"🔍 执行向量检索，Top-K: {decision.top_k}...")
            results = svc.retriever.retrieve(qvec, top_k=decision.top_k, doc_id=req.doc_id)
            logger.info(f"✅ 检索完成，获得 {len(results)} 个相关文档块")
            
            # 发送检索结果
            yield f"data: {json.dumps({'type': 'retrieval', 'content': len(results)})}\n\n"
            
            # 将results转换为chunks格式，用于构建提示词
            chunks = []
            for result in results:
                chunks.append({
                    "text": result["text"],
                    "score": result.get("similarity", 0)  # 假设有相似度分数
                })
            
            # 构建决策字典
            decision_dict = {
                "intent": decision.intent,
                "output_format": decision.output_format
            }
            
            # 构建完整提示词
            logger.debug("💬 构建完整回答提示词...")
            full_prompt = build_prompt(
                question=req.question,
                decision=decision_dict,
                chunks=chunks,
                format_analysis=format_result
            )
            logger.debug(f"📋 构建的完整提示词: {full_prompt[:200]}...")  # 只显示前200个字符
            
            # 发送构建的完整提示词
            yield f"data: {json.dumps({'type': 'prompt', 'content': full_prompt})}\n\n"
            
            # 将完整Prompt发送到Supabase，由Supabase转发给AI处理
            logger.info("🔄 通过Supabase获取AI流式响应...")
            
            # 生成唯一会话ID
            session_id = str(uuid.uuid4())
            
            # 创建AI请求并获取响应
            ai_response = svc._send_prompt_to_supabase_and_get_response(full_prompt)
            
            # 流式返回AI响应
            logger.info("🔄 开始流式返回AI响应...")
            
            # 将响应按字符流式发送
            for char in ai_response:
                yield f"data: {json.dumps({'type': 'token', 'content': char})}\n\n"
            
            # 发送完成信号
            yield f"data: {json.dumps({'type': 'done', 'content': 'complete'})}\n\n"
            
        except Exception as e:
            logger.error(f"处理流式问答请求时发生错误: {str(e)}")
            error_data = {
                "type": "error", 
                "content": f"处理请求时发生错误: {str(e)}"
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# 导入需要的模块
from server.rag.prompt_builder import build_prompt