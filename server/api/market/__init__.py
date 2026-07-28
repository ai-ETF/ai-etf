"""
市场数据 API 聚合器

按用途将行情数据拆分为 5 个子模块：
- quotes:     实时行情 + 榜单（高频查询）
- historical: K线 + 分时图（历史/当日走势）
- detail:     ETF 详细信息
- search:     搜索/筛选/分类
- money_flow: 资金流向
"""
import logging

from fastapi import APIRouter
from . import quotes, historical, detail, search, money_flow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])
router.include_router(quotes.router)
router.include_router(historical.router)
router.include_router(detail.router)
router.include_router(search.router)
router.include_router(money_flow.router)


@router.get("/health")
async def health_check():
    """市场数据服务健康检查"""
    return {"status": "ok", "service": "market"}


__all__ = [
    "quotes", "historical", "detail", "search", "money_flow", "router",
]
