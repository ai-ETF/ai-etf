"""账户日终估值与快照的关键用例。

覆盖设计文档 §5 的六条：
1. 净值齐全 → 分项闭合并标 valid
2. 缺非货基 T 日净值 → invalid，不参与日收益
3. 非交易日 → 拒绝
4. 首条快照收益为空；缺口日 period_days>1、daily_return=None
5. 同交易日重复执行 → 已 valid 不覆盖
6. 账户创建于 T 之后 → 不生成
"""
from datetime import date

import pytest

import server.services.trading_calendar as trading_calendar
from server.services.account_snapshot_service import (
    AccountSnapshotService,
    NotTradingDay,
    ValuationNotReady,
)

TRADE_DATE = "2026-01-05"
NEXT_DATE = "2026-01-06"
CALENDAR_DAYS = [
    "2026-01-05",
    "2026-01-06",
    "2026-01-07",
    "2026-01-08",
]


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table):
        self._c = client
        self._table = table
        self._op = "select"
        self._filters = []
        self._select_cols = "*"
        self._orders = []
        self._limit = None
        self._range = None
        self._payload = None
        self._on_conflict = None

    def select(self, cols="*", **_kwargs):
        self._op = "select"
        self._select_cols = cols
        return self

    def upsert(self, rows, on_conflict=None):
        self._op = "upsert"
        self._payload = rows
        self._on_conflict = on_conflict
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def order(self, col, desc=False, **_kwargs):
        self._orders.append((col, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = self._c.rows.setdefault(self._table, [])
        if self._op == "upsert":
            keys = [k.strip() for k in (self._on_conflict or "").split(",") if k.strip()]
            for incoming in self._payload:
                if keys:
                    existing = next(
                        (r for r in rows if all(r.get(k) == incoming.get(k) for k in keys)),
                        None,
                    )
                else:
                    existing = None
                if existing is None:
                    rows.append(dict(incoming))
                else:
                    existing.update(incoming)
            return FakeResult(self._payload)

        matched = [dict(r) for r in rows if self._match(r)]
        for col, desc in self._orders:
            matched.sort(key=lambda r: r.get(col), reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        if self._range is not None:
            start, end = self._range
            matched = matched[start : end + 1]
        if self._select_cols != "*":
            cols = [c.strip() for c in self._select_cols.split(",")]
            matched = [{c: r.get(c) for c in cols} for r in matched]
        return FakeResult(matched)

    def _match(self, row):
        for op, col, val in self._filters:
            row_value = row.get(col)
            if op == "eq" and row_value != val:
                return False
            if op == "gt" and (row_value is None or row_value <= val):
                return False
            if op == "in" and row_value not in val:
                return False
        return True


class FakeClient:
    def __init__(self, rows=None):
        self.rows = rows or {}

    def table(self, name):
        return FakeQuery(self, name)


def _install_calendar():
    trading_calendar.install_snapshot(
        CALENDAR_DAYS,
        coverage_start=date(2025, 12, 1),
        coverage_end=date(2026, 2, 1),
    )


@pytest.fixture(autouse=True)
def _calendar():
    _install_calendar()
    yield
    trading_calendar.reset_cache()


def _base_rows(created_at="2026-01-01T00:00:00+08:00"):
    return {
        "accounts": [
            {
                "user_id": "u1",
                "cash": 50000.0,
                "frozen_cash": 1000.0,
                "created_at": created_at,
            }
        ],
        "positions": [
            {"user_id": "u1", "fund_code": "000198", "quantity": 20000.0},
            {"user_id": "u1", "fund_code": "110001", "quantity": 1000.0},
        ],
        "fund_nav": [
            {"fund_code": "110001", "nav_date": TRADE_DATE, "unit_nav": 1.5}
        ],
        "position_lots": [
            {
                "user_id": "u1",
                "fund_code": "000198",
                "source": "income",
                "nav_date": TRADE_DATE,
                "quantity": 0.6,
            }
        ],
        "trade_orders": [
            {"user_id": "u1", "direction": "sell", "status": "settling", "net_amount": 500.0}
        ],
        "account_snapshots": [],
    }


def test_净值齐全_分项闭合且有效():
    svc = AccountSnapshotService(FakeClient(_base_rows()))
    result = svc.run(date(2026, 1, 5))

    assert result.valid == 1
    assert result.invalid == 0
    row = svc.client.rows["account_snapshots"][0]
    assert row["status"] == "valid"
    # 现金 50000 + 冻结 1000 + 在途 500 + 货基 20000 + 110001 的 1500
    assert row["total_assets"] == 73000.0
    assert row["position_value"] == 21500.0
    assert (
        row["cash"] + row["frozen_cash"] + row["settling_cash"] + row["position_value"]
        == row["total_assets"]
    )
    assert row["position_count"] == 2
    assert row["money_fund_income_date"] == TRADE_DATE
    assert row["source"] == "scheduled"
    coverage = {item["fund_code"]: item for item in row["nav_coverage"]}
    assert coverage["000198"]["unit_nav"] == 1.0
    assert coverage["110001"]["nav_date"] == TRADE_DATE


def test_缺非货基T日净值_标invalid且不参与日收益():
    rows = _base_rows()
    rows["fund_nav"] = []
    rows["account_snapshots"] = [
        {
            "user_id": "u1",
            "snapshot_date": TRADE_DATE,
            "total_assets": 73000.0,
            "cash": 50000.0,
            "frozen_cash": 1000.0,
            "settling_cash": 500.0,
            "position_value": 21500.0,
            "total_pnl": -27000.0,
            "total_return_rate": -0.27,
            "status": "valid",
        }
    ]
    svc = AccountSnapshotService(FakeClient(rows))
    result = svc.run(date(2026, 1, 6))

    assert result.invalid == 1
    invalid_row = next(
        r for r in svc.client.rows["account_snapshots"] if r["snapshot_date"] == NEXT_DATE
    )
    assert invalid_row["status"] == "invalid"
    assert "missing_nav:110001" in invalid_row["invalid_reason"]

    items = svc.daily_returns("u1")["items"]
    assert [item["date"] for item in items] == [TRADE_DATE]

    with pytest.raises(ValuationNotReady):
        svc.snapshot_user("u1", date(2026, 1, 6))


def test_非交易日_拒绝生成():
    svc = AccountSnapshotService(FakeClient(_base_rows()))
    with pytest.raises(NotTradingDay):
        svc.run(date(2026, 1, 10))
    assert svc.client.rows["account_snapshots"] == []


def test_首条收益为空_缺口日不算单日():
    svc = AccountSnapshotService(
        FakeClient(
            {
                "account_snapshots": [
                    _snapshot_row("2026-01-05", 100000.0),
                    _snapshot_row("2026-01-06", 100500.0),
                    _snapshot_row("2026-01-08", 101000.0),
                ]
            }
        )
    )
    items = svc.daily_returns("u1", days=10)["items"]

    assert len(items) == 3
    assert items[0]["period_days"] is None
    assert items[0]["daily_return"] is None
    assert items[1]["period_days"] == 1
    assert items[1]["daily_return"] == 0.005
    assert items[2]["period_days"] == 2  # 01-07、01-08
    assert items[2]["period_return"] == pytest.approx(0.00497512, abs=1e-6)
    assert items[2]["daily_return"] is None


def test_重复执行_有效快照不被覆盖():
    existing = _snapshot_row(TRADE_DATE, 12345.0)
    rows = _base_rows()
    rows["account_snapshots"] = [existing]
    svc = AccountSnapshotService(FakeClient(rows))

    result = svc.run(date(2026, 1, 5))

    assert result.skipped_valid == 1
    assert result.upserted == 0
    assert svc.client.rows["account_snapshots"] == [existing]


def test_账户创建于T之后_不生成():
    svc = AccountSnapshotService(
        FakeClient(_base_rows(created_at="2026-01-07T00:00:00+08:00"))
    )
    result = svc.run(date(2026, 1, 6))

    assert result.skipped_not_created == 1
    assert svc.client.rows["account_snapshots"] == []


def _snapshot_row(snapshot_date, total_assets):
    return {
        "user_id": "u1",
        "snapshot_date": snapshot_date,
        "total_assets": total_assets,
        "cash": total_assets,
        "frozen_cash": 0.0,
        "settling_cash": 0.0,
        "position_value": 0.0,
        "total_pnl": total_assets - 100000.0,
        "total_return_rate": (total_assets - 100000.0) / 100000.0,
        "status": "valid",
    }
