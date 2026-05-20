"""
买入决策 Skill 节点函数

实现追问链、决策框架、执行计划生成等核心节点。
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from server.llm import get_llm
from server.graphs.lyra.state import LyraState
from server.graphs.lyra.workflows.buy_decision.state import (
    BuyDecisionSkillState,
    create_initial_buy_decision_state,
)
from server.skills.loader import SkillLoader
from server.graphs.lyra.prompts import get_system_prompt
from langgraph.types import interrupt

logger = logging.getLogger(__name__)


def _get_skill_loader() -> SkillLoader:
    """获取买入决策 Skill 加载器"""
    from server.skills.registry import get_skill_registry
    registry = get_skill_registry()
    metadata = registry.get_skill("buy-decision")
    return SkillLoader(metadata.path)


def _get_skill_state(state: LyraState) -> BuyDecisionSkillState:
    """从莱拉状态中提取买入决策 Skill 状态"""
    skill_state = state.get("skill_state", {})
    extra = skill_state.get("extra", {})
    if not extra:
        return create_initial_buy_decision_state()
    return BuyDecisionSkillState(**{k: v for k, v in extra.items() if k in BuyDecisionSkillState.__annotations__})


def _update_skill_state(
    state: LyraState,
    skill_state: BuyDecisionSkillState,
) -> Dict[str, Any]:
    """更新莱拉状态中的 Skill 状态"""
    return {
        "skill_state": {
            "current_step": "buy_decision",
            "extra": dict(skill_state),
        }
    }


async def quick_response_node(state: LyraState) -> Dict[str, Any]:
    """
    快速响应节点

    输出预告式回答，告知用户正在处理。
    """
    user_input = state["current_input"]
    targets = _extract_targets(user_input)

    skill_state = _get_skill_state(state)
    skill_state["targets"] = targets

    response = f"好的，我帮你看看{'、'.join(targets)}的情况。正在整理数据，请稍等..."

    logger.info(f"快速响应: targets={targets}")

    return {
        "response": response,
        **_update_skill_state(state, skill_state),
    }


async def intent_routing_node(state: LyraState) -> Dict[str, Any]:
    """
    意图分流节点

    判断用户是"简单了解"还是"深入分析"。
    """
    skill_state = _get_skill_state(state)
    user_input = state["current_input"]

    # 加载意图分流指引
    loader = _get_skill_loader()
    routing_guide = loader.load_reference("intent_routing")

    prompt = f"""{routing_guide}

用户问题："{user_input}"

