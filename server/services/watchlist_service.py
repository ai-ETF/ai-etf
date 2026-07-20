"""
自选股服务

提供自选股的增删查功能，使用 Supabase 存储。
首次使用时会自动创建 watchlist 表。
"""

import os
import logging
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class WatchlistService:
    """自选股服务"""

    TABLE_NAME = "watchlist"

    def __init__(self):
        self._client = None
        self._ensure_table()

    @property
    def client(self):
        """延迟初始化 Supabase 客户端"""
        if self._client is None:
            from server.storage.supabase_client import get_supabase
            self._client = get_supabase()
        return self._client

    def _ensure_table(self):
        """确保 watchlist 表存在（如不存在则提示用户手动创建）"""
        self._create_table_if_not_exists()

    def _create_table_if_not_exists(self):
        """创建 watchlist 表（如果不存在）"""
        if not self.client:
            logger.error("Supabase 客户端未初始化")
            return False

        try:
            # 尝试查询表，如果不存在会抛出异常
            self.client.table(self.TABLE_NAME).select("id").limit(1).execute()
            return True
        except Exception as e:
            error_msg = str(e)
            if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
                logger.info(f"watchlist 表不存在，尝试创建...")
                return self._create_table_via_sql()
            # 其他错误，可能表已存在
            return True

    def _create_table_via_sql(self) -> bool:
        """通过 RPC 或直接 SQL 创建表"""
        # Supabase 不能直接通过 Python SDK 执行 DDL
        # 需要用户在 Supabase 控制台手动创建，或者我们用 RPC
        logger.warning("""
自选股功能需要先在 Supabase 创建表，请执行以下 SQL：

CREATE TABLE IF NOT EXISTS watchlist (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100),
  sort_order INT DEFAULT 0,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  UNIQUE(user_id, fund_code)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_code ON watchlist(fund_code);
""")
        return False

    def _resolve_user_id(self, user_id: str) -> str:
        """
        将用户ID统一转为UUID格式
        - 如果已经是UUID格式，直接返回
        - 如果是简单字符串（如 test-user-001），生成稳定UUID
        """
        import uuid as uuid_mod
        try:
            uuid_mod.UUID(user_id)
            return user_id
        except (ValueError, AttributeError):
            resolved = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, f"user_{user_id}"))
            logger.debug(f"user_id '{user_id}' 转换为UUID: {resolved}")
            return resolved

    def add(self, user_id: str, fund_code: str, fund_name: str = None) -> dict:
        """
        添加自选股

        参数:
            user_id: 用户ID
            fund_code: 基金代码
            fund_name: 基金名称（可选）

        返回:
            {"success": bool, "message": str, "item": dict}
        """
        if not self.client:
            return {"success": False, "message": "数据库连接失败", "item": None}

        try:
            # 如果没有提供名称，尝试获取
            if not fund_name:
                from server.services.finance_api_service import FinanceApiService
                svc = FinanceApiService()
                spot_data = svc.query_spot(fund_code)
                if spot_data:
                    fund_name = spot_data.get("name", "")

            # 统一转换成UUID
            actual_user_id = self._resolve_user_id(user_id)

            # 检查是否已存在
            existing = self.client.table(self.TABLE_NAME).select("*").eq("user_id", actual_user_id).eq("fund_code", fund_code).execute()

            if existing.data:
                return {
                    "success": False,
                    "message": "该ETF已在自选列表中",
                    "item": existing.data[0]
                }

            # 插入新记录
            data = {
                "user_id": actual_user_id,
                "fund_code": fund_code,
                "fund_name": fund_name,
                "sort_order": 0,
            }

            result = self.client.table(self.TABLE_NAME).insert(data).execute()

            if result.data:
                logger.info(f"添加自选股成功: user={user_id}, code={fund_code}")
                return {
                    "success": True,
                    "message": "添加成功",
                    "item": self._format_item(result.data[0])
                }
            else:
                return {"success": False, "message": "添加失败", "item": None}

        except Exception as e:
            logger.error(f"添加自选股失败: {e}")
            error_msg = str(e)

            # 检查是否是表不存在
            if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
                self._create_table_via_sql()
                return {"success": False, "message": "自选股表未创建，请先执行SQL创建表", "item": None}

            # 检查是否是重复
            if "duplicate" in error_msg.lower() or "unique" in error_msg.lower():
                return {"success": False, "message": "该ETF已在自选列表中", "item": None}

            return {"success": False, "message": f"添加失败: {error_msg}", "item": None}

    def remove(self, user_id: str, fund_code: str) -> dict:
        """
        移除自选股

        参数:
            user_id: 用户ID
            fund_code: 基金代码

        返回:
            {"success": bool, "message": str}
        """
        if not self.client:
            return {"success": False, "message": "数据库连接失败"}

        try:
            actual_user_id = self._resolve_user_id(user_id)
            result = self.client.table(self.TABLE_NAME).delete().eq("user_id", actual_user_id).eq("fund_code", fund_code).execute()

            if result.data:
                logger.info(f"移除自选股成功: user={user_id}, code={fund_code}")
                return {"success": True, "message": "移除成功"}
            else:
                return {"success": False, "message": "未找到该自选股"}

        except Exception as e:
            logger.error(f"移除自选股失败: {e}")
            return {"success": False, "message": f"移除失败: {str(e)}"}

    def list(self, user_id: str, include_quote: bool = True) -> dict:
        """
        查询自选股列表

        参数:
            user_id: 用户ID
            include_quote: 是否包含实时行情

        返回:
            {"total": int, "items": list}
        """
        if not self.client:
            return {"total": 0, "items": []}

        try:
            actual_user_id = self._resolve_user_id(user_id)
            result = self.client.table(self.TABLE_NAME).select("*").eq("user_id", actual_user_id).order("sort_order").order("created_at", desc=True).execute()

            items = [self._format_item(item) for item in result.data]

            # 如果需要实时行情
            if include_quote and items:
                from server.services.finance_api_service import FinanceApiService
                svc = FinanceApiService()

                fund_codes = [item["fund_code"] for item in items]
                quotes = {}  # code -> quote_data

                # 批量获取行情
                for code in fund_codes:
                    quote = svc.query_spot(code)
                    if quote:
                        quotes[code] = quote

                # 填充行情数据
                for item in items:
                    quote = quotes.get(item["fund_code"])
                    if quote:
                        item["price"] = quote.get("price")
                        item["change_pct"] = quote.get("change_pct")
                        item["change"] = quote.get("change")

            logger.info(f"查询自选股列表: user={user_id}, total={len(items)}")
            return {"total": len(items), "items": items}

        except Exception as e:
            logger.error(f"查询自选股列表失败: {e}")
            return {"total": 0, "items": []}

    def clear(self, user_id: str) -> dict:
        """
        清空自选股列表

        参数:
            user_id: 用户ID

        返回:
            {"success": bool, "message": str, "removed_count": int}
        """
        if not self.client:
            return {"success": False, "message": "数据库连接失败", "removed_count": 0}

        try:
            actual_user_id = self._resolve_user_id(user_id)
            result = self.client.table(self.TABLE_NAME).delete().eq("user_id", actual_user_id).execute()
            removed_count = len(result.data) if result.data else 0

            logger.info(f"清空自选股: user={user_id}, removed={removed_count}")
            return {"success": True, "message": f"已清空 {removed_count} 个自选股", "removed_count": removed_count}

        except Exception as e:
            logger.error(f"清空自选股失败: {e}")
            return {"success": False, "message": f"清空失败: {str(e)}", "removed_count": 0}

    def _format_item(self, data: dict) -> dict:
        """格式化数据库记录为返回格式"""
        return {
            "id": data.get("id", ""),
            "user_id": data.get("user_id", ""),
            "fund_code": data.get("fund_code", ""),
            "fund_name": data.get("fund_name", ""),
            "sort_order": data.get("sort_order", 0),
            "created_at": data.get("created_at", ""),
            "price": None,
            "change_pct": None,
            "change": None,
        }