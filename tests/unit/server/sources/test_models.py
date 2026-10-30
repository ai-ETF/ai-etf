"""多源适配器归一化模型与错误类型单元测试。

模块名称：server/sources/models.py
所测功能：`to_decimal` 字段清洗、`SourceError` / `AllSourcesFailed` 错误语义、
         「域级 vs 接口级」失败分类集合、`BaseSource` 对未实现能力的显式拒绝。
测试方法：纯函数直测 + 内联上游字段样本；不联网、不连数据库。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.2 / §5.2。
"""
from decimal import Decimal

import pytest

from server.sources.models import (
    DOMAIN_LEVEL_KINDS,
    AllSourcesFailed,
    BaseSource,
    FailureKind,
    SourceError,
    SourceMeta,
    to_decimal,
)


class _StubSource(BaseSource):
    """只声明元信息、不实现任何能力的源，用于验证「未实现即显式报错」。"""

    meta = SourceMeta(
        name="stub",
        domain="d.example.com",
        capabilities=frozenset({"history"}),
    )


# ==================== to_decimal：正常数据 ====================


def test_to_decimal_保留上游净值精度():
    """两组真实样本：单位净值 4 位小数、日增长率带符号。"""
    assert to_decimal("1.7196") == Decimal("1.7196")
    assert to_decimal("-0.27") == Decimal("-0.27")
    assert to_decimal("0") == Decimal("0")


def test_to_decimal_不丢尾随零且不经过浮点():
    """`0.1250` 这类增长率必须保持十进制字面量，不能先转 float。"""
    value = to_decimal("0.1250")

    assert value == Decimal("0.1250")
    assert str(value) == "0.1250"


def test_to_decimal_接受上游数字类型():
    assert to_decimal(1.5) == Decimal("1.5")
    assert to_decimal(0) == Decimal("0")


# ==================== to_decimal：空值 / 异常 ====================


@pytest.mark.parametrize(
    "value",
    [None, "", "-", "--", "---", "nan", "NaN", "None", "null"],
)
def test_to_decimal_上游空值统一返回None(value):
    """东财用 `--`/空串表示缺失；必须收敛成 None 而不是 0。"""
    assert to_decimal(value) is None


@pytest.mark.parametrize("value", ["abc", "1.2.3", "1,234.5"])
def test_to_decimal_非法文本返回None(value):
    assert to_decimal(value) is None


# ==================== 错误模型 ====================


def test_SourceError_携带源名与失败分类():
    error = SourceError("em_lsjz", FailureKind.HTTP_403, "GET ... 返回 403")

    assert error.source == "em_lsjz"
    assert error.kind is FailureKind.HTTP_403
    assert "[em_lsjz] HTTP_403" in str(error)
    assert "403" in str(error)


def test_AllSourcesFailed_保留每个源的失败原因():
    error = AllSourcesFailed(
        "history",
        [
            {"source": "em_pingzhongdata", "kind": "TIMEOUT", "error": "15s"},
            {"source": "em_lsjz", "kind": "EMPTY_PAYLOAD", "error": "空"},
        ],
    )

    assert error.capability == "history"
    assert [item["source"] for item in error.tried] == ["em_pingzhongdata", "em_lsjz"]
    assert "em_pingzhongdata=TIMEOUT(15s)" in str(error)
    assert "em_lsjz=EMPTY_PAYLOAD(空)" in str(error)


def test_AllSourcesFailed_无候选源时给出明确说明():
    error = AllSourcesFailed("calendar", [])

    assert error.tried == []
    assert "没有可用的候选源" in str(error)


def test_失败分类_域级集合固定():
    """域级失败只有连接层问题；解析类失败绝不能熔断整个域名（§5.2）。"""
    assert DOMAIN_LEVEL_KINDS == frozenset(
        {
            FailureKind.TIMEOUT,
            FailureKind.HTTP_403,
            FailureKind.HTTP_429,
            FailureKind.HTTP_5XX,
            FailureKind.CONNECTION_ERROR,
        }
    )
    for kind in (
        FailureKind.EMPTY_PAYLOAD,
        FailureKind.PARSE_ERROR,
        FailureKind.SCHEMA_DRIFT,
        FailureKind.INVALID_REQUEST,
        FailureKind.UNEXPECTED,
    ):
        assert kind not in DOMAIN_LEVEL_KINDS


def test_BaseSource_未实现能力显式拒绝而不是返回空():
    source = _StubSource()

    with pytest.raises(NotImplementedError, match="stub"):
        source.fetch_latest_batch(["110020"])
    with pytest.raises(NotImplementedError, match="stub"):
        source.fetch_calendar()
