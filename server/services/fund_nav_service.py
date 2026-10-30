"""场外基金净值读服务。

设计依据：`docs/20-设计/行情/多源适配器接入方案.md` §4.3 / §4.6 /
`docs/20-设计/基金与交易/场外净值与基金元数据存储设计.md` §2.5。

约束（勿破坏）：

- **净值唯一读入口**：业务层不得直接访问 `SourceRouter`、akshare 或 `fund_nav*` 表；
- **本服务不触网**（唯一例外是 `get_history` 的首次读穿透，委托给
  `FundNavSyncService.ensure_history`）；
- 货基（`000198`）不在本服务内特判，由 `PortfolioService` 自己按 1.0000 估值；
- 历史未补齐且补数失败时抛 `FundNavUnavailable`，**不得返回片段冒充完整历史**。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional

from server.sources.models import NavPoint

if TYPE_CHECKING:  # 只用于类型标注：运行期反向 import 会成环
    from server.services.fund_nav_sync_service import FundNavSyncService

logger = logging.getLogger(__name__)

# PostgREST 默认单次最多返回 1000 行；分页读取必须显式 range
_PAGE_SIZE = 1000

# 历史净值的合理上限：全量约 4000 点，避免异常参数把响应撑爆
_MAX_LIMIT = 20000


class NavLookupStatus(str, Enum):
    """单日净值查询的四种结果，必须可区分。"""

    OK = "ok"
    NOT_YET_PUBLISHED = "not_yet_published"
    FETCH_FAILED = "fetch_failed"
    # 该日期本身没有净值（非净值日 / 基金成立前），重试也不会出现
    NO_NAV = "no_nav"


@dataclass(frozen=True)
class NavLookup:
    status: NavLookupStatus
    point: Optional[NavPoint]
    reason: Optional[str] = None


@dataclass(frozen=True)
class LatestNav:
    """最新净值的最小投影：只含持仓 / 下单预估 / 问答实际用到的字段。"""

    fund_code: str
    nav_date: date
    unit_nav: Decimal


class FundNotSupported(Exception):
    """基金不在支持目录（`fund_catalog`）内。

    产品只做场外基金：场内 ETF / 非白名单基金既不能交易，也不提供净值与详情查询
    （2026-10-26 决策）。调用方（API）应映射为 404，且**不得回退上游**——
    回退会让「搜不到、买不了」的代码在详情页「看得见」。
    """

    def __init__(self, fund_code: str):
        self.fund_code = fund_code
        super().__init__(f"基金 {fund_code} 不在支持目录内")


class FundNavUnavailable(Exception):
    """历史净值不可用（未补齐且补数失败，或库中无该基金）。

    调用方（API）应映射为 503，而不是返回空列表冒充「没有历史」。
    """

    def __init__(self, fund_code: str, reason: str, detail: Optional[str] = None):
        self.fund_code = fund_code
        self.reason = reason
        self.detail = detail
        message = f"基金 {fund_code} 的历史净值不可用: {reason}"
        if detail:
            message = f"{message}（{detail}）"
        super().__init__(message)


class FundNavService:
    """净值唯一读入口（无状态，可注入 client / sync 便于测试）。"""

    def __init__(self, client=None, sync: Optional["FundNavSyncService"] = None):
        self._client = client
        self._sync = sync

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase

            self._client = get_supabase()
        return self._client

    @property
    def sync(self) -> "FundNavSyncService":
        if self._sync is None:
            from server.services.fund_nav_sync_service import FundNavSyncService

            self._sync = FundNavSyncService(client=self.client)
        return self._sync

    # ==================== 最新净值 ====================

    def get_latest(self, code: str) -> Optional[LatestNav]:
        """读 `fund_nav_state.latest_*`；库中无最新净值时返回 None。"""
        code = self._validate_code(code)
        row = self._get_state(code)
        if not row or row.get("latest_nav_date") is None:
            return None
        return LatestNav(
            fund_code=code,
            nav_date=_parse_date(row["latest_nav_date"]),
            unit_nav=_to_decimal(row.get("latest_unit_nav")),
        )

    def get_latest_batch(self, codes: list[str]) -> dict[str, LatestNav]:
        """持仓页一次批量读取；缺失的代码不出现在返回字典里。"""
        normalized = [self._validate_code(c) for c in codes or [] if str(c).strip()]
        if not normalized:
            return {}
        rows = self._select_states(normalized)
        result: dict[str, LatestNav] = {}
        for row in rows:
            if row.get("latest_nav_date") is None:
                continue
            unit_nav = _to_decimal(row.get("latest_unit_nav"))
            if unit_nav is None:
                continue
            result[row["fund_code"]] = LatestNav(
                fund_code=row["fund_code"],
                nav_date=_parse_date(row["latest_nav_date"]),
                unit_nav=unit_nav,
            )
        return result

    def in_catalog(self, code: str) -> bool:
        """该代码是否在支持目录内（`fund_catalog` 视图命中）。

        目录 = `fund_trade_rule` 有行且 `fund.lifecycle_status='active'`。
        不在目录内的代码不提供净值/详情查询与交易（`FundNotSupported`）。
        """
        if not code or not str(code).strip():
            return False
        result = (
            self.client.table("fund_catalog")
            .select("fund_code")
            .eq("fund_code", str(code).strip())
            .limit(1)
            .execute()
        )
        return bool(result.data)

    # ==================== 历史净值 ====================

    def get_history(self, code: str, limit: Optional[int] = None) -> list[NavPoint]:
        """按 `nav_date` 升序返回历史净值。

        历史未补齐（`history_status != 'ready'`）时先做一次读穿透补数；
        补数失败抛 `FundNavUnavailable`，不返回已有片段。
        """
        code = self._validate_code(code)
        if limit is not None:
            limit = int(limit)
            if limit < 1:
                raise ValueError(f"limit 必须 >= 1: {limit}")
            limit = min(limit, _MAX_LIMIT)

        state = self._get_state(code)
        if not state or state.get("history_status") != "ready":
            fill = self.sync.ensure_history(code)
            if fill.status not in ("ready", "skipped"):
                raise FundNavUnavailable(code, fill.status, fill.error)
        return self._read_points(code, limit)

    def get_nav_on(self, code: str, on_date: date) -> NavLookup:
        """指定日期的净值，只读 DB、不触网。

        判定顺序见存储设计 §2.5，五步不可调换。
        """
        code = self._validate_code(code)
        if not isinstance(on_date, date):
            raise TypeError(f"on_date 必须是 date: {on_date!r}")

        row = (
            self.client.table("fund_nav")
            .select("fund_code,nav_date,unit_nav,accumulated_nav,daily_growth,source")
            .eq("fund_code", code)
            .eq("nav_date", on_date.isoformat())
            .limit(1)
            .execute()
        ).data
        if row:
            return NavLookup(NavLookupStatus.OK, _to_point(row[0]))

        state = self._get_state(code)
        if not state:
            # 连状态行都没有：没有任何证据支持「该日没有净值」
            return NavLookup(
                NavLookupStatus.FETCH_FAILED, None, reason="no_state"
            )

        latest_date = state.get("latest_nav_date")
        if latest_date is None:
            return NavLookup(
                NavLookupStatus.FETCH_FAILED, None, reason="history_not_complete"
            )
        latest_date = _parse_date(latest_date)

        if on_date > latest_date:
            return NavLookup(NavLookupStatus.NOT_YET_PUBLISHED, None)

        if state.get("history_status") != "ready":
            return NavLookup(
                NavLookupStatus.FETCH_FAILED, None, reason="history_not_complete"
            )

        start_raw = state.get("history_start_date")
        if start_raw is None:
            return NavLookup(
                NavLookupStatus.FETCH_FAILED, None, reason="history_start_unknown"
            )
        start_date = _parse_date(start_raw)

        if start_date <= on_date <= latest_date:
            # 覆盖区间内却没有记录 = 真实缺口，需要 repair
            return NavLookup(NavLookupStatus.FETCH_FAILED, None, reason="gap")
        if on_date < start_date:
            return NavLookup(
                NavLookupStatus.NO_NAV, None, reason=self._no_nav_reason(code, on_date)
            )
        return NavLookup(NavLookupStatus.NO_NAV, None, reason="no_nav")

    # ==================== DB 读取 ====================

    def _get_state(self, code: str) -> Optional[dict]:
        result = (
            self.client.table("fund_nav_state")
            .select(
                "fund_code,history_status,latest_nav_date,latest_unit_nav,"
                "history_start_date,last_checked_at,last_success_at,last_error"
            )
            .eq("fund_code", code)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def _select_states(self, codes: list[str]) -> list[dict]:
        result = (
            self.client.table("fund_nav_state")
            .select("fund_code,latest_nav_date,latest_unit_nav")
            .in_("fund_code", codes)
            .execute()
        )
        return result.data or []

    def _read_points(self, code: str, limit: Optional[int]) -> list[NavPoint]:
        """按日期倒序分页读取，最后反转为升序。

        `limit=None` 时必须分页：PostgREST 单次最多返回 1000 行，
        全量历史约 3000–4000 点，只读一页会静默截断。
        """
        if limit is not None:
            rows = (
                self.client.table("fund_nav")
                .select("fund_code,nav_date,unit_nav,accumulated_nav,daily_growth,source")
                .eq("fund_code", code)
                .order("nav_date", desc=True)
                .limit(limit)
                .execute()
            ).data or []
            return [_to_point(row) for row in reversed(rows)]

        rows: list[dict] = []
        offset = 0
        while True:
            page = (
                self.client.table("fund_nav")
                .select("fund_code,nav_date,unit_nav,accumulated_nav,daily_growth,source")
                .eq("fund_code", code)
                .order("nav_date", desc=True)
                .range(offset, offset + _PAGE_SIZE - 1)
                .execute()
            ).data or []
            rows.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        return [_to_point(row) for row in reversed(rows)]

    def _no_nav_reason(self, code: str, on_date: date) -> str:
        """NO_NAV 的排查提示：早于成立日时补 `before_establishment`（不改变状态）。"""
        try:
            result = (
                self.client.table("fund")
                .select("establish_date")
                .eq("fund_code", code)
                .limit(1)
                .execute()
            )
        except Exception as exc:  # 排查提示失败不影响判定结果
            logger.warning(f"查询成立日期失败（{code}）: {exc}")
            return "before_history_start"
        if not result.data or not result.data[0].get("establish_date"):
            return "before_history_start"
        establish = _parse_date(result.data[0]["establish_date"])
        return "before_establishment" if on_date < establish else "before_history_start"

    @staticmethod
    def _validate_code(code: str) -> str:
        text = str(code).strip() if code is not None else ""
        if not text:
            raise ValueError("基金代码不能为空")
        return text


# ==================== 行映射工具 ====================


def _to_decimal(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _to_point(row: dict) -> NavPoint:
    return NavPoint(
        fund_code=str(row["fund_code"]),
        nav_date=_parse_date(row["nav_date"]),
        unit_nav=_to_decimal(row.get("unit_nav")),
        accumulated_nav=_to_decimal(row.get("accumulated_nav")),
        daily_growth=_to_decimal(row.get("daily_growth")),
        source=str(row.get("source") or ""),
    )


# 进程级「按基金」锁：服务实例每次请求新建，锁必须放在模块级才有意义。
# `get_history` 的读穿透与 `ensure_history` 共用这把锁，保证并发首次访问只下载一次。
_code_locks: dict[str, threading.Lock] = {}
_code_locks_guard = threading.Lock()


def code_lock(code: str) -> threading.Lock:
    """取得该基金代码的进程级互斥锁（懒创建）。"""
    with _code_locks_guard:
        lock = _code_locks.get(code)
        if lock is None:
            lock = threading.Lock()
            _code_locks[code] = lock
        return lock
