"""新浪上证指数日 K —— `calendar` 能力的解析路径冗余。

端点：由 `ak.stock_zh_index_daily(symbol="sh000001")` 封装（新浪日 K）。
域名：`finance.sina.com.cn`

## ⚠️ 它不是域名级故障隔离

`sina_trade_date` 与本源**同属 `finance.sina.com.cn`**。域名被拒时两个一起挂，
所以它们只构成**解析路径的冗余**（应对混淆串格式变化），不是「日历有双源了」。
日历真正的韧性来自 DB 持久化（见 `docs/20-设计/基金与交易/交易日历缓存.md`）。

## 实测（2026-10-18）

- 8743 行 / 0.39s，含完整日期序列；由日期集合反推交易日。
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


def parse_index_daily_frame(frame: Any, source: str) -> CalendarData:
    """上证指数日 K 的每一行都是一个交易日 → 日期集合就是日历。"""
    if frame is None or getattr(frame, "empty", True):
        raise SourceError(source, FailureKind.EMPTY_PAYLOAD, "上证指数日K返回为空")

    dates: set[date] = set()
    try:
        for _, row in frame.iterrows():
            raw = row["date"] if "date" in row else row.iloc[0]
            parsed = _to_date(raw)
            if parsed is not None:
                dates.add(parsed)
    except Exception as exc:
        raise SourceError(
            source, FailureKind.PARSE_ERROR, f"指数日K结构解析失败: {exc}"
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


class SinaIndexDailySource(BaseSource):
    meta = SourceMeta(
        name="sina_index_daily",
        domain="finance.sina.com.cn",
        capabilities=frozenset({CAP_CALENDAR}),
        priority=200,
        timeout=15.0,
        description="上证指数日K反推交易日；与 sina_trade_date 同域名，仅解析冗余",
    )

    @staticmethod
    def _load():
        import akshare as ak

        return ak.stock_zh_index_daily(symbol="sh000001")

    def fetch_calendar(self) -> CalendarData:
        frame = run_akshare_with_timeout(
            self.meta.name, self.meta.timeout, self._load
        )
        return parse_index_daily_frame(frame, self.meta.name)
