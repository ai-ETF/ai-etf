"""portfolio_service 单元测试：场外基金持仓交易服务（分批）。

模块名称：server/services/portfolio_service.py
所测功能（分批添加）：
  - 时间工具：_parse_time（时区归一）、_is_before_cutoff（15:00 截止）、
    _is_trading_day（交易日，注入日历快照）、_next_trading_day（下一交易日）
测试方法：纯函数直测 + 注入假日历快照，全程不联网、不连 Supabase。
"""
import json
import sys
import types
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

import server.services.fund_fee_service as fee_svc_mod
import server.services.fund_risk_service as fund_risk_service_mod
import server.services.portfolio_service as portfolio_service
import server.services.risk_service as risk_service_mod
import server.services.trading_calendar as trading_calendar
from server.services.trading_calendar_cache import CalendarUnavailable
from server.services.portfolio_service import (
    MONEY_FUND_CODE,
    NavUnavailableForConfirm,
    PortfolioService,
    _parse_time,
)


# ==================== _parse_time：时区归一 ====================


def test_parse_time_带Z时区_归一为北京时间():
    # "02:00Z" = UTC 02:00 = 北京 10:00
    dt = _parse_time("2026-01-05T02:00:00Z")
    assert dt.tzinfo is None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 1, 5, 10, 0)


def test_parse_time_带加00_00时区():
    dt = _parse_time("2026-01-05T02:00:00+00:00")
    assert dt.hour == 10


def test_parse_time_带加08_00时区_本就是北京():
    dt = _parse_time("2026-01-05T10:00:00+08:00")
    assert dt.hour == 10
    assert dt.tzinfo is None


def test_parse_time_无时区_原样返回去时区():
    dt = _parse_time("2026-01-05T10:00:00")
    assert dt.hour == 10
    assert dt.tzinfo is None


# ==================== _is_before_cutoff：15:00 截止 ====================


def test_14点59_在截止前():
    assert PortfolioService._is_before_cutoff(datetime(2026, 1, 5, 14, 59)) is True


def test_15点整_不在截止前():
    assert PortfolioService._is_before_cutoff(datetime(2026, 1, 5, 15, 0)) is False


def test_9点30_在截止前():
    assert PortfolioService._is_before_cutoff(datetime(2026, 1, 5, 9, 30)) is True


# ==================== _is_trading_day：交易日 ====================


def test_交易日_日历命中():
    trading_calendar.install_snapshot(["2026-01-05", "2026-01-06"])
    assert PortfolioService._is_trading_day(date(2026, 1, 5)) is True


def test_非交易日_日历未命中():
    trading_calendar.install_snapshot(
        ["2026-01-05"], coverage_start=date(2026, 1, 1), coverage_end=date(2026, 1, 31)
    )
    assert PortfolioService._is_trading_day(date(2026, 1, 10)) is False


def test_日历未就绪_抛CalendarUnavailable():
    """无兜底：不会退化回「周一至周五」。"""
    with pytest.raises(CalendarUnavailable):
        PortfolioService._is_trading_day(date(2026, 1, 5))


# ==================== _next_trading_day：下一交易日 ====================


def test_next_trading_day_返回下一个交易日():
    trading_calendar.install_snapshot(["2026-01-06"])
    assert PortfolioService._next_trading_day(date(2026, 1, 5)) == date(2026, 1, 6)


def test_next_trading_day_14天无交易日_抛错():
    """删除 d+1 兜底后，日历数据可疑必须显式失败。"""
    trading_calendar.install_snapshot(
        [], coverage_start=date(2026, 1, 1), coverage_end=date(2026, 3, 1)
    )
    with pytest.raises(RuntimeError):
        PortfolioService._next_trading_day(date(2026, 1, 5))


# ==================== 风控净值替身 ====================


class FakeRiskService:
    """替身：需同时支持实例化（get_latest_profile）与静态访问（get_risk_warning）。"""

    profile = None  # 类级属性，测试里设置

    def get_latest_profile(self, user_id):
        return self.profile

    @staticmethod
    def get_risk_warning(user_risk_level, user_risk_label, fund_risk_level, fund_risk_label):
        return {
            "level": "info",
            "user_risk_level": user_risk_level,
            "fund_risk_level": fund_risk_level,
        }


class FakeFundRiskService:
    risk_profile = None  # 类级属性，测试里设置

    def get_risk_profile(self, fund_code):
        return self.risk_profile


class FakeFeeService:
    def __init__(self, fund_name=None):
        self._fund_name = fund_name

    def get_fund_name(self, fund_code, rule=None):
        return self._fund_name


def _patch_risk_services(monkeypatch, profile, fund_risk):
    FakeRiskService.profile = profile
    FakeFundRiskService.risk_profile = fund_risk
    monkeypatch.setattr(risk_service_mod, "RiskService", FakeRiskService)
    monkeypatch.setattr(fund_risk_service_mod, "FundRiskService", FakeFundRiskService)


class FakeFundNav:
    """净值读服务替身：`latest`/`lookup` 都是 {code: 值}，值为 None 表示查不到。"""

    def __init__(self, latest=None, lookup=None):
        self.latest = latest or {}
        self.lookup = lookup or {}

    def get_latest(self, code):
        from datetime import date

        from server.services.fund_nav_service import LatestNav

        nav = self.latest.get(code)
        if nav is None:
            return None
        return LatestNav(fund_code=code, nav_date=date(2026, 1, 6), unit_nav=nav)

    def get_latest_batch(self, codes):
        found = (self.get_latest(c) for c in codes)
        return {n.fund_code: n for n in found if n is not None}

    def get_nav_on(self, code, on_date):
        from server.services.fund_nav_service import NavLookup, NavLookupStatus

        found = self.lookup.get(code)
        if isinstance(found, NavLookup):
            return found
        if found is None:
            return NavLookup(NavLookupStatus.FETCH_FAILED, None, reason="no_state")
        return _ok_lookup(code, on_date, found)


