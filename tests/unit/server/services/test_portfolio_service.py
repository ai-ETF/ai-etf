"""portfolio_service 单元测试：场外基金持仓交易服务（分批）。

模块名称：server/services/portfolio_service.py
所测功能（分批添加）：
  - 时间工具：_parse_time（时区归一）、_is_before_cutoff（15:00 截止）、
    _is_trading_day（交易日，需 akshare 替身）、_next_trading_day（下一交易日）
测试方法：纯函数直测 + sys.modules 注入 akshare 替身（避免真实联网/重导入），全程不联网、不连 Supabase。
"""
import json
import sys
import types
import urllib.request
from datetime import date, datetime
from decimal import Decimal

import pytest

import server.services.finance_api_service as finance_api_mod
import server.services.fund_fee_service as fee_svc_mod
import server.services.fund_risk_service as fund_risk_service_mod
import server.services.portfolio_service as portfolio_service
import server.services.risk_service as risk_service_mod
from server.services.portfolio_service import (
    MONEY_FUND_CODE,
    PortfolioService,
    _parse_time,
)


# ==================== akshare 替身 ====================


class _FakeTradeCalendar:
    """模拟 akshare.tool_trade_date_hist_sina() 返回的 DataFrame（支持 iterrows + 下标取值）。"""

    def __init__(self, trade_dates):
        self._rows = [{"trade_date": d} for d in trade_dates]

    def iterrows(self):
        for i, row in enumerate(self._rows):
            yield i, row


def _patch_trade_calendar(monkeypatch, trade_dates):
    """把 akshare 模块替换为只含交易日历的假模块。"""
    mod = types.ModuleType("akshare")
    mod.tool_trade_date_hist_sina = lambda: _FakeTradeCalendar(trade_dates)
    monkeypatch.setitem(sys.modules, "akshare", mod)


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


def test_交易日_日历命中(monkeypatch):
    _patch_trade_calendar(monkeypatch, ["2026-01-05", "2026-01-06"])
    assert PortfolioService._is_trading_day(date(2026, 1, 5)) is True


def test_非交易日_日历未命中(monkeypatch):
    _patch_trade_calendar(monkeypatch, ["2026-01-05", "2026-01-06"])
    assert PortfolioService._is_trading_day(date(2026, 1, 10)) is False


def test_akshare异常_回退工作日判断(monkeypatch):
    mod = types.ModuleType("akshare")

    def _boom():
        raise RuntimeError("network fail")

    mod.tool_trade_date_hist_sina = _boom
    monkeypatch.setitem(sys.modules, "akshare", mod)
    assert PortfolioService._is_trading_day(date(2026, 1, 5)) is True   # 周一
    assert PortfolioService._is_trading_day(date(2026, 1, 10)) is False  # 周六


# ==================== _next_trading_day：下一交易日 ====================


def test_next_trading_day_返回下一个交易日(monkeypatch):
    _patch_trade_calendar(monkeypatch, ["2026-01-06"])
    assert PortfolioService._next_trading_day(date(2026, 1, 5)) == date(2026, 1, 6)


def test_next_trading_day_无交易日时返回次日(monkeypatch):
    _patch_trade_calendar(monkeypatch, [])
    assert PortfolioService._next_trading_day(date(2026, 1, 5)) == date(2026, 1, 6)


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


class FakeFinanceApi:
    def __init__(self, name=None):
        self._name = name

    def query_spot(self, fund_code):
        if self._name is None:
            return None
        return {"name": self._name}


class _FakeNavRow:
    def __init__(self, nav):
        self._nav = nav

    def get(self, key, default=None):
        return self._nav if key == "单位净值" else default


class _FakeNavDf:
    def __init__(self, nav):
        self._nav = nav
        self.empty = False

    @property
    def iloc(self):
        return self

    def __getitem__(self, idx):
        return _FakeNavRow(self._nav)


def _patch_risk_services(monkeypatch, profile, fund_risk):
    FakeRiskService.profile = profile
    FakeFundRiskService.risk_profile = fund_risk
    monkeypatch.setattr(risk_service_mod, "RiskService", FakeRiskService)
    monkeypatch.setattr(fund_risk_service_mod, "FundRiskService", FakeFundRiskService)


