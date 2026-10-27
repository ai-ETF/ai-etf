"""
自选股服务

提供自选股的增删查功能，使用 Supabase 存储。
user_id 来自 JWT 认证（Supabase auth.users 的 UUID），无需做格式转换。
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class WatchlistService:
    """自选股服务"""

    TABLE_NAME = "watchlist"

    def __init__(self):
        from server.storage.supabase_client import get_supabase

        self._client = get_supabase()

    def add(self, user_id: str, fund_code: str, fund_name: str = None) -> dict:
        """
        添加自选股

        参数:
            user_id: 用户 UUID（来自 JWT）
            fund_code: 基金代码
            fund_name: 基金名称（可选，未提供时自动获取）

        返回:
            {"success": bool, "message": str, "item": dict}
        """
        if not self._client:
            return {"success": False, "message": "数据库连接失败", "item": None}

        try:
            # 未提供名称时从基金主数据补（2026-10-26：不再从实时行情快照取名称）
            if not fund_name:
                from server.services.fund_meta_service import FundMetaService

                meta = FundMetaService().get(fund_code)
                if meta is not None:
                    fund_name = meta.fund_name

            # 检查是否已存在
            existing = (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .eq("user_id", user_id)
                .eq("fund_code", fund_code)
                .execute()
            )

            if existing.data:
                return {
                    "success": False,
                    "message": "该ETF已在自选列表中",
                    "item": existing.data[0],
                }

            # 插入新记录
            now = datetime.utcnow().isoformat()
            data = {
                "user_id": user_id,
                "fund_code": fund_code,
                "fund_name": fund_name or "",
                "sort_order": 0,
                "created_at": now,
                "updated_at": now,
            }

            result = self._client.table(self.TABLE_NAME).insert(data).execute()

            if result.data:
                logger.info(f"添加自选股成功: user={user_id}, code={fund_code}")
                return {
                    "success": True,
                    "message": "添加成功",
                    "item": self._format_item(result.data[0]),
                }
            else:
                return {"success": False, "message": "添加失败", "item": None}

        except Exception as e:
            logger.error(f"添加自选股失败: {e}")
            error_msg = str(e)

            if "duplicate" in error_msg.lower() or "unique" in error_msg.lower():
                return {"success": False, "message": "该ETF已在自选列表中", "item": None}

            return {"success": False, "message": f"添加失败: {error_msg}", "item": None}

    def remove(self, user_id: str, fund_code: str) -> dict:
        """
        移除自选股

        参数:
            user_id: 用户 UUID（来自 JWT）
            fund_code: 基金代码

        返回:
            {"success": bool, "message": str}
        """
        if not self._client:
            return {"success": False, "message": "数据库连接失败"}

        try:
            result = (
                self._client.table(self.TABLE_NAME)
                .delete()
                .eq("user_id", user_id)
                .eq("fund_code", fund_code)
                .execute()
            )

            if result.data:
                logger.info(f"移除自选股成功: user={user_id}, code={fund_code}")
                return {"success": True, "message": "移除成功"}
            else:
                return {"success": False, "message": "未找到该自选股"}

        except Exception as e:
            logger.error(f"移除自选股失败: {e}")
            return {"success": False, "message": f"移除失败: {str(e)}"}

    def list(self, user_id: str, include_quote: bool = True) -> dict:
        """查询自选股列表。

        参数:
            user_id: 用户 UUID（来自 JWT）
            include_quote: 是否附带最新净值（2026-10-26 起由实时行情改为
                DB 最新净值；`include_quote=False` 时不查）

        返回:
            {"total": int, "items": list}
        """
        if not self._client:
            return {"total": 0, "items": []}

        try:
            result = (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .eq("user_id", user_id)
                .order("sort_order")
                .order("created_at", desc=True)
                .execute()
            )

            items = [self._format_item(item) for item in result.data]

            if include_quote and items:
                from server.services.fund_nav_service import FundNavService

                latest = FundNavService().get_latest_batch(
                    [item["fund_code"] for item in items]
                )
                for item in items:
                    nav = latest.get(item["fund_code"])
                    if nav is not None:
                        item["nav"] = float(nav.unit_nav)
                        item["nav_date"] = nav.nav_date.isoformat()

            logger.info(f"查询自选股列表: user={user_id}, total={len(items)}")
            return {"total": len(items), "items": items}

        except Exception as e:
            logger.error(f"查询自选股列表失败: {e}")
            return {"total": 0, "items": []}

    def clear(self, user_id: str) -> dict:
        """
        清空自选股列表

        参数:
            user_id: 用户 UUID（来自 JWT）

        返回:
            {"success": bool, "message": str, "removed_count": int}
        """
        if not self._client:
            return {"success": False, "message": "数据库连接失败", "removed_count": 0}

        try:
            result = (
                self._client.table(self.TABLE_NAME)
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
            removed_count = len(result.data) if result.data else 0

            logger.info(
                f"清空自选股: user={user_id}, removed={removed_count}"
            )
            return {
                "success": True,
                "message": f"已清空 {removed_count} 个自选股",
                "removed_count": removed_count,
            }

        except Exception as e:
            logger.error(f"清空自选股失败: {e}")
            return {
                "success": False,
                "message": f"清空失败: {str(e)}",
                "removed_count": 0,
            }

    def _format_item(self, data: dict) -> dict:
        """格式化数据库记录为返回格式（净值字段由 `list()` 按需填充）"""
        return {
            "id": data.get("id", ""),
            "user_id": data.get("user_id", ""),
            "fund_code": data.get("fund_code", ""),
            "fund_name": data.get("fund_name", ""),
            "sort_order": data.get("sort_order", 0),
            "created_at": data.get("created_at", ""),
            "nav": None,
            "nav_date": None,
        }