"""
场外基金目录 API 端点

提供「可交易场外基金」的列表/搜索与详情查询，供前端选基金下单。

数据来源为 fund_fee_rules 白名单表 —— 出现在列表里 = 系统支持该基金；
不在列表里的基金下单会被直接拒绝（白名单机制）。

注意「在列表里」≠「当前能买」：目录会如实记录基金的申购状态
（subscribe_status），「暂停申购/封闭期」等状态的基金仍在列表里
（已持有的份额可以赎回），但买入会被拒。前端应据 subscribe_status 灰置买入按钮。

提供：
- GET /api/portfolio/funds              基金列表（支持关键词搜索 + 分页）
- GET /api/portfolio/funds/{fund_code}  单只基金详情（含申购/赎回费率分档）

与 /api/market/search 的区别：market 搜的是**场内 ETF 行情**，
此处是**场外可交易基金**（含交易规则与风险画像），两者用途不同。
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from server.auth import get_current_user
from server.models.schemas import (
    OffExchangeFundDetailResponse,
    OffExchangeFundItem,
    OffExchangeFundListResponse,
)
from server.services.fund_fee_service import FundFeeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _normalize_tiers(value):
    """Supabase 的 jsonb 通常已反序列化为 list，兼容仍为字符串的情况。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            logger.warning("费率分档 JSON 解析失败，按空处理")
            return None
    return value


@router.get("/funds", response_model=OffExchangeFundListResponse)
async def list_funds(
    keyword: str = Query(None, description="关键词，匹配基金代码或名称"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    current_user: str = Depends(get_current_user),
):
    """
    查询可交易的场外基金列表（需 JWT 认证）

    - 不带 keyword 时按基金代码顺序返回全部白名单基金
    - keyword 同时匹配基金代码与名称（模糊、不区分大小写）
    - 返回项含交易参数（最低申购金额、T+N）与风险等级；
      费率分档明细不在此接口返回，请调用详情接口
    """
    logger.info(f"查询场外基金列表: user={current_user}, keyword={keyword!r}, "
                f"page={page}, page_size={page_size}")
    svc = FundFeeService()
    result = svc.list_supported_funds(keyword=keyword, page=page, page_size=page_size)

    return OffExchangeFundListResponse(
        total=result["total"],
        page=page,
        page_size=page_size,
        items=[OffExchangeFundItem(**item) for item in result["items"]],
    )


@router.get("/funds/{fund_code}", response_model=OffExchangeFundDetailResponse)
async def get_fund_detail(
    fund_code: str,
    current_user: str = Depends(get_current_user),
):
    """
    查询单只场外基金的交易详情（需 JWT 认证）

    返回该基金的完整交易规则：运作费率、最低申购金额、T+N 确认/到账天数、
    申购费金额分档、赎回费持有天数分档，以及风险画像。
    基金不在白名单内时返回 404。
    """
    logger.info(f"查询场外基金详情: user={current_user}, code={fund_code}")
    svc = FundFeeService()
    detail = svc.get_fund_detail(fund_code)
    if not detail:
        raise HTTPException(status_code=404, detail=f"暂不支持基金 {fund_code} 的交易")

    return OffExchangeFundDetailResponse(
        **detail,
        purchase_fee_tiers=_normalize_tiers(detail.get("purchase_fee_tiers")),
        redemption_fee_tiers=_normalize_tiers(detail.get("redemption_fee_tiers")),
    )
