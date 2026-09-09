"""jwt_handler 单元测试：本地校验 Supabase JWT（HS256）。

被测行为 verify_supabase_token(token, secret)：
- 合法未过期 + 正确 secret → 返回 payload，含 sub；
- secret 不匹配（token 被篡改/伪造） → None；
- 已过期 → None；
- secret 为空（未配置） → None。

造“合法 token”用同一 secret 在本地自签（pyjwt 纯本地解密，不联网）。
"""
import time

import jwt
import pytest

from server.auth.jwt_handler import verify_supabase_token
from server.config.settings import SETTINGS

# 测试密钥需 >= 32 字节，避免 pyjwt 的 InsecureKeyLengthWarning
TEST_SECRET = "unit-test-secret-0123456789abcdef0123456789"
WRONG_SECRET = "unit-test-wrong-secret-0123456789abcdefgh"


def _claims(sub: str = "user-123", exp_offset: float = 3600) -> dict:
    """构造一份接近 Supabase 签发的 claims。"""
    now = time.time()
    return {
        "sub": sub,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": now,
        "exp": now + exp_offset,
    }


def _sign(payload: dict, secret: str) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


def test_合法token_返回payload并含sub():
    token = _sign(_claims(), TEST_SECRET)
    payload = verify_supabase_token(token, secret=TEST_SECRET)
    assert payload is not None
    assert payload["sub"] == "user-123"


def test_secret不匹配_返回None():
    token = _sign(_claims(), TEST_SECRET)
    assert verify_supabase_token(token, secret=WRONG_SECRET) is None


def test_已过期token_返回None():
    token = _sign(_claims(exp_offset=-3600), TEST_SECRET)
    assert verify_supabase_token(token, secret=TEST_SECRET) is None


def test_未配置secret_返回None(monkeypatch):
    monkeypatch.setattr(SETTINGS, "SUPABASE_JWT_SECRET", None)
    token = _sign(_claims(), TEST_SECRET)
    assert verify_supabase_token(token) is None