def _patch_akshare_nav(monkeypatch, nav):
    mod = types.ModuleType("akshare")

    def _fund_open_fund_info_em(symbol=None, indicator=None):
        if nav is None:
            return None
        return _FakeNavDf(nav)

    mod.fund_open_fund_info_em = _fund_open_fund_info_em
    monkeypatch.setitem(sys.modules, "akshare", mod)


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


# ==================== _get_nav：净值 ====================


def test_get_nav_货币基金_恒为1():
    assert PortfolioService()._get_nav(MONEY_FUND_CODE) == Decimal("1.0000")


def test_get_nav_非货基_返回接口净值(monkeypatch):
    _patch_akshare_nav(monkeypatch, nav="1.2345")
    assert PortfolioService()._get_nav("110020") == Decimal("1.2345")


def test_get_nav_接口返回空_返回None(monkeypatch):
    _patch_akshare_nav(monkeypatch, nav=None)
    assert PortfolioService()._get_nav("110020") is None


def test_get_nav_接口异常_返回None(monkeypatch):
    mod = types.ModuleType("akshare")

    def _boom(symbol=None, indicator=None):
        raise RuntimeError("fail")

    mod.fund_open_fund_info_em = _boom
    monkeypatch.setitem(sys.modules, "akshare", mod)
    assert PortfolioService()._get_nav("110020") is None


# ==================== _get_fund_name：基金名称 ====================


def test_fund_name_优先读rule():
    assert PortfolioService()._get_fund_name("110020", rule={"fund_name": "易方达"}) == "易方达"


def test_fund_name_从费率规则查(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeService(fund_name="费率名"))
    assert PortfolioService()._get_fund_name("110020") == "费率名"


def test_fund_name_从行情兜底(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeService(fund_name=None))
    monkeypatch.setattr(finance_api_mod, "FinanceApiService", lambda: FakeFinanceApi(name="行情名"))
    assert PortfolioService()._get_fund_name("110020") == "行情名"


def test_fund_name_全部无_返回基金代码(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeService(fund_name=None))
    monkeypatch.setattr(finance_api_mod, "FinanceApiService", lambda: FakeFinanceApi(name=None))
    assert PortfolioService()._get_fund_name("110020") == "110020"


# ==================== 富 FakeClient（多表内存替身） ====================


class FakeResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


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
        return True


class FakeClient:
    """内存多表替身：rows 为 {表名: [行 dict]}，不产生任何网络/DB IO。"""

    def __init__(self, rows=None, error=None):
        self.rows = rows or {}
        self.error = error

    def table(self, name):
        return FakeQuery(self, name)


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


def _patch_per10k(monkeypatch, value):
    monkeypatch.setattr(PortfolioService, "_money_fund_per10k_income", lambda self: Decimal(value))


def test_入账_无持仓_跳过(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.credit_money_fund_income()
    assert result["status"] == "ok"
    assert result["credited"] == 0


def test_入账_有持仓_折算份额并更新(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": MONEY_FUND_CODE, "quantity": 100000, "principal": 100000},
    ]})
    result = svc.credit_money_fund_income()
    # income = 100000 * 0.2229 / 10000 = 2.229 → 四舍五入 2.23
    assert result["credited"] == 1
    assert result["total_income"] == 2.23
    assert svc._client.rows["positions"][0]["quantity"] == 100002.23


def test_入账_份额为0_跳过(monkeypatch):
    _patch_per10k(monkeypatch, "0.2229")
    svc = PortfolioService()
    svc._client = FakeClient({"positions": [
        {"id": "p1", "user_id": "u1", "fund_code": MONEY_FUND_CODE, "quantity": 0},
    ]})
    result = svc.credit_money_fund_income()
    assert result["credited"] == 0


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
    monkeypatch.setattr(PortfolioService, "_get_nav", lambda self, code: Decimal("2.0"))
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
    result = svc.account_summary("u1")
    assert result["cash"] == 90000.0
    assert result["frozen_cash"] == 10000.0
    assert result["position_value"] == 20000.0
    assert result["total_assets"] == 120000.0
    assert result["total_pnl"] == 20000.0
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


# ==================== apply_purchase：申购 ====================

RULE = {
    "fund_code": "110020",
    "fund_name": "易方达沪深300ETF联接A",
    "fund_type": "of",
    "confirm_delay": 1,
    "min_purchase_amount": 10.0,
    "redeem_settle_delay": 3,
}


