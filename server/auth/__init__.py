"""
认证模块

提供 JWT 验证功能，对接 Supabase Auth。
"""
from .jwt_handler import verify_supabase_token

__all__ = ["verify_supabase_token"]
