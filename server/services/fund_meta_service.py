"""基金元数据读服务。

设计依据：`docs/20-设计/行情/多源适配器接入方案.md` §4.3。

- 业务层不得为「经理 / 公司 / QDII」再出一趟网，元数据只从 `fund` 表读；
- 元数据缺失时返回 `None`，由调用方显式处理；**不提供 `is_qdii()` 这种缺失即
  `False` 的便捷方法**，避免把「不知道」伪装成「不是 QDII」。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

import logging

logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000

_META_FIELDS = (
    "fund_code,fund_name,ftype,manager_company,fund_manager,"
    "tracking_index,tracking_index_code,establish_date,net_asset_scale,"
    "risk_level_code,is_qdii,qdii_reason,lifecycle_status"
)


@dataclass(frozen=True)
class FundMeta:
    fund_code: str
    fund_name: str
    ftype: Optional[str] = None
    manager_company: Optional[str] = None
    fund_manager: Optional[str] = None
    tracking_index: Optional[str] = None
    tracking_index_code: Optional[str] = None
    establish_date: Optional[date] = None
    net_asset_scale: Optional[Decimal] = None
    risk_level_code: Optional[str] = None
    is_qdii: Optional[bool] = None
    qdii_reason: Optional[str] = None
    lifecycle_status: str = "active"


class FundMetaService:
    """基金元数据读入口（无状态，可注入 client）。"""

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase

            self._client = get_supabase()
        return self._client

    def get(self, code: str) -> Optional[FundMeta]:
        text = str(code).strip() if code is not None else ""
        if not text:
            return None
        result = (
            self.client.table("fund")
            .select(_META_FIELDS)
            .eq("fund_code", text)
            .limit(1)
            .execute()
        )
        return _to_meta(result.data[0]) if result.data else None

    def get_batch(self, codes: list[str]) -> dict[str, FundMeta]:
        normalized = [str(c).strip() for c in codes or [] if str(c).strip()]
        if not normalized:
            return {}
        result = (
            self.client.table("fund")
            .select(_META_FIELDS)
            .in_("fund_code", normalized)
            .execute()
        )
        return {row["fund_code"]: _to_meta(row) for row in result.data or []}

    def search(self, keyword: str, limit: int = 10) -> list[FundMeta]:
        """在**支持目录**（`fund_catalog`）内按代码或名称模糊搜索。

        只搜 `fund_catalog` 而不是 `fund`：后者含未上架 / 无交易规则的基金，
        搜出来用户买不了（2026-10-26 决策：场内 ETF 不在目录内，搜代码无结果）。

        参数:
            keyword: 代码片段（"1100"）或名称片段（"红利"）
            limit: 返回条数上限

        返回:
            按 `fund_code` 升序排列的元数据列表；无匹配返回空列表
        """
        pattern = _ilike_pattern(keyword)
        if pattern is None or limit < 1:
            return []
        result = (
            self.client.table("fund_catalog")
            .select(_META_FIELDS)
            .or_(f"fund_code.ilike.{pattern},fund_name.ilike.{pattern}")
            .order("fund_code")
            .limit(int(limit))
            .execute()
        )
        return [_to_meta(row) for row in result.data or []]


def _ilike_pattern(keyword: str) -> Optional[str]:
    """把用户输入转成 PostgREST `ilike` 的 `*片段*` 模式；空输入返回 None。

    PostgREST 的过滤串用 `,` 分隔条件、`()` 分组、`*` 作通配符，
    因此这里剔除会让过滤语法断裂的字符，避免用户输入被当成语法解析。
    基金名称为中文、代码为数字，剔掉这些字符不影响正常搜索。
    """
    text = str(keyword or "").strip()
    forbidden = set(",()*%\\")
    cleaned = "".join(ch for ch in text if ch not in forbidden)
    if not cleaned:
        return None
    return f"*{cleaned}*"


def _to_meta(row: dict) -> FundMeta:
    return FundMeta(
        fund_code=str(row["fund_code"]),
        fund_name=str(row.get("fund_name") or ""),
        ftype=row.get("ftype"),
        manager_company=row.get("manager_company"),
        fund_manager=row.get("fund_manager"),
        tracking_index=row.get("tracking_index"),
        tracking_index_code=row.get("tracking_index_code"),
        establish_date=_to_date(row.get("establish_date")),
        net_asset_scale=_to_decimal(row.get("net_asset_scale")),
        risk_level_code=row.get("risk_level_code"),
        is_qdii=row.get("is_qdii"),
        qdii_reason=row.get("qdii_reason"),
        lifecycle_status=row.get("lifecycle_status") or "active",
    )


def _to_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _to_decimal(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return Decimal(str(value))
