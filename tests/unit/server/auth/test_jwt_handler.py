"""jwt_handler 单元测试：本地校验 Supabase JWT。

分两组：

HS256（对称）—— 被测行为 verify_supabase_token(token, secret)：
- 合法未过期 + 正确 secret → 返回 payload，含 sub；
- secret 不匹配（token 被篡改/伪造） → None；
- 已过期 → None；
- secret 为空（未配置） → None。

ES256（非对称）—— 被测行为 verify_supabase_token(token)：
- JWKS 里有对应 kid 的公钥且签名匹配 → 返回 payload；
- 签名不匹配（换了一把私钥） → None；
- kid 不在 JWKS 里 → None；
- JWKS 拉不到 → None（失败关闭，不放行未验签的 token）；
- 未配置 SUPABASE_URL → None；
- alg=none 的裸 token → None（不能被降级绕过）。

造 token 一律本地自签（pyjwt 纯本地加解密，不联网）；ES256 那组把
jwt_handler.PyJWKClient 换成假客户端喂固定的 JWKS，避免真发 HTTP。
"""
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

import server.auth.jwt_handler as jwt_handler
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


# ---------------------------------------------------------------------------
# ES256（非对称）—— 新项目 / supabase CLI >= 2.x 的本地栈走这条
# ---------------------------------------------------------------------------

ES256_KID = "unit-test-kid-es256"
SUPABASE_URL = "http://127.0.0.1:54321"


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    """jwt_handler 模块级缓存了 JWKS 客户端，用例之间必须隔离，否则互相污染。"""
    jwt_handler._jwks_client = None
    jwt_handler._jwks_client_url = None
    yield
    jwt_handler._jwks_client = None
    jwt_handler._jwks_client_url = None


def _ec_private_key():
    return ec.generate_private_key(ec.SECP256R1())


def _public_jwk(public_key) -> dict:
    jwk = json.loads(ECAlgorithm.to_jwk(public_key))
    jwk["kid"] = ES256_KID
    return jwk


def _sign_es256(payload: dict, private_key, kid: str = ES256_KID) -> str:
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": kid})


class _FakeJWK:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """替掉 PyJWKClient：不发 HTTP，按 kid 从固定 JWKS 里取公钥。"""

    jwks: list[dict] = []

    def __init__(self, uri: str, **_kwargs):
        self.uri = uri

    def get_signing_key_from_jwt(self, token: str):
        kid = jwt.get_unverified_header(token).get("kid")
        for jwk in self.jwks:
            if jwk.get("kid") == kid:
                return _FakeJWK(ECAlgorithm.from_jwk(json.dumps(jwk)))
        raise jwt.PyJWKClientError(f"Unable to find a signing key that matches: {kid!r}")


@pytest.fixture
def es256_env(monkeypatch):
    """签一对 EC 密钥，把假 JWKS 客户端装进 jwt_handler，并配好 SUPABASE_URL。"""
    private_key = _ec_private_key()
    _FakeJWKSClient.jwks = [_public_jwk(private_key.public_key())]
    monkeypatch.setattr(jwt_handler, "PyJWKClient", _FakeJWKSClient)
    monkeypatch.setattr(SETTINGS, "SUPABASE_URL", SUPABASE_URL)
    return private_key


def test_非对称ES256_从JWKS取公钥验证通过(es256_env):
    token = _sign_es256(_claims(), es256_env)
    payload = verify_supabase_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"


def test_非对称ES256_签名不匹配_返回None(es256_env):
    # 换一把私钥签，JWKS 里仍是原来那把的公钥
    token = _sign_es256(_claims(), _ec_private_key())
    assert verify_supabase_token(token) is None


def test_非对称ES256_已过期_返回None(es256_env):
    token = _sign_es256(_claims(exp_offset=-3600), es256_env)
    assert verify_supabase_token(token) is None


def test_非对称ES256_kid不在JWKS_返回None(es256_env):
    token = _sign_es256(_claims(), es256_env, kid="unknown-kid")
    assert verify_supabase_token(token) is None


def test_非对称ES256_JWKS拉不到_失败关闭(es256_env, monkeypatch):
    """公钥取不到时必须 401，绝不能放行未验签的 token。"""

    def _boom(uri, **_kwargs):
        raise jwt.PyJWKClientError("connection refused")

    monkeypatch.setattr(jwt_handler, "PyJWKClient", _boom)
    token = _sign_es256(_claims(), es256_env)
    assert verify_supabase_token(token) is None


def test_非对称ES256_未配置SUPABASE_URL_返回None(es256_env, monkeypatch):
    monkeypatch.setattr(SETTINGS, "SUPABASE_URL", None)
    token = _sign_es256(_claims(), es256_env)
    assert verify_supabase_token(token) is None


def test_alg为none不被降级放行():
    """alg=none 的裸 token 必须落进 HS256 分支被拒，不能绕过验签。"""
    token = jwt.encode(_claims(), key=None, algorithm="none")
    assert verify_supabase_token(token, secret=TEST_SECRET) is None