def _ok_lookup(code, nav_date, nav):
    from server.services.fund_nav_service import NavLookup, NavLookupStatus, NavPoint

    return NavLookup(
        NavLookupStatus.OK,
        NavPoint(
            fund_code=code,
            nav_date=nav_date,
            unit_nav=Decimal(str(nav)),
            accumulated_nav=None,
            daily_growth=None,
            source="eastmoney",
        ),
    )


def _patch_latest_nav(monkeypatch, navs, default=None):
    """把 `_latest_nav` 换成按代码查表的替身（货基特判不参与，仍由真实方法处理）。"""
    monkeypatch.setattr(
        portfolio_service.PortfolioService,
        "_latest_nav",
        lambda self, code: (
            Decimal("1.0000") if code == MONEY_FUND_CODE else navs.get(code, default)
        ),
    )


def _patch_latest_nav_batch(monkeypatch, navs):
    """把 `_latest_nav_batch`（持仓页用）换成查表替身。"""
    monkeypatch.setattr(
        portfolio_service.PortfolioService,
        "_latest_nav_batch",
        lambda self, codes: {c: navs[c] for c in codes if c in navs},
    )


def _patch_confirm_nav(monkeypatch, nav=None, error=None):
    """把 `_confirm_nav` 换成固定值 / 固定异常的替身，供确认流程用例使用。"""
    def _fake(self, order):
        if error is not None:
            raise error
        return Decimal(str(nav))

    monkeypatch.setattr(portfolio_service.PortfolioService, "_confirm_nav", _fake)


# ==================== _get_risk_warning：风险提示 ====================


def test_风险提示_画像与基金风险齐全_返回提示(monkeypatch):
    _patch_risk_services(
        monkeypatch,
        profile={"risk_level": "conservative", "risk_label": "保守型"},
        fund_risk={"risk_level": "moderate", "risk_label": "中等风险"},
    )
    warning = PortfolioService()._get_risk_warning("u1", "110020")
    assert warning["level"] == "info"
    assert warning["user_risk_level"] == "conservative"
    assert warning["fund_risk_level"] == "moderate"


def test_风险提示_无画像_返回None(monkeypatch):
    _patch_risk_services(monkeypatch, profile=None, fund_risk={"risk_level": "moderate"})
    assert PortfolioService()._get_risk_warning("u1", "110020") is None


def test_风险提示_无基金风险_返回None(monkeypatch):
    _patch_risk_services(monkeypatch, profile={"risk_level": "conservative"}, fund_risk=None)
    assert PortfolioService()._get_risk_warning("u1", "110020") is None


def test_风险提示_异常_返回None不影响交易(monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(risk_service_mod, "RiskService", _boom)
    assert PortfolioService()._get_risk_warning("u1", "110020") is None


# ==================== 净值读取（只读 DB） ====================


def test_latest_nav_货币基金_恒为1():
    assert PortfolioService()._latest_nav(MONEY_FUND_CODE) == Decimal("1.0000")


def test_latest_nav_非货基_取读服务最新值():
    svc = PortfolioService(fund_nav=FakeFundNav(latest={"110020": Decimal("1.2345")}))
    assert svc._latest_nav("110020") == Decimal("1.2345")


def test_latest_nav_库中无数据_返回None():
    svc = PortfolioService(fund_nav=FakeFundNav())
    assert svc._latest_nav("110020") is None


def test_latest_nav_batch_一次取回_货基仍为1():
    svc = PortfolioService(fund_nav=FakeFundNav(latest={"110020": Decimal("1.5")}))
    navs = svc._latest_nav_batch(["110020", MONEY_FUND_CODE, "000071"])
    assert navs == {"110020": Decimal("1.5"), MONEY_FUND_CODE: Decimal("1.0000")}


def test_confirm_nav_四态_只有OK能确认():
    """四态必须可区分：未公布/取数失败/无净值日都抛「保持 pending」，不是拒单。"""
    from datetime import date

    from server.services.fund_nav_service import NavLookup, NavLookupStatus

    order = {"id": "o1", "fund_code": "110020", "confirm_date": "2026-01-05"}
    on_date = date(2026, 1, 5)
    cases = [
        (NavLookupStatus.NOT_YET_PUBLISHED, None),
        (NavLookupStatus.FETCH_FAILED, "history_not_complete"),
        (NavLookupStatus.NO_NAV, "before_establishment"),
    ]
    for status, reason in cases:
        svc = PortfolioService(
            fund_nav=FakeFundNav(lookup={"110020": NavLookup(status, None, reason)})
        )
        with pytest.raises(NavUnavailableForConfirm) as exc_info:
            svc._confirm_nav(order)
        assert exc_info.value.status == status.value
        assert exc_info.value.nav_date == on_date

    ok = PortfolioService(fund_nav=FakeFundNav(lookup={"110020": _ok_lookup("110020", on_date, "1.5")}))
    assert ok._confirm_nav(order) == Decimal("1.5")


def test_confirm_nav_货基不查读服务():
    svc = PortfolioService(fund_nav=FakeFundNav())
    order = {"id": "o1", "fund_code": MONEY_FUND_CODE, "confirm_date": "2026-01-05"}
    assert svc._confirm_nav(order) == Decimal("1.0000")


def test_confirm_nav_缺确认日_抛普通异常不保持pending():
    """没有 confirm_date 是数据错误，必须拒单（不能当「净值还没到」无限重试）。"""
    svc = PortfolioService(fund_nav=FakeFundNav())
    with pytest.raises(RuntimeError):
        svc._confirm_nav({"id": "o1", "fund_code": "110020", "confirm_date": None})


# ==================== _get_fund_name：基金名称 ====================


def test_fund_name_优先读rule():
    assert PortfolioService()._get_fund_name("110020", rule={"fund_name": "易方达"}) == "易方达"


def test_fund_name_从费率规则查(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeService(fund_name="费率名"))
    assert PortfolioService()._get_fund_name("110020") == "费率名"


def test_fund_name_全部无_返回基金代码(monkeypatch):
    """2026-10-26：实时行情兜底已删除，取不到名称时直接返回代码，不再触网。"""
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeService(fund_name=None))
    assert PortfolioService()._get_fund_name("110020") == "110020"


