"""
莱拉主控 Agent 节点函数

实现意图识别、情绪检测、路由、输出等核心节点。
"""
import json
import logging
import asyncio
from typing import Dict, Any, Optional
from uuid import uuid4

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from server.config.settings import SETTINGS
from server.graphs.lyra.state import LyraState, create_initial_state
from server.graphs.lyra.prompts import (
    get_system_prompt,
    detect_emotion,
    get_emotion_intervention_prompt,
    get_intent_classification_prompt,
)
from server.skills.registry import get_skill_registry
from server.skills.loader import SkillLoader
from server.llm import get_llm, get_llm_with_tools
from server.graphs.lyra.tools import INTENT_TOOLS, TOOL_NAME_TO_INTENT

logger = logging.getLogger(__name__)


async def entry_node(state: LyraState) -> Dict[str, Any]:
    """
    入口节点

    1. 将用户输入添加到消息历史（避免重复添加）
    2. 触发小研异步数据收集
    """
    logger.info(
        f"用户输入: session_id={state.get('session_id')}, "
        f"input={state['current_input'][:50]}..."
    )

    messages = state.get("messages", [])
    # 避免重复添加同一条消息（多轮对话循环回来时 current_input 可能不变）
    current_input = state["current_input"]
    if not messages or not (
        hasattr(messages[-1], "content") and messages[-1].content == current_input
    ):
        messages.append(HumanMessage(content=current_input))

    # 尝试从用户输入中提取标的
    targets = _extract_targets(state["current_input"])
    xiaoyan_request_id = str(uuid4())

    # 异步触发小研数据收集（不等待完成）
    # 在 MVP 中，我们先同步收集简要数据
    # TODO: 改为真正的异步触发
    data_status = state.get("data_status", {
        "collection_id": xiaoyan_request_id,
        "brief_ready": False,
        "detail_ready": False,
        "progress": "0%",
    })

    return {
        "messages": messages,
        "xiaoyan_request_id": xiaoyan_request_id,
        "data_status": data_status,
    }


async def check_emotion_node(state: LyraState) -> Dict[str, Any]:
    """
    情绪检测节点

    每轮对话检测情绪信号，返回检测到的情绪标签。
    """
    user_input = state["current_input"]
    emotion_flags = detect_emotion(user_input)

    logger.info(f"情绪检测: {emotion_flags or '无情绪信号'}")

    return {
        "emotion_flags": emotion_flags,
        "emotion_intervened": False,
    }


