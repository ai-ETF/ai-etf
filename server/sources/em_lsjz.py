"""东财 `f10/lsjz` —— 单只最近净值源（`latest` + `history_recent`）。

端点：`https://api.fund.eastmoney.com/f10/lsjz?fundCode=...&pageIndex=...&pageSize=...`
域名：`api.fund.eastmoney.com`（**与 `fund.eastmoney.com` 独立**，对「域名被拒」
这类故障是净值线真正的隔离备选）

## 实测（2026-10-18）

- 110020：`TotalCount=4160`，`pageSize=20` → 4 KB / 0.18s；
- **`pageSize` 上限是 20**：传 100 仍返 20 条，传 500 返回 0 条；
- 因此**不能做全量历史**（4160 点要 208 次请求），能力声明为
  `latest` + `history_recent`，不做 `history`（设计文档 Q7）。

## ⚠️ 坑：货基字段同名但语义不同

对货币基金，`DWJZ` = **万份收益**、`LJJZ` = **7 日年化**，不是单位/累计净值。
同一个字段名在普通基金上是净值。映射函数**必须按基金类型分叉**：本实现检测
`Data.FundType == "005"` 后直接抛 `INVALID_REQUEST`，把货基留给现有的万份收益
专线（`portfolio_service._money_fund_per_10k_income`），绝不把 0.2221 当净值。
"""
import math
from datetime import date
from typing import Any, Optional

from server.sources.http import HttpSource
from server.sources.models import (
    CAP_HISTORY_RECENT,
    CAP_LATEST,
    FailureKind,
    NavPoint,
    SourceError,
    SourceMeta,
    to_decimal,
)

URL = "https://api.fund.eastmoney.com/f10/lsjz"

# 服务端上限实测为 20；超过它的请求只会返回 20 条，不能靠单次请求拿更多。
PAGE_SIZE = 20
# 本源的定位是「最近 N 条兜底」，不是全量历史。超过 200 点意味着 10+ 次请求，
# 交给声明 history 的源更合适；这里直接拒绝，让路由器继续尝试下一个源。
MAX_POINTS = 200

_MONEY_FUND_TYPE = "005"


def parse_lsjz_payload(
    payload: Any, code: str, source: str, limit: int
) -> list[NavPoint]:
    """把一页 lsjz JSON 解析成按日期升序的净值点。"""
    if not isinstance(payload, dict):
        raise SourceError(source, FailureKind.PARSE_ERROR, "响应不是 JSON 对象")

    err_code = payload.get("ErrCode")
    if err_code not in (None, 0, "0"):
        raise SourceError(
            source,
            FailureKind.EMPTY_PAYLOAD,
            f"上游返回错误对象: ErrCode={err_code} ErrMsg={payload.get('ErrMsg')!r}",
        )

    data = payload.get("Data")
    if not isinstance(data, dict):
        raise SourceError(
            source,
            FailureKind.EMPTY_PAYLOAD,
            f"响应 Data 为空: {payload.get('ErrMsg')!r}",
        )

    if str(data.get("FundType") or "") == _MONEY_FUND_TYPE:
        raise SourceError(
            source,
            FailureKind.INVALID_REQUEST,
            f"{code} 是货币基金：DWJZ/LJJZ 分别是万份收益/7日年化，不能当净值使用",
        )

    rows = data.get("LSJZList")
    if not isinstance(rows, list) or not rows:
        raise SourceError(
            source, FailureKind.EMPTY_PAYLOAD, f"{code} 的 LSJZList 为空"
        )

    points: list[NavPoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            nav_date = date.fromisoformat(str(row.get("FSRQ")))
        except (TypeError, ValueError):
            continue
        points.append(
            NavPoint(
                fund_code=code,
                nav_date=nav_date,
                unit_nav=to_decimal(row.get("DWJZ")),
                accumulated_nav=to_decimal(row.get("LJJZ")),
                daily_growth=to_decimal(row.get("JZZZL")),
                source=source,
            )
        )

    if not points:
        raise SourceError(
            source, FailureKind.EMPTY_PAYLOAD, f"{code} 没有可解析的净值日期"
        )

    points.sort(key=lambda p: p.nav_date)
    deduped: list[NavPoint] = []
    for point in points:
        if deduped and deduped[-1].nav_date == point.nav_date:
            deduped[-1] = point
        else:
            deduped.append(point)
    return deduped[-limit:] if limit else deduped


class EmLsjzSource(HttpSource):
    meta = SourceMeta(
        name="em_lsjz",
        domain="api.fund.eastmoney.com",
        capabilities=frozenset({CAP_LATEST, CAP_HISTORY_RECENT}),
        priority=90,
        timeout=15.0,
        description="东财单只最近净值，pageSize 上限 20；域名独立于 fund.eastmoney.com",
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": "https://fundf10.eastmoney.com/",
    }

    def fetch_history(self, code: str, limit: Optional[int] = None) -> list[NavPoint]:
        if limit is None:
            raise SourceError(
                self.meta.name,
                FailureKind.INVALID_REQUEST,
                "em_lsjz 只支持最近 N 条，不能做全量历史（pageSize 上限 20）",
            )
        if limit < 1:
            raise SourceError(
                self.meta.name, FailureKind.INVALID_REQUEST, f"limit 必须 >= 1: {limit}"
            )
        if limit > MAX_POINTS:
            raise SourceError(
                self.meta.name,
                FailureKind.INVALID_REQUEST,
                f"limit={limit} 超过本源的最近 {MAX_POINTS} 条定位；请使用 history 源",
            )

        pages = math.ceil(limit / PAGE_SIZE)
        collected: list[NavPoint] = []
        for page_index in range(1, pages + 1):
            payload = self._get_json(
                URL,
                params={
                    "fundCode": code,
                    "pageIndex": page_index,
                    "pageSize": PAGE_SIZE,
                },
            )
            points = parse_lsjz_payload(payload, code, self.meta.name, PAGE_SIZE)
            collected.extend(points)
            if len(points) < PAGE_SIZE:  # 已到最后一页
                break

        # 多页之间可能有重叠，按日期去重后取最近 limit 条
        by_date = {point.nav_date: point for point in collected}
        merged = [by_date[key] for key in sorted(by_date)]
        if not merged:
            raise SourceError(
                self.meta.name, FailureKind.EMPTY_PAYLOAD, f"{code} 没有取到净值"
            )
        return merged[-limit:]
