"""
场外基金手续费规则服务

仅支持 fund_fee_rules 表中已配置的场外开放式基金，查不到规则直接拒绝交易。
不支持默认费率兜底 —— 交易规则不能靠猜。

白名单机制：从 fund_fee_rules 表查询，表中有记录才允许交易。
赎回费按 JSON 档位计算，每只基金档位可不同。
申购费按 JSON 金额分档计算，支持不同金额不同费率。
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# 场外基金列表接口的字段集（不含两个费率分档 JSON，避免列表响应过大；
# 分档明细走 get_fee_rule / 详情接口）
FUND_SUMMARY_FIELDS = (
    "fund_code, fund_name, fund_type, share_class, min_purchase_amount, "
    "max_purchase_amount, subscribe_status, confirm_delay, redeem_settle_delay, "
    "management_fee_rate, custody_fee_rate, sales_service_fee_rate"
)

MAX_PAGE_SIZE = 100

# ==================== 申购状态（fund_fee_rules.subscribe_status）====================
# 取值来自天天基金 jjfl 页「交易状态」小节的「申购状态」行
# （server/services/fund_fee_source.py 的 fetch_jjfl 解析；移动端接口的 SGZT 未被采用）。
# 定义放在这里：同步侧（fund_catalog_sync）与交易侧（portfolio_service）都要用，
# 而本模块是两者共同依赖的「费率规则语义」模块。
OPEN_SUBSCRIBE_STATUS = "开放申购"
LIMITED_SUBSCRIBE_STATUS = "限大额"

# 只有这两种状态接受申购；其余（暂停申购/封闭期/认购期/…）只允许赎回。
# 注意 subscribe_status 为 NULL 的是迁移前的存量行，按开放申购兼容处理 ——
# 所以这里判断的是「非空且不在集合内」，而不是「不在集合内」。
PURCHASABLE_SUBSCRIBE_STATUSES = (OPEN_SUBSCRIBE_STATUS, LIMITED_SUBSCRIBE_STATUS)


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
        查询基金的费率规则。单基金查询用此方法。

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

    def get_fee_rules_batch(self, fund_codes: list) -> dict:
        """
        批量查询基金费率规则。一次 Supabase 请求查询所有基金。

        参数:
            fund_codes: 基金代码列表（会去重）

        返回:
            {fund_code: fee_rule dict} 的 dict，查不到的基金不在 dict 中
        """
        if not self.client:
            logger.error("数据库不可用")
            return {}

        codes = list(set(fund_codes))  # 去重
        if not codes:
            return {}

        try:
            result = (
                self.client.table("fund_fee_rules")
                .select("*")
                .in_("fund_code", codes)
                .execute()
            )
            rules = {}
            if result.data:
                for row in result.data:
                    code = row.get("fund_code")
                    if code:
                        rules[code] = row
            logger.debug(f"批量查询费率: {len(codes)} 只基金 → {len(rules)} 条结果")
            return rules
        except Exception as e:
            logger.error(f"批量查询费率规则失败: {e}")
            return {}

    # ==================== 白名单列表查询（可交易基金目录） ====================

    def list_supported_funds(self, keyword: Optional[str] = None,
                             page: int = 1, page_size: int = 20) -> dict:
        """
        分页查询白名单内可交易的场外基金（fund_type='of'），供前端选基金。

        参数:
            keyword: 关键词，匹配基金代码或名称（模糊，不区分大小写）；为空则返回全部
            page: 页码，从 1 开始
            page_size: 每页条数（上限 MAX_PAGE_SIZE）

        返回:
            {"total": int, "items": [fee_rule dict + 风险字段]}
        """
        if not self.client:
            logger.error("数据库不可用")
            return {"total": 0, "items": []}

        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        start = (page - 1) * page_size

        try:
            query = (
                self.client.table("fund_fee_rules")
                .select(FUND_SUMMARY_FIELDS, count="exact")
                .eq("fund_type", "of")
            )
            kw = self._sanitize_keyword(keyword)
            if kw:
                # PostgREST 的 or_ 过滤：代码或名称模糊匹配
                query = query.or_(f"fund_code.ilike.%{kw}%,fund_name.ilike.%{kw}%")
            query = query.order("fund_code").range(start, start + page_size - 1)

            result = query.execute()
            items = result.data or []
            total = result.count if result.count is not None else len(items)
            self._attach_risk(items)
            logger.debug(f"基金目录查询: keyword={keyword!r} page={page} → {len(items)}/{total}")
            return {"total": total, "items": items}
        except Exception as e:
            logger.error(f"查询基金目录失败: {e}")
            return {"total": 0, "items": []}

    def get_fund_detail(self, fund_code: str) -> Optional[dict]:
        """
        查询单只基金的完整交易规则（含费率分档 + 风险画像）。

        返回: fee_rule dict（附加风险字段），查不到返回 None
        """
        rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None
        self._attach_risk([rule])
        return rule

    @staticmethod
    def _sanitize_keyword(keyword: Optional[str]) -> str:
        """
        清理搜索关键词。

        PostgREST 的 or_ 过滤器用逗号/括号分隔表达式，关键词里若含这些字符
        会破坏过滤语法，故统一剔除，只保留字母数字与中文。
        """
        if not keyword:
            return ""
        return re.sub(r"[^\w一-鿿]", "", str(keyword).strip())

    def _attach_risk(self, items: list):
        """给基金行批量附加风险画像字段。查不到的基金不加字段（不臆造风险等级）。"""
        codes = [i["fund_code"] for i in items if i.get("fund_code")]
        if not codes:
            return
        try:
            result = (
                self.client.table("fund_risk_profiles")
                .select("fund_code, breadth_score, volatility_score, market_score, "
                        "board_score, risk_level, risk_label")
                .in_("fund_code", codes)
                .execute()
            )
        except Exception as e:
            logger.error(f"批量查询风险画像失败: {e}")
            return
        risk_by_code = {r["fund_code"]: r for r in (result.data or [])}
        for item in items:
            risk = risk_by_code.get(item.get("fund_code"))
            if not risk:
                continue
            item["breadth_score"] = risk.get("breadth_score")
            item["volatility_score"] = risk.get("volatility_score")
            item["market_score"] = risk.get("market_score")
            item["board_score"] = risk.get("board_score")
            item["risk_level"] = risk.get("risk_level")
            item["risk_label"] = risk.get("risk_label")

    # ==================== 申购费（外扣法，金额分档） ====================

    def calc_purchase_fee(self, fund_code: str, amount: float,
                          rule: Optional[dict] = None) -> Optional[dict]:
        """
        计算申购费（外扣法，按金额分档，支持固定费用）。

        外扣法（比例费率）：
            净申购金额 = 申购金额 / (1 + 申购费率)
            申购费用 = 申购金额 - 净申购金额

        固定费用（如 ≥1000万 每笔1000元）：
            fee = fixed_fee, net_amount = amount - fixed_fee

        参数:
            fund_code: 基金代码
            amount: 申购金额（元）
            rule: 已查询的费率规则（可选，传入则避免重复查询）

        返回:
            {"fee": float, "net_amount": float} 或 None（不支持该基金）
        """
        if rule is None:
            rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None

        # 按金额分档匹配
        tiers_data = rule.get("purchase_fee_tiers")
        if isinstance(tiers_data, str):
            tiers_data = json.loads(tiers_data)
        if not tiers_data:
            # 规则缺失/为空即拒绝 —— 不允许按默认费率兜底（交易规则不能靠猜）
            logger.error(f"基金 {fund_code} 缺少 purchase_fee_tiers，拒绝计算申购费")
            return None

        tier = self._match_purchase_tier(tiers_data, amount)
        rate = float(tier.get("rate") or 0)
        fixed_fee = float(tier.get("fixed_fee") or 0)

        # 固定费用模式
        if fixed_fee > 0:
            return {"fee": fixed_fee, "net_amount": amount - fixed_fee}

        if rate == 0:
            return {"fee": 0.0, "net_amount": amount}

        net_amount = amount / (1.0 + rate)
        fee = amount - net_amount
        return {"fee": round(fee, 2), "net_amount": round(net_amount, 2)}

    @staticmethod
    def _match_purchase_tier(tiers: list, amount: float) -> dict:
        """
        按申购金额匹配费率档位，返回匹配到的档位 dict。

        tiers 结构: [{"amount": N, "rate": R, "fixed_fee": F, "inclusive": bool}]
        - amount: 金额分界点（可选；不提供表示匹配所有金额，如 C 类全免申购费）
        - rate: 比例费率（与 fixed_fee 互斥，优先 fixed_fee）
        - fixed_fee: 固定费用（如每笔1000元），存在则忽略 rate
        - inclusive=false（默认）: amount < tier.amount 时命中
        - inclusive=true: amount <= tier.amount 时命中（用于最后一档兜底）

        匹配不到任何档位时返回最后一档。
        """
        # 分离：有 amount 的档位先按金额匹配，无 amount 的档位作为兜底
        amount_tiers = [t for t in tiers if "amount" in t]
        universal_tiers = [t for t in tiers if "amount" not in t]

        if amount_tiers:
            # 先尝试金额分档匹配
            tiers_sorted = sorted(amount_tiers, key=lambda t: float(t.get("amount") or 0))
            for tier in tiers_sorted:
                tier_amount = float(tier.get("amount") or 0)
                inclusive = tier.get("inclusive", False)
                if inclusive:
                    if amount <= tier_amount:
                        return tier
                else:
                    if amount < tier_amount:
                        return tier
            # 所有金额档位都没命中 → 兜底档
            if universal_tiers:
                return universal_tiers[0]
            return tiers_sorted[-1]

        # 无金额分档（如 C 类全免申购费）
        if universal_tiers:
            return universal_tiers[0]
        # 档位为空 —— 规则不完整，直接暴露而不是猜一个默认费率
        raise ValueError("purchase_fee_tiers 为空，无可用费率档位")

    # ==================== 赎回费（JSON 档位，支持 inclusive） ====================

    def calc_redemption_fee(self, fund_code: str, amount: float, hold_days: int,
                            rule: Optional[dict] = None) -> Optional[float]:
        """
        计算赎回费（按 JSON 档位匹配，支持 inclusive 边界语义）。

        参数:
            fund_code: 基金代码
            amount: 赎回金额（元）
            hold_days: 持有天数
            rule: 已查询的费率规则（可选，传入则避免重复查询）

        返回:
            赎回费（元），或 None（不支持该基金 / 缺少费率规则）
        """
        if rule is None:
            rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None

        tiers_data = rule.get("redemption_fee_tiers")
        if tiers_data is None:
            # 规则缺失即拒绝 —— 与申购侧一致，不允许按"免赎回费"放行
            logger.error(f"基金 {fund_code} 缺少 redemption_fee_tiers，拒绝计算赎回费")
            return None

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
            # 空档位 = 规则不完整，同样拒绝，不做免赎回费兜底
            logger.error(f"基金 {fund_code} 的 redemption_fee_tiers 为空，拒绝计算赎回费")
            return None

        # 从小到大排序，按档位匹配
        # 每个档位支持 inclusive 字段：
        #   inclusive=False（默认）: hold_days < tier.days 时命中
        #   inclusive=True: hold_days <= tier.days 时命中（用于最后一档"≥N天"）
        tiers_sorted = sorted(tiers, key=lambda t: t["days"])
        rate = 0.0
        for tier in tiers_sorted:
            days = tier["days"]
            inclusive = tier.get("inclusive", False)
            if inclusive:
                if hold_days <= days:
                    rate = tier["rate"]
                    break
            else:
                if hold_days < days:
                    rate = tier["rate"]
                    break

        fee = amount * rate
        return round(fee, 2)

    # ==================== 简单查询（支持传入 rule 避免重复查询） ====================

    def _require_rule_field(self, fund_code: str, rule: Optional[dict], field: str):
        """
        读取费率规则中的必填字段，缺失即抛错。

        规则不完整时直接暴露，不用默认值兜底 —— 否则会用错误的天数/金额
        把交易做完，问题被静默吞掉。与模块「交易规则不能靠猜」原则一致。
        """
        if rule is None:
            rule = self.get_fee_rule(fund_code)
        if rule is None:
            raise ValueError(f"基金 {fund_code} 无费率规则，不支持交易")
        value = rule.get(field)
        if value is None:
            raise ValueError(f"基金 {fund_code} 的费率规则缺少 {field}")
        return value

    def get_min_purchase_amount(self, fund_code: str, rule: Optional[dict] = None) -> float:
        """获取最低申购金额（元）。字段缺失即报错，配置为 0 表示无门槛。"""
        return float(self._require_rule_field(fund_code, rule, "min_purchase_amount"))

    def get_confirm_delay(self, fund_code: str, rule: Optional[dict] = None) -> int:
        """获取申购确认延迟天数（T+N）。字段缺失即报错，不默认 T+1。"""
        return int(self._require_rule_field(fund_code, rule, "confirm_delay"))

    def get_redeem_settle_delay(self, fund_code: str, rule: Optional[dict] = None) -> int:
        """获取赎回到账延迟天数（T+N）。字段缺失即报错，不默认 T+3。"""
        return int(self._require_rule_field(fund_code, rule, "redeem_settle_delay"))

    def get_fund_name(self, fund_code: str, rule: Optional[dict] = None) -> Optional[str]:
        """获取基金名称"""
        if rule is None:
            rule = self.get_fee_rule(fund_code)
        if rule is None:
            return None
        return rule.get("fund_name")
