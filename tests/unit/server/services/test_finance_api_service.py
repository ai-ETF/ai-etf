"""finance_api_service 单元测试：行情数据查询与格式化。

模块名称：server/services/finance_api_service.py
所测功能：纯函数（_score_match/_extract_fund_name/_clean_rate/_safe_float）、行情（_format_spot_data/
         query_spot/query_ranking/refresh_spot_cache）、K线（query_kline/缓存/query_intraday）、
         资金流、搜索分类、明细
测试方法：纯函数直测；读缓存方法给 _spot_dict 种入样本；akshare 依赖方法用 sys.modules 注入
         假 akshare 返回录制样本 DataFrame，全程离线、不联网。
"""
import sys
import types

import pandas as pd
import pytest

import server.services.finance_api_service as finance_api
from server.services.finance_api_service import FinanceApiService


# ==================== 样本数据 ====================


def _spot(code="512890", name="红利低波ETF", **overrides):
    """构造一只 ETF 的行情 dict（字段同 _format_spot_data 输出）。"""
    d = {
        "code": code, "name": name, "data_date": "2026-01-05", "update_time": "10:00:00",
        "price": 1.5, "change": 0.01, "change_pct": 0.67, "prev_close": 1.49,
        "open": 1.49, "high": 1.52, "low": 1.48, "amplitude": 2.68,
        "volume": 1000000, "amount": 1500000, "turnover_rate": 1.5, "volume_ratio": 0.8,
        "bid_price": 1.5, "ask_price": 1.51, "outer_vol": 600000, "inner_vol": 400000,
        "order_ratio": 0.2, "main_inflow": 100000, "main_inflow_pct": 6.7,
        "latest_shares": 1000000000, "float_mv": 1500000000, "total_mv": 1500000000,
        "source": "api",
    }
    d.update(overrides)
    return d


def _spot_df(rows):
    """构造行情 DataFrame（列名同 akshare fund_etf_spot_em）。"""
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _reset_spot_dict():
    FinanceApiService._spot_dict = None
    FinanceApiService._fund_list_cache = None
    yield
    FinanceApiService._spot_dict = None
    FinanceApiService._fund_list_cache = None


def _install_fake_akshare(monkeypatch, **dfs):
    """把 akshare 替换为返回录制样本 DataFrame 的假模块。"""
    mod = types.ModuleType("akshare")
    for name, df in dfs.items():
        setattr(mod, name, lambda df=df, **kw: df)
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod


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


def test_extract_fund_name_已知基金():
    assert FinanceApiService()._extract_fund_name("华泰柏瑞红利低波ETF的净值是多少") == "华泰柏瑞红利低波"


def test_extract_fund_name_正则匹配():
    # 问题中含 ≥4 个连续中文 + ETF 的片段
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


# ==================== _format_spot_data ====================


def test_format_spot_data_dict输入():
    row = {"代码": "512890", "名称": "红利低波ETF", "最新价": 1.5, "涨跌幅": 0.67}
    d = FinanceApiService._format_spot_data(row)
    assert d["code"] == "512890"
    assert d["name"] == "红利低波ETF"
    assert d["price"] == 1.5
    assert d["change_pct"] == 0.67
    assert d["source"] == "api"


def test_format_spot_data_缺失字段回退默认():
    d = FinanceApiService._format_spot_data({})
    assert d["code"] == ""
    assert d["price"] == 0.0
    assert d["name"] == ""


# ==================== query_spot / query_ranking ====================


def test_query_spot_命中():
    FinanceApiService._spot_dict = {"512890": _spot()}
    assert FinanceApiService().query_spot("512890")["code"] == "512890"


def test_query_spot_未命中返回None():
    FinanceApiService._spot_dict = {"512890": _spot()}
    assert FinanceApiService().query_spot("999999") is None


def test_query_spot_空缓存返回None():
    assert FinanceApiService().query_spot("512890") is None


def test_query_ranking_按涨跌幅降序():
    FinanceApiService._spot_dict = {
        "a": _spot(code="a", change_pct=1.0),
        "b": _spot(code="b", change_pct=3.0),
        "c": _spot(code="c", change_pct=2.0),
    }
    results = FinanceApiService().query_ranking(sort_by="change_pct", top_n=2)
    assert [r["code"] for r in results] == ["b", "c"]


