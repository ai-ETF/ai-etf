"""场外基金净值同步服务（唯一写入口）。

设计依据：`docs/20-设计/行情/多源适配器接入方案.md` §4.5 / §4.7 /
`docs/20-设计/基金与交易/场外净值与基金元数据存储设计.md` §3.6。

职责边界：

- 只由调度器 / 管理脚本 / `FundNavService.get_history` 的读穿透调用；
- 写库只走三个 RPC（`merge_fund_nav` / `upsert_fund_nav_state`，
  目录同步走 `upsert_fund_catalog`），**不在应用层拼 upsert**；
- 失败只写 `last_error`，不动 `latest_*`；库中旧值永远保留。
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional

import fcntl

from server.services.fund_nav_service import (
    FundNavService,
    NavLookup,
    NavLookupStatus,
    code_lock,
)
from server.sources.models import AllSourcesFailed, NavPoint

logger = logging.getLogger(__name__)

NAV_UPDATE_LOCK_PATH = os.environ.get(
    "FUND_NAV_LOCK_PATH", "/tmp/fund_nav_update.lock"
)

# 单次 RPC 建议不超过 500 行（存储设计 §4.4.2）
MERGE_BATCH_SIZE = 500
# PostgREST 单次最多 1000 行
_PAGE_SIZE = 1000
# 货基净值恒 1.0000，不参与场外净值同步
MONEY_FUND_CODE = "000198"

BEIJING_TZ = timezone(timedelta(hours=8))


class NavLockBusy(RuntimeError):
    """已有净值更新任务在跑，未取到锁（不算失败，本轮跳过）。"""


@contextmanager
def nav_update_lock():
    """净值更新互斥锁（非阻塞）。

    flock 随文件描述符关闭自动释放 —— 进程崩溃/被杀也不会留下死锁。
    """
    fd = os.open(NAV_UPDATE_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise NavLockBusy(f"已有净值更新在跑（锁文件 {NAV_UPDATE_LOCK_PATH}）")
        yield
    finally:
        os.close(fd)


@dataclass
class UpdateResult:
    codes: int = 0
    batch_hit: int = 0
    single_fallback: int = 0
    unmatched: int = 0
    failed: int = 0
    inserted: int = 0
    revised: int = 0
    elapsed_ms: int = 0
    failures: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "codes": self.codes,
            "batch_hit": self.batch_hit,
            "single_fallback": self.single_fallback,
            "unmatched": self.unmatched,
            "failed": self.failed,
            "inserted": self.inserted,
            "revised": self.revised,
            "elapsed_ms": self.elapsed_ms,
            "failures": self.failures,
        }


@dataclass
class HistoryFillResult:
    fund_code: str
    status: str  # ready / partial / failed / skipped
    inserted: int = 0
    revised: int = 0
    start_date: Optional[date] = None
    error: Optional[str] = None
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status in ("ready", "skipped")


class FundNavSyncService:
    """净值唯一写入口（无状态，可注入 client / router 便于测试）。"""

    def __init__(self, client=None, router=None):
        self._client = client
        self._router = router

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase

            self._client = get_supabase()
        return self._client

    @property
    def router(self):
        if self._router is None:
            from server.sources import get_router

            self._router = get_router()
        return self._router

    # ==================== 最新净值 ====================

    def update_batch(
        self, codes: Optional[list[str]] = None, use_lock: bool = True
    ) -> UpdateResult:
        """更新白名单基金的最新净值。

        流程（接入方案 §4.5）：批量源 → 逐点合并 → 批量未命中的代码单只兜底 →
        更新 `fund_nav_state`。拿不到单飞锁时抛 `NavLockBusy`，由调用方视为跳过。
        """
        if use_lock:
            with nav_update_lock():
                return self._update_batch(codes)
        return self._update_batch(codes)

    def _update_batch(self, codes: Optional[list[str]]) -> UpdateResult:
        started = time.monotonic()
        targets = self._normalize(codes) if codes is not None else self._whitelist_codes()
        result = UpdateResult(codes=len(targets))
        if not targets:
            logger.info("净值更新跳过：白名单为空")
            result.elapsed_ms = _elapsed_ms(started)
            return result

        batch = self.router.fetch_latest_batch(targets)  # 全失败时按契约上抛
        rows: list[dict] = []
        latest_by_code: dict[str, NavPoint] = {}
        for code, points in batch.items():
            valid = [p for p in points if _valid_point(p)]
            if not valid:
                continue
            rows.extend(_to_row(p) for p in valid)
            latest_by_code[code] = valid[-1]

        result.batch_hit = len(latest_by_code)
        merged = self._merge(rows)
        result.inserted += merged[0]
        result.revised += merged[2]

        for code, point in latest_by_code.items():
            self._mark_latest(code, point)

        missing = [c for c in targets if c not in batch]
        result.unmatched = len(missing)
        for code in missing:
            try:
                point = self.router.fetch_latest(code)
            except AllSourcesFailed as exc:
                result.failed += 1
                result.failures[code] = str(exc)
                self._mark_error(code, str(exc))
                logger.warning(f"单只净值更新失败: {code} → {exc}")
                continue
            if not _valid_point(point):
                result.failed += 1
                result.failures[code] = "上游返回空净值"
                self._mark_error(code, "上游返回空净值")
                continue
            inserted, _, revised = self._merge([_to_row(point)])
            result.inserted += inserted
            result.revised += revised
            result.single_fallback += 1
            self._mark_latest(code, point)

        result.elapsed_ms = _elapsed_ms(started)
        logger.info(
            "净值批量更新完成: codes=%s batch_hit=%s fallback=%s failed=%s "
            "inserted=%s revised=%s elapsed_ms=%s",
            result.codes,
            result.batch_hit,
            result.single_fallback,
            result.failed,
            result.inserted,
            result.revised,
            result.elapsed_ms,
        )
        return result

    # ==================== 历史补齐 ====================

    def ensure_history(self, code: str) -> HistoryFillResult:
        """补齐单只基金的全量历史（幂等；`ready` 直接跳过）。"""
        started = time.monotonic()
        code = str(code).strip()
        with code_lock(code):
            state = self._get_state(code)
            if state and state.get("history_status") == "ready":
                return HistoryFillResult(
                    fund_code=code,
                    status="skipped",
                    start_date=_to_date(state.get("history_start_date")),
                )
            return self._fill_history(code, started)

    def repair(self, code: str, on_date: date) -> NavLookup:
        """补某一个日期的净值缺口：先近 20 条，未命中再全量历史。"""
        code = str(code).strip()
        try:
            recent = self.router.fetch_history_recent(code, 20)
        except AllSourcesFailed as exc:
            logger.warning(f"repair 近端取数失败，转全量: {code} → {exc}")
            recent = []

        point = next(
            (p for p in recent if p.nav_date == on_date and _valid_point(p)), None
        )
        if point is not None:
            self._merge([_to_row(point)])
            self._mark_latest(code, point)
            logger.info(f"repair 命中近端数据: {code} {on_date}")
            return NavLookup(NavLookupStatus.OK, point)

        started = time.monotonic()
        with code_lock(code):
            fill = self._fill_history(code, started)
        if not fill.ok:
            logger.error(f"repair 全量补齐失败: {code} {on_date} → {fill.error}")
            return NavLookup(NavLookupStatus.FETCH_FAILED, None, reason=fill.status)

        return FundNavService(client=self.client).get_nav_on(code, on_date)

    def _fill_history(self, code: str, started: float) -> HistoryFillResult:
        """下载并合并全量历史。调用方负责持有 `code_lock(code)`。"""
        logger.info(f"开始补齐历史净值: {code}")
        try:
            points = self.router.fetch_history(code)
        except AllSourcesFailed as exc:
            message = str(exc)
            self._mark_error(code, message, history_status="failed")
            return HistoryFillResult(
                fund_code=code,
                status="failed",
                error=message,
                elapsed_ms=_elapsed_ms(started),
            )

        valid = [p for p in points if _valid_point(p)]
        if not valid:
            self._mark_error(code, "上游返回空净值", history_status="failed")
            return HistoryFillResult(
                fund_code=code,
                status="failed",
                error="上游返回空净值",
                elapsed_ms=_elapsed_ms(started),
            )

        inserted = revised = 0
        try:
            for chunk in _chunks([_to_row(p) for p in valid], MERGE_BATCH_SIZE):
                part = self._merge(chunk)
                inserted += part[0]
                revised += part[2]
        except Exception as exc:
            done = inserted + revised
            status = "partial" if done > 0 else "failed"
            logger.error(f"历史净值写入失败: {code} status={status} → {exc}")
            self._mark_error(code, str(exc), history_status=status)
            return HistoryFillResult(
                fund_code=code,
                status=status,
                inserted=inserted,
                revised=revised,
                error=str(exc),
                elapsed_ms=_elapsed_ms(started),
            )

        first = valid[0]
        last = valid[-1]
        self._upsert_state(
            code,
            history_status="ready",
            latest_nav_date=last.nav_date,
            latest_unit_nav=last.unit_nav,
            history_start_date=first.nav_date,
            got_data=True,
        )
        elapsed = _elapsed_ms(started)
        logger.info(
            f"历史净值补齐完成: {code} points={len(valid)} inserted={inserted} "
            f"revised={revised} range={first.nav_date}~{last.nav_date} elapsed_ms={elapsed}"
        )
        return HistoryFillResult(
            fund_code=code,
            status="ready",
            inserted=inserted,
            revised=revised,
            start_date=first.nav_date,
            elapsed_ms=elapsed,
        )

    # ==================== 持仓预热 ====================

    def warm_positions(self, pause: float = 0.5) -> list[HistoryFillResult]:
        """持仓预热：`quantity > 0` 且历史未补齐的基金逐只 `ensure_history`。

        串行执行并限速，避免对上游形成突发流量；单只失败不阻塞其余基金。
        货基不参与（净值恒 1.0000，没有同步价值）。
        """
        codes = self._position_codes()
        results: list[HistoryFillResult] = []
        for code in codes:
            state = self._get_state(code)
            if state and state.get("history_status") == "ready":
                continue
            try:
                results.append(self.ensure_history(code))
            except Exception as exc:  # 单只失败不阻塞其余基金
                logger.error(f"持仓预热失败: {code} → {exc}", exc_info=True)
                results.append(
                    HistoryFillResult(fund_code=code, status="failed", error=str(exc))
                )
            time.sleep(pause)
        logger.info(
            "持仓历史预热完成: 候选 %s 只，实际补齐 %s 只", len(codes), len(results)
        )
        return results

    # ==================== 启动补偿 ====================

    def startup_update_if_stale(self) -> Optional[UpdateResult]:
        """服务启动时：今天还没检查过（`last_checked_at` 落后）就补跑一轮。"""
        today_start = datetime.combine(
            datetime.now(BEIJING_TZ).date(), dtime.min, tzinfo=BEIJING_TZ
        )
        try:
            row = (
                self.client.table("fund_nav_state")
                .select("fund_code")
                .gte("last_checked_at", today_start.isoformat())
                .limit(1)
                .execute()
            ).data
        except Exception as exc:
            logger.warning(f"启动检查净值状态失败，跳过补偿: {exc}")
            return None
        if row:
            return None
        try:
            result = self.update_batch()
        except NavLockBusy as exc:
            logger.info(f"启动补偿跳过：{exc}")
            return None
        except Exception as exc:
            logger.error(f"启动补偿更新失败: {exc}", exc_info=True)
            return None
        logger.info(f"启动补偿更新完成: {result.as_dict()}")
        return result

    # ==================== 观测 ====================

    def describe(self) -> dict:
        """覆盖率与最近失败，供 `/admin` 脚本与运维查看。"""
        states = self._all_states()
        by_status: dict[str, int] = {}
        last_checked = None
        errors = []
        for row in states:
            status = row.get("history_status") or "unknown"
            by_status[status] = by_status.get(status, 0) + 1
            checked = row.get("last_checked_at")
            if checked and (last_checked is None or checked > last_checked):
                last_checked = checked
            if status in ("failed", "partial") and row.get("last_error"):
                errors.append(
                    {
                        "fund_code": row.get("fund_code"),
                        "history_status": status,
                        "last_error": row.get("last_error"),
                        "last_checked_at": checked,
                    }
                )
        return {
            "funds_tracked": len(states),
            "by_status": by_status,
            "last_checked_at": last_checked,
            "nav_rows": self._count("fund_nav"),
            "revision_rows": self._count("fund_nav_revision"),
            "recent_failures": errors[:20],
        }

    # ==================== DB 写入 ====================

    def _merge(self, rows: list[dict]) -> tuple[int, int, int]:
        inserted = updated = revised = 0
        for chunk in _chunks(rows, MERGE_BATCH_SIZE):
            if not chunk:
                continue
            data = self.client.rpc("merge_fund_nav", {"rows": chunk}).execute().data
            if isinstance(data, list) and data:
                item = data[0]
            elif isinstance(data, dict):
                item = data
            else:
                item = {}
            inserted += int(item.get("inserted") or 0)
            updated += int(item.get("updated") or 0)
            revised += int(item.get("revised") or 0)
        return inserted, updated, revised

    def _mark_latest(self, code: str, point: NavPoint) -> None:
        self._upsert_state(
            code,
            latest_nav_date=point.nav_date,
            latest_unit_nav=point.unit_nav,
            got_data=True,
        )

    def _mark_error(
        self, code: str, message: str, history_status: Optional[str] = None
    ) -> None:
        try:
            self._upsert_state(
                code, error=message[:500], history_status=history_status
            )
        except Exception:  # 状态写失败不能盖住原始错误
            logger.exception(f"写净值状态失败: {code}")

    def _upsert_state(
        self,
        code: str,
        *,
        history_status: Optional[str] = None,
        latest_nav_date: Optional[date] = None,
        latest_unit_nav: Optional[Decimal] = None,
        history_start_date: Optional[date] = None,
        got_data: bool = False,
        error: Optional[str] = None,
    ) -> None:
        params = {
            "p_fund_code": code,
            "p_history_status": history_status,
            "p_latest_nav_date": latest_nav_date.isoformat() if latest_nav_date else None,
            "p_latest_unit_nav": _decimal_str(latest_unit_nav),
            "p_history_start_date": (
                history_start_date.isoformat() if history_start_date else None
            ),
            "p_got_data": got_data,
            "p_error": error,
        }
        self.client.rpc("upsert_fund_nav_state", params).execute()

    # ==================== DB 读取 ====================

    def _whitelist_codes(self) -> list[str]:
        """目录（`fund_catalog`）中的场外基金代码；分页避免 1000 行截断。"""
        rows = _select_paged(
            lambda start, end: (
                self.client.table("fund_catalog")
                .select("fund_code")
                .eq("fund_type", "of")
                .order("fund_code")
                .range(start, end)
                .execute()
            )
        )
        codes = [row["fund_code"] for row in rows if row.get("fund_code")]
        return [code for code in codes if code != MONEY_FUND_CODE]

    def _position_codes(self) -> list[str]:
        rows = _select_paged(
            lambda start, end: (
                self.client.table("positions")
                .select("fund_code")
                .gt("quantity", 0)
                .range(start, end)
                .execute()
            )
        )
        codes = {row["fund_code"] for row in rows if row.get("fund_code")}
        return sorted(code for code in codes if code != MONEY_FUND_CODE)

    def _get_state(self, code: str) -> Optional[dict]:
        result = (
            self.client.table("fund_nav_state")
            .select("fund_code,history_status,latest_nav_date,latest_unit_nav,"
                    "history_start_date,last_checked_at,last_error")
            .eq("fund_code", code)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def _all_states(self) -> list[dict]:
        return _select_paged(
            lambda start, end: (
                self.client.table("fund_nav_state")
                .select("fund_code,history_status,last_checked_at,last_error")
                .order("fund_code")
                .range(start, end)
                .execute()
            )
        )

    def _count(self, table: str) -> int:
        result = (
            self.client.table(table)
            .select("fund_code", count="exact")
            .limit(1)
            .execute()
        )
        return int(result.count or 0)

    @staticmethod
    def _normalize(codes: Iterable[str]) -> list[str]:
        seen: list[str] = []
        for code in codes or []:
            text = str(code).strip() if code is not None else ""
            if text and text not in seen:
                seen.append(text)
        return seen


# ==================== 工具 ====================


def _valid_point(point: NavPoint) -> bool:
    """R10：不写 0 净值；单位净值缺失的点直接丢弃。"""
    return point.unit_nav is not None and point.unit_nav > 0


def _to_row(point: NavPoint) -> dict:
    return {
        "fund_code": point.fund_code,
        "nav_date": point.nav_date.isoformat(),
        "unit_nav": _decimal_str(point.unit_nav),
        "accumulated_nav": _decimal_str(point.accumulated_nav),
        "daily_growth": _decimal_str(point.daily_growth),
        "source": point.source,
    }


def _decimal_str(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _to_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _chunks(items: list, size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _select_paged(query_builder) -> list[dict]:
    """按 `range` 分页取全量（PostgREST 单次最多 1000 行）。"""
    rows: list[dict] = []
    offset = 0
    while True:
        page = query_builder(offset, offset + _PAGE_SIZE - 1).data or []
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            return rows
        offset += _PAGE_SIZE
