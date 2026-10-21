"""自解析 HTTP 取数基类单元测试。

模块名称：server/sources/http.py
所测功能：状态码 → `FailureKind` 映射、网络异常归一化、超时透传、
         JSON 解析失败分类、响应编码设置。
测试方法：子类覆盖 `session` 属性注入 `FakeSession` / `FakeResponse`；
         不联网、不连数据库。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.5 / §5.2。
"""
import pytest
import requests

from server.sources.http import HttpSource
from server.sources.models import FailureKind, SourceError, SourceMeta


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None, json_exc=None):
        self.status_code = status_code
        self.text = text
        self.encoding = None
        self._json_data = json_data
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls: list = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        if self.exc is not None:
            raise self.exc
        return self.response


class StubHttpSource(HttpSource):
    meta = SourceMeta(
        name="stub",
        domain="d.example.com",
        capabilities=frozenset({"history"}),
        timeout=7.5,
    )

    def __init__(self, session):
        super().__init__()
        self.fake_session = session

    @property
    def session(self):
        return self.fake_session


def _get(source, url="https://d.example.com/x", **kwargs):
    return source._get(url, **kwargs)


# ==================== 正常数据 ====================


def test_200返回文本并透传参数与超时():
    session = FakeSession(FakeResponse(text='var fS_name = "测试基金";'))
    source = StubHttpSource(session)

    text = source._get_text(
        "https://fund.eastmoney.com/pingzhongdata/110020.js",
        params={"a": "1"},
        headers={"Referer": "https://fund.eastmoney.com/"},
    )

    assert text == 'var fS_name = "测试基金";'
    assert session.calls[0] == {
        "url": "https://fund.eastmoney.com/pingzhongdata/110020.js",
        "params": {"a": "1"},
        "headers": {"Referer": "https://fund.eastmoney.com/"},
        "timeout": 7.5,
    }


def test_200返回JSON():
    session = FakeSession(FakeResponse(json_data={"Data": {"DWJZ": "1.7219"}}))
    source = StubHttpSource(session)

    assert source._get_json("https://api.example.com/x") == {"Data": {"DWJZ": "1.7219"}}


def test_响应编码被统一设置为utf8():
    response = FakeResponse(text="中文")
    source = StubHttpSource(FakeSession(response))

    _get(source)

    assert response.encoding == "utf-8"


# ==================== 异常：HTTP 状态码 ====================


@pytest.mark.parametrize(
    "status,kind",
    [
        (403, FailureKind.HTTP_403),
        (429, FailureKind.HTTP_429),
        (500, FailureKind.HTTP_5XX),
        (503, FailureKind.HTTP_5XX),
        (404, FailureKind.INVALID_REQUEST),
    ],
)
def test_状态码映射到失败分类(status, kind):
    source = StubHttpSource(FakeSession(FakeResponse(status_code=status)))

    with pytest.raises(SourceError) as excinfo:
        _get(source)

    assert excinfo.value.kind is kind
    assert str(status) in excinfo.value.message


def test_403错误信息标明域名被拒():
    source = StubHttpSource(FakeSession(FakeResponse(status_code=403)))

    with pytest.raises(SourceError) as excinfo:
        _get(source)

    assert "域名被拒" in excinfo.value.message


# ==================== 异常：网络层 ====================


def test_超时转成TIMEOUT并带超时值():
    source = StubHttpSource(FakeSession(exc=requests.Timeout("read timed out")))

    with pytest.raises(SourceError) as excinfo:
        _get(source)

    assert excinfo.value.kind is FailureKind.TIMEOUT
    assert "7.5s" in excinfo.value.message


def test_连接失败转成CONNECTION_ERROR():
    source = StubHttpSource(
        FakeSession(exc=requests.ConnectionError("RemoteDisconnected"))
    )

    with pytest.raises(SourceError) as excinfo:
        _get(source)

    assert excinfo.value.kind is FailureKind.CONNECTION_ERROR
    assert "连接失败" in excinfo.value.message


def test_其它请求异常也归为CONNECTION_ERROR():
    source = StubHttpSource(FakeSession(exc=requests.RequestException("boom")))

    with pytest.raises(SourceError) as excinfo:
        _get(source)

    assert excinfo.value.kind is FailureKind.CONNECTION_ERROR
    assert "RequestException" in excinfo.value.message


def test_JSON解析失败记PARSE_ERROR():
    source = StubHttpSource(
        FakeSession(FakeResponse(json_exc=ValueError("Expecting value")))
    )

    with pytest.raises(SourceError) as excinfo:
        source._get_json("https://api.example.com/x")

    assert excinfo.value.kind is FailureKind.PARSE_ERROR
    assert "不是合法 JSON" in excinfo.value.message