def test_query_ranking_空缓存返回空列表():
    assert FinanceApiService().query_ranking() == []


# ==================== refresh_spot_cache ====================


def test_refresh_spot_cache_刷新成功(monkeypatch):
    monkeypatch.setattr("server.services.spot_cache_scheduler._is_trading_time", lambda: True)
    _install_fake_akshare(monkeypatch, fund_etf_spot_em=_spot_df([{"代码": "512890", "名称": "红利低波ETF", "最新价": 1.5}]))
    assert FinanceApiService.refresh_spot_cache() is True
    assert FinanceApiService._spot_dict is not None


def test_refresh_spot_cache_非交易时段且已有缓存_跳过(monkeypatch):
    monkeypatch.setattr("server.services.spot_cache_scheduler._is_trading_time", lambda: False)
    FinanceApiService._spot_dict = {"512890": _spot()}
    assert FinanceApiService.refresh_spot_cache() is True  # 返回 True 表示缓存仍有效


def test_refresh_spot_cache_异常返回False(monkeypatch):
    monkeypatch.setattr("server.services.spot_cache_scheduler._is_trading_time", lambda: True)
    mod = types.ModuleType("akshare")

    def _boom(**kw):
        raise RuntimeError("net fail")

    mod.fund_etf_spot_em = _boom
    monkeypatch.setitem(sys.modules, "akshare", mod)
    assert FinanceApiService.refresh_spot_cache() is False


# ==================== query_kline / 缓存 ====================


def _kline_df(dates=("2026-01-05", "2026-01-06")):
    return pd.DataFrame([
        {"日期": d, "开盘": 1.5, "收盘": 1.6, "最高": 1.7, "最低": 1.4,
         "成交量": 100000, "成交额": 150000, "振幅": 20.0, "涨跌幅": 6.67, "涨跌额": 0.1, "换手率": 1.0}
        for d in dates
    ])


