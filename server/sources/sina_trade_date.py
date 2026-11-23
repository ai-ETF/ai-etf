"""新浪交易日历（混淆文本）—— `calendar` 能力。

端点：`https://finance.sina.com.cn/realstock/company/klc_td_sh.txt`
域名：`finance.sina.com.cn`

## 为什么继续走 akshare

该接口只是一段 **508 字节的混淆文本**，解码逻辑在 akshare 的 `hk_js_decode`
（`py_mini_racer` 执行 JS）。设计文档 §4.5 决定：复杂混淆串**不重复造解析**，
继续用 akshare，外面包线程池超时（akshare 内部 `requests.get` 没有 timeout）。

## 实测（2026-10-18）

- 508 B / 0.13s / 约 8800 个交易日（1990-12-19 → 2026-12-31）。
"""
from datetime import date, datetime
from typing import Any

from server.sources.akshare_util import run_akshare_with_timeout
from server.sources.models import (
    CAP_CALENDAR,
    BaseSource,
    CalendarData,
    FailureKind,
    SourceError,
    SourceMeta,
)

# 正常约 8800 个交易日；低于该量级视为上游截断 / 格式变化，拒绝写入。
MIN_TRADING_DAYS = 1000


def _to_date(value: Any):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def parse_trade_date_frame(frame: Any, source: str) -> CalendarData:
    """把 akshare 的 `trade_date` DataFrame 归一化成 `CalendarData`。"""
    if frame is None or getattr(frame, "empty", True):
        raise SourceError(source, FailureKind.EMPTY_PAYLOAD, "交易日历返回为空")

    dates: set[date] = set()
    try:
        for _, row in frame.iterrows():
            raw = row["trade_date"] if "trade_date" in row else row.iloc[0]
            parsed = _to_date(raw)
            if parsed is not None:
                dates.add(parsed)
    except Exception as exc:  # pandas 结构变化 → 解析失败，不是静默空
        raise SourceError(
            source, FailureKind.PARSE_ERROR, f"交易日历结构解析失败: {exc}"
        ) from exc

    if not dates:
        raise SourceError(source, FailureKind.EMPTY_PAYLOAD, "没有解析出任何交易日")
    if len(dates) < MIN_TRADING_DAYS:
        raise SourceError(
            source,
            FailureKind.SCHEMA_DRIFT,
            f"只解析出 {len(dates)} 个交易日，明显少于正常量级（{MIN_TRADING_DAYS}+）",
        )

    return CalendarData(
        trading_days=frozenset(dates),
        coverage_start=min(dates),
        coverage_end=max(dates),
        source=source,
    )


class SinaTradeDateSource(BaseSource):
    meta = SourceMeta(
        name="sina_trade_date",
        domain="finance.sina.com.cn",
        capabilities=frozenset({CAP_CALENDAR}),
        priority=100,
        timeout=15.0,
        description="新浪交易日历混淆文本，akshare 解码；格式一变解码全废",
    )

    @staticmethod
    def _load():
        import akshare as ak

        return ak.tool_trade_date_hist_sina()

    def fetch_calendar(self) -> CalendarData:
        frame = run_akshare_with_timeout(
            self.meta.name, self.meta.timeout, self._load
        )
        return parse_trade_date_frame(frame, self.meta.name)