async def emotion_intervention_node(state: LyraState) -> Dict[str, Any]:
    """
    情绪干预节点

    对检测到的情绪进行三步法干预：情绪确认 → 认知重构 → 行动框架
    """
    emotion_flags = state.get("emotion_flags", [])
    user_input = state["current_input"]

    # 选择第一个检测到的情绪进行干预
    emotion = emotion_flags[0] if emotion_flags else "anxiety"

    logger.info(f"执行情绪干预: emotion={emotion}")

    # 构建情绪干预 Prompt
    emotion_prompt = get_emotion_intervention_prompt(emotion, user_input)

    # 使用 LLM 生成干预回复
    llm = get_llm()

    messages = [
        SystemMessage(content=get_system_prompt()),
        SystemMessage(content=emotion_prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        response_text = response.content

        logger.info(f"情绪干预回复: {response_text[:100]}...")

        return {
            "response": response_text,
            "emotion_intervened": True,
            "should_end": False,
        }

    except Exception as e:
        logger.error(f"情绪干预失败: {e}")
        return {
            "response": "我理解你现在的感受。让我们先冷静一下，再看看具体数据。",
            "emotion_intervened": True,
            "error": str(e),
        }


async def classify_intent_node(state: LyraState) -> Dict[str, Any]:
    """
    意图识别节点

    两层路由：
    1. 快速通道：关键词匹配（置信度 > 0.8 直接使用）
    2. LLM tool calling：让 LLM 通过 bind_tools 选择意图工具
    """
    user_input = state["current_input"]
    registry = get_skill_registry()

    # 快速通道：关键词匹配
    matched_skill = registry.select_skill(user_input)
    if matched_skill and matched_skill.name != "unknown":
        logger.info(f"意图识别（关键词快速通道）: skill={matched_skill.name}")
        return {
            "intent": matched_skill.name,
            "current_skill": matched_skill.name,
            "intent_confidence": 0.9,
        }

    # LLM tool calling 路由
    intent = await _llm_classify_intent_with_tools(user_input)

    logger.info(f"意图识别（tool calling）: intent={intent}")
    return {
        "intent": intent,
        "current_skill": intent if intent != "unknown" else None,
        "intent_confidence": 1.0 if intent != "unknown" else 0.3,
    }


async def check_data_status_node(state: LyraState) -> Dict[str, Any]:
    """
    检查数据状态节点

    检查小研的数据收集进度，如果数据就绪则注入到状态中。
    """
    # MVP: 数据收集是同步的，这里简单检查
    # TODO: 接入真正的小研异步数据收集
    data_status = state.get("data_status", {})

    if data_status.get("brief_ready"):
        logger.info("简要数据已就绪")
    else:
        logger.info("简要数据未就绪，等待中...")

    return {}


async def _llm_direct_answer(state: LyraState) -> str:
    """没有 skill 实现时，调用 LLM 直接回答用户问题"""
    user_input = state.get("current_input", "")
    messages = state.get("messages", [])

    try:
        llm = get_llm()
        system_prompt = get_system_prompt()

        # 构建对话历史（最近 5 条）
        chat_messages = [SystemMessage(content=system_prompt)]
        for msg in messages[-5:]:
            chat_messages.append(msg)
        chat_messages.append(HumanMessage(content=user_input))

        response = await llm.ainvoke(chat_messages)
        return response.content
    except Exception as e:
        logger.error(f"LLM 直接回答失败: {e}")
        return "抱歉，我暂时无法回答这个问题。请稍后再试。"


async def output_node(state: LyraState) -> Dict[str, Any]:
    """
    输出节点

    格式化最终响应并输出。
    如果没有 skill 生成的响应，调用 LLM 直接回答。
    """
    response = state.get("response")

    if not response:
        intent = state.get("intent")

        if intent == "unknown":
            response = "这个问题我还在学习中。你可以试试问我关于 ETF 买入、对比、定投方面的问题。"
        else:
            # 没有 skill 实现的意图，让 LLM 直接回答
            response = await _llm_direct_answer(state)

    messages = state.get("messages", [])
    # 避免重复追加同一条响应
    if response and (
        not messages
        or not hasattr(messages[-1], "content")
        or messages[-1].content != response
    ):
        messages.append(AIMessage(content=response))

    logger.info(f"输出响应: {response[:100] if response else 'None'}...")

    # 没有 skill 实现的意图直接结束，避免循环
    # 只有 buy_decision 有完整 skill 实现，由 skill 自己控制是否结束
    current_skill = state.get("current_skill")
    has_skill_flow = current_skill == "buy_decision"
    should_end = not has_skill_flow

    return {
        "response": response,
        "messages": messages,
        "should_end": should_end,
    }


async def save_state_node(state: LyraState) -> Dict[str, Any]:
    """
    保存状态节点

    将当前状态持久化到 Supabase。
    """
    try:
        from server.storage.session_repo import get_session_repo

        repo = get_session_repo()
        await repo.save_state(
            session_id=state["session_id"],
            user_id=state["user_id"],
            state=dict(state),
        )
        logger.debug(f"状态已保存: session_id={state['session_id']}")
    except Exception as e:
        logger.error(f"保存状态失败: {e}")

    return {}


async def route_to_skill_node(state: LyraState) -> Dict[str, Any]:
    """
    路由到 Skill 节点

    加载对应 Skill 的内容，注入到状态中。
    """
    skill_name = state.get("current_skill")

    if not skill_name:
        return {"response": None}

    registry = get_skill_registry()
    metadata = registry.get_skill(skill_name)

    if not metadata:
        return {"response": None}

    # 加载完整 Skill 内容
    loader = SkillLoader(metadata.path)
    skill_content = loader.load_full_skill()
    skill_config = loader.load_config()

    logger.info(f"已加载 Skill: {skill_name}")

    # 将 Skill 信息存入 skill_state
    skill_state = state.get("skill_state", {})
    skill_state["extra"] = {
        "skill_content": skill_content,
        "skill_config": skill_config,
        "skill_name": skill_name,
    }

    return {
        "skill_state": skill_state,
    }


# ========== 辅助函数 ==========


def _extract_targets(text: str) -> list[str]:
    """
    从用户输入中提取标的名称

    简单实现：提取常见的 ETF 关键词
    后续可改用 NER 模型
    """
    # 常见 ETF 名称关键词
    known_etfs = [
        "消费50", "消费80", "沪深300", "中证500", "创业板",
        "科创50", "半导体", "芯片", "新能源", "光伏",
        "医药", "医疗", "银行", "证券", "军工",
        "白酒", "消费", "科技", "红利", "纳指",
    ]

    targets = []
    for etf in known_etfs:
        if etf in text:
            targets.append(etf)

    return list(set(targets))


async def _llm_classify_intent_with_tools(user_input: str) -> str:
    """
    使用 LLM tool calling 分类意图

    通过 bind_tools 让 LLM 直接选择意图工具，比自由文本解析更可靠。

    Args:
        user_input: 用户输入

    Returns:
        意图类别
    """

    try:
        llm_with_tools = get_llm_with_tools(INTENT_TOOLS)

        messages = [
            SystemMessage(content=get_intent_classification_prompt()),
            HumanMessage(content=user_input),
        ]

        response = await llm_with_tools.ainvoke(messages)

        # 解析 tool_calls
        if response.tool_calls:
            tool_name = response.tool_calls[0]["name"]
            intent = TOOL_NAME_TO_INTENT.get(tool_name, "unknown")
            return intent

        return "unknown"

    except Exception as e:
        logger.error(f"LLM tool calling 意图分类失败: {e}")
        return "unknown"
