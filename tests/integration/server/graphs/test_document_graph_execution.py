"""P2-8 LangGraph 图执行集成测试：文档图真实 ainvoke 编排。

模块名称：文档分析图（classify_document_type → analyze_structure）
所测功能：真实图执行、文档类型分类、结构分析、返回结构
使用的测试方法：真实 ainvoke + 规则快速通道（不 mock LLM）
"""
import asyncio

import pytest

pytestmark = pytest.mark.integration


def test_文档图_分类ETF报告():
    from server.graphs.document.graph import arun_document_analysis

    result = asyncio.run(
        arun_document_analysis("本基金为股票型基金，投资范围包括国内依法发行的股票、债券。")
    )
    assert result["document_type"] in ("etf_report", "fund_prospectus", "general_document")
    assert 0.0 <= result["confidence"] <= 1.0
    assert "content_structure" in result
    assert "suggested_chunk_strategy" in result


def test_文档图_空内容不崩溃():
    from server.graphs.document.graph import arun_document_analysis

    result = asyncio.run(arun_document_analysis(""))
    assert "document_type" in result