class FakeFeeSvc:
    """替身：get_fee_rule / get_fee_rules_batch 返回固定规则。"""

    def __init__(self, rule):
        self.rule = rule

    def get_fee_rule(self, fund_code):
        return self.rule

    def get_fee_rules_batch(self, fund_codes):
        return {code: self.rule for code in fund_codes}


def _patch_purchase_common(monkeypatch, rule, account, risk_warning=None):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(rule))
    monkeypatch.setattr(portfolio_service, "_beijing_now", lambda: datetime(2026, 1, 5, 10, 0))
    monkeypatch.setattr(PortfolioService, "_is_trading_day", staticmethod(lambda d: True))
    monkeypatch.setattr(PortfolioService, "_next_trading_day", staticmethod(lambda d: date(2026, 1, 6)))
    monkeypatch.setattr(PortfolioService, "_get_nav", lambda self, code: Decimal("1.5"))
    monkeypatch.setattr(PortfolioService, "_calc_purchase_fee",
                        lambda self, code, amt, rule=None: {"fee": Decimal("1.5"), "net_amount": Decimal("998.5")})
    monkeypatch.setattr(PortfolioService, "_get_fund_name", lambda self, code, rule=None: "易方达")
    monkeypatch.setattr(PortfolioService, "_get_risk_warning", lambda self, uid, code: risk_warning)
    monkeypatch.setattr(PortfolioService, "_ensure_account", lambda self, uid: account)


def test_申购_不支持基金(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(None))
    result = PortfolioService().apply_purchase("u1", "999999", Decimal("1000"))
    assert result["success"] is False
    assert "暂不支持基金" in result["message"]


def test_申购_场内ETF拦截(monkeypatch):
    etf_rule = dict(RULE, fund_type="etf")
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(etf_rule))
    result = PortfolioService().apply_purchase("u1", "510300", Decimal("1000"))
    assert result["success"] is False
    assert "场内 ETF" in result["message"]


def test_申购_余额不足(monkeypatch):
    account = {"id": "a1", "user_id": "u1", "cash": 500.0, "frozen_cash": 0}
    _patch_purchase_common(monkeypatch, RULE, account)
    svc = PortfolioService()
    svc._client = FakeClient({"accounts": [dict(account)]})
    result = svc.apply_purchase("u1", "110020", Decimal("1000"))
    assert result["success"] is False
    assert "可用现金不足" in result["message"]


def test_申购_正常_冻结资金并写订单(monkeypatch):
    account = {"id": "a1", "user_id": "u1", "cash": 100000.0, "frozen_cash": 0}
    _patch_purchase_common(monkeypatch, RULE, account)
    svc = PortfolioService()
    svc._client = FakeClient({"accounts": [dict(account)]})
    result = svc.apply_purchase("u1", "110020", Decimal("1000"))
    assert result["success"] is True
    assert result["data"]["status"] == "pending"
    assert result["data"]["cash_remaining"] == 99000.0
    assert result["data"]["frozen_cash"] == 1000.0
    assert svc._client.rows["accounts"][0]["cash"] == 99000.0
    assert svc._client.rows["accounts"][0]["frozen_cash"] == 1000.0
    assert len(svc._client.rows["trade_orders"]) == 1


def test_申购_携带风险提示(monkeypatch):
    account = {"id": "a1", "user_id": "u1", "cash": 100000.0, "frozen_cash": 0}
    _patch_purchase_common(monkeypatch, RULE, account, risk_warning={"level": "info"})
    svc = PortfolioService()
    svc._client = FakeClient({"accounts": [dict(account)]})
    result = svc.apply_purchase("u1", "110020", Decimal("1000"))
    assert result["success"] is True
    assert result["risk_warning"] == {"level": "info"}


# ==================== apply_redeem：赎回 ====================


def _patch_redeem_common(monkeypatch, rule, position, pending_buys=(), pending_sells=()):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(rule))
    monkeypatch.setattr(portfolio_service, "_beijing_now", lambda: datetime(2026, 1, 5, 10, 0))
    monkeypatch.setattr(PortfolioService, "_is_trading_day", staticmethod(lambda d: True))
    monkeypatch.setattr(PortfolioService, "_next_trading_day", staticmethod(lambda d: date(2026, 1, 6)))
    monkeypatch.setattr(PortfolioService, "_get_fund_name", lambda self, code, rule=None: "易方达")
    monkeypatch.setattr(PortfolioService, "_get_position", lambda self, uid, code: position)


