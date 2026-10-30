"""watchlist_service 单元测试：自选股增删查清。

模块名称：server/services/watchlist_service.py
所测功能：add（正常新增 / 重复添加 / 名称缺失时从主数据补）、remove（移除 / 不存在）、
         list（含净值 / 不含净值 / 空列表）、clear（清空）、_format_item（单项格式化）
测试方法：替换 svc._client 为内存 FakeClient（支持 select/insert/delete/eq/order），
         名称与净值分别用 FakeFundMeta / FakeFundNav 替身，全程不联网、不连 Supabase。

2026-10-26：自选股不再展示实时行情（30 秒轮询已下线），改为展示 DB 最新净值。
"""
import datetime
import types

import pytest

from server.services.watchlist_service import WatchlistService


# ==================== 替身：模拟 Supabase client ====================


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """模拟 supabase 链式 table().select/insert/delete().eq()/order().execute()。"""

    def __init__(self, client):
        self._client = client
        self._op = None
        self._filters = {}
        self._insert_data = None

    def select(self, *_args, **_kwargs):
        self._op = "select"
        return self

    def insert(self, data):
        self._op = "insert"
        self._insert_data = data
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def order(self, *_args, **_kwargs):
        # 排序对断言无影响，仅保证链式不中断
        return self

    def execute(self):
        if self._client.error is not None:
            raise self._client.error

        if self._op == "insert":
            row = dict(self._insert_data)
            row["id"] = row.get("id") or f"id-{len(self._client.rows) + 1}"
            self._client.rows.append(row)
            return FakeResult([row])

        matched = [r for r in self._client.rows if self._match(r)]

        if self._op == "delete":
            self._client.rows = [r for r in self._client.rows if not self._match(r)]
            return FakeResult(matched)

        # select（默认）
        return FakeResult(matched)

    def _match(self, row):
        return all(row.get(col) == val for col, val in self._filters.items())


class FakeClient:
    """内存行集合替身：按 op 与 eq 条件操作 rows，不产生任何网络/DB IO。"""

    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error

    def table(self, _name):
        return FakeQuery(self)


class FakeFundMeta:
    """替身：按基金代码返回主数据名称。"""

    name_by_code = {}

    def get(self, fund_code):
        name = self.name_by_code.get(fund_code)
        return types.SimpleNamespace(fund_name=name) if name else None


class FakeFundNav:
    """替身：按基金代码返回最新净值。"""

    nav_by_code = {}

    def get_latest_batch(self, codes):
        return {
            code: types.SimpleNamespace(unit_nav=nav, nav_date=datetime.date(2026, 1, 6))
            for code, nav in ((c, self.nav_by_code.get(c)) for c in codes)
            if nav is not None
        }


# ==================== fixture 与样本 ====================


@pytest.fixture
def svc():
    service = WatchlistService()
    service._client = FakeClient()
    return service


def _row(user_id="u1", fund_code="512890", fund_name="红利低波ETF"):
    return {
        "id": "w1",
        "user_id": user_id,
        "fund_code": fund_code,
        "fund_name": fund_name,
        "sort_order": 0,
        "created_at": "2026-01-01T00:00:00",
    }


# ==================== _format_item：单项格式化 ====================


def test_格式化单项_字段齐全且行情字段默认为None(svc):
    item = svc._format_item(_row())
    assert item == {
        "id": "w1",
        "user_id": "u1",
        "fund_code": "512890",
        "fund_name": "红利低波ETF",
        "sort_order": 0,
        "created_at": "2026-01-01T00:00:00",
        "nav": None,
        "nav_date": None,
    }


def test_格式化单项_字段缺失回退默认值(svc):
    item = svc._format_item({})
    assert item["id"] == ""
    assert item["fund_code"] == ""
    assert item["sort_order"] == 0
    assert item["nav"] is None


# ==================== add：新增自选股 ====================


def test_正常新增_返回成功并格式化(svc):
    result = svc.add("u1", "512890", fund_name="红利低波ETF")
    assert result["success"] is True
    assert result["item"]["fund_code"] == "512890"
    assert result["item"]["fund_name"] == "红利低波ETF"


def test_重复添加_返回已存在(svc):
    svc._client.rows = [_row()]
    result = svc.add("u1", "512890", fund_name="红利低波ETF")
    assert result["success"] is False
    assert result["message"] == "该ETF已在自选列表中"