def test_query_kline_从akshare获取(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    _install_fake_akshare(monkeypatch, fund_etf_hist_em=_kline_df())
    results = FinanceApiService().query_kline("512890", period="daily")
    assert len(results) == 2
    assert results[0]["date"] == "2026-01-05"
    assert results[0]["close"] == 1.6


def test_query_kline_日期过滤与limit(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    _install_fake_akshare(monkeypatch, fund_etf_hist_em=_kline_df(("2026-01-05", "2026-01-06", "2026-01-07")))
    # start_date 过滤后剩 [06, 07]，limit 用 tail 取最近 1 条 → 07
    results = FinanceApiService().query_kline("512890", start_date="2026-01-06", limit=1)
    assert len(results) == 1
    assert results[0]["date"] == "2026-01-07"


def test_query_kline_空数据返回空列表(monkeypatch):
    _install_fake_akshare(monkeypatch, fund_etf_hist_em=pd.DataFrame())
    assert FinanceApiService().query_kline("512890") == []


def test_kline缓存_保存后能加载(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    df = _kline_df()
    FinanceApiService._save_kline_cache("512890", "daily", df)
    loaded = FinanceApiService._load_kline_cache("512890", "daily")
    assert loaded is not None
    assert len(loaded) == 2


def test_kline缓存_不存在返回None(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_api, "KLINE_CACHE_DIR", str(tmp_path))
    assert FinanceApiService._load_kline_cache("nonexist", "daily") is None


# ==================== query_intraday / fallback ====================


def _min_kline_df():
    return pd.DataFrame([
        {"时间": "09:31", "开盘": 1.5, "收盘": 1.51, "最高": 1.52, "最低": 1.49, "成交量": 1000, "成交额": 1500},
        {"时间": "09:32", "开盘": 1.51, "收盘": 1.52, "最高": 1.53, "最低": 1.50, "成交量": 2000, "成交额": 3000},
    ])


def test_query_intraday_真实分钟数据(monkeypatch):
    _install_fake_akshare(monkeypatch, fund_etf_hist_min_em=_min_kline_df())
    results = FinanceApiService().query_intraday("512890")
    assert len(results) == 2
    assert results[0]["time"] == "09:31"
    assert "change_pct" in results[0]


def test_query_intraday_分钟失败走模拟回退(monkeypatch):
    FinanceApiService._spot_dict = {"512890": _spot(prev_close=1.0, price=1.5, open=1.2, high=1.6, low=1.1, volume=24000, amount=36000)}
    monkeypatch.setattr(FinanceApiService, "query_kline", lambda self, code, **kw: [{"open": 1.2}])
    mod = types.ModuleType("akshare")

    def _boom(**kw):
        raise RuntimeError("no min data")

    mod.fund_etf_hist_min_em = _boom
    monkeypatch.setitem(sys.modules, "akshare", mod)
    results = FinanceApiService().query_intraday("512890")
    assert len(results) == 240  # 模拟 240 个时间点
    assert results[0]["time"] == "09:30"


# ==================== 资金流 ====================


def test_query_money_flow_命中并计算净流入():
    FinanceApiService._spot_dict = {"512890": _spot(outer_vol=600000, inner_vol=400000)}
    result = FinanceApiService().query_money_flow("512890")
    assert result["main_inflow"] == 100000
    assert result["net_flow"] == 200000  # 外盘 - 内盘


def test_query_money_flow_未命中返回None():
    assert FinanceApiService().query_money_flow("999999") is None


def test_query_money_flow_ranking_按主力净流入排序():
    FinanceApiService._spot_dict = {
        "a": _spot(code="a", main_inflow=100),
        "b": _spot(code="b", main_inflow=300),
    }
    results = FinanceApiService().query_money_flow_ranking(top_n=1)
    assert results[0]["code"] == "b"


# ==================== 搜索 / 筛选 / 分类 ====================


def test_search_etf_按名称匹配():
    FinanceApiService._spot_dict = {"512890": _spot(name="红利低波ETF")}
    results = FinanceApiService().search_etf("红利低波")
    assert len(results) == 1
    assert results[0]["code"] == "512890"


def test_search_etf_空缓存返回空():
    assert FinanceApiService().search_etf("红利低波") == []


def test_filter_etf_按涨跌幅筛选():
    FinanceApiService._spot_dict = {
        "a": _spot(code="a", name="红利低波ETF", change_pct=1.0),
        "b": _spot(code="b", name="科技ETF", change_pct=5.0),
    }
    results = FinanceApiService().filter_etf({"keyword": "ETF", "min_return": 3.0})
    assert [r["code"] for r in results] == ["b"]


def test_get_categories_统计分类():
    FinanceApiService._spot_dict = {"512890": _spot(name="红利低波ETF"), "515450": _spot(name="南方标普红利低波")}
    cats = FinanceApiService().get_categories()
    assert any(c["category"] == "红利ETF" for c in cats)


def test_get_category_funds_返回分类下基金():
    FinanceApiService._spot_dict = {"512890": _spot(name="红利低波ETF")}
    results = FinanceApiService().get_category_funds("红利ETF")
    assert results[0]["code"] == "512890"


# ==================== 明细 / 历史净值 ====================


def test_query_detail_返回详情(monkeypatch):
    FinanceApiService._spot_dict = {"512890": _spot()}
    _install_fake_akshare(
        monkeypatch,
        fund_overview_em=pd.DataFrame([{"基金代码": "512890", "基金全称": "华泰柏瑞中证红利低波动ETF", "基金简称": "红利低波ETF"}]),
        fund_etf_fund_info_em=pd.DataFrame([{"净值日期": "2026-01-05", "单位净值": 1.5, "累计净值": 1.5, "日增长率": 0.5}]),
    )
    detail = FinanceApiService().query_detail("512890")
    assert detail["code"] == "512890"
    assert "realtime" in detail
    assert detail["nav_history"][0]["nav"] == 1.5


def test_query_detail_无数据返回None(monkeypatch):
    FinanceApiService._spot_dict = None
    _install_fake_akshare(
        monkeypatch,
        fund_overview_em=pd.DataFrame(),
        fund_etf_fund_info_em=pd.DataFrame(),
    )
    assert FinanceApiService().query_detail("999999") is None
