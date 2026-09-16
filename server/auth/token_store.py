"""
access token 内存级撤销清单

登录/注册签发的 access token 是无状态 HS256 JWT，Supabase 无法在
到期前撤销它（见 supabase_auth sign_out 文档注释）。因此登出 / 注销
后需在应用内存中维护黑名单，使已注销的 token 即时失效。

局限：清单仅存于内存，进程重启即清空，未到期的 token 会恢复有效。
本应用 token 有效期仅 1 小时，风险可接受；如需持久化可换 Redis/DB。
"""
import threading
import time

_revoked: dict[str, float] = {}  # token -> exp(epoch 秒)
_lock = threading.Lock()


def revoke(token: str, exp: float) -> None:
    """将 token 加入撤销清单，到期时间由 JWT 的 exp 决定。"""
    with _lock:
        _revoked[token] = exp


def is_revoked(token: str, now: float | None = None) -> bool:
    """判断 token 是否已被撤销，并惰性清理已过期的条目。

    now: 可注入的当前时间（epoch 秒）。测试时传入固定值即可确定性验证
    “过期清理”逻辑；为 None 时取真实时钟 time.time()（生产路径）。
    """
    current = time.time() if now is None else now
    with _lock:
        expired = [t for t, e in _revoked.items() if e <= current]
        for t in expired:
            _revoked.pop(t, None)
        return token in _revoked
