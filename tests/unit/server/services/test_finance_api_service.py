"""finance_api_service 单元测试：纯函数、目录内搜索、K线、分时、详情/历史净值。

模块名称：server/services/finance_api_service.py

测试方法：纯函数直测；读 DB 的方法注入替身（`FakeFundNav` / `FakeFundMeta`）；
akshare 依赖的方法用 sys.modules 注入假 akshare 返回录制样本，全程离线、不联网。

2026-10-26：30 秒行情缓存下线，`query_spot` / `query_ranking` / `refresh_spot_cache`
/ 资金流 / 筛选 / 分类的用例随实现一并删除；新增「目录外代码 → `FundNotSupported`」
与「搜索只命中目录内基金」的守卫用例。
"""
import sys
import types
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

import server.services.finance_api_service as finance_api
from server.services.finance_api_service import FinanceApiService
from server.services.fund_meta_service import FundMeta
from server.sources.models import NavPoint


# ==================== 样本数据 ====================


def _nav_df(rows):
    """构造单位净值走势 DataFrame（列名同 akshare fund_open_fund_info_em 单位净值走势）。"""
    return pd.DataFrame([
        {"净值日期": d, "单位净值": nav, "日增长率": growth} for d, nav, growth in rows
    ])


def _acc_nav_df(rows):
    """构造累计净值走势 DataFrame（列名同 akshare 的累计净值走势）。"""
    return pd.DataFrame([{"净值日期": d, "累计净值": nav} for d, nav in rows])


def _install_nav_akshare(monkeypatch, unit_df, acc_df=None, overview_df=None, calls=None):
    """替身 fund_open_fund_info_em：按 indicator 返回样本，并**记录每次调用的入参**。

    - 入参被记录进 calls，测里可断言 symbol 就是被请求的那只基金
      （历史缺陷正是漏传基金代码，旧替身对传不传一视同仁，导致该缺陷测不出来）；
    - fund_etf_fund_info_em 被替换成「一调用就抛错」，防止回退到该已失效接口。
    """
    calls = [] if calls is None else calls
    if overview_df is None:
        overview_df = pd.DataFrame([{
            "基金代码": "110020", "基金全称": "易方达沪深300ETF联接A", "基金简称": "易方达沪深300ETF联接",
        }])
    mod = types.ModuleType("akshare")

    def fund_open_fund_info_em(symbol=None, indicator=None, **kw):
        calls.append({"symbol": symbol, "indicator": indicator})
        if "累计" in (indicator or ""):
            return acc_df if acc_df is not None else pd.DataFrame()
        return unit_df

    def fund_etf_fund_info_em(*a, **kw):
        raise AssertionError(
            "fund_etf_fund_info_em 已不可用（上游表结构变更且必须显式传 fund），"
            "历史净值请走 fund_open_fund_info_em"
        )

    mod.fund_open_fund_info_em = fund_open_fund_info_em
    mod.fund_etf_fund_info_em = fund_etf_fund_info_em
    mod.fund_overview_em = lambda df=overview_df, **kw: df
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod, calls


def _install_fake_akshare(monkeypatch, **dfs):
    """把 akshare 替换为返回录制样本 DataFrame 的假模块（不校验入参）。"""
    mod = types.ModuleType("akshare")
    for name, df in dfs.items():
        setattr(mod, name, lambda df=df, **kw: df)
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod


def _point(day, unit, acc=None, growth=None, code="110020"):
    return NavPoint(
        fund_code=code,
        nav_date=date.fromisoformat(day),
        unit_nav=Decimal(str(unit)),
        accumulated_nav=None if acc is None else Decimal(str(acc)),
        daily_growth=None if growth is None else Decimal(str(growth)),
        source="eastmoney",
    )


class FakeFundNav:
    """净值读服务替身：只实现 finance_api_service 用到的 in_catalog/get_*/get_history。"""

    def __init__(self, in_catalog=True, latest=None, points=None, error=None):
        self._in_catalog = in_catalog
        self.latest = latest
        self.points = points or []
        self.error = error
        self.history_calls = []
        self.latest_batch_calls = []

    def in_catalog(self, code):
        return self._in_catalog

    def get_latest(self, code):
        return self.latest

    def get_latest_batch(self, codes):
        self.latest_batch_calls.append(list(codes))
        if self.latest is None:
            return {}
        return {c: self.latest for c in codes if c == self.latest.fund_code}

    def get_history(self, code, limit=None):
        self.history_calls.append({"code": code, "limit": limit})
        if self.error is not None:
            raise self.error
        return self.points[-limit:] if limit else self.points