def test_名称缺失_从基金主数据补名称(svc, monkeypatch):
    monkeypatch.setattr("server.services.fund_meta_service.FundMetaService", FakeFundMeta)
    FakeFundMeta.name_by_code = {"512890": "红利低波ETF"}

    result = svc.add("u1", "512890")  # 不传 fund_name
    assert result["success"] is True
    assert result["item"]["fund_name"] == "红利低波ETF"


# ==================== remove：移除自选股 ====================


def test_正常移除_返回成功(svc):
    svc._client.rows = [_row()]
    result = svc.remove("u1", "512890")
    assert result["success"] is True
    assert result["message"] == "移除成功"


def test_移除不存在的记录_返回未找到(svc):
    result = svc.remove("u1", "999999")
    assert result["success"] is False
    assert result["message"] == "未找到该自选股"


# ==================== list：查询列表 ====================


def test_含净值_附带最新净值(svc, monkeypatch):
    svc._client.rows = [_row()]
    monkeypatch.setattr("server.services.fund_nav_service.FundNavService", FakeFundNav)
    FakeFundNav.nav_by_code = {"512890": 1.23}

    result = svc.list("u1", include_quote=True)
    assert result["total"] == 1
    assert result["items"][0]["nav"] == 1.23
    assert result["items"][0]["nav_date"] == "2026-01-06"


def test_不含净值_净值字段为None(svc):
    svc._client.rows = [_row()]
    result = svc.list("u1", include_quote=False)
    assert result["total"] == 1
    assert result["items"][0]["nav"] is None
    assert result["items"][0]["nav_date"] is None


def test_空列表_返回0项(svc):
    result = svc.list("u1")
    assert result["total"] == 0
    assert result["items"] == []


# ==================== clear：清空 ====================


def test_清空_返回移除数量(svc):
    svc._client.rows = [_row("u1", "512890", "红利低波ETF"), _row("u1", "510300", "沪深300ETF")]
    result = svc.clear("u1")
    assert result["success"] is True
    assert result["removed_count"] == 2


def test_清空空列表_数量为0仍成功(svc):
    result = svc.clear("u1")
    assert result["success"] is True
    assert result["removed_count"] == 0


# ==================== 数据库不可用 / 异常兜底 ====================


def test_数据库不可用_add_返回连接失败(svc):
    svc._client = None
    assert svc.add("u1", "512890", fund_name="红利低波ETF") == {
        "success": False,
        "message": "数据库连接失败",
        "item": None,
    }


def test_数据库不可用_remove_返回连接失败(svc):
    svc._client = None
    assert svc.remove("u1", "512890") == {"success": False, "message": "数据库连接失败"}


def test_数据库不可用_list_返回空(svc):
    svc._client = None
    assert svc.list("u1") == {"total": 0, "items": []}


def test_数据库不可用_clear_返回连接失败(svc):
    svc._client = None
    assert svc.clear("u1") == {
        "success": False,
        "message": "数据库连接失败",
        "removed_count": 0,
    }


def test_add_异常_返回添加失败(svc):
    svc._client = FakeClient(error=RuntimeError("db error"))
    result = svc.add("u1", "512890", fund_name="红利低波ETF")
    assert result["success"] is False
    assert result["message"] == "添加失败: db error"


def test_add_唯一约束冲突_返回已存在(svc):
    # 错误信息含 duplicate/unique 时映射为「已存在」
    svc._client = FakeClient(error=RuntimeError("duplicate key value violates unique constraint"))
    result = svc.add("u1", "512890", fund_name="红利低波ETF")
    assert result["success"] is False
    assert result["message"] == "该ETF已在自选列表中"


def test_remove_异常_返回移除失败(svc):
    svc._client = FakeClient(error=RuntimeError("db error"))
    result = svc.remove("u1", "512890")
    assert result["success"] is False
    assert result["message"] == "移除失败: db error"


def test_list_异常_返回空(svc):
    svc._client = FakeClient(error=RuntimeError("db error"))
    assert svc.list("u1") == {"total": 0, "items": []}


def test_clear_异常_返回清空失败(svc):
    svc._client = FakeClient(error=RuntimeError("db error"))
    result = svc.clear("u1")
    assert result["success"] is False
    assert result["message"] == "清空失败: db error"
    assert result["removed_count"] == 0