def test_赎回_不支持基金(monkeypatch):
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(None))
    result = PortfolioService().apply_redeem("u1", "999999", Decimal("100"))
    assert result["success"] is False
    assert "暂不支持基金" in result["message"]


def test_赎回_未持有基金(monkeypatch):
    _patch_redeem_common(monkeypatch, RULE, position=None)
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.apply_redeem("u1", "110020", Decimal("100"))
    assert result["success"] is False
    assert "未持有基金" in result["message"]


def test_赎回_份额不足(monkeypatch):
    position = {"id": "p1", "user_id": "u1", "fund_code": "110020", "quantity": 50, "cost_price": 1.5}
    _patch_redeem_common(monkeypatch, RULE, position)
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.apply_redeem("u1", "110020", Decimal("100"))
    assert result["success"] is False
    assert "可赎份额不足" in result["message"]


def test_赎回_存在待确认申购_拒绝(monkeypatch):
    position = {"id": "p1", "user_id": "u1", "fund_code": "110020", "quantity": 200, "cost_price": 1.5}
    _patch_redeem_common(monkeypatch, RULE, position)
    svc = PortfolioService()
    svc._client = FakeClient({"trade_orders": [
        {"id": "o1", "user_id": "u1", "fund_code": "110020", "direction": "buy", "status": "pending"},
    ]})
    result = svc.apply_redeem("u1", "110020", Decimal("100"))
    assert result["success"] is False
    assert "待确认的申购" in result["message"]


def test_赎回_正常_写卖出订单(monkeypatch):
    position = {"id": "p1", "user_id": "u1", "fund_code": "110020", "quantity": 200, "cost_price": 1.5}
    _patch_redeem_common(monkeypatch, RULE, position)
    svc = PortfolioService()
    svc._client = FakeClient()
    result = svc.apply_redeem("u1", "110020", Decimal("100"))
    assert result["success"] is True
    assert result["data"]["status"] == "pending"
    assert len(svc._client.rows["trade_orders"]) == 1
    assert svc._client.rows["trade_orders"][0]["direction"] == "sell"


# ==================== _confirm_one_order：单笔订单确认 ====================

BUY_ORDER = {
    "id": "o1", "user_id": "u1", "fund_code": "110020", "fund_name": "易方达",
    "direction": "buy", "amount": 1000.0, "price": 1.5, "quantity": 0.0, "fee": 1.5,
}

SELL_ORDER = {
    "id": "o1", "user_id": "u1", "fund_code": "110020", "fund_name": "易方达",
    "direction": "sell", "amount": 0.0, "price": 0.0, "quantity": 100.0, "fee": 0.0,
}


def test_确认_买入_建仓并解冻(monkeypatch):
    monkeypatch.setattr(PortfolioService, "_get_nav", lambda self, code: Decimal("1.5"))
    monkeypatch.setattr(PortfolioService, "_calc_purchase_fee",
                        lambda self, code, amt, rule=None: {"fee": Decimal("1.5"), "net_amount": Decimal("998.5")})
    monkeypatch.setattr(PortfolioService, "_next_trading_day", staticmethod(lambda d: date(2026, 1, 8)))
    svc = PortfolioService()
    svc._client = FakeClient({
        "accounts": [{"id": "a1", "user_id": "u1", "cash": 99000.0, "frozen_cash": 1000.0}],
        "positions": [],
        "trade_orders": [dict(BUY_ORDER)],
    })
    svc._confirm_one_order(dict(BUY_ORDER), date(2026, 1, 6), rule=RULE)
    assert svc._client.rows["accounts"][0]["frozen_cash"] == 0.0
    assert len(svc._client.rows["positions"]) == 1
    assert svc._client.rows["positions"][0]["quantity"] == 665.67
    assert len(svc._client.rows["trade_flow"]) == 1
    assert svc._client.rows["trade_orders"][0]["status"] == "completed"


def test_确认_买入_账户不存在_抛错(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"accounts": []})
    with pytest.raises(RuntimeError, match="账户不存在"):
        svc._confirm_one_order(dict(BUY_ORDER), date(2026, 1, 6), rule=RULE)