请判断这个用户的意图是"简单了解"还是"深入分析"。
只返回 "simple" 或 "deep"，不要解释。"""

    try:
        llm = get_llm()
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        route = response.content.strip().lower()

        if route not in ("simple", "deep"):
            route = "deep"  # 默认走深入分析

    except Exception as e:
        logger.error(f"意图分流失败: {e}")
        route = "deep"

    skill_state["intent_route"] = route
    logger.info(f"意图分流: route={route}")

    return _update_skill_state(state, skill_state)


async def output_brief_report_node(state: LyraState) -> Dict[str, Any]:
    """
    输出简要数据报告节点

    将小研的简要数据格式化为用户可读的报告。
    """
    brief_data = state.get("brief_data")
    skill_state = _get_skill_state(state)
    targets = skill_state.get("targets", [])

    if not brief_data:
        report = "暂时无法获取数据，我们继续聊你的需求。"
    else:
        # 格式化简要报告
        comparison = brief_data.get("comparison", {})
        lines = [f"## {' vs '.join(targets)} 快速画像\n"]

        # 估值对比表
        lines.append("| 维度 | " + " | ".join(targets) + " |")
        lines.append("|------|" + "|".join(["------"] * len(targets)) + "|")

        for dim in ["估值(PE)", "资金流向"]:
            row = [dim]
            for t in targets:
                t_data = comparison.get(t, {})
                if dim == "估值(PE)":
                    val = t_data.get("valuation", {})
                    pe = val.get("pe", "N/A")
                    pct = val.get("pe_percentile", "")
                    row.append(f"{pe}（{pct}）" if pe != "N/A" else "N/A")
                elif dim == "资金流向":
                    flow = t_data.get("fund_flow", {})
                    row.append(flow.get("interpretation", "N/A"))
            lines.append("| " + " | ".join(row) + " |")

        # 市场观点
        market_view = brief_data.get("market_view_summary", "")
        if market_view:
            lines.append(f"\n**市场观点**：{market_view}")

        report = "\n".join(lines)

    # 根据意图分流决定后续
    if skill_state.get("intent_route") == "simple":
        report += "\n\n如果你是想做投资决策，我可以帮你深入分析，包括你的投资目标、风险承受能力这些，要不要继续聊？"
        return {
            "response": report,
            "should_end": True,
        }
    else:
        # 深入分析路径
        report += "\n\n接下来我想多了解你一些，这样我能给你更有针对性的分析。我会问你几个问题，大概花1-2分钟。你随时可以跳过任何问题。\n\n需要说明的是，我不会告诉你该买什么，但我会帮你理清思路，让你自己做判断。"

    skill_state["inquiry_step"] = 1
    return {
        "response": report,
        **_update_skill_state(state, skill_state),
    }


async def inquiry_chain_node(state: LyraState) -> Dict[str, Any]:
    """
    追问链节点

    使用 LangGraph interrupt() 原语实现多轮问答。
    每次生成问题后调用 interrupt() 暂停图执行，等待用户回复。
    用户回复后通过 Command(resume=answer) 恢复执行。
    """

    skill_state = _get_skill_state(state)
    step = skill_state.get("inquiry_step", 1)

    loader = _get_skill_loader()
    inquiry_guide = loader.load_reference("inquiry")

    # 检查是否应该跳过
    if skill_state.get("skip_remaining_inquiry") or skill_state.get("user_impatient"):
        return await _skip_to_detail_report(state, skill_state)

    # 记录用户上一轮的回答（step > 1 时，interrupt 返回了用户回答）
    if step > 1:
        user_answer = interrupt({
            "type": "inquiry_wait",
            "step": step - 1,
            "message": "等待用户回答追问问题",
        })
        # user_answer 是 Command(resume=value) 中的 value
        answers = skill_state.get("inquiry_answers", {})
        answers = _record_answer(answers, step - 1, user_answer)
        skill_state["inquiry_answers"] = answers

    # 根据步骤生成追问
    prompt = _build_inquiry_prompt(step, skill_state, inquiry_guide, state["current_input"])

    try:
        llm = get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=get_system_prompt()),
            SystemMessage(content=f"# 买入决策 Skill 指令\n\n{inquiry_guide}"),
            HumanMessage(content=prompt),
        ])
        reply = response.content

    except Exception as e:
        logger.error(f"追问生成失败: {e}")
        reply = "我们继续聊聊你的投资需求。"

    # 更新步骤
    if step == 2:
        # 步骤2后面插入标的理解（直接给，不追问）
        targets = skill_state.get("targets", [])
        target_info = _generate_target_understanding(targets, skill_state)
        reply += f"\n\n{target_info}"
        skill_state["target_understanding_given"] = True
        skill_state["inquiry_step"] = 3
    elif step == 5:
        # 步骤5是四条纪律
        skill_state["inquiry_step"] = 6
    else:
        skill_state["inquiry_step"] = step + 1

    return {
        "response": reply,
        **_update_skill_state(state, skill_state),
    }


async def four_rules_node(state: LyraState) -> Dict[str, Any]:
    """
    四条纪律节点

    追问第5步：买入后操作规则
    """
    skill_state = _get_skill_state(state)
    user_input = state["current_input"]

    loader = _get_skill_loader()
    four_rules_guide = loader.load_reference("four_rules")

    prompt = f"""{four_rules_guide}

用户之前的回答：
- 投资目标：{skill_state.get('inquiry_answers', {}).get('goal', '未回答')}
- 投资期限：{skill_state.get('inquiry_answers', {}).get('horizon', '未回答')}
- 风险承受：{skill_state.get('inquiry_answers', {}).get('risk_tolerance', '未回答')}

用户当前输入："{user_input}"

