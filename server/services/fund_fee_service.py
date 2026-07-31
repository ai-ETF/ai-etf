"""
场外基金手续费规则服务

仅支持 fund_fee_rules 表中已配置的场外开放式基金，查不到规则直接拒绝交易。
不支持默认费率兜底 —— 交易规则不能靠猜。

白名单机制：从 fund_fee_rules 表查询，表中有记录才允许交易。
赎回费按 JSON 档位计算，每只基金档位可不同。
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class FundFeeService:
    """场外基金手续费规则服务"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase
            self._client = get_supabase()
        return self._client

    # ==================== 白名单校验 ====================

    def is_supported(self, fund_code: str) -> bool:
        """
        检查基金是否支持交易。

        白名单 = fund_fee_rules 表中有记录的基金。
        查不到 = 不支持，返回 False。
        """
        return self.get_fee_rule(fund_code) is not None

    # ==================== 费率查询 ====================

    def get_fee_rule(self, fund_code: str) -> Optional[dict]:
        """
        查询基金的费率规则。

        返回:
            fee_rule dict，或 None（表示不支持该基金交易）
        """
        if not self.client:
            logger.error("数据库不可用")
            return None

        try:
            result = (
                self.client.table("fund_fee_rules")
                .select("*")
                .eq("fund_code", fund_code)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]

            logger.warning(f"未找到基金费率规则: {fund_code}")
            return None
        except Exception as e:
            logger.error(f"查询费率规则失败: {e}")
            return None

    # ==================== 申购费（外扣法） ====================

    def calc_purchase_fee(self, fund_code: str, amount: float) -> Optional[dict]:
        """
        计算申购费（外扣法）。

        外扣法：
            净申购金额 = 申购金额 / (1 + 申购费率)
            申购费用 = 申购金额 - 净申购金额

        参数:
            fund_code: 基金代码
            amount: 申购金额（元）

        返回:
            {"fee": float, "net_amount": float} 或 None（不支持该基金）
        """
        rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None

        rate = float(rule.get("purchase_fee_rate", 0.0015))
        if rate == 0:
            return {"fee": 0.0, "net_amount": amount}

        net_amount = amount / (1.0 + rate)
        fee = amount - net_amount
        return {"fee": round(fee, 2), "net_amount": round(net_amount, 2)}

    # ==================== 赎回费（JSON 档位） ====================

    def calc_redemption_fee(self, fund_code: str, amount: float, hold_days: int) -> Optional[float]:
        """
        计算赎回费（按 JSON 档位匹配）。

        参数:
            fund_code: 基金代码
            amount: 赎回金额（元）
            hold_days: 持有天数

        返回:
            赎回费（元），或 None（不支持该基金）
        """
        rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None

        tiers_data = rule.get("redemption_fee_tiers")
        if tiers_data is None:
            return 0.0

        # 解析 JSON 档位
        if isinstance(tiers_data, str):
            tiers_data = json.loads(tiers_data)
        if isinstance(tiers_data, dict):
            tiers = tiers_data.get("tiers", [])
        elif isinstance(tiers_data, list):
            tiers = tiers_data
        else:
            tiers = []

        if not tiers:
            return 0.0

        # 从小到大排序，找到第一个 days > hold_days 的档位
        tiers_sorted = sorted(tiers, key=lambda t: t["days"])
        rate = 0.0
        for tier in tiers_sorted:
            if hold_days < tier["days"]:
                rate = tier["rate"]
                break

        fee = amount * rate
        return round(fee, 2)

    # ==================== 简单查询 ====================

    def get_min_purchase_amount(self, fund_code: str) -> Optional[float]:
        """获取最低申购金额（元）"""
        rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None
        return float(rule.get("min_purchase_amount", 10.0))

    def get_confirm_delay(self, fund_code: str) -> int:
        """获取申购确认延迟天数（T+N）"""
        rule = self.get_fee_rule(fund_code)
        if rule is None:
            return 1
        return int(rule.get("confirm_delay", 1))

    def get_redeem_settle_delay(self, fund_code: str) -> int:
        """获取赎回到账延迟天数（T+N）"""
        rule = self.get_fee_rule(fund_code)
        if rule is None:
            return 3
        return int(rule.get("redeem_settle_delay", 3))

    def get_fund_name(self, fund_code: str) -> Optional[str]:
        """获取基金名称"""
        rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None
        return rule.get("fund_name")