class FakeFundMeta:
    """元数据读服务替身：search 返回预置列表，get 按代码取。"""

    def __init__(self, metas=None):
        self.metas = metas or []
        self.search_calls = []

    def search(self, keyword, limit=10):
        self.search_calls.append({"keyword": keyword, "limit": limit})
        return self.metas[:limit]

    def get(self, code):
        for meta in self.metas:
            if meta.fund_code == code:
                return meta
        return None


@pytest.fixture(autouse=True)
def _offline_fund_nav(monkeypatch):
    """默认把净值读服务换成「目录内、无数据」替身，保证用例不连 DB、不触网。

    默认 `in_catalog=True`：本文件测的是目录内基金的行为；测目录外守卫的用例
    自己注入 `in_catalog=False` 的替身。

    替换的是**惰性属性内部 import 的类**，而不是 `FinanceApiService.fund_nav` 属性本身 ——
    后者会把构造参数注入的替身也一起覆盖掉（属性优先于 `self._fund_nav`）。
    """
    import server.services.fund_nav_service as nav_module

    fake = FakeFundNav()
    monkeypatch.setattr(nav_module, "FundNavService", lambda *a, **kw: fake)
    return fake


# ==================== 纯函数 ====================


def test_score_match_精确匹配():
    score, is_exact = FinanceApiService._score_match("红利低波", "华泰柏瑞红利低波ETF")
    assert is_exact is True
    assert score >= 1.0


def test_score_match_名称包含查询_精确():
    score, is_exact = FinanceApiService._score_match("红利低波", "红利低波")
    assert is_exact is True


def test_score_match_部分匹配_非精确():
    score, is_exact = FinanceApiService._score_match("红低波", "华泰柏瑞红利低波ETF")
    assert is_exact is False
    assert 0 <= score < 1


def test_score_match_无交集_零分():
    score, is_exact = FinanceApiService._score_match("zzz", "红利低波ETF")
    assert score == 0
    assert is_exact is False


def test_extract_fund_name_带ETF后缀():
    # KNOWN_FUNDS 快捷映射已删除（2026-10-26），走正则提取
    assert FinanceApiService()._extract_fund_name("华泰柏瑞红利低波ETF的净值是多少") == "华泰柏瑞红利低波ETF"


def test_extract_fund_name_正则匹配():
    name = FinanceApiService()._extract_fund_name("查询科技龙头ETF的行情")
    assert "科技龙头ETF" in name


def test_extract_fund_name_无基金返回None():
    assert FinanceApiService()._extract_fund_name("你好") is None


def test_clean_rate_提取百分比():
    assert FinanceApiService._clean_rate("管理费率 0.50%") == "0.50%"


def test_clean_rate_占位符返回空():
    assert FinanceApiService._clean_rate("---") == ""


def test_clean_rate_无百分号原样返回():
    assert FinanceApiService._clean_rate("0.50") == "0.50"


def test_safe_float_数字():
    assert FinanceApiService._safe_float("1.5") == 1.5


def test_safe_float_NaN返回None():
    assert FinanceApiService._safe_float(float("nan")) is None


def test_safe_float_非法返回None():
    assert FinanceApiService._safe_float("abc") is None


# ==================== 搜索（只搜支持目录） ====================


def test_search_catalog_名称命中并带最新净值():
    from server.services.fund_nav_service import LatestNav

    fake_nav = FakeFundNav(
        latest=LatestNav(fund_code="110020", nav_date=date(2026, 1, 6), unit_nav=Decimal("1.5200")),
    )
    fake_meta = FakeFundMeta([
        FundMeta(fund_code="110020", fund_name="易方达沪深300ETF联接A", ftype="指数型-股票",
                 net_asset_scale=Decimal("123456789.12")),
    ])

    results = FinanceApiService(fund_nav=fake_nav, fund_meta=fake_meta).search_catalog("沪深300")

    assert results == [{
        "code": "110020",
        "name": "易方达沪深300ETF联接A",
        "fund_type": "指数型-股票",
        "net_asset_scale": "123456789.12",
        "nav": 1.52,
        "nav_date": "2026-01-06",
    }]
    assert fake_meta.search_calls == [{"keyword": "沪深300", "limit": 10}]