def test_确认_卖出_减仓并回款(monkeypatch):
    monkeypatch.setattr(PortfolioService, "_get_nav", lambda self, code: Decimal("1.5"))
    monkeypatch.setattr(PortfolioService, "_calc_redemption_fee", lambda self, code, amt, days, rule=None: Decimal("10.0"))
    svc = PortfolioService()
    svc._client = FakeClient({
        "accounts": [{"id": "a1", "user_id": "u1", "cash": 100000.0, "frozen_cash": 0}],
        "positions": [{"id": "p1", "user_id": "u1", "fund_code": "110020", "quantity": 200, "cost_price": 1.5, "confirm_date": "2026-01-01"}],
        "trade_orders": [dict(SELL_ORDER)],
    })
    svc._confirm_one_order(dict(SELL_ORDER), date(2026, 1, 6), rule=RULE)
    assert svc._client.rows["positions"][0]["quantity"] == 100.0
    assert svc._client.rows["accounts"][0]["cash"] == 100140.0
    assert len(svc._client.rows["trade_flow"]) == 1
    assert svc._client.rows["trade_orders"][0]["status"] == "completed"


def test_确认_卖出_持仓不存在_抛错(monkeypatch):
    svc = PortfolioService()
    svc._client = FakeClient({"positions": []})
    with pytest.raises(RuntimeError, match="持仓"):
        svc._confirm_one_order(dict(SELL_ORDER), date(2026, 1, 6), rule=RULE)


def test_确认_卖出_费率缺失_拒绝确认(monkeypatch):
    monkeypatch.setattr(PortfolioService, "_get_nav", lambda self, code: Decimal("1.5"))
    monkeypatch.setattr(PortfolioService, "_calc_redemption_fee", lambda self, code, amt, days, rule=None: None)
    svc = PortfolioService()
    svc._client = FakeClient({
        "positions": [{"id": "p1", "user_id": "u1", "fund_code": "110020", "quantity": 200, "cost_price": 1.5, "confirm_date": "2026-01-01"}],
    })
    with pytest.raises(RuntimeError, match="缺少赎回费率"):
        svc._confirm_one_order(dict(SELL_ORDER), date(2026, 1, 6), rule=RULE)


# ==================== confirm_pending_orders：批量确认 ====================


def test_确认批量_数据库不可用(monkeypatch):
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    result = PortfolioService().confirm_pending_orders()
    assert result["status"] == "error"


def test_确认批量_无待确认订单(monkeypatch):
    monkeypatch.setattr(portfolio_service, "_beijing_date", lambda: date(2026, 1, 6))
    monkeypatch.setattr(PortfolioService, "_is_trading_day", staticmethod(lambda d: True))
    svc = PortfolioService()
    svc._client = FakeClient({"trade_orders": []})
    result = svc.confirm_pending_orders()
    assert result["status"] == "ok"
    assert result["processed"] == 0


def test_确认批量_全部确认成功(monkeypatch):
    monkeypatch.setattr(portfolio_service, "_beijing_date", lambda: date(2026, 1, 6))
    monkeypatch.setattr(PortfolioService, "_is_trading_day", staticmethod(lambda d: True))
    confirmed = []
    monkeypatch.setattr(PortfolioService, "_confirm_one_order",
                        lambda self, order, today, rule=None: confirmed.append(order["id"]))
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(RULE))
    svc = PortfolioService()
    svc._client = FakeClient({"trade_orders": [
        {"id": "o1", "user_id": "u1", "fund_code": "110020", "status": "pending", "confirm_date": "2026-01-06"},
        {"id": "o2", "user_id": "u2", "fund_code": "110020", "status": "pending", "confirm_date": "2026-01-05"},
    ]})
    result = svc.confirm_pending_orders()
    assert result["processed"] == 2
    assert sorted(confirmed) == ["o1", "o2"]


def test_确认批量_失败订单标记failed(monkeypatch):
    monkeypatch.setattr(portfolio_service, "_beijing_date", lambda: date(2026, 1, 6))
    monkeypatch.setattr(PortfolioService, "_is_trading_day", staticmethod(lambda d: True))

    def _boom(order, today, rule=None):
        raise RuntimeError("confirm fail")

    monkeypatch.setattr(PortfolioService, "_confirm_one_order", _boom)
    monkeypatch.setattr(fee_svc_mod, "FundFeeService", lambda: FakeFeeSvc(RULE))
    svc = PortfolioService()
    svc._client = FakeClient({"trade_orders": [
        {"id": "o1", "user_id": "u1", "fund_code": "110020", "status": "pending", "confirm_date": "2026-01-05"},
    ]})
    result = svc.confirm_pending_orders()
    assert result["processed"] == 1
    assert svc._client.rows["trade_orders"][0]["status"] == "failed"
