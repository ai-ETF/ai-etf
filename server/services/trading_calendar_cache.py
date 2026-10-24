"""A 股交易日历的持久化缓存与人工刷新。

设计依据：`docs/20-设计/基金与交易/交易日历缓存.md`（C2–C5）。

职责边界：

- 取数：只调用 `SourceRouter.fetch_calendar()`，不直接碰 akshare / HTTP；
- 持久化：`trading_calendar`（逐日）+ `trading_calendar_state`（单行）；
- 内存：进程内 `frozenset[date]`，请求路径只读它；
- 刷新：管理接口触发，一次 `replace_trading_calendar` RPC 完成事务性整表替换。

**无兜底**：快照未载入抛 `CalendarUnavailable`，日期越界抛
`CalendarOutOfCoverage`；不按星期几猜测，也不返回默认值。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from server.sources.models import AllSourcesFailed, CalendarData, FailureKind

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))

# 正常约 8800 个交易日；低于该量级视为上游截断，拒绝整次刷新。
MIN_TRADING_DAYS = 1000

# 接口整体时限：超过则不写库，直接 504。
REFRESH_TIMEOUT_SECONDS = 30.0

# PostgREST 默认单次最多返回 1000 行，分页读取。
PAGE_SIZE = 1000

# dry_run / 正式刷新返回的 diff 明细上限（正常年度刷新约 365 条）。
DIFF_LIMIT = 2000


# ==================== 错误与状态 ====================


class CalendarUnavailable(Exception):
    """快照未载入（DB 为空 / 读取失败），无法判断某天是否交易日。

    错误信息携带原因（DB 为空、读取失败、最后一次错误），便于运维定位。
    """


class CalendarOutOfCoverage(Exception):
    """查询日期早于 coverage_start 或晚于 coverage_end。

    覆盖区间外不猜值：既不当交易日，也不当非交易日。
    """

    def __init__(self, target: date, coverage_start: date, coverage_end: date,
                 last_error: Optional[str] = None):
        self.target = target
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end
        self.last_error = last_error
        detail = (
            f"日期 {target.isoformat()} 超出交易日历覆盖区间 "
            f"[{coverage_start.isoformat()}, {coverage_end.isoformat()}]"
        )
        if last_error:
            detail += f"；最近错误: {last_error}"
        super().__init__(detail)


class CalendarDataInvalid(Exception):
    """源返回的数据未通过刷新前校验，拒绝整次刷新（不写库）。"""


class CalendarRefreshTimeout(Exception):
    """人工刷新超过整体时限，未写库。"""


class RefreshInProgress(Exception):
    """已有刷新在执行（进程内非阻塞锁）。"""


class CalendarStatus(str, Enum):
    """`calendar_status(d)` 的四种结果；前两种才能回答 bool。"""

    TRADING = "TRADING"
    NON_TRADING = "NON_TRADING"
    UNAVAILABLE = "UNAVAILABLE"
    OUT_OF_COVERAGE = "OUT_OF_COVERAGE"


@dataclass(frozen=True)
class CalendarSnapshot:
    """内存快照：只保留交易日集合 + 覆盖区间，非交易日由区间推出。"""

    trading_days: frozenset[date]
    coverage_start: date
    coverage_end: date
    source: str


@dataclass(frozen=True)
class RefreshResult:
    """一次人工刷新的结果（dry_run 与正式调用共用）。"""

    coverage_start: date
    coverage_end: date
    source: str
    dry_run: bool
    stats: dict
    diff: list[dict]
    diff_truncated: bool
    elapsed_ms: int


# ==================== 缓存 ====================


class TradingCalendarCache:
    """交易日历快照：DB 载入、只读查询、人工刷新。

    `client` / `router` 可注入；生产环境懒加载 `get_supabase()` 与
    `get_router()`，测试可以完全绕开 DB 与网络。
    """

    def __init__(self, client: Any = None, router: Any = None) -> None:
        self._client = client
        self._router = router
        self._snapshot: Optional[CalendarSnapshot] = None
        self._last_error: Optional[str] = None
        self._unavailable_reason: Optional[str] = None
        # 只保护快照引用的替换，读路径无锁。
        self._snapshot_lock = threading.Lock()
        # 人工刷新互斥：非阻塞获取，已有刷新时直接 409。
        self._refresh_lock = threading.Lock()

    # ---------- 依赖 ----------

    @property
    def client(self) -> Any:
        if self._client is None:
            from server.storage.supabase_client import get_supabase

            self._client = get_supabase()
        return self._client

    @property
    def router(self) -> Any:
        if self._router is None:
            from server.sources import get_router

            self._router = get_router()
        return self._router

    # ---------- 只读状态 ----------

    @property
    def ready(self) -> bool:
        return self._snapshot is not None

    @property
    def snapshot(self) -> Optional[CalendarSnapshot]:
        with self._snapshot_lock:
            return self._snapshot

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def reset(self) -> None:
        """清空内存快照（测试专用；不影响 DB）。"""
        with self._snapshot_lock:
            self._snapshot = None
        self._last_error = None
        self._unavailable_reason = None

    def install_snapshot(
        self,
        trading_days,
        coverage_start: Optional[date] = None,
        coverage_end: Optional[date] = None,
        source: str = "test",
    ) -> None:
        """测试专用：直接注入假快照，不读 DB。"""
        days = frozenset(
            d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
            for d in trading_days
        )
        start = coverage_start or (min(days) if days else None)
        end = coverage_end or (max(days) if days else None)
        if start is None or end is None:
            raise ValueError("install_snapshot 需要至少一个交易日或显式覆盖区间")
        with self._snapshot_lock:
            self._snapshot = CalendarSnapshot(days, start, end, source)
        self._last_error = None
        self._unavailable_reason = None

    def status(self, d: date) -> CalendarStatus:
        """只读查询：不发请求、不抛异常，把「不知道」与「非交易日」分开。"""
        snapshot = self.snapshot
        if snapshot is None:
            return CalendarStatus.UNAVAILABLE
        if d < snapshot.coverage_start or d > snapshot.coverage_end:
            return CalendarStatus.OUT_OF_COVERAGE
        return (
            CalendarStatus.TRADING
            if d in snapshot.trading_days
            else CalendarStatus.NON_TRADING
        )

    def is_trading_day(self, d: date) -> bool:
        """是否为 A 股交易日。

        只在「快照就绪且日期在覆盖区间内」时返回 bool；其余情况抛错，
        不把「未知」静默当成 False / True。
        """
        snapshot = self.snapshot
        if snapshot is None:
            reason = self._unavailable_reason or "快照未载入"
            raise CalendarUnavailable(
                f"交易日历不可用（{reason}），无法判断 {d.isoformat()}；"
                f"请先调用管理接口刷新日历"
            )

        # 只取一次快照，避免读取过程中恰好发生刷新导致口径不一致。
        if d < snapshot.coverage_start or d > snapshot.coverage_end:
            raise CalendarOutOfCoverage(
                d, snapshot.coverage_start, snapshot.coverage_end, self._last_error
            )
        return d in snapshot.trading_days

    # ---------- DB 载入 ----------

    def load_from_db(self) -> bool:
        """进程启动时一次性载入快照；失败只记 ERROR，不抛异常、不触网。

        DB 为空 / 读取失败时 `ready=false`，进程继续启动 —— 管理刷新接口
        与本服务同进程，崩进程会让「新环境首次拉取」无法执行。
        """
        try:
            client = self.client
            if client is None:
                raise RuntimeError("Supabase 客户端不可用")

            state_rows = (
                client.table("trading_calendar_state")
                .select("coverage_start,coverage_end,last_error,last_success_at")
                .eq("id", True)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not state_rows:
                raise RuntimeError("trading_calendar_state 为空（尚未刷新过）")

            state = state_rows[0]
            coverage_start = _parse_date(state.get("coverage_start"))
            coverage_end = _parse_date(state.get("coverage_end"))
            if coverage_start is None or coverage_end is None:
                raise RuntimeError("trading_calendar_state 缺少覆盖区间")

            trading_days = self._read_trading_days()
            if not trading_days:
                raise RuntimeError("trading_calendar 没有交易日行")

            self._last_error = state.get("last_error")
            self._install(CalendarSnapshot(
                trading_days=frozenset(trading_days),
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                source="db",
            ))
            logger.info(
                "交易日历快照已载入：%s 个交易日，覆盖 %s → %s",
                len(trading_days), coverage_start, coverage_end,
            )
            return True
        except Exception as exc:  # 启动不因日历缺失而失败
            self._snapshot = None
            self._unavailable_reason = f"{type(exc).__name__}: {exc}"
            logger.error("交易日历快照载入失败，日历相关业务调用将抛错: %s", exc,
                         exc_info=True)
            return False

    def _read_trading_days(self) -> set[date]:
        """分页读取全部交易日（PostgREST 单次最多 1000 行）。"""
        days: set[date] = set()
        offset = 0
        while True:
            rows = (
                self.client.table("trading_calendar")
                .select("trade_date")
                .eq("is_trading_day", True)
                .order("trade_date")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
                .data
                or []
            )
            for row in rows:
                parsed = _parse_date(row.get("trade_date"))
                if parsed is not None:
                    days.add(parsed)
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        return days

    def _read_existing_rows(self) -> dict[date, bool]:
        """读取整张逐日表（含非交易日），用于计算 diff。"""
        rows_map: dict[date, bool] = {}
        offset = 0
        while True:
            rows = (
                self.client.table("trading_calendar")
                .select("trade_date,is_trading_day")
                .order("trade_date")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
                .data
                or []
            )
            for row in rows:
                parsed = _parse_date(row.get("trade_date"))
                if parsed is not None:
                    rows_map[parsed] = bool(row.get("is_trading_day"))
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        return rows_map

    # ---------- 人工刷新 ----------

    def refresh(self, dry_run: bool = False) -> RefreshResult:
        """人工全量刷新：拉取 → 校验 → diff →（可选）整表替换 + 替换内存。

        失败时旧快照与内存原样保留，`state.last_error` 尽力记录；
        不重试、不换源、不写任何替代数据。
        """
        if not self._refresh_lock.acquire(blocking=False):
            raise RefreshInProgress("已有交易日历刷新正在执行")

        started = time.monotonic()
        try:
            data = self.router.fetch_calendar()
            self._validate(data)

            existing = self._read_existing_rows()
            new_rows = _expand_natural_days(data)
            stats, diff, diff_truncated = _diff_rows(existing, new_rows)

            if not dry_run:
                if time.monotonic() - started > REFRESH_TIMEOUT_SECONDS:
                    raise CalendarRefreshTimeout(
                        f"刷新耗时超过 {REFRESH_TIMEOUT_SECONDS:.0f}s，未写库"
                    )
                self._replace_in_db(data)
                self._install(CalendarSnapshot(
                    trading_days=data.trading_days,
                    coverage_start=data.coverage_start,
                    coverage_end=data.coverage_end,
                    source=data.source,
                ))
            elapsed_ms = int((time.monotonic() - started) * 1000)

            logger.info(
                "交易日历刷新%s完成：覆盖 %s → %s，%s 个交易日，"
                "新增 %s / 更新 %s / 未变 %s / 删除 %s，耗时 %sms",
                "预览" if dry_run else "",
                data.coverage_start, data.coverage_end, len(data.trading_days),
                stats["inserted"], stats["updated"], stats["unchanged"],
                stats["deleted"], int((time.monotonic() - started) * 1000),
            )
            return RefreshResult(
                coverage_start=data.coverage_start,
                coverage_end=data.coverage_end,
                source=data.source,
                dry_run=dry_run,
                stats=stats,
                diff=diff,
                diff_truncated=diff_truncated,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            self._record_error(exc)
            raise
        finally:
            self._refresh_lock.release()

    def _validate(self, data: CalendarData) -> None:
        """拒绝坏数据：宁可整次失败，也不把坏快照写进唯一真相源。"""
        if not data.trading_days:
            raise CalendarDataInvalid("源返回的交易日集合为空")
        if len(data.trading_days) < MIN_TRADING_DAYS:
            raise CalendarDataInvalid(
                f"只返回 {len(data.trading_days)} 个交易日，"
                f"明显少于正常量级（{MIN_TRADING_DAYS}+）"
            )
        if data.coverage_start > data.coverage_end:
            raise CalendarDataInvalid(
                f"覆盖区间非法：{data.coverage_start} > {data.coverage_end}"
            )
        today = datetime.now(BEIJING_TZ).date()
        if data.coverage_end < today:
            raise CalendarDataInvalid(
                f"覆盖终点 {data.coverage_end} 早于今天 {today}，数据不可用"
            )

    def _replace_in_db(self, data: CalendarData) -> None:
        """一次 RPC 完成删旧 + 写新 + 更新 state（单事务）。"""
        payload = [d.isoformat() for d in sorted(data.trading_days)]
        response = self.client.rpc(
            "replace_trading_calendar",
            {"p_trading_days": payload, "p_source": data.source},
        ).execute()
        if not response.data:
            raise RuntimeError("replace_trading_calendar 未返回结果")

    def _record_error(self, exc: Exception) -> None:
        """尽力把失败写进 state；DB 本身故障时只记日志，不掩盖原始异常。"""
        message = f"{type(exc).__name__}: {exc}"[:2000]
        self._last_error = message
        try:
            self.client.table("trading_calendar_state").upsert(
                {
                    "id": True,
                    "last_error": message,
                    "last_error_at": datetime.now(BEIJING_TZ).isoformat(),
                },
                on_conflict="id",
            ).execute()
        except Exception as record_exc:
            logger.error("记录交易日历 last_error 失败: %s", record_exc)

    def _install(self, snapshot: CalendarSnapshot) -> None:
        with self._snapshot_lock:
            self._snapshot = snapshot
        self._unavailable_reason = None
        self._last_error = None

    # ---------- 状态报告 ----------

    def describe(self) -> dict:
        """`GET status` 的只读数据：内存快照 + DB 状态 + 行数统计。

        顶层字段直接对应运维手册 §3.1 的核验项；`snapshot` / `state` 保留原始
        明细，便于排查。DB 读取失败时带 `db_error`，不掩盖。
        """
        snapshot = self.snapshot
        report: dict = {
            "ready": snapshot is not None,
            "coverage_start": None,
            "coverage_end": None,
            "source": None,
            "last_success_at": None,
            "last_error": self._last_error,
            "last_error_at": None,
            "days": None,
            "trading_days": None,
            "snapshot": None,
            "state": None,
        }
        if snapshot is not None:
            report["coverage_start"] = snapshot.coverage_start
            report["coverage_end"] = snapshot.coverage_end
            report["source"] = snapshot.source
            report["trading_days"] = len(snapshot.trading_days)
            report["snapshot"] = {
                "coverage_start": snapshot.coverage_start.isoformat(),
                "coverage_end": snapshot.coverage_end.isoformat(),
                "trading_days": len(snapshot.trading_days),
                "source": snapshot.source,
            }

        try:
            state_rows = (
                self.client.table("trading_calendar_state")
                .select("*")
                .eq("id", True)
                .limit(1)
                .execute()
                .data
                or []
            )
            state = state_rows[0] if state_rows else None
            report["state"] = state
            if state:
                report["coverage_start"] = state.get("coverage_start")
                report["coverage_end"] = state.get("coverage_end")
                report["last_success_at"] = state.get("last_success_at")
                report["last_error"] = state.get("last_error")
                report["last_error_at"] = state.get("last_error_at")

            total = (
                self.client.table("trading_calendar")
                .select("trade_date", count="exact", head=True)
                .execute()
                .count
            )
            trading = (
                self.client.table("trading_calendar")
                .select("trade_date", count="exact", head=True)
                .eq("is_trading_day", True)
                .execute()
                .count
            )
            report["days"] = total
            report["trading_days"] = trading
        except Exception as exc:
            report["db_error"] = f"{type(exc).__name__}: {exc}"
            logger.error("读取交易日历状态失败: %s", exc, exc_info=True)

        return report


# ==================== 纯函数 ====================


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _expand_natural_days(data: CalendarData) -> dict[date, bool]:
    """把交易日集合展开成覆盖区间内每个自然日的 {date: is_trading_day}。"""
    rows: dict[date, bool] = {}
    current = data.coverage_start
    while current <= data.coverage_end:
        rows[current] = current in data.trading_days
        current += timedelta(days=1)
    return rows


def _diff_rows(
    existing: dict[date, bool],
    new_rows: dict[date, bool],
) -> tuple[dict, list[dict], bool]:
    """对比现有快照与新快照，返回 stats、变更明细与是否被截断。"""
    inserted = sorted(d for d in new_rows if d not in existing)
    deleted = sorted(d for d in existing if d not in new_rows)
    updated = sorted(
        d for d in new_rows if d in existing and existing[d] != new_rows[d]
    )
    unchanged = sum(
        1 for d in new_rows if d in existing and existing[d] == new_rows[d]
    )

    diff: list[dict] = []
    for d in inserted:
        diff.append({"trade_date": d.isoformat(), "old": None, "new": new_rows[d]})
    for d in updated:
        diff.append({"trade_date": d.isoformat(), "old": existing[d], "new": new_rows[d]})
    for d in deleted:
        diff.append({"trade_date": d.isoformat(), "old": existing[d], "new": None})
    diff.sort(key=lambda item: item["trade_date"])

    truncated = len(diff) > DIFF_LIMIT
    stats = {
        "inserted": len(inserted),
        "updated": len(updated),
        "unchanged": unchanged,
        "deleted": len(deleted),
    }
    return stats, (diff[:DIFF_LIMIT] if truncated else diff), truncated


# ==================== 单例 ====================

_cache = TradingCalendarCache()


def get_calendar_cache() -> TradingCalendarCache:
    """全进程唯一的日历缓存实例。"""
    return _cache
