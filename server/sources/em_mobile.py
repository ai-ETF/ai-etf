"""东财移动端基础信息 —— 单只最新净值源（`latest`）。

端点：`https://fundmobapi.eastmoney.com/FundMNewApi/FundMNBasicInformation`
域名：`fundmobapi.eastmoney.com`（与 `fund.eastmoney.com` / `api.fund.eastmoney.com`
都独立，是净值线第三个可隔离的出口）

## 实测（2026-10-18）

- 110020：约 2.4 KB / 单只，`FSRQ=2026-10-16 DWJZ=1.7219 LJJZ=1.7219 RZDF=0.13`；
- **`daily_growth` 对应 `RZDF`**（日增长率），不是 `JZZZL`。已核对设计文档 §6.1。

## ⚠️ 货基检测

该接口不返回 FundType 代码，只有 `FTYPE` 文本。货币基金的 `FTYPE` 含「货币」，
检测到后按 `INVALID_REQUEST` 拒绝，避免把万份收益当单位净值（同 `em_lsjz` 的坑）。
"""
from datetime import date
from typing import Any, Optional

from server.sources.http import HttpSource
from server.sources.models import (
    CAP_LATEST,
    FailureKind,
    NavPoint,
    SourceError,
    SourceMeta,
    to_decimal,
)

URL = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNBasicInformation"
PARAMS = {
    "deviceid": "1",
    "plat": "Iphone",
    "product": "EFund",
    "version": "1",
}


def parse_mobile_payload(payload: Any, code: str, source: str) -> NavPoint:
    if not isinstance(payload, dict):
        raise SourceError(source, FailureKind.PARSE_ERROR, "响应不是 JSON 对象")

    error_code = payload.get("ErrCode")
    if payload.get("Success") is False or error_code not in (None, 0, "0"):
        raise SourceError(
            source,
            FailureKind.EMPTY_PAYLOAD,
            f"上游返回错误对象: ErrCode={error_code} ErrMsg={payload.get('ErrMsg')!r}",
        )

    data = payload.get("Datas")
    if not isinstance(data, dict) or not data:
        raise SourceError(source, FailureKind.EMPTY_PAYLOAD, f"{code} 的 Datas 为空")

    if "货币" in str(data.get("FTYPE") or ""):
        raise SourceError(
            source,
            FailureKind.INVALID_REQUEST,
            f"{code} 是货币基金（{data.get('FTYPE')}），DWJZ/LJJZ 不是净值口径",
        )

    try:
        nav_date = date.fromisoformat(str(data.get("FSRQ")))
    except (TypeError, ValueError) as exc:
        raise SourceError(
            source,
            FailureKind.EMPTY_PAYLOAD,
            f"{code} 的 FSRQ 非法: {data.get('FSRQ')!r}",
        ) from exc

    return NavPoint(
        fund_code=code,
        nav_date=nav_date,
        unit_nav=to_decimal(data.get("DWJZ")),
        accumulated_nav=to_decimal(data.get("LJJZ")),
        daily_growth=to_decimal(data.get("RZDF")),
        source=source,
    )


class EmMobileSource(HttpSource):
    meta = SourceMeta(
        name="em_mobile",
        domain="fundmobapi.eastmoney.com",
        capabilities=frozenset({CAP_LATEST}),
        priority=95,
        timeout=15.0,
        description="东财移动端基础信息，单只最新净值；字段 RZDF=日增长率",
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": "https://fundmobapi.eastmoney.com/",
    }

    def fetch_history(self, code: str, limit: Optional[int] = None) -> list[NavPoint]:
        if limit is None:
            raise SourceError(
                self.meta.name,
                FailureKind.INVALID_REQUEST,
                "em_mobile 只提供最新一条，不能做全量历史",
            )
        if limit < 1:
            raise SourceError(
                self.meta.name, FailureKind.INVALID_REQUEST, f"limit 必须 >= 1: {limit}"
            )
        params = dict(PARAMS, FCODE=code)
        payload = self._get_json(URL, params=params)
        point = parse_mobile_payload(payload, code, self.meta.name)
        return [point]