# ==================== 富 FakeClient（多表内存替身） ====================


class FakeResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _CheckViolation(Exception):
    """模拟 PostgREST 因违反 CHECK 约束返回的 400（真实环境为 HTTP 400，不写入）。"""


# 镜像基线迁移里的 CHECK 约束 —— 否则单测替身什么状态都收，「写了一个数据库不认的
# 状态值」这类 bug（曾真实存在：status="failed"）在单测里永远不会暴露。
_CHECK_CONSTRAINTS = {
    "trade_orders": {
        "status": ("pending", "completed", "cancelled", "rejected", "reserved"),
    },
}


class FakeQuery:
    """模拟 supabase 链式调用：table().select/insert/update/delete().eq/lte().order().limit().range().execute()。"""

    def __init__(self, client, table_name):
        self._c = client
        self._table = table_name
        self._op = None
        self._filters = []          # (op, col, val)
        self._insert_data = None
        self._update_data = None
        self._select_cols = "*"
        self._limit = None
        self._range = None
        self._with_count = False

    def select(self, *cols, **kwargs):
        self._op = "select"
        self._select_cols = cols[0] if cols else "*"
        if kwargs.get("count") == "exact":
            self._with_count = True
        return self

    def insert(self, data):
        self._op = "insert"
        self._insert_data = data
        return self

    def update(self, data):
        self._op = "update"
        self._update_data = data
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        if self._c.error is not None:
            raise self._c.error
        if self._op == "insert":
            self._check(self._insert_data)
        elif self._op == "update":
            self._check(self._update_data)
        rows = self._c.rows.setdefault(self._table, [])

        if self._op == "insert":
            row = dict(self._insert_data)
            row["id"] = row.get("id") or f"id-{len(rows) + 1}"
            rows.append(row)
            return FakeResult([row])

        matched = [r for r in rows if self._match(r)]

        if self._op == "update":
            for r in matched:
                r.update(self._update_data)
            return FakeResult(matched)

        if self._op == "delete":
            self._c.rows[self._table] = [r for r in rows if not self._match(r)]
            return FakeResult(matched)

        # select
        out = matched
        if self._limit is not None:
            out = out[: self._limit]
        if self._range is not None:
            s, e = self._range
            out = out[s : e + 1]
        if self._select_cols != "*":
            out = [{self._select_cols: r.get(self._select_cols)} for r in out]
        if self._with_count:
            return FakeResult(out, count=len(matched))
        return FakeResult(out)

    def _match(self, row):
        for op, col, val in self._filters:
            rv = row.get(col)
            if op == "eq" and rv != val:
                return False
            if op == "lte" and (rv is None or rv > val):
                return False
            if op == "in" and rv not in val:
                return False
            if op == "gt" and (rv is None or rv <= val):
                return False
            if op == "gte" and (rv is None or rv < val):
                return False
        return True

    def _check(self, data):
        """按 _CHECK_CONSTRAINTS 校验待写入的取值，违反即抛错（模拟数据库拒绝写入）。"""
        for col, allowed in _CHECK_CONSTRAINTS.get(self._table, {}).items():
            value = (data or {}).get(col)
            if value is not None and value not in allowed:
                raise _CheckViolation(
                    f'{self._table}.{col} 违反 CHECK 约束: {value!r} 不在 {allowed} 中'
                )


class FakeRpc:
    """rpc() 链式替身：记录调用参数，返回脚本化的 jsonb 结果。"""

    def __init__(self, client, name, params):
        self._c = client
        self._name = name
        self._params = params

    def execute(self):
        self._c.rpc_calls.append((self._name, dict(self._params or {})))
        payload = self._c.rpc_responses.get(self._name, {})
        if callable(payload):
            payload = payload(self._params)
        return FakeResult(payload)


class FakeClient:
    """内存多表替身：rows 为 {表名: [行 dict]}，不产生任何网络/DB IO。"""

    def __init__(self, rows=None, error=None):
        self.rows = rows or {}
        self.error = error
        self.rpc_calls = []
        self.rpc_responses = {}

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params=None):
        return FakeRpc(self, name, params)


# ==================== 时间冻结 / urllib 替身 ====================


def _freeze_beijing_date(monkeypatch, d):
    monkeypatch.setattr(portfolio_service, "_beijing_date", lambda: d)


def _urlopen_boom(req, timeout=None):
    raise RuntimeError("network down")


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._data).encode()


def _patch_urlopen(monkeypatch, data):
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(data)
    )


# ==================== _money_fund_per10k_income：货基万份收益 ====================


def test_万份收益_取第一条非今天的有效记录(monkeypatch):
    _freeze_beijing_date(monkeypatch, date(2026, 1, 10))
    PortfolioService._money_fund_cache = {}
    _patch_urlopen(
        monkeypatch,
        {"Data": {"LSJZList": [
            {"FSRQ": "2026-01-10", "DWJZ": "0.3"},     # 今天，跳过
            {"FSRQ": "2026-01-09", "DWJZ": "0.2229"},  # 昨天
        ]}},
    )
    assert PortfolioService()._money_fund_per10k_income() == Decimal("0.2229")


