"""东财 `pingzhongdata` —— 净值线全量历史源（`history`）。

端点：`https://fund.eastmoney.com/pingzhongdata/{code}.js`
域名：`fund.eastmoney.com`

## 为什么自解析

原实现走 `ak.fund_open_fund_info_em`，该函数**没有 timeout**，上游卡住会把调用线程
一直挂住。这里直接抓 JS 并解析，用 `requests` 的真 timeout（设计文档 §4.5）。

## 实测事实（2026-10-18）

- 110020：603 KB / 0.7s / 4163 个净值点；
- **同一次响应里同时包含** `Data_netWorthTrend`（单位净值 + 日增长率）与
  `Data_ACWorthTrend`（累计净值）。设计文档 §6.1 写的「累计净值需第二次请求」是
  akshare 的旧行为（它把两个 indicator 拆成两次请求），自解析后一次请求即可，
  因此本源的 `timeout` 按单次大响应设置。

## 字段映射

| 归一化字段 | 上游 |
|---|---|
| `nav_date` | `Data_netWorthTrend[].x`（epoch 毫秒，北京时间零点） |
| `unit_nav` | `Data_netWorthTrend[].y` |
| `daily_growth` | `Data_netWorthTrend[].equityReturn`（百分数） |
| `accumulated_nav` | `Data_ACWorthTrend[][1]`，按**日期**合并（不按下标） |
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from server.sources.http import HttpSource
from server.sources.models import (
    CAP_HISTORY,
    FailureKind,
    NavPoint,
    SourceError,
    SourceMeta,
    to_decimal,
)

URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"

_NET_TREND_RE = re.compile(r"Data_netWorthTrend\s*=\s*(\[.*?\])\s*;", re.S)
_ACC_TREND_RE = re.compile(r"Data_ACWorthTrend\s*=\s*(\[.*?\])\s*;", re.S)
_FS_NAME_RE = re.compile(r'fS_name\s*=\s*"([^"]*)"')

BEIJING_TZ = timezone(timedelta(hours=8))


def _loads_js_array(raw: str, source: str) -> Any:
    """解析 JS 数组字面量。

    正常返回是合法 JSON；个别基金末尾会带逗号（JS 允许、JSON 不允许），
    这里先去掉尾逗号再重试一次。
    """
    try:
        return json.loads(raw)
    except ValueError:
        cleaned = re.sub(r",\s*([\]}])", r"\1", raw)
        try:
            return json.loads(cleaned)
        except ValueError as exc:
            raise SourceError(
                source, FailureKind.PARSE_ERROR, f"JS 数组解析失败: {exc}"
            ) from exc


def _ms_to_date(value: Any) -> Optional[date]:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=BEIJING_TZ).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def parse_pingzhongdata(
    text: str,
    code: str,
    source: str,
    limit: Optional[int] = None,
) -> list[NavPoint]:
    """把 pingzhongdata 的 JS 文本解析成按日期升序的 `NavPoint` 列表。

    纯函数，便于单测（内嵌样本，不联网）。
    """
    if limit is not None and limit < 1:
        raise SourceError(source, FailureKind.INVALID_REQUEST, f"limit 必须 >= 1: {limit}")

    net_match = _NET_TREND_RE.search(text)
    if net_match is None:
        # 货币基金没有 Data_netWorthTrend（实测 000198）；这是「不适用」，不是上游改版。
        name_match = _FS_NAME_RE.search(text)
        fund_name = name_match.group(1) if name_match else ""
        if "货币" in fund_name:
            raise SourceError(
                source,
                FailureKind.INVALID_REQUEST,
                f"{code} 是货币基金（{fund_name}），净值线不适用；货基走万份收益接口",
            )
        raise SourceError(
            source,
            FailureKind.SCHEMA_DRIFT,
            f"响应中找不到 Data_netWorthTrend（基金 {code}），上游格式可能已变更",
        )

    net_trend = _loads_js_array(net_match.group(1), source)
    if not isinstance(net_trend, list):
        raise SourceError(source, FailureKind.SCHEMA_DRIFT, "Data_netWorthTrend 不是数组")

    # 累计净值：缺失不阻塞单位净值（设计文档 §4.2.1：两个字段各自可空）。
    accumulated: dict[date, Optional[Any]] = {}
    acc_match = _ACC_TREND_RE.search(text)
    if acc_match is not None:
        acc_trend = _loads_js_array(acc_match.group(1), source)
        if isinstance(acc_trend, list):
            for item in acc_trend:
                if isinstance(item, list) and len(item) >= 2:
                    d = _ms_to_date(item[0])
                    if d is not None:
                        accumulated[d] = to_decimal(item[1])

    points: list[NavPoint] = []
    for item in net_trend:
        if not isinstance(item, dict):
            continue
        nav_date = _ms_to_date(item.get("x"))
        if nav_date is None:
            continue
        points.append(
            NavPoint(
                fund_code=code,
                nav_date=nav_date,
                unit_nav=to_decimal(item.get("y")),
                accumulated_nav=accumulated.get(nav_date),
                daily_growth=to_decimal(item.get("equityReturn")),
                source=source,
            )
        )

    if not points:
        raise SourceError(
            source, FailureKind.EMPTY_PAYLOAD, f"{code} 的净值趋势为空"
        )

    # 按日期升序并去重（同一日期只保留最后一条，避免上游偶发重复把缓存写乱）。
    points.sort(key=lambda p: p.nav_date)
    deduped: list[NavPoint] = []
    for point in points:
        if deduped and deduped[-1].nav_date == point.nav_date:
            deduped[-1] = point
        else:
            deduped.append(point)

    if limit is not None:
        deduped = deduped[-limit:]
    return deduped


class EmPingzhongdataSource(HttpSource):
    meta = SourceMeta(
        name="em_pingzhongdata",
        domain="fund.eastmoney.com",
        capabilities=frozenset({CAP_HISTORY}),
        priority=100,
        timeout=15.0,
        description="东财净值走势 JS，全量历史；同一响应含单位净值与累计净值",
    )

    def fetch_history(self, code: str, limit: Optional[int] = None) -> list[NavPoint]:
        text = self._get_text(URL.format(code=code))
        return parse_pingzhongdata(text, code, self.meta.name, limit)
