"""
RAG 知识库客户端

封装现有的 Retriever，提供异步接口，用于获取投行观点、行业分析框架等。
"""
import logging
from typing import Dict, Any, List, Optional

from server.rag.embedder import Embedder
from server.rag.retriever import Retriever

logger = logging.getLogger(__name__)


class RAGClient:
    """
    RAG 知识库客户端

    封装现有的 Embedder 和 Retriever，提供异步查询接口。
    用于获取投行观点、行业分析框架等高质量内容。
    """

    def __init__(self):
        self._embedder: Optional[Embedder] = None
        self._retriever: Optional[Retriever] = None

    @property
    def embedder(self) -> Embedder:
        """延迟初始化 Embedder"""
        if self._embedder is None:
            self._embedder = Embedder()
        return self._embedder

    @property
    def retriever(self) -> Retriever:
        """延迟初始化 Retriever"""
        if self._retriever is None:
            self._retriever = Retriever()
        return self._retriever

    async def query(
        self,
        query_text: str,
        top_k: int = 5,
        doc_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行 RAG 查询

        Args:
            query_text: 查询文本
            top_k: 返回结果数量
            doc_id: 限定文档 ID（可选）

        Returns:
            检索结果列表，每个元素包含 text, score, metadata
        """
        try:
            # 生成查询向量
            query_embedding = self.embedder.embed_text(query_text)

            # 执行向量检索
            results = self.retriever.retrieve(
                query_embedding=query_embedding,
                top_k=top_k,
                doc_id=doc_id,
            )

            return results

        except Exception as e:
            logger.error(f"RAG 查询失败: {e}")
            return []

    async def query_institution_views(
        self,
        targets: List[str],
        top_k_per_target: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        查询投行观点

        Args:
            targets: 标的/行业名称列表，如 ["消费50", "消费80", "消费"]
            top_k_per_target: 每个标的返回的结果数

        Returns:
            投行观点列表
        """
        views = []

        for target in targets:
            query = f"{target} 券商研报 观点 分析"
            results = await self.query(query, top_k=top_k_per_target)

            for r in results:
                views.append({
                    "target": target,
                    "content": r.get("text", ""),
                    "score": r.get("score", 0),
                    "source": r.get("doc_name", "未知来源"),
                })

        return views

    async def query_industry_framework(
        self,
        industry: str,
    ) -> Dict[str, Any]:
        """
        查询行业分析框架

        Args:
            industry: 行业名称，如 "消费", "科技", "医药"

        Returns:
            行业分析框架数据
        """
        query = f"{industry}行业 分析框架 核心指标 误区"
        results = await self.query(query, top_k=3)

        framework = {
            "industry": industry,
            "analysis_dimensions": [],
            "key_indicators": [],
            "common_mistakes": [],
            "raw_content": "",
        }

        if results:
            # 合并检索结果
            contents = [r.get("text", "") for r in results]
            framework["raw_content"] = "\n\n".join(contents)

        return framework

    async def query_bull_bear_views(
        self,
        target: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        查询看多/看空观点

        Args:
            target: 标的名称

        Returns:
            {"bull": [...], "bear": [...]}
        """
        bull_query = f"{target} 看多 乐观 上涨 机会 利好"
        bear_query = f"{target} 看空 悲观 下跌 风险 利空"

        bull_results = await self.query(bull_query, top_k=3)
        bear_results = await self.query(bear_query, top_k=3)

        def format_views(results: List[Dict]) -> List[Dict]:
            formatted = []
            for r in results:
                formatted.append({
                    "content": r.get("text", ""),
                    "score": r.get("score", 0),
                    "source": r.get("doc_name", "未知来源"),
                })
            return formatted

        return {
            "bull": format_views(bull_results),
            "bear": format_views(bear_results),
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        检查 RAG 数据源健康状态

        Returns:
            健康状态信息
        """
        status = {
            "status": "unknown",
            "error": None,
            "doc_count": 0,
        }

        try:
            # 执行一个简单查询测试
            results = await self.query("测试查询", top_k=1)
            status["status"] = "ok"
            status["doc_count"] = len(results)

        except Exception as e:
            status["status"] = "down"
            status["error"] = str(e)

        return status


# 全局单例
_client: Optional[RAGClient] = None


def get_rag_client() -> RAGClient:
    """获取 RAGClient 单例"""
    global _client
    if _client is None:
        _client = RAGClient()
    return _client