def test_search_catalog_无命中返回空列表():
    svc = FinanceApiService(fund_nav=FakeFundNav(), fund_meta=FakeFundMeta([]))
    assert svc.search_catalog("512890") == []


def test_search_catalog_场内ETF代码搜不到():
    """目录 = fund_catalog；场内 ETF 不在目录内，搜代码必须无结果。"""
    svc = FinanceApiService(fund_nav=FakeFundNav(), fund_meta=FakeFundMeta([]))
    assert svc.search_catalog("512890", limit=10) == []


# ==================== 目录外守卫 ====================


def test_query_detail_目录外抛FundNotSupported():
    from server.services.fund_nav_service import FundNotSupported

    svc = FinanceApiService(fund_nav=FakeFundNav(in_catalog=False), fund_meta=FakeFundMeta())

    with pytest.raises(FundNotSupported) as exc:
        svc.query_detail("512890")
    assert "512890" in str(exc.value)


def test_query_nav_history_目录外抛FundNotSupported():
    from server.services.fund_nav_service import FundNotSupported

    svc = FinanceApiService(fund_nav=FakeFundNav(in_catalog=False))

    with pytest.raises(FundNotSupported):
        svc._query_nav_history("512890")


def test_query_nav_目录外抛FundNotSupported():
    from server.services.fund_nav_service import FundNotSupported

    svc = FinanceApiService(fund_nav=FakeFundNav(in_catalog=False))

    with pytest.raises(FundNotSupported):
        svc._query_nav("512890")


# ==================== query_kline / 缓存 ====================


def _kline_df(dates=("2026-01-05", "2026-01-06")):
    """构造日K DataFrame（列名同 akshare fund_etf_hist_sina）。"""
    return pd.DataFrame([
        {"date": d, "open": 1.5, "close": 1.6, "high": 1.7, "low": 1.4,
         "volume": 100000, "amount": 150000, "postVol": None, "postAmt": None}
        for d in dates
    ])


