"""
基金手续费规则服务

从 fund_fee_rules 表读取费率规则，支持两种基金类型：
- 场外基金 (fund_type=otf)：申购费（外扣法）+ 赎回费（持有天数阶梯）
- 场内ETF (fund_type=etf)：券商佣金（万2.5，最低5元）
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

        返回:
            fee_rule dict（含 fund_type 和 commission_rate）
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
        """提供默认费率规则（按2025年证监会新规）"""
        # 根据 ETF 代码前缀自动判断类型
        fund_type = 'etf' if fund_code[:2] in ('51', '15', '16', '58') else 'otf'
        return {
            "fund_code": fund_code,
            "fund_name": "",
            "fund_type": fund_type,
            "purchase_fee_rate": 0.0015,          # 申购费率 0.15%（互联网渠道1折）
            "redemption_fee_rate_7d": 0.0150,     # <7天 1.5%（惩罚性）
            "redemption_fee_rate_30d": 0.0100,    # 7-30天 1.0%
            "redemption_fee_rate_1y": 0.0050,     # 30-180天 0.5%
            "redemption_fee_rate_over1y": 0.0,    # ≥180天 0%（多数基金）
            "redemption_fee_rate_180d": 0.0025,   # 180-365天 0.25%（部分基金）
            "management_fee_rate": 0.015,
            "custody_fee_rate": 0.0025,
            "commission_rate": 0.00025,           # ETF券商佣金 万2.5
            "min_purchase_amount": 1.0,
        }

    # ==================== 基金类型 ====================

    def get_fund_type(self, fund_code: str) -> str:
        """
        获取基金类型。

        返回:
            'otf' (场外基金) 或 'etf' (场内ETF)
        """
        rule = self.get_fee_rule(fund_code)
        return rule.get("fund_type", "otf") if rule else "otf"

    # ==================== 佣金（ETF专用） ====================

    def calc_commission(self, fund_code: str, amount: float) -> float:
        """
        计算券商佣金（场内ETF专用）。

        佣金 = max(amount * commission_rate, 5.0)
        最低佣金 5 元（行业惯例）。

        参数:
            fund_code: 基金代码
            amount: 成交金额（元）

        返回:
            佣金（元）
        """
        rule = self.get_fee_rule(fund_code)
        rate = rule.get("commission_rate", 0.00025)
        fee = amount * rate
        return round(max(fee, 5.0), 2)

    # ==================== 申购费（场外基金专用） ====================

    def calc_purchase_fee(self, fund_code: str, amount: float) -> float:
        """
        计算申购费（场外基金，前端收费，外扣法）。

        ETF 返回 0（ETF 不使用申购费，用佣金）。

        外扣法：
            净申购金额 = 申购金额 / (1 + 申购费率)
            申购费用 = 申购金额 - 净申购金额
        """
        rule = self.get_fee_rule(fund_code)
        fund_type = rule.get("fund_type", "otf")
        if fund_type == 'etf':
            return 0.0
        rate = rule.get("purchase_fee_rate", 0.0015)
        if rate == 0:
            return 0.0
        net_amount = amount / (1 + rate)
        fee = amount - net_amount
        return round(fee, 2)

    # ==================== 赎回费（场外基金专用） ====================

    def calc_redemption_fee(
        self,
        fund_code: str,
        amount: float,
        hold_days: int,
    ) -> float:
        """
        计算赎回费（场外基金，按2025年证监会新规）。

        ETF 返回 0（ETF 不使用赎回费，用佣金）。

        持有天数档位：
        - < 7天：1.5%（惩罚性）
        - 7天 ~ < 30天：1.0%
        - 30天 ~ < 180天：0.5%
        - ≥ 180天：0%（多数基金）
        """
        rule = self.get_fee_rule(fund_code)
        fund_type = rule.get("fund_type", "otf")
        if fund_type == 'etf':
            return 0.0

        if hold_days < 7:
            rate = rule.get("redemption_fee_rate_7d", 0.015)
        elif hold_days < 30:
            rate = rule.get("redemption_fee_rate_30d", 0.01)
        elif hold_days < 180:
            rate = rule.get("redemption_fee_rate_1y", 0.005)
        else:
            rate = rule.get("redemption_fee_rate_over1y", 0.0)

        fee = amount * rate
        return round(fee, 2)

    # ==================== 统一费用入口 ====================

    def calc_fee_for_trade(
        self,
        fund_code: str,
        amount: float,
        direction: str,
        hold_days: int = 0,
    ) -> dict:
        """
        统一费用计算入口，按 fund_type 自动选择费用模型。

        参数:
            fund_code: 基金代码
            amount: 成交金额（元）
            direction: 'buy' 或 'sell'
            hold_days: 持有天数（仅场外基金卖出时使用）

        返回:
            {"fee": float, "fee_type": str, "fund_type": str}
            fee_type: "commission" / "purchase" / "redemption"
        """
        rule = self.get_fee_rule(fund_code)
        fund_type = rule.get("fund_type", "otf")

        if fund_type == 'etf':
            fee = self.calc_commission(fund_code, amount)
            return {"fee": fee, "fee_type": "commission", "fund_type": "etf"}
        else:
            if direction == 'buy':
                fee = self.calc_purchase_fee(fund_code, amount)
                return {"fee": fee, "fee_type": "purchase", "fund_type": "otf"}
            else:
                fee = self.calc_redemption_fee(fund_code, amount, hold_days)
                return {"fee": fee, "fee_type": "redemption", "fund_type": "otf"}

    # ==================== 简单查询 ====================

    def get_min_purchase_amount(self, fund_code: str) -> float:
        """获取最低申购金额"""
        rule = self.get_fee_rule(fund_code)
        return float(rule.get("min_purchase_amount", 1.0))

    def get_purchase_fee_rate(self, fund_code: str) -> float:
        """获取申购费率"""
        rule = self.get_fee_rule(fund_code)
        return float(rule.get("purchase_fee_rate", 0.0015))