def test_万份收益_接口空列表_抛错(monkeypatch):
    _freeze_beijing_date(monkeypatch, date(2026, 1, 10))
    PortfolioService._money_fund_cache = {}
    _patch_urlopen(monkeypatch, {"Data": {"LSJZList": []}})
    with pytest.raises(RuntimeError, match="空列表"):
        PortfolioService()._money_fund_per10k_income()


def test_万份收益_网络异常_抛错(monkeypatch):
    _freeze_beijing_date(monkeypatch, date(2026, 1, 10))
    PortfolioService._money_fund_cache = {}
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_boom)
    with pytest.raises(RuntimeError, match="网络"):
        PortfolioService()._money_fund_per10k_income()


def test_万份收益_缓存命中_不重复请求(monkeypatch):
    _freeze_beijing_date(monkeypatch, date(2026, 1, 10))
    PortfolioService._money_fund_cache = {}
    _patch_urlopen(
        monkeypatch,
        {"Data": {"LSJZList": [{"FSRQ": "2026-01-09", "DWJZ": "0.2229"}]}},
    )
    svc = PortfolioService()
    first = svc._money_fund_per10k_income()
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_boom)
    second = svc._money_fund_per10k_income()
    assert first == second == Decimal("0.2229")


# ==================== credit_money_fund_income：货基收益入账 ====================


def test_货基自动申购确认_走confirm_buy_order_RPC():
    """自动申购不在应用层直接建仓：统一走 RPC，保证 lot 与 positions 不分叉。"""
    svc = PortfolioService()
    svc._client = FakeClient({"trade_orders": [
        {"id": "o1", "user_id": "u1", "fund_code": MONEY_FUND_CODE, "direction": "buy",
         "status": "pending", "amount": 1000.0, "fee": 0.0},
    ]})
    svc._client.rpc_responses["confirm_buy_order"] = {"result": "completed"}
    svc._confirm_money_fund_order("u1")

    name, params = svc._client.rpc_calls[0]
    assert name == "confirm_buy_order"
    assert params["p_order_id"] == "o1"
    assert params["p_nav"] == 1.0
    assert params["p_net_amount"] == 1000.0
    assert params["p_quantity"] == 1000.0
    assert params["p_residual"] == 0.0


def _patch_per10k(monkeypatch, value, income_date="2026-01-09"):
    """替身万份收益：同时写缓存里的计息日（RPC 幂等键要用）。"""
    PortfolioService._money_fund_cache = {
        "date": "2026-01-10", "per10k_income": Decimal(value), "income_date": income_date,
    }
    monkeypatch.setattr(PortfolioService, "_money_fund_per10k_income", lambda self: Decimal(value))


def test_入账_无持仓_跳过(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.credit_money_fund_income()
    assert result["status"] == "ok"
    assert result["credited"] == 0
    assert result["income_date"] == "2026-01-09"


def test_入账_有持仓_走原子RPC(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": MONEY_FUND_CODE, "quantity": 100000, "principal": 100000},
    ]})
    svc._client.rpc_responses["credit_money_fund_income_atomic"] = {"result": "credited"}
    result = svc.credit_money_fund_income()
    # income = 100000 * 0.2229 / 10000 = 2.229 → 四舍五入 2.23
    assert result["credited"] == 1
    assert result["total_income"] == 2.23
    name, params = svc._client.rpc_calls[0]
    assert name == "credit_money_fund_income_atomic"
    assert params["p_income"] == 2.23
    assert params["p_income_date"] == "2026-01-09"
    # 份额由 RPC 从 lot 重算，应用层不再直接改 positions
    assert svc._client.rows["positions"][0]["quantity"] == 100000


def test_入账_同日重复入账按跳过处理(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": MONEY_FUND_CODE, "quantity": 100000},
    ]})
    svc._client.rpc_responses["credit_money_fund_income_atomic"] = {"result": "already_credited"}
    result = svc.credit_money_fund_income()
    assert result["credited"] == 0 and result["skipped"] == 1
    assert result["status"] == "ok"


def test_入账_缺少计息日_拒绝入账(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229", income_date=None)
    svc = PortfolioService()
    svc._client = FakeClient()
    with pytest.raises(RuntimeError, match="计息日"):
        svc.credit_money_fund_income()


def test_入账_份额为0_跳过(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": MONEY_FUND_CODE, "quantity": 0},
    ]})
    result = svc.credit_money_fund_income()
    assert result["credited"] == 0
    assert svc._client.rpc_calls == []


def test_入账_数据库不可用_抛错(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    svc = PortfolioService()
    with pytest.raises(RuntimeError, match="数据库不可用"):
        svc.credit_money_fund_income()


# ==================== _get_position：查询持仓 ====================


def test_get_position_有持仓_返回行(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": "110020", "quantity": 100},
    ]})
    pos = svc._get_position("u1", "110020")
    assert pos["id"] == "p1"


def test_get_position_无持仓_返回None(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient()
    assert svc._get_position("u1", "110020") is None


def test_get_position_数据库不可用_返回None(monkeypatch):
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    assert PortfolioService()._get_position("u1", "110020") is None


# ==================== _ensure_account：确保账户存在 ====================


def test_ensure_account_已有账户_直接返回(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"accounts": [
        {"id": "a1", "user_id": "u1", "cash": 100000.0, "frozen_cash": 0},
    ]})
    monkeypatch.setattr(PortfolioService, "_auto_invest_money_fund", lambda self, uid: None)
    account = svc._ensure_account("u1")
    assert account["id"] == "a1"


