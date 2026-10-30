"""
市场数据 API 聚合器

2026-10-26：场内 ETF 的 30 秒行情轮询下线后，行情/榜单/资金流/筛选/分类接口
一并删除（`quotes.py`、`money_flow.py`）。剩余子模块：

- historical: K线 + 分时图（历史/当日走势）
- detail:     基金详细信息
- search:     搜索（只搜支持目录内的场外基金）
"""
import logging

from fastapi import APIRouter
from . import historical, detail, search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])
router.include_router(historical.router)
router.include_router(detail.router)
router.include_router(search.router)


@router.get("/health")
async def health_check():
    """市场数据服务健康检查"""
    return {"status": "ok", "service": "market"}


__all__ = [
    "historical", "detail", "search", "router",
]