def test_query_kline_从akshare获取(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    _install_fake_akshare(monkeypatch, fund_etf_hist_sina=_kline_df())
    results = FinanceApiService().query_kline("512890", period="daily")
    assert len(results) == 2
    assert results[0]["date"] == "2026-01-05"
    assert results[0]["close"] == 1.6


def test_query_kline_由日线补出涨跌幅与振幅(monkeypatch, tmp_path):
    """新浪日K没有涨跌幅/振幅列，必须由相邻收盘价现算（首根无前收 → 0）。"""
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    daily = pd.DataFrame([
        {"date": "2026-01-05", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.0, "volume": 10, "amount": 100},
        {"date": "2026-01-06", "open": 1.0, "high": 1.5, "low": 1.0, "close": 1.1, "volume": 20, "amount": 200},
    ])
    _install_fake_akshare(monkeypatch, fund_etf_hist_sina=daily)
    out = FinanceApiService().query_kline("512890")
    assert out[0]["change"] == 0.0 and out[0]["change_pct"] == 0.0 and out[0]["amplitude"] == 0.0
    assert out[1]["change"] == pytest.approx(0.1)
    assert out[1]["change_pct"] == pytest.approx(10.0)      # (1.1-1.0)/1.0
    assert out[1]["amplitude"] == pytest.approx(50.0)       # (1.5-1.0)/1.0


def test_query_kline_周线由日线重采样(monkeypatch, tmp_path):
    """新浪只有日线接口，周/月线聚合：open=首、high=最高、low=最低、close=末、volume/amount=求和。"""
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    daily = pd.DataFrame([
        {"date": "2026-01-05", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 10, "amount": 100},
        {"date": "2026-01-06", "open": 1.1, "high": 1.5, "low": 1.0, "close": 1.4, "volume": 20, "amount": 200},
        {"date": "2026-01-12", "open": 1.4, "high": 1.6, "low": 1.3, "close": 1.5, "volume": 30, "amount": 300},
    ])
    _install_fake_akshare(monkeypatch, fund_etf_hist_sina=daily)
    weekly = FinanceApiService().query_kline("512890", period="weekly")
    assert len(weekly) == 2
    assert (weekly[0]["open"], weekly[0]["high"], weekly[0]["low"], weekly[0]["close"]) == (1.0, 1.5, 0.9, 1.4)
    assert weekly[0]["volume"] == 30  # 10 + 20
    assert weekly[0]["amount"] == 300
    # 日期取区间内最后一个**实际交易日**，不是 W-FRI 的周五：01-05 那周只有 05/06，
    # 若按区间末日标会得到 01-09，本周还会标出没到的未来周五，前端按日期过滤会丢数据
    assert [w["date"] for w in weekly] == ["2026-01-06", "2026-01-12"]


def test_query_kline_日期过滤与limit(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    _install_fake_akshare(monkeypatch, fund_etf_hist_sina=_kline_df(("2026-01-05", "2026-01-06", "2026-01-07")))
    # start_date 过滤后剩 [06, 07]，limit 用 tail 取最近 1 条 → 07
    results = FinanceApiService().query_kline("512890", start_date="2026-01-06", limit=1)
    assert len(results) == 1
    assert results[0]["date"] == "2026-01-07"


def test_query_kline_空数据返回空列表(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    _install_fake_akshare(monkeypatch, fund_etf_hist_sina=pd.DataFrame())
    assert FinanceApiService().query_kline("512890") == []


def test_kline缓存_保存后能加载(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    df = _kline_df()
    FinanceApiService._save_kline_cache("512890", "daily", df)
    loaded = FinanceApiService._load_kline_cache("512890", "daily")
    assert loaded is not None
    assert len(loaded) == 2
    # read_json 会把 date 还原成 Timestamp，str() 后带 " 00:00:00"，
    # 与未命中缓存时（"%Y-%m-%d"）不一致 —— 缓存命中与否必须返回同一格式
    assert [str(d) for d in loaded["date"]] == ["2026-01-05", "2026-01-06"]


def test_kline缓存_不存在返回None(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    assert FinanceApiService._load_kline_cache("nonexist", "daily") is None


# ==================== query_intraday ====================


def _min_kline_df(days=("2026-01-05 09:31:00", "2026-01-05 09:32:00", "2026-01-06 09:31:00")):
    """构造分钟 DataFrame（列名同 akshare stock_zh_a_minute），默认跨两个交易日。"""
    return pd.DataFrame([
        {"day": d, "open": 1.5, "close": 1.51, "high": 1.52, "low": 1.49, "volume": 1000, "amount": 1500}
        for d in days
    ])


def test_query_intraday_真实分钟数据_只取当日(monkeypatch, tmp_path):
    """新浪分钟接口返回约 1970 根的滚动窗口（跨多个交易日），必须按当日过滤。

    不过滤会把十几天的走势画成一天——这是换源时最容易踩的坑。
    """
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(finance_api, "beijing_now", lambda: datetime(2026, 1, 5, 10, 0))
    _install_fake_akshare(monkeypatch, stock_zh_a_minute=_min_kline_df())
    results = FinanceApiService().query_intraday("512890")
    assert len(results) == 2  # 01-06 那根被当日过滤掉
    assert [r["time"] for r in results] == ["09:31", "09:32"]
    assert all("change_pct" in r for r in results)


def test_query_intraday_涨跌幅以昨收为基准(monkeypatch, tmp_path):
    """昨收取自日K里「今天之前」的最后一根（实时快照已下线）。"""
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(finance_api, "beijing_now", lambda: datetime(2026, 1, 5, 10, 0))
    monkeypatch.setattr(
        FinanceApiService,
        "query_kline",
        lambda self, code, **kw: [{"date": "2026-01-02", "close": 1.0}],
    )
    _install_fake_akshare(monkeypatch, stock_zh_a_minute=_min_kline_df())
    results = FinanceApiService().query_intraday("512890")
    assert results[0]["change_pct"] == pytest.approx(51.0)  # (1.51 - 1.00) / 1.00


def test_query_intraday_取不到当日数据返回空列表(monkeypatch):
    """2026-10-26：模拟分时降级已删除（依赖已下线的行情缓存，且生成伪造数据）。"""
    mod = types.ModuleType("akshare")

    def _boom(**kw):
        raise RuntimeError("no min data")

    mod.stock_zh_a_minute = _boom
    monkeypatch.setitem(sys.modules, "akshare", mod)
    assert FinanceApiService().query_intraday("512890") == []


# ==================== 明细 / 历史净值（目录内） ====================


def test_query_detail_返回详情(monkeypatch):
    _install_fake_akshare(monkeypatch, fund_overview_em=pd.DataFrame([{"基金代码": "110020", "基金全称": "易方达沪深300ETF联接A"}]))
    fake = FakeFundNav(points=[_point("2026-01-05", 1.5, 1.5, 0.5), _point("2026-01-06", 1.52, 1.52, 1.33)])
    detail = FinanceApiService(fund_nav=fake, fund_meta=FakeFundMeta()).query_detail("110020")

    assert detail["code"] == "110020"
    assert "realtime" not in detail  # 实时行情已下线
    assert [i["date"] for i in detail["nav_history"]] == ["2026-01-05", "2026-01-06"]
    assert detail["nav_history"][0]["nav"] == 1.5
    assert detail["nav_history"][0]["daily_growth"] == 0.5
    assert detail["nav_history"][1]["accumulated_nav"] == 1.52
    # 历史必须按被请求的基金代码取
    assert fake.history_calls == [{"code": "110020", "limit": FinanceApiService.DEFAULT_NAV_LIMIT}]


def test_query_detail_默认返回近2年条数_可按参数收窄(monkeypatch):
    _install_fake_akshare(monkeypatch, fund_overview_em=pd.DataFrame([{"基金代码": "110020", "基金全称": "易方达沪深300ETF联接A"}]))
    points = [
        _point((date(2024, 1, 1) + timedelta(days=i)).isoformat(), 1.0 + i / 1000)
        for i in range(600)
    ]
    svc = FinanceApiService(fund_nav=FakeFundNav(points=points), fund_meta=FakeFundMeta())

    assert len(svc.query_detail("110020")["nav_history"]) == FinanceApiService.DEFAULT_NAV_LIMIT
    assert len(svc.query_detail("110020", nav_limit=10)["nav_history"]) == 10
    # 取的是最近 N 条，不是最早 N 条
    assert svc.query_detail("110020", nav_limit=1)["nav_history"][0]["date"] == points[-1].nav_date.isoformat()


def test_query_detail_概览与净值皆空返回None(monkeypatch):
    _install_nav_akshare(monkeypatch, unit_df=pd.DataFrame(), overview_df=pd.DataFrame())
    svc = FinanceApiService(fund_nav=FakeFundNav(points=[]), fund_meta=FakeFundMeta())
    assert svc.query_detail("110020") is None


def test_query_nav_history_累计净值取自同一点():
    """目录内基金不请求「累计净值走势」：累计值就在同一条 NavPoint 里。"""
    fake = FakeFundNav(points=[_point("2026-01-05", 1.5, 2.8, 0.5), _point("2026-01-06", 1.52, 2.82, 1.33)])

    nav = FinanceApiService(fund_nav=fake)._query_nav_history("110020", limit=1)

    assert fake.history_calls == [{"code": "110020", "limit": 1}]
    assert nav == [{"date": "2026-01-06", "nav": 1.52, "accumulated_nav": 2.82, "daily_growth": 1.33}]


def test_query_nav_history_全量返回():
    """limit=None（全量）不截断，供需要完整历史（如近2年以上）的调用方使用。"""
    points = [_point(f"2026-01-{d:02d}", 1.0 + d / 100, growth=0.1) for d in range(1, 29)]
    assert len(FinanceApiService(fund_nav=FakeFundNav(points=points))._query_nav_history("110020", limit=None)) == 28


def test_query_nav_history_补数失败_上抛FundNavUnavailable():
    """历史不可用 ≠ 没有历史：必须上抛让 API 映射 503，不能返回空列表。"""
    from server.services.fund_nav_service import FundNavUnavailable

    err = FundNavUnavailable("110020", "failed", "上游超时")
    svc = FinanceApiService(fund_nav=FakeFundNav(error=err))

    with pytest.raises(FundNavUnavailable):
        svc._query_nav_history("110020")


def test_query_nav_目录内读DB_不触网():
    from server.services.fund_nav_service import LatestNav

    fake = FakeFundNav(
        latest=LatestNav(fund_code="110020", nav_date=date(2026, 1, 6), unit_nav=Decimal("1.5200")),
    )
    assert FinanceApiService(fund_nav=fake)._query_nav("110020") == {"nav": "1.5200", "nav_date": "2026-01-06"}


def test_query_nav_目录内无数据_保持空字典契约():
    svc = FinanceApiService(fund_nav=FakeFundNav(latest=None))
    assert svc._query_nav("110020") == {}