def test_ensure_account_新账户_插入并触发自动申购(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient()
    calls = []
    monkeypatch.setattr(PortfolioService, "_auto_invest_money_fund", lambda self, uid: calls.append(uid))
    account = svc._ensure_account("u1")
    assert account["cash"] == 100000.0
    assert calls == ["u1"]
    assert svc._client.rows["accounts"][0]["user_id"] == "u1"


def test_ensure_account_数据库不可用_抛错(monkeypatch):
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    with pytest.raises(RuntimeError, match="数据库不可用"):
        PortfolioService()._ensure_account("u1")


# ==================== list_positions：持仓列表 ====================


def test_list_positions_数据库不可用_返回空(monkeypatch):
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    assert PortfolioService().list_positions("u1") == {
        "total": 0, "items": [], "total_pnl": 0, "total_position_value": 0,
    }


def test_list_positions_不含行情(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": "110020", "fund_name": "易方达", "quantity": 100, "cost_price": 1.5},
    ]})
    result = svc.list_positions("u1", include_quote=False)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["market_price"] is None
    assert item["cost_value"] == 150.0
    assert item["pnl"] == 0


def test_list_positions_含行情_货基特殊估值(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": MONEY_FUND_CODE, "fund_name": "天弘余额宝",
         "quantity": 100500, "cost_price": 1.0, "principal": 100000},
    ]})
    result = svc.list_positions("u1", include_quote=True)
    item = result["items"][0]
    assert item["market_price"] == 1.0
    assert item["market_value"] == 100500.0
    assert item["pnl"] == 500.0


def test_list_positions_含行情_非货基查净值(monkeypatch):
    _patch_latest_nav_batch(monkeypatch, {"110020": Decimal("2.0")})
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": "110020", "fund_name": "易方达", "quantity": 100, "cost_price": 1.5},
    ]})
    result = svc.list_positions("u1", include_quote=True)
    item = result["items"][0]
    assert item["market_price"] == 2.0
    assert item["market_value"] == 200.0
    assert item["pnl"] == 50.0


# ==================== account_summary：账户概况 ====================


def test_account_summary_正常_汇总现金冻结与持仓市值(monkeypatch):
    svc = PortfolioService()
    monkeypatch.setattr(PortfolioService, "_ensure_account", lambda self, uid: {"id": "a1"})
    monkeypatch.setattr(PortfolioService, "_auto_invest_money_fund", lambda self, uid: None)
    monkeypatch.setattr(PortfolioService, "get_account", lambda self, uid: {"cash": 90000.0, "frozen_cash": 10000.0})
    monkeypatch.setattr(PortfolioService, "list_positions",
                        lambda self, uid, include_quote=True: {"total": 1, "total_position_value": 20000.0})
    monkeypatch.setattr(PortfolioService, "_settling_cash", lambda self, uid: Decimal("5000.00"))
    result = svc.account_summary("u1")
    assert result["cash"] == 90000.0
    assert result["frozen_cash"] == 10000.0
    assert result["settling_cash"] == 5000.0
    assert result["position_value"] == 20000.0
    # 在途赎回款算资产：现金 9w + 冻结 1w + 在途 5k + 持仓 2w
    assert result["total_assets"] == 125000.0
    assert result["total_pnl"] == 25000.0
    assert result["position_count"] == 1


def test_account_summary_无账户_返回初始默认(monkeypatch):
    svc = PortfolioService()
    monkeypatch.setattr(PortfolioService, "_ensure_account", lambda self, uid: None)
    monkeypatch.setattr(PortfolioService, "_auto_invest_money_fund", lambda self, uid: None)
    monkeypatch.setattr(PortfolioService, "get_account", lambda self, uid: None)
    result = svc.account_summary("u1")
    assert result["cash"] == 100000.0
    assert result["total_assets"] == 100000.0
    assert result["position_count"] == 0


def test_账户概况_在途赎回款只统计settling卖单(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"trade_orders": [
        {"user_id": "u1", "direction": "sell", "status": "settling", "net_amount": 500.0},
        {"user_id": "u1", "direction": "sell", "status": "settling", "net_amount": 250.5},
        {"user_id": "u1", "direction": "sell", "status": "pending", "net_amount": 300.0},
        {"user_id": "u1", "direction": "buy", "status": "settling", "net_amount": 999.0},
        {"user_id": "u2", "direction": "sell", "status": "settling", "net_amount": 777.0},
    ]})
    assert svc._settling_cash("u1") == Decimal("750.50")


# ==================== query_trade_flow：交易流水 ====================


def test_query_trade_flow_正常(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"trade_flow": [
        {"id": "f1", "user_id": "u1", "fund_code": "110020", "direction": "buy", "trade_time": "2026-01-05T10:00:00"},
        {"id": "f2", "user_id": "u1", "fund_code": "110020", "direction": "sell", "trade_time": "2026-01-06T10:00:00"},
    ]})
    result = svc.query_trade_flow("u1")
    assert result["total"] == 2
    assert len(result["items"]) == 2
    assert result["total_pages"] == 1


def test_query_trade_flow_按基金和方向过滤(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"trade_flow": [
        {"id": "f1", "user_id": "u1", "fund_code": "110020", "direction": "buy", "trade_time": "x"},
        {"id": "f2", "user_id": "u1", "fund_code": "110020", "direction": "sell", "trade_time": "x"},
        {"id": "f3", "user_id": "u1", "fund_code": "001595", "direction": "buy", "trade_time": "x"},
    ]})
    result = svc.query_trade_flow("u1", fund_code="110020", direction="buy")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "f1"


