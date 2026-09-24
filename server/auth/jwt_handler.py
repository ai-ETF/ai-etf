"""
JWT 验证工具

对接 Supabase Auth：验证 Supabase 签发的 JWT access_token，
从 payload 中提取用户身份信息。

Supabase 有两种签名方式，**两种都要支持**：

- **HS256（对称）**：用项目设置里的 JWT Secret 签，密钥就是 ``SUPABASE_JWT_SECRET``。
  老项目走这条。
- **ES256 / RS256（非对称）**：用签名密钥对签，必须拿公钥验；公钥从
  ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json`` 按 token 头部的 ``kid`` 取。
  新项目，以及 supabase CLI >= 2.x（实测 2.114.0）起的本地栈，走这条。

只认 HS256 会让所有带 ``Authorization`` 的接口在非对称签名环境下**全部 401**：
2026-09-24 实测本地栈只签 ES256（CLI 硬校验只接受 RS256/ES256，且 GOTRUE_JWT_KEYS
恒被赋值，没有回退到 GOTRUE_JWT_SECRET 的分支），详见 docs/e2e/05-执行计划.md 的缺陷登记。
"""
import logging
from typing import Optional

import jwt
from jwt import PyJWKClient

from server.config.settings import SETTINGS

logger = logging.getLogger(__name__)

# 非对称签名算法白名单。
# token 头部的 alg 是**验签前**就读的、攻击者可控的字段，所以只有落在白名单里才走公钥分支；
# 其余一律交给 HS256 分支，由 jwt.decode 的 algorithms=["HS256"] 兜底拒绝（含 alg=none）。
_ASYMMETRIC_ALGS = frozenset({"ES256", "RS256"})

# JWKS 客户端按 URL 缓存，避免每个请求都去拉一遍公钥
_jwks_client: Optional[PyJWKClient] = None
_jwks_client_url: Optional[str] = None


def _jwks_uri() -> Optional[str]:
    """从本地配置拼 JWKS 地址，未配置 SUPABASE_URL 时返回 None。

    刻意**不**用 token 里的 ``iss`` 来定位公钥：那是验签前就读的、攻击者可控的字段，
    拿它去发请求等于开放 SSRF。公钥来源必须来自本地配置。
    """
    base = (SETTINGS.SUPABASE_URL or "").rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json" if base else None


def _get_jwks_client(uri: str) -> PyJWKClient:
    global _jwks_client, _jwks_client_url
    if _jwks_client is None or _jwks_client_url != uri:
        # lifespan=300：JWKS 缓存 5 分钟。密钥轮换后最多 5 分钟内自动跟上，
        # 又不至于每个未知 kid 都触发一次远端拉取（那会变成一个放大面）。
        _jwks_client = PyJWKClient(uri, cache_keys=True, lifespan=300, timeout=10)
        _jwks_client_url = uri
    return _jwks_client


def _verify_asymmetric(token: str, alg: str) -> Optional[dict]:
    """用 JWKS 里的公钥验证非对称签名（ES256 / RS256）。"""
    uri = _jwks_uri()
    if not uri:
        logger.error("未配置 SUPABASE_URL，无法取 JWKS 公钥验证 %s token", alg)
        return None

    try:
        signing_key = _get_jwks_client(uri).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            # alg 已在白名单内，公钥又来自本地配置的 JWKS，不存在算法混淆
            algorithms=[alg],
            audience="authenticated",
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        logger.warning("JWT 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT 验证失败（{alg}）: {e}")
        return None
    except jwt.PyJWKClientError as e:
        # 公钥拉不到（网络不通 / kid 不在 JWKS 里）。
        # **失败关闭**：宁可 401，也绝不放行一个没验过签的 token。
        logger.error(f"取 JWKS 公钥失败（{uri}）: {e}")
        return None


def verify_supabase_token(token: str, secret: Optional[str] = None) -> Optional[dict]:
    """
    验证 Supabase JWT，返回 payload。

    按 token 头部的 ``alg`` 分派：非对称（ES256/RS256）走 JWKS 公钥验签，
    其余走 HS256 对称验签。payload 中的关键字段：
    - sub: 用户 UUID（Supabase auth.users 表的主键）
    - exp: 过期时间
    - role: 用户角色（通常为 "authenticated"）

    Args:
        token: JWT 字符串（不含 "Bearer " 前缀）
        secret: HS256 验签密钥。测试时传入固定 secret 可确定性验证；
                为 None 时回退到 SETTINGS.SUPABASE_JWT_SECRET（生产路径）。
                非对称签名不使用此参数，公钥一律从 SETTINGS.SUPABASE_URL 拼出的 JWKS 取。

    Returns:
        验证成功返回 payload dict，失败返回 None
    """
    try:
        header = jwt.get_unverified_header(token)
    except (jwt.InvalidTokenError, ValueError) as e:
        logger.warning(f"JWT 头部无法解析: {e}")
        return None

    alg = header.get("alg")
    if alg in _ASYMMETRIC_ALGS:
        return _verify_asymmetric(token, alg)

    secret = secret or SETTINGS.SUPABASE_JWT_SECRET
    if not secret:
        logger.error("未配置 SUPABASE_JWT_SECRET，无法验证 JWT")
        return None

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_exp": True},  # 验证过期时间
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT 验证失败: {e}")
        logger.debug(f"Secret 长度: {len(secret)} 字符")
        return None