请按四条纪律的流程，逐一询问用户。先从第一条开始。"""

    try:
        llm = get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=prompt),
        ])
        reply = response.content

        # 记录四条纪律
        answers = skill_state.get("inquiry_answers", {})
        answers["post_buy_rules"] = user_input
        skill_state["inquiry_answers"] = answers

    except Exception as e:
        reply = "在你决定买之前，我们想清楚买入之后怎么办。几个问题：\n\n1. 你现在的买入逻辑是什么？什么情况下你会觉得这个逻辑不成立了？"

    skill_state["inquiry_step"] = 6
    return {
        "response": reply,
        **_update_skill_state(state, skill_state),
    }


async def output_detail_report_node(state: LyraState) -> Dict[str, Any]:
    """
    输出详细数据报告节点

    追问完成后，输出详细的数据分析报告。
    """
    detail_data = state.get("detail_data")
    skill_state = _get_skill_state(state)
    targets = skill_state.get("targets", [])
    answers = skill_state.get("inquiry_answers", {})

    if not detail_data:
        report = "暂时无法获取详细数据。你可以先根据已有的信息做判断，有具体问题随时问我。"
    else:
        # 构建详细报告
        report = _build_detail_report(detail_data, targets, answers)

    report += "\n\n以上是完整的数据分析。接下来，如果你想聊'我该怎么买'——包括选哪个、买多少、什么时候买——可以继续问我。"

    return {
        "response": report,
        **_update_skill_state(state, skill_state),
    }


async def decision_framework_node(state: LyraState) -> Dict[str, Any]:
    """
    决策框架节点

    根据用户的问题类型，提供对应的决策框架。
    """
    skill_state = _get_skill_state(state)
    user_input = state["current_input"]

    loader = _get_skill_loader()
    framework_guide = loader.load_reference("decision_framework")

    prompt = f"""{framework_guide}

用户问题："{user_input}"
用户的回答：
{skill_state.get('inquiry_answers', {})}

请根据用户的问题选择合适的决策框架，帮用户做决策分析。"""

    try:
        llm = get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=prompt),
        ])
        reply = response.content

    except Exception as e:
        reply = "关于你提到的买入方式，建议考虑分批定投。你能告诉我你更倾向于哪种方式吗？"

    return {
        "response": reply,
        **_update_skill_state(state, skill_state),
    }


async def generate_exec_plan_node(state: LyraState) -> Dict[str, Any]:
    """
    生成执行计划文档节点

    整合用户所有回答和数据，生成执行计划文档。
    """
    skill_state = _get_skill_state(state)
    targets = skill_state.get("targets", [])
    answers = skill_state.get("inquiry_answers", {})
    brief_data = state.get("brief_data", {})
    detail_data = state.get("detail_data", {})

    loader = _get_skill_loader()
    template = loader.load_asset("exec_plan_template")

    # 填充模板
    content = template.replace("{YYYY-MM-DD}", datetime.now().strftime("%Y-%m-%d"))
    content = content.replace("{标的A} vs {标的B}", " vs ".join(targets))

    # 用户信息
    content = content.replace("{用户回答}", answers.get("goal", "未提供"))
    content = content.replace("{用户选择}", answers.get("self_match_response", "待确认"))

    response = f"好，我来帮你整理一下你的决策计划：\n\n{content}\n\n确认一下，这是你想要的吗？如果需要修改任何部分，随时告诉我。"

    return {
        "response": response,
        "should_end": True,
        **_update_skill_state(state, skill_state),
    }


# ========== 辅助函数 ==========


def _extract_targets(text: str) -> List[str]:
    """从用户输入中提取标的"""
    known_etfs = [
        "消费50", "消费80", "沪深300", "中证500", "创业板",
        "科创50", "半导体", "芯片", "新能源", "光伏",
        "医药", "医疗", "银行", "证券", "军工",
        "白酒", "消费", "科技", "红利", "纳指",
    ]
    return list(set(etf for etf in known_etfs if etf in text))


def _record_answer(
    answers: dict,
    step: int,
    user_input: str,
) -> dict:
    """记录用户回答"""
    step_map = {
        1: "goal",
        2: "horizon",
        3: "risk_tolerance",
        4: "self_match_response",
        5: "post_buy_rules",
    }
    key = step_map.get(step)
    if key:
        answers[key] = user_input
    return answers


def _build_inquiry_prompt(
    step: int,
    skill_state: BuyDecisionSkillState,
    inquiry_guide: str,
    current_input: str,
) -> str:
    """构建追问 Prompt"""
    answers = skill_state.get("inquiry_answers", {})
    targets = skill_state.get("targets", [])

    step_prompts = {
        1: f"""当前步骤：追问1 - 投资目标
用户问题："{current_input}"

用户需要投资的对象：{'、'.join(targets)}

请温和地询问用户的投资目标。参考话术：
"你这次想买{targets[0] if targets else '这个'}，主要是出于什么考虑？"

