"""
基金手续费规则服务

从 fund_fee_rules 表读取场外基金的申购/赎回费率规则。
支持按基金代码查询费率，根据持有天数计算赎回费率。
"""
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


class FundFeeService:
    """基金手续费规则服务"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase
            self._client = get_supabase()
        return self._client

    def get_fee_rule(self, fund_code: str) -> Optional[dict]:
        """
        查询基金的费率规则。

        参数:
            fund_code: 基金代码

        返回:
            fee_rule dict 或 None（不存在时返回默认费率）
        """
        if not self.client:
            logger.warning("数据库不可用，使用默认费率")
            return self._default_rule(fund_code)

        try:
            result = (
                self.client.table("fund_fee_rules")
                .select("*")
                .eq("fund_code", fund_code)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            logger.warning(f"未找到基金费率规则: {fund_code}，使用默认费率")
            return self._default_rule(fund_code)
        except Exception as e:
            logger.error(f"查询费率规则失败: {e}")
            return self._default_rule(fund_code)

    @staticmethod
    def _default_rule(fund_code: str) -> dict:
        """提供默认费率规则"""
        return {
            "fund_code": fund_code,
            "fund_name": "",
            "purchase_fee_rate": 0.0015,
            "redemption_fee_rate_7d": 0.0150,
            "redemption_fee_rate_30d": 0.0075,
            "redemption_fee_rate_1y": 0.0050,
            "redemption_fee_rate_over1y": 0.0,
            "management_fee_rate": 0.015,
            "custody_fee_rate": 0.0025,
            "min_purchase_amount": 1.0,
        }

    def calc_purchase_fee(self, fund_code: str, amount: float) -> float:
        """
        计算申购费（前端收费：申购费 = 申购金额 × 申购费率）

        参数:
            fund_code: 基金代码
            amount: 申购金额（元）

        返回:
            申购费（元）
        """
        rule = self.get_fee_rule(fund_code)
        rate = rule.get("purchase_fee_rate", 0.0015)
        fee = amount * rate
        return round(fee, 2)

    def calc_redemption_fee(
        self,
        fund_code: str,
        amount: float,
        hold_days: int,
    ) -> float:
        """
        计算赎回费。

        参数:
            fund_code: 基金代码
            amount: 赎回金额（元）
            hold_days: 持有天数

        返回:
            赎回费（元）
        """
        rule = self.get_fee_rule(fund_code)

        if hold_days < 7:
            rate = rule.get("redemption_fee_rate_7d", 0.015)
        elif hold_days < 30:
            rate = rule.get("redemption_fee_rate_30d", 0.0075)
        elif hold_days < 365:
            rate = rule.get("redemption_fee_rate_1y", 0.005)
        else:
            rate = rule.get("redemption_fee_rate_over1y", 0.0)

        fee = amount * rate
        return round(fee, 2)

    def get_min_purchase_amount(self, fund_code: str) -> float:
        """获取最低申购金额"""
        rule = self.get_fee_rule(fund_code)
        return float(rule.get("min_purchase_amount", 1.0))

    def get_purchase_fee_rate(self, fund_code: str) -> float:
        """获取申购费率"""
        rule = self.get_fee_rule(fund_code)
        return float(rule.get("purchase_fee_rate", 0.0015))
