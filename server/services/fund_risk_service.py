"""
基金风险等级服务

读取 fund_risk_profiles 独立表（与 fund_fee_rules 费率规则解耦）。
存储内容：四维评分 + risk_level + risk_label（中文标签入库，运行时直接读，不计算）。
查询逻辑：
- get_risk_profile: 单基金查询，返回 {risk_level, risk_label, breadth_score, ...} 或 None
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class FundRiskService:
    """基金风险等级查询服务"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase
            self._client = get_supabase()
        return self._client

    # ==================== 风险等级查询 ====================

    def get_risk_profile(self, fund_code: str) -> Optional[dict]:
        """
        查询基金风险画像（单基金）。

        返回:
            {risk_level, risk_label, breadth_score, volatility_score, market_score, board_score}
            或 None（基金未分级 / 数据库不可用）
        """
        if not self.client:
            logger.error("数据库不可用")
            return None

        try:
            result = (
                self.client.table("fund_risk_profiles")
                .select("*")
                .eq("fund_code", fund_code)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]

            logger.warning(f"未找到基金风险画像: {fund_code}")
            return None
        except Exception as e:
            logger.error(f"查询基金风险画像失败: {e}")
            return None

    def get_risk_level(self, fund_code: str) -> Optional[str]:
        """获取基金风险等级（moderate/aggressive/speculative），未分级返回 None"""
        profile = self.get_risk_profile(fund_code)
        if profile:
            return profile.get("risk_level")
        return None