def test_query_trade_flow_数据库不可用_返回空(monkeypatch):
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    result = PortfolioService().query_trade_flow("u1")
    assert result["total"] == 0
    assert result["items"] == []


# ==================== get_daily_returns：每日收益 ====================


def test_get_daily_returns_有快照_计算日收益率(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"account_snapshots": [
        {"user_id": "u1", "snapshot_date": "2026-01-05", "total_assets": 100000, "cash": 100000, "position_value": 0, "total_pnl": 0, "total_return_rate": 0},
        {"user_id": "u1", "snapshot_date": "2026-01-06", "total_assets": 101000, "cash": 100000, "position_value": 1000, "total_pnl": 1000, "total_return_rate": 0.01},
    ]})
    result = svc.get_daily_returns("u1")
    items = result["items"]
    assert len(items) == 2
    assert items[0]["date"] == "2026-01-05"
    assert items[0]["daily_return"] == 0.0
    assert items[1]["date"] == "2026-01-06"
    assert items[1]["daily_return"] == 0.01


def test_get_daily_returns_数据库不可用_返回空(monkeypatch):
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    assert PortfolioService().get_daily_returns("u1") == {"items": []}


# ==================== take_snapshot：每日快照 ====================


def test_take_snapshot_新建(monkeypatch):
    monkeypatch.setattr(PortfolioService, "account_summary",
                        lambda self, uid: {"total_assets": 100000.0, "cash": 100000.0, "position_value": 0, "total_pnl": 0, "total_return_rate": 0})
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.take_snapshot("u1", snapshot_date=date(2026, 1, 5))
    assert result["success"] is True
    assert len(svc._client.rows["account_snapshots"]) == 1
    assert svc._client.rows["account_snapshots"][0]["snapshot_date"] == "2026-01-05"


def test_take_snapshot_已存在则更新(monkeypatch):
    monkeypatch.setattr(PortfolioService, "account_summary",
                        lambda self, uid: {"total_assets": 101000.0, "cash": 100000.0, "position_value": 1000, "total_pnl": 1000, "total_return_rate": 0.01})
    svc = PortfolioService()
    svc._client = FakeClient({"account_snapshots": [
        {"id": "s1", "user_id": "u1", "snapshot_date": "2026-01-05", "total_assets": 100000.0},
    ]})
    result = svc.take_snapshot("u1", snapshot_date=date(2026, 1, 5))
    assert result["success"] is True
    assert len(svc._client.rows["account_snapshots"]) == 1
    assert svc._client.rows["account_snapshots"][0]["total_assets"] == 101000.0


def test_take_snapshot_写入在途赎回款(monkeypatch):
    monkeypatch.setattr(PortfolioService, "account_summary",
                        lambda self, uid: {"total_assets": 105000.0, "cash": 100000.0,
                                           "settling_cash": 5000.0, "position_value": 0,
                                           "total_pnl": 5000.0, "total_return_rate": 0.05})
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.take_snapshot("u1", snapshot_date=date(2026, 1, 5))
    row = svc._client.rows["account_snapshots"][0]
    assert row["settling_cash"] == 5000.0
    assert result["data"]["settling_cash"] == 5000.0


# ==================== set_auto_invest_config：余额理财开关 ====================


def test_set_auto_invest_config_正常(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"accounts": [
        {"id": "a1", "user_id": "u1", "cash": 100000.0, "frozen_cash": 0},
    ]})
    monkeypatch.setattr(PortfolioService, "_ensure_account", lambda self, uid: {"id": "a1"})
    result = svc.set_auto_invest_config("u1", enabled=True, reserve=5000)
    assert result["enabled"] is True
    assert result["reserve"] == 5000.0
    assert svc._client.rows["accounts"][0]["auto_invest_enabled"] is True
    assert svc._client.rows["accounts"][0]["auto_invest_reserve"] == 5000


def test_set_auto_invest_config_数据库不可用_抛错(monkeypatch):
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    with pytest.raises(RuntimeError, match="数据库不可用"):
        PortfolioService().set_auto_invest_config("u1", True, 5000)


# ==================== _auto_invest_money_fund：自动申购货基 ====================


def test_auto_invest_已持仓_跳过(monkeypatch):
    calls = []
    monkeypatch.setattr(PortfolioService, "_get_position", lambda self, uid, code: {"id": "p1"})
    monkeypatch.setattr(PortfolioService, "get_auto_invest_config", lambda self, uid: calls.append("config"))
    monkeypatch.setattr(PortfolioService, "apply_purchase", lambda self, uid, code, amt: calls.append("purchase"))
    PortfolioService()._auto_invest_money_fund("u1")
    assert calls == []


def test_auto_invest_未开启_跳过(monkeypatch):
    calls = []
    monkeypatch.setattr(PortfolioService, "_get_position", lambda self, uid, code: None)
    monkeypatch.setattr(PortfolioService, "get_auto_invest_config", lambda self, uid: {"enabled": False, "reserve": 0.0})
    monkeypatch.setattr(PortfolioService, "get_account", lambda self, uid: calls.append("account"))
    PortfolioService()._auto_invest_money_fund("u1")
    assert calls == []


def test_auto_invest_现金不超预留_跳过(monkeypatch):
    calls = []
    monkeypatch.setattr(PortfolioService, "_get_position", lambda self, uid, code: None)
    monkeypatch.setattr(PortfolioService, "get_auto_invest_config", lambda self, uid: {"enabled": True, "reserve": 10000.0})
    monkeypatch.setattr(PortfolioService, "get_account", lambda self, uid: {"cash": 8000.0})
    monkeypatch.setattr(PortfolioService, "apply_purchase", lambda self, uid, code, amt: calls.append("purchase"))
    PortfolioService()._auto_invest_money_fund("u1")
    assert calls == []


