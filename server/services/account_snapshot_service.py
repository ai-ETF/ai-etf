"""账户日终估值与快照。

设计依据：`docs/20-设计/基金与交易/账户日终估值与快照.md`。

口径要点：
- 以 A 股交易日 T 为单位，用 `fund_nav(nav_date=T)` 估值，不回退到更早净值；
- 总资产 = 可用现金 + 冻结资金 + 在途赎回款 + 持仓市值；
- 只有全部非货基持仓都拿到 T 日净值的快照才是 `valid`；
- 快照按 `(user_id, snapshot_date)` 幂等 upsert，已有效的快照不覆盖。
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from server.services.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)

# 与 portfolio_service 保持同一口径；这里不反向 import，避免服务间循环依赖。
INITIAL_CASH = Decimal("100000.00")
MONEY_FUND_CODE = "000198"
BEIJING_TZ = timezone(timedelta(hours=8))

_PAGE_SIZE = 1000          # PostgREST 单次最多返回 1000 行
_IN_CHUNK = 200            # 避免 IN 列表过长导致 URL 超限
_UPSERT_CHUNK = 500
_VALID_STATUS = "valid"
_INVALID_STATUS = "invalid"

_MONEY = Decimal("0.01")
_RATE = Decimal("0.000001")


class SnapshotError(Exception):
    """快照业务的基类异常。"""


class NotTradingDay(SnapshotError):
    """目标日期不是交易日，拒绝生成快照。"""

    def __init__(self, trade_date: date):
        self.trade_date = trade_date
        super().__init__(f"{trade_date.isoformat()} 不是交易日，不生成快照")


class ValuationNotReady(SnapshotError):
    """快照存在但无效，或用户/账户没有可估值的快照。"""


@dataclass(frozen=True)
class SnapshotRunResult:
    """一轮估值任务的统计结果。"""

    trade_date: date
    users_total: int
    valid: int
    invalid: int
    skipped_valid: int
    skipped_not_created: int
    upserted: int
    duration_ms: int
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat(),
            "users_total": self.users_total,
            "valid": self.valid,
            "invalid": self.invalid,
            "skipped_valid": self.skipped_valid,
            "skipped_not_created": self.skipped_not_created,
            "upserted": self.upserted,
            "duration_ms": self.duration_ms,
            "warnings": list(self.warnings),
        }


class AccountSnapshotService:
    """账户日终估值与快照（无状态，可注入 client 便于测试）。"""

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase

            self._client = get_supabase()
        return self._client

    # ==================== 对外入口 ====================

    def run(
        self,
        trade_date: date,
        source: str = "scheduled",
        user_ids: Optional[list[str]] = None,
    ) -> SnapshotRunResult:
        """对指定交易日的账户做统一估值并写入快照。

        参数:
            trade_date: 估值日，必须是交易日。
            source: `scheduled` / `manual` / `backfill`，写入快照来源。
            user_ids: 仅估算指定用户；为空表示全量。

        返回:
            `SnapshotRunResult` 统计结果。

        异常:
            `NotTradingDay`: 目标日期非交易日。
            `CalendarUnavailable` / `CalendarOutOfCoverage`: 交易日历不可用。
            RuntimeError: 数据库不可用或批量读取失败（不写半成品）。
        """
        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise TypeError(f"trade_date 必须是 date，实际 {trade_date!r}")
        if source not in ("scheduled", "manual", "backfill"):
            raise ValueError(f"未知快照来源: {source!r}")
        if not self.client:
            raise RuntimeError("数据库不可用")
        if not is_trading_day(trade_date):
            raise NotTradingDay(trade_date)

        started = time.monotonic()
        accounts = self._load_accounts(user_ids)
        result = SnapshotRunResult(
            trade_date=trade_date,
            users_total=len(accounts),
            valid=0,
            invalid=0,
            skipped_valid=0,
            skipped_not_created=0,
            upserted=0,
            duration_ms=0,
        )
        if not accounts:
            return _with_duration(result, started)

        positions_by_user = self._load_positions(user_ids)
        settling_by_user = self._load_settling_cash(user_ids)
        income_adjust_by_user = self._load_income_adjustments(trade_date, user_ids)
        income_t_users = self._load_income_users_on(trade_date, user_ids)
        existing_status = self._load_existing_status(trade_date, user_ids)
        codes = {
            pos["fund_code"]
            for positions in positions_by_user.values()
            for pos in positions
            if pos.get("fund_code") and pos["fund_code"] != MONEY_FUND_CODE
        }
        navs = self._load_navs(codes, trade_date)
        cutoff = _t_plus_one_start(trade_date)

        rows_to_write: list[dict] = []
        warnings: list[str] = []
        money_fund_users = {
            user_id
            for user_id, positions in positions_by_user.items()
            if any(pos.get("fund_code") == MONEY_FUND_CODE for pos in positions)
        }
        missing_income = money_fund_users - income_t_users

        for user_id, account in accounts.items():
            if existing_status.get(user_id) == _VALID_STATUS:
                result = _replace(result, skipped_valid=result.skipped_valid + 1)
                continue
            created_at = _parse_dt(account.get("created_at"))
            if created_at is not None and created_at >= cutoff:
                result = _replace(result, skipped_not_created=result.skipped_not_created + 1)
                continue
            try:
                row = self._value_user(
                    user_id=user_id,
                    account=account,
                    positions=positions_by_user.get(user_id, []),
                    settling_cash=settling_by_user.get(user_id, Decimal("0")),
                    income_adjust=income_adjust_by_user.get(user_id, Decimal("0")),
                    navs=navs,
                    trade_date=trade_date,
                    source=source,
                    money_fund_income_t=user_id in income_t_users,
                )
            except Exception as exc:  # 单用户数据异常不能拖垮整轮
                logger.exception("用户 %s 估值失败: %s", user_id, exc)
                row = self._invalid_snapshot(
                    user_id, trade_date, source, f"valuation_error:{type(exc).__name__}"
                )
            rows_to_write.append(row)
            if row["status"] == _VALID_STATUS:
                result = _replace(result, valid=result.valid + 1)
            else:
                result = _replace(result, invalid=result.invalid + 1)

        for chunk in _chunks(rows_to_write, _UPSERT_CHUNK):
            self.client.table("account_snapshots").upsert(
                chunk, on_conflict="user_id,snapshot_date"
            ).execute()
        result = _replace(result, upserted=len(rows_to_write))

        if missing_income:
            warnings.append(
                f"{len(missing_income)} 个货基持仓用户缺少 {trade_date.isoformat()} 的收益 lot"
            )
        result = _replace(result, warnings=warnings)
        final = _with_duration(result, started)
        logger.info(
            "[快照] %s 完成: users=%s valid=%s invalid=%s skipped_valid=%s "
            "skipped_not_created=%s upserted=%s duration=%sms",
            final.trade_date,
            final.users_total,
            final.valid,
            final.invalid,
            final.skipped_valid,
            final.skipped_not_created,
            final.upserted,
            final.duration_ms,
        )
        return final

    def snapshot_user(
        self, user_id: str, trade_date: date, source: str = "manual"
    ) -> dict:
        """确保指定用户在某交易日的快照存在且有效，返回快照行。

        异常:
            `NotTradingDay`: 非交易日。
            `ValuationNotReady`: 账户不存在，或快照为 invalid。
        """
        self.run(trade_date, source=source, user_ids=[user_id])
        rows = (
            self.client.table("account_snapshots")
            .select("*")
            .eq("user_id", user_id)
            .eq("snapshot_date", trade_date.isoformat())
            .limit(1)
            .execute()
        ).data or []
        if not rows:
            raise ValuationNotReady(f"用户 {user_id} 在 {trade_date.isoformat()} 没有账户或未生成快照")
        row = rows[0]
        if row.get("status") != _VALID_STATUS:
            raise ValuationNotReady(row.get("invalid_reason") or "估值无效")
        return row

    def daily_returns(self, user_id: str, days: int = 30) -> dict:
        """查询最近 N 条有效快照的区间收益。

        `daily_return` 仅在相邻交易日各有一条有效快照时有值；缺口日返回
        `period_days > 1` 与 `period_return`，`daily_return` 为 None。
        """
        if days < 1:
            raise ValueError("days 必须 >= 1")
        if not self.client:
            raise RuntimeError("数据库不可用")
        rows = (
            self.client.table("account_snapshots")
            .select(
                "snapshot_date,total_assets,cash,frozen_cash,settling_cash,"
                "position_value,total_pnl,total_return_rate"
            )
            .eq("user_id", user_id)
            .eq("status", _VALID_STATUS)
            .order("snapshot_date", desc=True)
            .limit(days + 1)
            .execute()
        ).data or []
        rows.reverse()

        computed: list[dict] = []
        for index, row in enumerate(rows):
            period_days: Optional[int] = None
            period_return: Optional[float] = None
            daily_return: Optional[float] = None
            if index > 0:
                prev_assets = _dec(rows[index - 1].get("total_assets"))
                curr_assets = _dec(row.get("total_assets"))
                if prev_assets > 0:
                    period_days = _count_trading_days(
                        _parse_date(rows[index - 1]["snapshot_date"]),
                        _parse_date(row["snapshot_date"]),
                    )
                    ratio = (curr_assets / prev_assets - Decimal("1")).quantize(
                        _RATE, rounding=ROUND_HALF_UP
                    )
                    period_return = float(ratio)
                    daily_return = period_return if period_days == 1 else None
                else:
                    logger.warning(
                        "用户 %s 在 %s 的总资产为 %s，无法计算区间收益",
                        user_id,
                        rows[index - 1].get("snapshot_date"),
                        prev_assets,
                    )
            computed.append(
                {
                    "date": str(row["snapshot_date"])[:10],
                    "total_assets": float(_dec(row.get("total_assets"))),
                    "cash": float(_dec(row.get("cash"))),
                    "frozen_cash": float(_dec(row.get("frozen_cash"))),
                    "settling_cash": float(_dec(row.get("settling_cash"))),
                    "position_value": float(_dec(row.get("position_value"))),
                    "total_pnl": float(_dec(row.get("total_pnl"))),
                    "total_return_rate": float(_dec(row.get("total_return_rate"))),
                    "period_days": period_days,
                    "period_return": period_return,
                    "daily_return": daily_return,
                }
            )

        items = computed[-days:] if len(computed) > days else computed
        return {"items": items}

    # ==================== 估值 ====================

    def _value_user(
        self,
        user_id: str,
        account: dict,
        positions: list[dict],
        settling_cash: Decimal,
        income_adjust: Decimal,
        navs: dict[str, Decimal],
        trade_date: date,
        source: str,
        money_fund_income_t: bool,
    ) -> dict:
        cash = _dec(account.get("cash"))
        frozen_cash = _dec(account.get("frozen_cash"))
        position_value = Decimal("0")
        coverage: list[dict] = []
        reasons: list[str] = []

        if cash < 0 or frozen_cash < 0 or settling_cash < 0:
            reasons.append("negative_cash_component")

        for pos in positions:
            code = str(pos.get("fund_code") or "").strip()
            quantity = _dec(pos.get("quantity"))
            if not code:
                reasons.append("missing_fund_code")
                continue
            if quantity < 0:
                reasons.append(f"negative_quantity:{code}")
                continue
            if code == MONEY_FUND_CODE:
                quantity_t = quantity - income_adjust
                if quantity_t < 0:
                    reasons.append(f"money_fund_income_adjustment_negative:{code}")
                    quantity_t = Decimal("0")
                value = quantity_t.quantize(_MONEY, rounding=ROUND_HALF_UP)
                coverage.append(
                    {
                        "fund_code": code,
                        "quantity": float(quantity_t),
                        "nav_date": trade_date.isoformat(),
                        "unit_nav": 1.0,
                        "value": float(value),
                    }
                )
            else:
                nav = navs.get(code)
                if nav is None or nav <= 0:
                    reasons.append(f"missing_nav:{code}")
                    coverage.append(
                        {
                            "fund_code": code,
                            "quantity": float(quantity),
                            "nav_date": trade_date.isoformat(),
                            "unit_nav": None,
                            "value": None,
                        }
                    )
                    continue
                value = (quantity * nav).quantize(_MONEY, rounding=ROUND_HALF_UP)
                coverage.append(
                    {
                        "fund_code": code,
                        "quantity": float(quantity),
                        "nav_date": trade_date.isoformat(),
                        "unit_nav": float(nav),
                        "value": float(value),
                    }
                )
            position_value += value

        cash = cash.quantize(_MONEY, rounding=ROUND_HALF_UP)
        frozen_cash = frozen_cash.quantize(_MONEY, rounding=ROUND_HALF_UP)
        settling_cash = settling_cash.quantize(_MONEY, rounding=ROUND_HALF_UP)
        position_value = position_value.quantize(_MONEY, rounding=ROUND_HALF_UP)
        total_assets = (cash + frozen_cash + settling_cash + position_value).quantize(
            _MONEY, rounding=ROUND_HALF_UP
        )
        total_pnl = (total_assets - INITIAL_CASH).quantize(_MONEY, rounding=ROUND_HALF_UP)
        total_return_rate = (
            (total_pnl / INITIAL_CASH).quantize(_RATE, rounding=ROUND_HALF_UP)
            if INITIAL_CASH > 0
            else Decimal("0")
        )

        return {
            "user_id": user_id,
            "snapshot_date": trade_date.isoformat(),
            "total_assets": float(total_assets),
            "cash": float(cash),
            "frozen_cash": float(frozen_cash),
            "settling_cash": float(settling_cash),
            "position_value": float(position_value),
            "total_pnl": float(total_pnl),
            "total_return_rate": float(total_return_rate),
            "position_count": len(positions),
            "status": _INVALID_STATUS if reasons else _VALID_STATUS,
            "invalid_reason": "; ".join(reasons)[:1000] if reasons else None,
            "source": source,
            "valuation_at": _now_iso(),
            "nav_coverage": coverage,
            "money_fund_income_date": trade_date.isoformat() if money_fund_income_t else None,
        }

    @staticmethod
    def _invalid_snapshot(
        user_id: str, trade_date: date, source: str, reason: str
    ) -> dict:
        """单用户估值异常时的兜底行：只留审计痕迹，不参与日收益。"""
        return {
            "user_id": user_id,
            "snapshot_date": trade_date.isoformat(),
            "total_assets": 0.0,
            "cash": 0.0,
            "frozen_cash": 0.0,
            "settling_cash": 0.0,
            "position_value": 0.0,
            "total_pnl": 0.0,
            "total_return_rate": 0.0,
            "position_count": 0,
            "status": _INVALID_STATUS,
            "invalid_reason": reason[:1000],
            "source": source,
            "valuation_at": _now_iso(),
            "nav_coverage": None,
            "money_fund_income_date": None,
        }

    # ==================== DB 读取 ====================

    def _load_accounts(self, user_ids: Optional[list[str]]) -> dict[str, dict]:
        rows = self._read_rows(
            "accounts", "user_id,cash,frozen_cash,created_at", user_ids=user_ids, order="user_id"
        )
        return {row["user_id"]: row for row in rows if row.get("user_id")}

    def _load_positions(self, user_ids: Optional[list[str]]) -> dict[str, list[dict]]:
        rows = self._read_rows(
            "positions",
            "user_id,fund_code,quantity",
            user_ids=user_ids,
            filters=[("gt", ("quantity", 0))],
            order="user_id",
        )
        result: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            if row.get("user_id"):
                result[row["user_id"]].append(row)
        return result

    def _load_settling_cash(self, user_ids: Optional[list[str]]) -> dict[str, Decimal]:
        rows = self._read_rows(
            "trade_orders",
            "user_id,net_amount",
            user_ids=user_ids,
            filters=[("eq", ("direction", "sell")), ("eq", ("status", "settling"))],
            order="id",
        )
        result: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in rows:
            if row.get("user_id"):
                result[row["user_id"]] += _dec(row.get("net_amount"))
        return result

    def _load_income_adjustments(
        self, trade_date: date, user_ids: Optional[list[str]]
    ) -> dict[str, Decimal]:
        """迟到快照修正：T 之后入账的货基收益 lot 要从当前份额里剔除。"""
        rows = self._read_rows(
            "position_lots",
            "user_id,quantity",
            user_ids=user_ids,
            filters=[
                ("eq", ("fund_code", MONEY_FUND_CODE)),
                ("eq", ("source", "income")),
                ("gt", ("nav_date", trade_date.isoformat())),
            ],
            order="id",
        )
        result: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in rows:
            if row.get("user_id"):
                result[row["user_id"]] += _dec(row.get("quantity"))
        return result

    def _load_income_users_on(
        self, trade_date: date, user_ids: Optional[list[str]]
    ) -> set[str]:
        """是否存在 T 日计息的货基收益 lot。"""
        rows = self._read_rows(
            "position_lots",
            "user_id",
            user_ids=user_ids,
            filters=[
                ("eq", ("fund_code", MONEY_FUND_CODE)),
                ("eq", ("source", "income")),
                ("eq", ("nav_date", trade_date.isoformat())),
            ],
            order="user_id",
        )
        return {row["user_id"] for row in rows if row.get("user_id")}

    def _load_existing_status(
        self, trade_date: date, user_ids: Optional[list[str]]
    ) -> dict[str, str]:
        rows = self._read_rows(
            "account_snapshots",
            "user_id,status",
            user_ids=user_ids,
            filters=[("eq", ("snapshot_date", trade_date.isoformat()))],
            order="user_id",
        )
        return {
            row["user_id"]: row.get("status")
            for row in rows
            if row.get("user_id")
        }

    def _load_navs(self, codes: set[str], trade_date: date) -> dict[str, Decimal]:
        navs: dict[str, Decimal] = {}
        for chunk in _chunks(sorted(codes), _IN_CHUNK):
            if not chunk:
                continue
            rows = _select_paged(
                lambda start, end: (
                    self.client.table("fund_nav")
                    .select("fund_code,unit_nav")
                    .eq("nav_date", trade_date.isoformat())
                    .in_("fund_code", chunk)
                    .order("fund_code")
                    .range(start, end)
                    .execute()
                )
            )
            for row in rows:
                code = row.get("fund_code")
                nav = _dec(row.get("unit_nav"))
                if code and nav > 0:
                    navs[code] = nav
        return navs

    def _read_rows(
        self,
        table: str,
        columns: str,
        *,
        user_ids: Optional[list[str]] = None,
        filters: Optional[list[tuple[str, tuple]]] = None,
        order: Optional[str] = None,
    ) -> list[dict]:
        """分页读取；`user_ids` 非空时按 IN 分块，空列表直接返回空。"""
        if user_ids is not None:
            if not user_ids:
                return []
            rows: list[dict] = []
            for chunk in _chunks(sorted(set(user_ids)), _IN_CHUNK):
                extra = list(filters or []) + [("in_", ("user_id", chunk))]
                rows.extend(
                    self._read_rows(
                        table, columns, user_ids=None, filters=extra, order=order
                    )
                )
            return rows

        def builder(start: int, end: int):
            query = self.client.table(table).select(columns)
            for method, args in filters or []:
                query = getattr(query, method)(*args)
            if order:
                query = query.order(order)
            return query.range(start, end).execute()

        return _select_paged(builder)


# ==================== 工具 ====================


def _select_paged(query_builder) -> list[dict]:
    """按 range 分页取全量（PostgREST 单次最多 1000 行）。"""
    rows: list[dict] = []
    offset = 0
    while True:
        page = query_builder(offset, offset + _PAGE_SIZE - 1).data or []
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            return rows
        offset += _PAGE_SIZE


def _chunks(values, size: int):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _dec(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"不是合法数字: {value!r}") from exc


def _parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _t_plus_one_start(trade_date: date) -> datetime:
    return datetime.combine(trade_date + timedelta(days=1), dtime(0, 0), tzinfo=BEIJING_TZ)


def _now_iso() -> str:
    return datetime.now(BEIJING_TZ).isoformat()


def _count_trading_days(start: date, end: date) -> int:
    """统计 `(start, end]` 内的交易日数；start/end 本身应为交易日。"""
    if end <= start:
        return 0
    count = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if is_trading_day(cursor):
            count += 1
    return count


def _replace(result: SnapshotRunResult, **changes) -> SnapshotRunResult:
    data = {
        "trade_date": result.trade_date,
        "users_total": result.users_total,
        "valid": result.valid,
        "invalid": result.invalid,
        "skipped_valid": result.skipped_valid,
        "skipped_not_created": result.skipped_not_created,
        "upserted": result.upserted,
        "duration_ms": result.duration_ms,
        "warnings": result.warnings,
    }
    data.update(changes)
    return SnapshotRunResult(**data)


def _with_duration(result: SnapshotRunResult, started: float) -> SnapshotRunResult:
    return _replace(result, duration_ms=int((time.monotonic() - started) * 1000))
