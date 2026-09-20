"""P2-8 LangGraph 图执行集成测试：QA 图真实 ainvoke 编排。

模块名称：QA 分析图（classify_intent → determine_format）
所测功能：真实图执行（规则快速通道不触发 LLM）、state 流转、返回结构
使用的测试方法：真实 ainvoke + 规则快速通道（comparison/factual_query 意图，不 mock LLM）

注：只测规则快速通道（命中规则直接返回、不触发 LLM），保证确定性；general 意图
会走 LLM tool-calling 路径，属 P2-10（LLM eval）范畴，此处不测。
"""
import asyncio

import pytest

pytestmark = pytest.mark.integration


def test_qa图_规则快速通道_comparison意图():
    from server.graphs.qa.graph import arun_qa_analysis

    result = asyncio.run(arun_qa_analysis("对比一下红利ETF和华泰柏瑞的差异"))
    assert result["intent"] == "comparison"
    assert result["top_k"] > 0
    assert result["output_format"] in ("text", "table")
    # 格式分析结果存在（determine_format 节点已执行）
    assert result.get("format_analysis")


def test_qa图_规则快速通道_factual_query意图():
    from server.graphs.qa.graph import arun_qa_analysis

    result = asyncio.run(arun_qa_analysis("红利ETF的净值是多少"))
    assert result["intent"] == "factual_query"
    assert result["top_k"] > 0