def test_auto_invest_可投资_申购并确认(monkeypatch):
    calls = []
    monkeypatch.setattr(PortfolioService, "_get_position", lambda self, uid, code: None)
    monkeypatch.setattr(PortfolioService, "get_auto_invest_config", lambda self, uid: {"enabled": True, "reserve": 10000.0})
    monkeypatch.setattr(PortfolioService, "get_account", lambda self, uid: {"cash": 50000.0})
    monkeypatch.setattr(PortfolioService, "apply_purchase",
                        lambda self, uid, code, amt: (calls.append(("purchase", amt)) or {"success": True, "message": "ok"}))
    monkeypatch.setattr(PortfolioService, "_confirm_money_fund_order", lambda self, uid: calls.append("confirm"))
    PortfolioService()._auto_invest_money_fund("u1")
    assert calls == [("purchase", Decimal("40000")), "confirm"]


# ==================== apply_purchase / apply_redeem：下单 RPC 映射 ====================
#
# 资金冻结、单日额度、可赎份额、幂等都由 PostgreSQL RPC 在事务内完成
# （行为用例见《订单确认-实现方案》§5.2），服务层只负责：
#   业务前置校验（白名单/ETF/申购状态/金额上下限）→ 算日期与费用 → 调 RPC → 映射结果。

RULE = {
    "fund_code": "110020",
    "fund_name": "易方达沪深300ETF联接A",
    "fund_type": "of",
    "confirm_delay": 1,
    "redeem_settle_delay": 3,
    "redeem_available_delay": 0,
    "min_purchase_amount": 10.0,
}


class FakeFeeSvc:
    """替身：get_fee_rule / get_fee_rules_batch 返回固定规则。"""

    def __init__(self, rule):
        self.rule = rule

    def get_fee_rule(self, fund_code):
        return self.rule

    def get_fee_rules_batch(self, fund_codes):
        return {code: self.rule for code in fund_codes}


def _patch_purchase_common(monkeypatch, rule=None, account=None):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(rule or RULE))
    monkeypatch.setattr(portfolio_service, "_beijing_now", lambda: datetime(2026, 1, 5, 10, 0))
    monkeypatch.setattr(PortfolioService, "_is_trading_day", staticmethod(lambda d: True))
    monkeypatch.setattr(PortfolioService, "_next_trading_day",
                        staticmethod(lambda d: d + timedelta(days=1)))
    _patch_latest_nav(monkeypatch, {}, default=Decimal("1.5"))
    monkeypatch.setattr(PortfolioService, "_calc_purchase_fee",
                        lambda self, code, amt, rule=None: {"fee": Decimal("1.5"),
                                                            "net_amount": Decimal("998.5")})
    monkeypatch.setattr(PortfolioService, "_get_fund_name", lambda self, code, rule=None: "易方达")
    monkeypatch.setattr(PortfolioService, "_get_risk_warning", lambda self, uid, code: None)
    monkeypatch.setattr(PortfolioService, "get_account",
                        lambda self, uid: account if account is not None
                        else {"cash": 100000.0, "frozen_cash": 0})


def test_申购_不支持基金(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(None))
    result = PortfolioService().apply_purchase("u1", "999999", Decimal("1000"))
    assert result["success"] is False
    assert "暂不支持基金" in result["message"]


def test_申购_场内ETF拦截(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(dict(RULE, fund_type="etf")))
    result = PortfolioService().apply_purchase("u1", "510300", Decimal("1000"))
    assert result["success"] is False
    assert "场内 ETF" in result["message"]


@pytest.mark.parametrize("状态", ["暂停申购", "封闭期"])
def test_申购_不可申购状态被拒且不调RPC(monkeypatch, 状态):
    _patch_purchase_common(monkeypatch, rule=dict(RULE, subscribe_status=状态))
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.apply_purchase("u1", "110020", Decimal("1000"))
    assert result["success"] is False
    assert 状态 in result["message"]
    assert svc._client.rpc_calls == []


def test_申购_限大额但上限为空被拒(monkeypatch):
    rule = dict(RULE, subscribe_status="限大额", max_purchase_amount=None)
    _patch_purchase_common(monkeypatch, rule=rule)
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.apply_purchase("u1", "110020", Decimal("1000"))
    assert result["success"] is False
    assert "限额信息暂不可用" in result["message"]
    assert svc._client.rpc_calls == []


def test_申购_低于最低金额被拒(monkeypatch):
    _patch_purchase_common(monkeypatch)
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.apply_purchase("u1", "110020", Decimal("5"))
    assert result["success"] is False
    assert "最低申购金额" in result["message"]


def test_申购_成功_参数与日期口径(monkeypatch):
    """T 日 = 受理日（也是成交净值日），确认日 = T+confirm_delay。"""
    _patch_purchase_common(monkeypatch, rule=dict(RULE, max_purchase_amount=5000.0))
    svc = PortfolioService()
    svc._client = FakeClient()
    svc._client.rpc_responses["place_purchase_order"] = {
        "result": "placed", "order": {"id": "o1", "status": "pending"},
    }
    result = svc.apply_purchase("u1", "110020", Decimal("1000"), client_order_id="ck-1")

    assert result["success"] is True
    data = result["data"]
    assert data["trade_date"] == "2026-01-05"
    assert data["confirm_date"] == "2026-01-06"
    assert data["available_date"] == "2026-01-06"  # redeem_available_delay=0
    assert data["order_id"] == "o1" and data["status"] == "pending"
    assert data["cash_remaining"] == 100000.0 and data["frozen_cash"] == 0

    name, params = svc._client.rpc_calls[0]
    assert name == "place_purchase_order"
    assert params["p_amount"] == 1000.0 and params["p_fee"] == 1.5
    assert params["p_net_amount"] == 998.5
    assert params["p_accepted_date"] == "2026-01-05"
    assert params["p_max_purchase_amount"] == 5000.0
    assert params["p_client_order_id"] == "ck-1"
    assert params["p_fee_snapshot"]["confirm_delay"] == 1