注意：如果用户表现出 FOMO 倾势（如"看到别人赚了"），温和地指出。""",
        2: f"""当前步骤：追问2 - 投资期限
用户之前的回答：
- 投资目标：{answers.get('goal', '未回答')}

请询问用户的投资期限。参考话术：
"你打算这笔钱投多久？是短期想赚一波就走，还是打算长期持有？" """,
        3: f"""当前步骤：追问3 - 风险认知
用户之前的回答：
- 投资目标：{answers.get('goal', '未回答')}
- 投资期限：{answers.get('horizon', '未回答')}
- 标的理解已提供

请询问用户的风险承受能力。参考话术：
"接下来这个问题比较重要：如果买了之后浮亏20%，你会怎么做？是会慌着想卖、加仓摊薄、还是能忍住不动？" """,
        4: f"""当前步骤：追问4 - 自我匹配
用户之前的回答：
- 投资目标：{answers.get('goal', '未回答')}
- 投资期限：{answers.get('horizon', '未回答')}
- 风险承受：{answers.get('risk_tolerance', '未回答')}

当前数据（如果有）：
{skill_state.get('brief_data', '暂无数据')}

请综合用户信息，让用户自己判断是否匹配。参考话术：
"综合一下前面聊的..." 然后问 "结合你自己的情况，你觉得现在买适合你吗？" """,
    }

    return step_prompts.get(step, f"当前步骤：{step}\n用户输入：{current_input}")


def _generate_target_understanding(
    targets: List[str],
    skill_state: BuyDecisionSkillState,
) -> str:
    """生成标的理解内容"""
    if not targets:
        return ""

    composition = skill_state.get("brief_data", {}).get("comparison", {})

    lines = ["在继续之前，先帮你了解一下这几个标的："]

    # 简单的标的描述（后续可通过 RAG 或 akshare 获取更详细的信息）
    target_descriptions = {
        "消费50": "追踪中证主要消费指数，50只成分股中白酒占比约35%，偏龙头集中",
        "消费80": "追踪中证消费80指数，80只成分股更分散，白酒占比约25%",
    }

    for target in targets:
        desc = target_descriptions.get(target, f"{target}，具体信息正在查询中")
        lines.append(f"- **{target}**：{desc}")

    if len(targets) >= 2:
        lines.append(f"\n简单说，{targets[0]}偏龙头集中，{targets[1]}更分散。这个差异后面会结合你的情况分析。")

    return "\n".join(lines)


def _build_detail_report(
    detail_data: dict,
    targets: List[str],
    answers: dict,
) -> str:
    """构建详细数据报告"""
    lines = [f"## {' vs '.join(targets)} 深度分析报告\n"]

    # 估值
    valuation = detail_data.get("valuation", {})
    if valuation:
        lines.append("### 一、核心数据对比\n")
        lines.append("| 维度 | " + " | ".join(targets) + " |")
        lines.append("|------|" + "|".join(["------"] * len(targets)) + "|")
        for t in targets:
            t_val = valuation.get(t, {})
            lines.append(f"| PE | {t_val.get('pe', 'N/A')} |")
        lines.append("")

    # 正反观点
    bull_views = detail_data.get("bull_views", [])
    bear_views = detail_data.get("bear_views", [])
    if bull_views or bear_views:
        lines.append("### 二、观点汇总\n")
        if bull_views:
            lines.append("**看多观点：**")
            for v in bull_views[:3]:
                lines.append(f"- {v.get('content', '')[:100]}")
        if bear_views:
            lines.append("\n**看空观点：**")
            for v in bear_views[:3]:
                lines.append(f"- {v.get('content', '')[:100]}")
        lines.append("")

    # 投行观点
    inst_views = detail_data.get("institution_views", [])
    if inst_views:
        lines.append("### 三、投行/券商观点\n")
        for v in inst_views[:5]:
            lines.append(f"- {v.get('source', '未知')}: {v.get('content', '')[:80]}")
        lines.append("")

    # 风险提示
    lines.append("### 风险提示\n")
    for w in detail_data.get("risk_warnings", []):
        lines.append(f"- {w}")

    return "\n".join(lines)


async def _skip_to_detail_report(
    state: LyraState,
    skill_state: BuyDecisionSkillState,
) -> Dict[str, Any]:
    """跳过追问链，直接到详细报告"""
    return await output_detail_report_node(state)
