"""fund_meta_service 单元测试：搜索只查 `fund_catalog`，输入要能安全拼进 PostgREST 过滤串。

模块名称：server/services/fund_meta_service.py
所测功能：`search()`（目录内代码/名称模糊搜索）、`_ilike_pattern()`（过滤语法转义）
测试方法：内存 FakeClient 记录查询链，不连 Supabase。
"""
from decimal import Decimal

from server.services.fund_meta_service import FundMetaService, _ilike_pattern


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    def select(self, fields):
        self._log["select"] = fields
        return self

    def or_(self, expr):
        self._log["or_"] = expr
        return self

    def order(self, column, **_kw):
        self._log["order"] = column
        return self

    def limit(self, n):
        self._log["limit"] = n
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.log = {}

    def table(self, name):
        self.log["table"] = name
        return _FakeQuery(self._rows, self.log)


def test_search_只查目录视图并拼or条件():
    client = _FakeClient([{
        "fund_code": "110020", "fund_name": "易方达沪深300ETF联接A",
        "ftype": "指数型-股票", "net_asset_scale": Decimal("1.2"),
        "lifecycle_status": "active",
    }])

    metas = FundMetaService(client=client).search("沪深300", limit=5)

    assert client.log["table"] == "fund_catalog"
    assert client.log["or_"] == "fund_code.ilike.*沪深300*,fund_name.ilike.*沪深300*"
    assert client.log["limit"] == 5
    assert [m.fund_code for m in metas] == ["110020"]


def test_search_输入含过滤语法字符时被剔除():
    client = _FakeClient([])
    assert FundMetaService(client=client).search("a,(b)*%") == []
    assert client.log["or_"] == "fund_code.ilike.*ab*,fund_name.ilike.*ab*"


def test_ilike_pattern_空输入返回None():
    assert _ilike_pattern("   ") is None
    assert _ilike_pattern(None) is None