def test_申购_幂等命中返回既有订单(monkeypatch):
    _patch_purchase_common(monkeypatch)
    svc = PortfolioService()
    svc._client = FakeClient()
    svc._client.rpc_responses["place_purchase_order"] = {
        "result": "existing", "order": {"id": "o9", "status": "pending"},
    }
    result = svc.apply_purchase("u1", "110020", Decimal("1000"), client_order_id="ck-1")
    assert result["success"] is True
    assert "重复提交" in result["message"] and "o9" in result["message"]


@pytest.mark.parametrize("rpc_result,片段", [
    ("insufficient_cash", "可用现金不足"),
    ("limit_exceeded", "单日累计申购上限"),
    ("idempotency_conflict", "幂等键"),
])
def test_申购_RPC失败结果映射(monkeypatch, rpc_result, 片段):
    _patch_purchase_common(monkeypatch)
    svc = PortfolioService()
    svc._client = FakeClient()
    svc._client.rpc_responses["place_purchase_order"] = {
        "result": rpc_result, "cash": 100.0, "used": 900.0, "limit": 1000.0,
    }
    result = svc.apply_purchase("u1", "110020", Decimal("1000"))
    assert result["success"] is False
    assert 片段 in result["message"]


def _patch_redeem_common(monkeypatch, rule=None):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(rule or RULE))
    monkeypatch.setattr(portfolio_service, "_beijing_now", lambda: datetime(2026, 1, 5, 10, 0))
    monkeypatch.setattr(PortfolioService, "_is_trading_day", staticmethod(lambda d: True))
    monkeypatch.setattr(PortfolioService, "_next_trading_day",
                        staticmethod(lambda d: d + timedelta(days=1)))
    monkeypatch.setattr(PortfolioService, "_get_fund_name", lambda self, code, rule=None: "易方达")


def test_赎回_成功_到账日与RPC参数(monkeypatch):
    _patch_redeem_common(monkeypatch)
    svc = PortfolioService()
    svc._client = FakeClient()
    svc._client.rpc_responses["place_redeem_order"] = {
        "result": "placed", "order": {"id": "s1", "status": "pending"},
    }
    result = svc.apply_redeem("u1", "110020", Decimal("100"), client_order_id="rk-1")

    assert result["success"] is True
    data = result["data"]
    assert data["trade_date"] == "2026-01-05"
    assert data["settle_date"] == "2026-01-08"  # T + 3 个交易日
    assert data["order_id"] == "s1"

    name, params = svc._client.rpc_calls[0]
    assert name == "place_redeem_order"
    assert params["p_quantity"] == 100.0
    assert params["p_client_order_id"] == "rk-1"
    assert params["p_settle_date"] == "2026-01-08"


@pytest.mark.parametrize("rpc_result,片段", [
    ("pending_purchase", "存在待确认的申购订单"),
    ("insufficient_shares", "可赎份额不足"),
    ("idempotency_conflict", "幂等键"),
])
def test_赎回_RPC失败结果映射(monkeypatch, rpc_result, 片段):
    _patch_redeem_common(monkeypatch)
    svc = PortfolioService()
    svc._client = FakeClient()
    svc._client.rpc_responses["place_redeem_order"] = {"result": rpc_result, "available": -10}
    result = svc.apply_redeem("u1", "110020", Decimal("100"))
    assert result["success"] is False
    assert 片段 in result["message"]


def test_赎回_幂等命中返回既有订单(monkeypatch):
    _patch_redeem_common(monkeypatch)
    svc = PortfolioService()
    svc._client = FakeClient()
    svc._client.rpc_responses["place_redeem_order"] = {
        "result": "existing", "order": {"id": "s9", "status": "pending"},
    }
    result = svc.apply_redeem("u1", "110020", Decimal("100"), client_order_id="rk-1")
    assert result["success"] is True
    assert "重复提交" in result["message"] and "s9" in result["message"]


# ==================== confirm_pending_orders：薄壳委派 Runner ====================


def test_确认批量_委派给OrderConfirmService(monkeypatch):
    """旧多表写实现已删除：薄壳只负责委派 Runner（策略见《执行机制》§3.5）。"""
    from server.services import order_confirm_service as ocs_mod

    captured = {}

    class FakeRunner:
        def run(self, trigger="manual"):
            captured["trigger"] = trigger
            return {"status": "ok", "scanned": 0, "processed": 0, "skipped": 0}

    monkeypatch.setattr(ocs_mod, "OrderConfirmService", FakeRunner)
    result = PortfolioService().confirm_pending_orders()
    assert result["status"] == "ok"
    assert captured["trigger"] == "manual"


# ==================== 架构守卫：交易链路不触网取净值 ====================


def test_交易服务不再直接调用akshare取净值():
    """净值只能经 FundNavService 读 DB（存储设计 §4.9）。

    守卫范围限定在 portfolio_service 自身：`finance_api_service` 仍保留目录外代码
    （场内 ETF）的上游回退，全仓 grep 会误报（接入方案 §4.11 的实现偏离说明）。
    """
    import inspect

    src = inspect.getsource(portfolio_service)
    assert "fund_open_fund_info_em" not in src
    assert "import akshare" not in src
