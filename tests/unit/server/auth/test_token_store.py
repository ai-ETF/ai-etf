"""token_store 单元测试：内存撤销清单（登出 / 注销后 token 即时失效）。

被测行为（大白话）：
- revoke(token, exp)：把 token 记入黑名单，并记下它本来几时过期；
- is_revoked(token, now)：还没到过期时间 → True（拒绝）；
                         已到过期时间 → False，且顺手清掉该条目。

“现在几点”通过可选参数 now 注入，测试无需等待真实时间、无需 monkeypatch。
"""
import pytest

from server.auth import token_store


@pytest.fixture(autouse=True)
def _reset_blacklist():
    """每个用例前清空模块级黑名单，保证用例间互不干扰。"""
    token_store._revoked.clear()
    yield


def test_撤销后未到期_token_判定为已撤销():
    token_store.revoke("tok-1", exp=2000)
    assert token_store.is_revoked("tok-1", now=1000) is True


def test_撤销后已到期_token_判定为未撤销并被清理():
    token_store.revoke("tok-1", exp=2000)
    assert token_store.is_revoked("tok-1", now=3000) is False
    # 惰性清理生效：过期的条目已从黑名单移除，不再占内存
    assert "tok-1" not in token_store._revoked


def test_多个token互不影响():
    token_store.revoke("tok-1", exp=2000)
    token_store.revoke("tok-2", exp=4000)
    # 到 3000：tok-1 已过期被清，tok-2 仍在名单内
    assert token_store.is_revoked("tok-1", now=3000) is False
    assert token_store.is_revoked("tok-2", now=3000) is True


def test_从未撤销的token_判定为未撤销():
    assert token_store.is_revoked("tok-3", now=1000) is False
