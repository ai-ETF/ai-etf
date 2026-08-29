"""
场外基金持仓交易服务

实现：
- 按金额申购（外扣法），按份额赎回
- 15:00 截止，非交易时段 pending，资金冻结不建仓
- 份额确认（T+N）后正式扣款建仓
- 加权平均成本价
- 交易流水分页查询
- 账户概况（现金/持仓市值/总资产/总盈亏/总收益率）
- 每日资产快照

仅支持 fund_fee_rules 表中已配置的场外开放式基金（fund_type='of'），查不到规则直接拒绝。
场内 ETF（fund_type='etf'）交易直接拦截。

优化：每次请求只查一次 get_fee_rule，将 rule dict 向下传递，避免重复远程查询。
"""
import logging
import json
import urllib.request
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

logger = logging.getLogger(__name__)

INITIAL_CASH = Decimal("100000.00")
BEIJING_TZ = timezone(timedelta(hours=8))

# 货币基金配置
# 真实货基收益机制：净值恒为 1.0000，每日按「万份收益」计息并复投（红利再投）。
# 因此这里不再模拟净值上涨，而是模拟复投：
#   - 净值固定 1.0000（_get_nav 直接返回）
#   - 每日把「万份收益」折算成份额加进 positions.quantity（份额逐日增长，即复利，
#     次日收益在更大的份额上计算），本金单独记录在 positions.principal（credit_money_fund_income）
# 注意：万份收益/年化数据获取失败时直接抛错，不做任何兜底默认值，
#       避免用虚假数字污染累计收益（旧版 MONEY_FUND_DEFAULT_ANNUAL_YIELD 兜底已废弃）。
MONEY_FUND_CODE = "000198"


def _beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def _now_iso() -> str:
    return _beijing_now().isoformat()


def _beijing_date() -> date:
    return _beijing_now().date()


def _parse_time(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        dt = dt.astimezone(BEIJING_TZ)
    return dt.replace(tzinfo=None)


class PortfolioService:
    """场外基金持仓交易服务"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase
            self._client = get_supabase()
        return self._client

    # ==================== 账户管理 ====================

    def _ensure_account(self, user_id: str) -> dict:
        if not self.client:
            raise RuntimeError("数据库不可用")
        result = (
            self.client.table("accounts")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]
        now = _now_iso()
        insert_data = {
            "user_id": user_id,
            "cash": float(INITIAL_CASH),
            "frozen_cash": 0,
            "created_at": now,
            "updated_at": now,
        }
        try:
            r = self.client.table("accounts").insert(insert_data).execute()
            if r.data and len(r.data) > 0:
                logger.info(f"新用户账户创建成功: user_id={user_id}")
                account = r.data[0]
                # 新用户自动将初始资金全额申购货币基金
                self._auto_invest_money_fund(user_id)
                return account
        except Exception:
            # 并发创建导致的重复键冲突，重新查询
            logger.warning(f"账户创建冲突，重查: user_id={user_id}")
            result = (
                self.client.table("accounts")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
        raise RuntimeError("账户创建失败")

    def _auto_invest_money_fund(self, user_id: str):
        """根据用户余额理财设置，将闲置现金自动申购货币基金。

        - 未开启余额理财：跳过
        - 已持仓货基：跳过
        - 可用现金 > 预留金额：超出部分自动申购并立即确认
        """
        try:
            # 已有货基持仓则跳过
            existing = self._get_position(user_id, MONEY_FUND_CODE)
            if existing:
                return
            # 查余额理财配置
            config = self.get_auto_invest_config(user_id)
            if not config["enabled"]:
                return
            # 取可用现金
            account = self.get_account(user_id)
            cash = Decimal(str(account["cash"])) if account else INITIAL_CASH
            reserve = Decimal(str(config["reserve"]))
            investable = cash - reserve
            if investable <= 0:
                logger.debug(f"用户 {user_id} 可用现金 {cash} 未超过预留 {reserve}，跳过")
                return
            result = self.apply_purchase(user_id, MONEY_FUND_CODE, investable)
            if result["success"]:
                logger.info(f"用户 {user_id} 自动申购货基成功: {float(investable):.2f} 元")
                self._confirm_money_fund_order(user_id)
            else:
                logger.warning(f"用户 {user_id} 自动申购货基失败: {result['message']}")
        except Exception as e:
            logger.error(f"用户 {user_id} 自动申购货基异常: {e}")

    def get_auto_invest_config(self, user_id: str) -> dict:
        """查询余额理财开关配置"""
        try:
            account = self.get_account(user_id)
            enabled = bool(account.get("auto_invest_enabled", False)) if account else False
            reserve = float(account.get("auto_invest_reserve", 0)) if account else 0.0
            return {
                "enabled": enabled,
                "reserve": reserve,
                "money_fund_code": MONEY_FUND_CODE,
                "money_fund_name": "天弘余额宝货币市场基金",
            }
        except Exception as e:
            logger.error(f"查询余额理财配置失败: {e}")
            return {
                "enabled": False, "reserve": 0.0,
                "money_fund_code": MONEY_FUND_CODE,
                "money_fund_name": "天弘余额宝货币市场基金",
            }

    def set_auto_invest_config(self, user_id: str, enabled: bool, reserve: float) -> dict:
        """设置余额理财开关和预留金额"""
        if not self.client:
            raise RuntimeError("数据库不可用")
        self._ensure_account(user_id)
        now = _now_iso()
        self.client.table("accounts").update({
            "auto_invest_enabled": enabled,
            "auto_invest_reserve": reserve,
            "updated_at": now,
        }).eq("user_id", user_id).execute()
        logger.info(f"用户 {user_id} 余额理财: enabled={enabled}, reserve={reserve}")
        return self.get_auto_invest_config(user_id)

    def _confirm_money_fund_order(self, user_id: str):
        """确认用户最新的货基 pending 申购订单（自动申购专用）。"""
        try:
            result = (
                self.client.table("trade_orders")
                .select("*")
                .eq("user_id", user_id)
                .eq("fund_code", MONEY_FUND_CODE)
                .eq("direction", "buy")
                .eq("status", "pending")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return
            from server.services.fund_fee_service import FundFeeService
            rule = FundFeeService().get_fee_rule(MONEY_FUND_CODE)
            today = _beijing_date()
            self._confirm_one_order(result.data[0], today, rule=rule)
            logger.info(f"用户 {user_id} 货基自动申购已确认")
        except Exception as e:
            logger.error(f"确认货基自动申购失败: {e}")

    def get_account(self, user_id: str) -> Optional[dict]:
        if not self.client:
            return None
        try:
            result = (
                self.client.table("accounts")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"查询账户失败: {e}")
            return None

    # ==================== 净值获取 ====================

    def _get_nav(self, fund_code: str) -> Optional[Decimal]:
        """获取场外基金最新净值。

        货币基金不查净值：真实货基净值恒为 1.0000，收益靠每日万份收益
        折算成份额加进 positions.quantity（份额逐日增长），不走净值上涨，
        因此直接返回 1.0000。
        """
        # 货币基金：净值恒 1.0000，不走 akshare（货基无单位净值走势数据集，且无意义）
        if fund_code == MONEY_FUND_CODE:
            return Decimal("1.0000")

        try:
            import akshare as ak
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                nav = latest.get("单位净值")
                if nav is not None:
                    return Decimal(str(nav))
        except Exception as e:
            logger.warning(f"查询基金净值失败 ({fund_code}): {e}")
        return None

    # ==================== 货基万份收益获取 ====================

    # 货基收益数据内存缓存（当天有效；缓存的是「成功获取」的结果，非兜底默认值）
    _money_fund_cache: dict = {}

    def _money_fund_per10k_income(self) -> Decimal:
        """获取货币基金最近已公布的「万份收益」（元/万份/日）。

        数据源：天天基金历史净值接口 lsjz。货基在该接口中字段被重定义：
          - DWJZ = 万份收益（持有 1 万份当天的收益金额，如 0.2229 元）
          - LJJZ = 7日年化收益率（% 数值，如 0.8150 表示 0.815%）
        当日数据通常在晚间披露，因此从最新往前取第一条「非今天」的记录，
        即最近一个完整计息日。

        设计决策（重要）：
        - 按北京日期缓存，当天多次调用不重复请求。
        - **不做任何兜底**：接口失败 / 返回空 / 字段缺失或非法时直接抛
          RuntimeError，由调用方（每日入账任务）上报。宁可当天不入账，
          也不用虚假数字污染累计收益——这是对旧版「默认年化兜底」的修正。
        """
        today = _beijing_date()
        today_iso = today.isoformat()
        cached_date = self._money_fund_cache.get("date")
        cached_income = self._money_fund_cache.get("per10k_income")
        if cached_date == today_iso and cached_income is not None:
            return Decimal(str(cached_income))

        logger.debug(f"获取货基 {MONEY_FUND_CODE} 万份收益（lsjz 接口）")
        try:
            url = (
                "https://api.fund.eastmoney.com/f10/lsjz"
                f"?fundCode={MONEY_FUND_CODE}&pageIndex=1&pageSize=5"
            )
            req = urllib.request.Request(url)
            req.add_header("Referer", "https://fundf10.eastmoney.com/")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            # 网络 / HTTP / JSON 解析异常：不兜底，直接上抛
            raise RuntimeError(
                f"获取货基 {MONEY_FUND_CODE} 万份收益失败（网络/解析）: {e}"
            ) from e

        items = data.get("Data", {}).get("LSJZList", [])
        if not items:
            raise RuntimeError(
                f"获取货基 {MONEY_FUND_CODE} 万份收益失败：接口返回空列表"
            )

        # 从最新往前找第一条「非今天」且 DWJZ 有效的记录
        for it in items:
            fsrq = str(it.get("FSRQ") or "")
            if not fsrq or fsrq == today_iso:
                continue  # 今日数据未披露/披露中，跳过
            raw = it.get("DWJZ")
            if raw is None or raw == "":
                continue  # 该日无万份收益字段，继续往前找
            try:
                income = Decimal(str(raw))
            except Exception:
                continue  # 字段非数字，继续往前找
            if income <= 0:
                continue
            self._money_fund_cache = {
                "date": today_iso,
                "per10k_income": income,
                "income_date": fsrq,
            }
            logger.info(f"货基万份收益: {MONEY_FUND_CODE} {fsrq} = {income} 元/万份")
            return income

        # 近 N 条记录都无效：不兜底，直接上抛
        raise RuntimeError(
            f"获取货基 {MONEY_FUND_CODE} 万份收益失败：近 {len(items)} 条记录均无有效 DWJZ"
        )

    # ==================== 货基每日收益入账 ====================

    def credit_money_fund_income(self) -> dict:
        """给所有持有货币基金的用户，按最近公布的万份收益把收益折算成份额。

        真实货基收益机制：净值恒 1.0000，每日按「万份收益」计息并复投。
        这里模拟为：当日收益折算成份额加进 positions.quantity（份额逐日增长，
        即复利——次日收益在更大份额上计算），本金 principal 保持不变。

        入账规则：
        - 当日收益 = 份额 × 昨日万份收益 / 10000，保留 2 位小数（分）。
          NAV=1.0000，故收益（元）= 新增份额，直接 quantity += 收益。
        - 收益 <= 0 的持仓跳过（子分位舍入到 0，如刚买入、份额极小；货基无日亏）。
        - 万份收益获取失败时直接抛异常（不兜底），整个任务中断，
          由调度器记录错误——宁可当天不入账，也不用虚假数据。

        由 spot_cache_scheduler 每日 00:05 调用（届时昨日万份收益已披露）。
        不做历史回填：从本方法上线的下一天起逐日入账。
        """
        # 1. 先取万份收益（失败即抛错，无兜底）——在循环前只请求一次
        per10k = self._money_fund_per10k_income()
        logger.info(f"[货基收益] 万份收益 = {per10k} 元/万份，开始逐仓折算份额")

        if not self.client:
            raise RuntimeError("数据库不可用")

        # 2. 查出所有持有货基的持仓
        result = (
            self.client.table("positions")
            .select("*")
            .eq("fund_code", MONEY_FUND_CODE)
            .execute()
        )
        positions = result.data or []
        if not positions:
            logger.info("[货基收益] 暂无货基持仓，跳过入账")
            return {
                "status": "ok", "credited": 0,
                "per10k_income": float(per10k), "total_income": 0.0,
            }

        now = _now_iso()
        credited = 0
        total_income = Decimal("0")
        errors = []

        # 3. 逐仓入账：收益折算成份额，quantity 逐日增长（本金 principal 不变）
        for pos in positions:
            user_id = pos.get("user_id")
            qty = Decimal(str(pos.get("quantity", 0) or 0))
            if qty <= 0:
                logger.debug(f"[货基收益] user={user_id} 份额为 0，跳过")
                continue

            income = (qty * per10k / Decimal("10000")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if income <= 0:
                logger.debug(f"[货基收益] user={user_id} 当日收益 {income} 元，跳过")
                continue

            new_qty = (qty + income).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            try:
                self.client.table("positions").update({
                    "quantity": float(new_qty),
                    "updated_at": now,
                }).eq("id", pos["id"]).execute()
                total_income += income
                credited += 1
                logger.info(
                    f"[货基收益] user={user_id} 份额 {qty} +{income} = {new_qty}"
                    f"（本金不变）"
                )
            except Exception as e:
                # 单仓 DB 失败只记录，不影响其他用户
                # （与数据源失败「整个任务中断」是两种不同级别的错误处理）
                errors.append(f"{user_id}: {e}")
                logger.error(f"[货基收益] user={user_id} 入账失败: {e}", exc_info=True)

        result = {
            "status": "ok" if not errors else "partial",
            "credited": credited,
            "per10k_income": float(per10k),
            "total_income": float(total_income.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "errors": errors,
        }
        logger.info(
            f"[货基收益] 入账完成: 成功 {credited} 仓, 合计 {result['total_income']} 元, "
            f"错误 {len(errors)}"
        )
        return result

    def _get_fund_name(self, fund_code: str, rule: Optional[dict] = None) -> str:
        """获取基金名称（优先从 rule 中读取，避免重复查询）"""
        if rule:
            name = rule.get("fund_name")
            if name:
                return name
        from server.services.fund_fee_service import FundFeeService
        svc = FundFeeService()
        name = svc.get_fund_name(fund_code, rule)
        if name:
            return name
        try:
            from server.services.finance_api_service import FinanceApiService
            spot = FinanceApiService().query_spot(fund_code)
            if spot and spot.get("name"):
                return spot["name"]
        except Exception:
            pass
        return fund_code

    # ==================== 交易时间判断 ====================

    @staticmethod
    def _is_trading_day(d: date) -> bool:
        """判断是否为 A 股交易日"""
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            for _, row in df.iterrows():
                try:
                    if date.fromisoformat(str(row['trade_date'])) == d:
                        return True
                except ValueError:
                    pass
            return False
        except Exception:
            return d.weekday() < 5

    @staticmethod
    def _is_before_cutoff(dt: datetime) -> bool:
        """判断是否在 15:00 截止前"""
        return dt.hour < 15

    @staticmethod
    def _next_trading_day(d: date) -> date:
        """获取下一个交易日"""
        for i in range(1, 15):
            nd = d + timedelta(days=i)
            if PortfolioService._is_trading_day(nd):
                return nd
        return d + timedelta(days=1)

    # ==================== 手续费计算（接受 rule 参数避免重复查询） ====================

    def _calc_purchase_fee(self, fund_code: str, amount: Decimal,
                           rule: Optional[dict] = None) -> Optional[dict]:
        """计算申购费，返回 None 表示不支持该基金。rule 可传入避免重复查询。"""
        from server.services.fund_fee_service import FundFeeService
        svc = FundFeeService()
        result = svc.calc_purchase_fee(fund_code, float(amount), rule=rule)
        if result is None:
            return None
        return {
            "fee": Decimal(str(result["fee"])),
            "net_amount": Decimal(str(result["net_amount"])),
        }

    def _calc_redemption_fee(self, fund_code: str, amount: Decimal,
                              hold_days: int, rule: Optional[dict] = None) -> Optional[Decimal]:
        """计算赎回费，返回 None 表示不支持该基金。rule 可传入避免重复查询。"""
        from server.services.fund_fee_service import FundFeeService
        svc = FundFeeService()
        fee = svc.calc_redemption_fee(fund_code, float(amount), hold_days, rule=rule)
        if fee is None:
            return None
        return Decimal(str(fee))

    # ==================== 申购 ====================

    def apply_purchase(self, user_id: str, fund_code: str, amount: Decimal,
            price: Optional[Decimal] = None) -> dict:
        """
        场外基金按金额申购。

        参数:
            user_id: 用户 ID
            fund_code: 基金代码
            amount: 申购金额（元）
            price: 净值（不传则自动获取）
        """
        try:
            # 0. 校验基金白名单 + ETF 拦截（只查一次 rule）
            from server.services.fund_fee_service import FundFeeService
            fee_svc = FundFeeService()
            rule = fee_svc.get_fee_rule(fund_code)
            if rule is None:
                return {
                    "success": False,
                    "message": f"暂不支持基金 {fund_code} 的交易",
                    "data": None,
                }
            # ETF 拦截：场内 ETF 不通过场外渠道交易
            if rule.get("fund_type") == "etf":
                return {
                    "success": False,
                    "message": "场内 ETF 暂不支持交易，请使用场外开放式基金",
                    "data": None,
                }

            now_beijing = _beijing_now()

            # 1. 计算确认日（从 rule 中直接读取，不再重复查询）
            confirm_delay = int(rule.get("confirm_delay", 1))
            if self._is_trading_day(now_beijing.date()) and self._is_before_cutoff(now_beijing):
                confirm_date = now_beijing.date()
                day_label = "当日"
            else:
                confirm_date = self._next_trading_day(now_beijing.date())
                day_label = "下一交易日"

            actual_confirm = confirm_date
            for _ in range(confirm_delay):
                actual_confirm = self._next_trading_day(actual_confirm)

            # 2. 校验最低申购金额（从 rule 中直接读取）
            min_amount = Decimal(str(rule.get("min_purchase_amount", 10.0)))
            if amount < min_amount:
                return {
                    "success": False,
                    "message": f"申购金额 {float(amount):.2f} 元低于最低申购金额 {float(min_amount):.2f} 元",
                    "data": None,
                }

            # 3. 获取净值（必须在冻结资金之前）
            if price is None:
                price = self._get_nav(fund_code)
            if price is None or price <= 0:
                return {"success": False, "message": f"无法获取基金 {fund_code} 的净值", "data": None}

            # 4. 计算申购费（传入 rule 避免重复查询）
            fee_result = self._calc_purchase_fee(fund_code, amount, rule=rule)
            if fee_result is None:
                return {"success": False, "message": f"暂不支持基金 {fund_code} 的交易", "data": None}
            fee = fee_result["fee"]
            net_amount = fee_result["net_amount"]

            # 5. 获取基金名称（传入 rule 避免重复查询）
            fund_name = self._get_fund_name(fund_code, rule=rule)

            # 5a. 生成风险提示（建议性，任何异常都不影响交易）
            risk_warning = self._get_risk_warning(user_id, fund_code)

            # 6. 校验可用现金
            account = self._ensure_account(user_id)
            cash = Decimal(str(account["cash"]))
            frozen_cash = Decimal(str(account.get("frozen_cash", 0)))

            if cash < amount:
                return {
                    "success": False,
                    "message": f"可用现金不足：需 {float(amount):.2f} 元，实际可用 {float(cash):.2f} 元",
                    "data": None,
                }

            now = _now_iso()

            # 场外基金统一走 pending 流程：冻结资金，不立即建仓
            # T+1 确认时由 confirm_pending_orders() 按确认日净值计算精确份额
            self.client.table("accounts").update({
                "cash": float(cash - amount),
                "frozen_cash": float(frozen_cash + amount),
                "updated_at": now,
            }).eq("user_id", user_id).execute()

            # 写委托记录（pending，份额待确认后填入）
            # 如果写订单失败，回滚冻结资金
            try:
                self._write_trade_order(
                    user_id, fund_code, fund_name, "buy", amount,
                    Decimal("0"), Decimal("0"), fee, "pending",
                    confirm_date=actual_confirm.isoformat(),
                )
            except Exception:
                self.client.table("accounts").update({
                    "cash": float(cash),
                    "frozen_cash": float(frozen_cash),
                    "updated_at": now,
                }).eq("user_id", user_id).execute()
                raise

            message = (
                f"申购申请已提交（{day_label}受理），"
                f"将于 {actual_confirm.isoformat()} 确认份额（T+{confirm_delay}），资金已冻结"
            )

            logger.info(
                f"申购pending: user={user_id}, code={fund_code}, "
                f"amount={amount}, fee={fee}, confirm={actual_confirm.isoformat()}"
            )

            return {
                "success": True,
                "message": message,
                "data": {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "amount": float(amount),
                    "price": float(price),
                    "fee": float(fee),
                    "net_amount": float(net_amount),
                    "confirm_date": actual_confirm.isoformat(),
                    "cash_remaining": float(cash - amount),
                    "frozen_cash": float(frozen_cash + amount),
                    "status": "pending",
                    "trade_time": now,
                },
                "risk_warning": risk_warning,
            }

        except Exception as e:
            logger.error(f"申购失败: {e}", exc_info=True)
            return {"success": False, "message": f"申购失败: {str(e)}", "data": None}

    # ==================== 风险提示 ====================

    def _get_risk_warning(self, user_id: str, fund_code: str) -> Optional[dict]:
        """
        读取用户画像 + 基金风险等级，生成交易风险提示（建议性）。

        任何异常都不影响交易：返回 None 表示无提示/数据缺失。
        """
        try:
            from server.services.risk_service import RiskService
            from server.services.fund_risk_service import FundRiskService

            profile = RiskService().get_latest_profile(user_id)
            fund_risk = FundRiskService().get_risk_profile(fund_code)
            if not profile or not fund_risk:
                return None

            return RiskService.get_risk_warning(
                user_risk_level=profile["risk_level"],
                user_risk_label=profile["risk_label"],
                fund_risk_level=fund_risk["risk_level"],
                fund_risk_label=fund_risk["risk_label"],
            )
        except Exception as e:
            logger.warning(f"获取风险提示失败（不影响交易）: user={user_id}, code={fund_code}: {e}")
            return None

    # ==================== 赎回 ====================

    def apply_redeem(self, user_id: str, fund_code: str, quantity: Decimal,
             price: Optional[Decimal] = None) -> dict:
        """
        场外基金按份额赎回。

        参数:
            user_id: 用户 ID
            fund_code: 基金代码
            quantity: 赎回份额
            price: 净值（不传则自动获取）
        """
        try:
            # 0. 校验基金白名单 + ETF 拦截（只查一次 rule）
            from server.services.fund_fee_service import FundFeeService
            fee_svc = FundFeeService()
            rule = fee_svc.get_fee_rule(fund_code)
            if rule is None:
                return {
                    "success": False,
                    "message": f"暂不支持基金 {fund_code} 的交易",
                    "data": None,
                }
            # ETF 拦截
            if rule.get("fund_type") == "etf":
                return {
                    "success": False,
                    "message": "场内 ETF 暂不支持交易，请使用场外开放式基金",
                    "data": None,
                }

            now_beijing = _beijing_now()

            # 1. 计算确认日
            if self._is_trading_day(now_beijing.date()) and self._is_before_cutoff(now_beijing):
                confirm_date = now_beijing.date()
            else:
                confirm_date = self._next_trading_day(now_beijing.date())

            # 2. 校验持仓
            position = self._get_position(user_id, fund_code)
            if not position:
                return {"success": False, "message": f"未持有基金 {fund_code}，无法赎回", "data": None}

            # 2a. 检查是否存在 pending 申购（份额未确认前不可赎回）
            pending_buys = (
                self.client.table("trade_orders")
                .select("*")
                .eq("user_id", user_id)
                .eq("fund_code", fund_code)
                .eq("direction", "buy")
                .eq("status", "pending")
                .execute()
            )
            if pending_buys.data:
                return {
                    "success": False,
                    "message": f"基金 {fund_code} 存在待确认的申购订单，份额确认前无法赎回",
                    "data": None,
                }

            # 2b. 计算可用份额（扣除已有 pending 赎回订单）
            current_qty = Decimal(str(position["quantity"]))
            pending_sells = (
                self.client.table("trade_orders")
                .select("quantity")
                .eq("user_id", user_id)
                .eq("fund_code", fund_code)
                .eq("direction", "sell")
                .eq("status", "pending")
                .execute()
            )
            pending_qty = Decimal("0")
            if pending_sells.data:
                for ps in pending_sells.data:
                    pending_qty += Decimal(str(ps.get("quantity", 0)))

            available_qty = current_qty - pending_qty
            if quantity > available_qty:
                return {
                    "success": False,
                    "message": f"可赎份额不足：需 {float(quantity)} 份，实际可用 {float(available_qty)} 份"
                               + (f"（{float(pending_qty)} 份在待确认赎回订单中）" if pending_qty > 0 else ""),
                    "data": None,
                }

            # 3. 获取基金名称（传入 rule 避免重复查询）
            fund_name = self._get_fund_name(fund_code, rule=rule)

            # 场外基金统一走 pending 流程：不立即入账，T+1 确认后由 confirm_pending_orders() 处理
            # 赎回费在确认时按确认日净值和持有天数计算
            redeem_delay = int(rule.get("redeem_settle_delay", 3))
            settle_date = confirm_date
            for _ in range(redeem_delay):
                settle_date = self._next_trading_day(settle_date)

            now = _now_iso()

            self._write_trade_order(
                user_id, fund_code, fund_name, "sell",
                Decimal("0"), Decimal("0"),  # 金额和净值确认时按确认日填入
                quantity, Decimal("0"), "pending",
                confirm_date=confirm_date.isoformat(),
            )

            message = f"赎回申请已提交，将于 {settle_date.isoformat()} 到账（T+{redeem_delay}）"

            logger.info(
                f"赎回pending: user={user_id}, code={fund_code}, "
                f"qty={quantity}, confirm={confirm_date.isoformat()}, settle={settle_date.isoformat()}"
            )

            return {
                "success": True,
                "message": message,
                "data": {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "amount": 0.0,
                    "price": 0.0,
                    "fee": 0.0,
                    "quantity": float(quantity),
                    "confirm_date": confirm_date.isoformat(),
                    "settle_date": settle_date.isoformat(),
                    "status": "pending",
                    "trade_time": now,
                },
            }

        except Exception as e:
            logger.error(f"赎回失败: {e}", exc_info=True)
            return {"success": False, "message": f"赎回失败: {str(e)}", "data": None}

    # ==================== 持仓查询 ====================

    def _get_position(self, user_id: str, fund_code: str) -> Optional[dict]:
        if not self.client:
            return None
        result = (
            self.client.table("positions")
            .select("*")
            .eq("user_id", user_id)
            .eq("fund_code", fund_code)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    def list_positions(self, user_id: str, include_quote: bool = True) -> dict:
        if not self.client:
            return {"total": 0, "items": [], "total_pnl": 0, "total_position_value": 0}

        try:
            result = (
                self.client.table("positions")
                .select("*")
                .eq("user_id", user_id)
                .order("updated_at", desc=True)
                .execute()
            )
            items = result.data or []
            total_pnl = Decimal("0")
            total_position_value = Decimal("0")

            for item in items:
                qty = Decimal(str(item.get("quantity", 0)))
                cost_price = Decimal(str(item.get("cost_price", 0)))
                cost_value = qty * cost_price

                if include_quote:
                    if item["fund_code"] == MONEY_FUND_CODE:
                        # 货基特殊估值：净值恒 1.0000，收益已折算成份额（quantity 逐日增长）。
                        # 本金 = principal（累计投入，元）；市值 = 份额 × 1.0 = 份额；
                        # 盈亏 = 市值 − 本金 = 份额 − 本金（即累计收益）。
                        principal = Decimal(str(item.get("principal", 0) or 0))
                        principal_q = principal.quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        market_value = qty.quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        pnl = (market_value - principal_q).quantize(
                            Decimal("0.02"), rounding=ROUND_HALF_UP
                        )
                        item["market_price"] = 1.0000
                        item["market_value"] = float(market_value)
                        item["cost_value"] = float(principal_q)
                        item["pnl"] = float(pnl)
                        item["pnl_pct"] = float(
                            (pnl / principal_q * Decimal("100")).quantize(
                                Decimal("0.0001"), rounding=ROUND_HALF_UP
                            )
                        ) if principal_q > 0 else 0
                        total_pnl += pnl
                        total_position_value += market_value
                    else:
                        market_price = self._get_nav(item["fund_code"])
                        if market_price and market_price > 0:
                            market_value = (qty * market_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            item["market_price"] = float(market_price)
                            item["market_value"] = float(market_value)
                            item["cost_value"] = float(cost_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                            item["pnl"] = float((market_value - cost_value).quantize(Decimal("0.02"), rounding=ROUND_HALF_UP))
                            item["pnl_pct"] = float(
                                ((market_price - cost_price) / cost_price * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                            ) if cost_price > 0 else 0
                            total_pnl += Decimal(str(item["pnl"]))
                            total_position_value += market_value
                        else:
                            item["market_price"] = None
                            item["market_value"] = None
                            item["cost_value"] = float(cost_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                            item["pnl"] = 0
                            item["pnl_pct"] = 0
                else:
                    item["market_price"] = None
                    item["market_value"] = None
                    item["cost_value"] = float(cost_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                    item["pnl"] = 0
                    item["pnl_pct"] = 0

                item["quantity"] = float(qty)
                item["cost_price"] = float(cost_price)

            return {
                "total": len(items),
                "items": items,
                "total_pnl": float(total_pnl.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
                "total_position_value": float(total_position_value.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
            }

        except Exception as e:
            logger.error(f"查询持仓失败: {e}", exc_info=True)
            return {"total": 0, "items": [], "total_pnl": 0, "total_position_value": 0}

    # ==================== 账户概况 ====================

    def account_summary(self, user_id: str) -> dict:
        try:
            # 确保账户存在
            self._ensure_account(user_id)
            # 新老用户一视同仁：闲置现金自动申购货基
            self._auto_invest_money_fund(user_id)
            account = self.get_account(user_id)
            if not account:
                return {
                    "cash": float(INITIAL_CASH),
                    "frozen_cash": 0,
                    "position_value": 0,
                    "total_assets": float(INITIAL_CASH),
                    "total_pnl": 0,
                    "total_return_rate": 0,
                    "position_count": 0,
                }

            cash = Decimal(str(account["cash"]))
            frozen_cash = Decimal(str(account.get("frozen_cash", 0)))
            positions_data = self.list_positions(user_id, include_quote=True)
            position_value = Decimal(str(positions_data["total_position_value"]))
            total_assets = cash + frozen_cash + position_value
            total_pnl = total_assets - INITIAL_CASH
            total_return_rate = (total_pnl / INITIAL_CASH) if INITIAL_CASH > 0 else Decimal("0")

            return {
                "cash": float(cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "frozen_cash": float(frozen_cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "position_value": float(position_value.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
                "total_assets": float(total_assets.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
                "total_pnl": float(total_pnl.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
                "total_return_rate": float(total_return_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
                "position_count": positions_data["total"],
            }

        except Exception as e:
            logger.error(f"账户概况查询失败: {e}", exc_info=True)
            return {"cash": 0, "frozen_cash": 0, "position_value": 0, "total_assets": 0, "total_pnl": 0, "total_return_rate": 0, "position_count": 0}

    # ==================== Pending 订单确认 ====================

    def confirm_pending_orders(self, skip_trading_day_check: bool = False) -> dict:
        """
        扫描 trade_orders 中 status='pending' 且 confirm_date 到期的订单，
        执行资金扣款/入账、持仓创建/更新、写流水。

        参数:
            skip_trading_day_check: 如果为 True，即使非交易日也确认所有到期订单
                                   （用于启动补偿和手动触发）

        交易日：确认 confirm_date <= today 的订单
        非交易日：确认 confirm_date < today 的遗漏订单（启动补偿机制）
        由定时调度器在每个交易日调用，也在服务启动时调用。
        """
        if not self.client:
            return {"status": "error", "message": "数据库不可用"}

        today = _beijing_date()
        is_trading = self._is_trading_day(today)

        try:
            query = (
                self.client.table("trade_orders")
                .select("*")
                .eq("status", "pending")
            )

            if skip_trading_day_check or is_trading:
                # 手动触发 或 交易日：确认到今天及之前的
                query = query.lte("confirm_date", today.isoformat())
            else:
                # 非交易日定时任务：只确认昨天及之前遗漏的
                yesterday = today - timedelta(days=1)
                query = query.lte("confirm_date", yesterday.isoformat())

            result = query.execute()

            orders = result.data or []
            if not orders:
                return {"status": "ok", "message": "无待确认订单", "processed": 0}

            # 预加载所有涉及的基金费率规则（一次批量查询代替每笔单独查询）
            fund_codes = list({o.get("fund_code") for o in orders if o.get("fund_code")})
            from server.services.fund_fee_service import FundFeeService
            fee_svc = FundFeeService()
            rules_map = fee_svc.get_fee_rules_batch(fund_codes)
            logger.info(f"预加载费率规则: {len(fund_codes)} 只基金 → {len(rules_map)} 条")

            confirmed = 0
            failed = 0
            for order in orders:
                try:
                    rule = rules_map.get(order.get("fund_code"))
                    self._confirm_one_order(order, today, rule=rule)
                    confirmed += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"确认订单失败 {order.get('id')}: {e}", exc_info=True)
                    try:
                        self.client.table("trade_orders").update({
                            "status": "failed",
                            "reject_reason": str(e)[:200],
                            "updated_at": _now_iso(),
                        }).eq("id", order["id"]).execute()
                    except Exception:
                        pass

            logger.info(f"Pending 订单确认完成: 成功 {confirmed}, 失败 {failed}")
            return {
                "status": "ok",
                "message": f"确认完成: 成功 {confirmed}, 失败 {failed}",
                "processed": confirmed + failed,
            }

        except Exception as e:
            logger.error(f"确认 pending 订单失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e), "processed": 0}

    def _confirm_one_order(self, order: dict, today: date, rule: Optional[dict] = None) -> None:
        """确认单笔 pending 订单。rule 可预加载传入避免重复查询。"""
        order_id = order["id"]
        user_id = order["user_id"]
        fund_code = order["fund_code"]
        fund_name = order["fund_name"]
        direction = order["direction"]
        amount = Decimal(str(order["amount"]))
        price = Decimal(str(order["price"]))
        quantity = Decimal(str(order["quantity"]))
        fee = Decimal(str(order["fee"]))
        now = _now_iso()

        # 如果未预加载 rule，回退到单独查询（手动确认场景）
        if rule is None:
            from server.services.fund_fee_service import FundFeeService
            rule = FundFeeService().get_fee_rule(fund_code)

        if direction == "buy":
            # --- 申购确认 ---
            # 1. 先解冻资金（放在最前面，异常时资金已释放不会被锁死）
            account_result = (
                self.client.table("accounts")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            if not account_result.data:
                raise RuntimeError(f"用户 {user_id} 账户不存在")
            account = account_result.data[0]
            frozen_cash = Decimal(str(account.get("frozen_cash", 0)))
            new_frozen = frozen_cash - amount
            if new_frozen < 0:
                logger.warning(f"冻结资金不足: user={user_id}, frozen={frozen_cash}, amount={amount}")
                new_frozen = Decimal("0")

            self.client.table("accounts").update({
                "frozen_cash": float(new_frozen),
                "updated_at": now,
            }).eq("user_id", user_id).execute()

            # 2. 获取当日净值
            nav = self._get_nav(fund_code)
            if nav is None or nav <= 0:
                nav = price  # 回退到订单中的价格

            # 3. 计算申购费和净金额
            fee_result = self._calc_purchase_fee(fund_code, amount, rule=rule)
            if fee_result:
                actual_fee = fee_result["fee"]
                net_amount = fee_result["net_amount"]
            else:
                actual_fee = fee
                net_amount = amount - fee

            # 4. 计算实际份额
            actual_qty = (net_amount / nav).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # 5. 建仓
            pos_result = (
                self.client.table("positions")
                .select("*")
                .eq("user_id", user_id)
                .eq("fund_code", fund_code)
                .execute()
            )
            is_money_fund = fund_code == MONEY_FUND_CODE
            if pos_result.data and len(pos_result.data) > 0:
                position = pos_result.data[0]
                old_qty = Decimal(str(position["quantity"]))
                old_cost_price = Decimal(str(position["cost_price"]))
                if is_money_fund:
                    # 货基加仓：只增份额与本金，成本价恒 1.0000（不加权平均）。
                    # 本金 = 原本金 + 申购净额（复投收益产生的份额不计入本金）。
                    new_qty = old_qty + actual_qty
                    new_cost_price = Decimal("1.0000")
                    old_principal = Decimal(str(position.get("principal", 0) or 0))
                    new_principal = (old_principal + net_amount).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                else:
                    total_cost_basis = old_qty * old_cost_price + net_amount
                    new_qty = old_qty + actual_qty
                    new_cost_price = (total_cost_basis / new_qty).quantize(
                        Decimal("0.0001"), rounding=ROUND_HALF_UP
                    ) if new_qty > 0 else nav
                    new_principal = None
            else:
                position = None
                new_qty = actual_qty
                if is_money_fund:
                    # 货基新仓：本金 = 申购净额，成本价恒 1.0000
                    new_cost_price = Decimal("1.0000")
                    new_principal = net_amount.quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                else:
                    new_cost_price = (net_amount / actual_qty).quantize(
                        Decimal("0.0001"), rounding=ROUND_HALF_UP
                    ) if actual_qty > 0 else nav
                    new_principal = None

            # 份额可赎回日（T+2）
            available_date = today
            for _ in range(2):
                available_date = self._next_trading_day(available_date)

            if position:
                update_data = {
                    "quantity": float(new_qty),
                    "cost_price": float(new_cost_price),
                    "confirm_date": today.isoformat(),
                    "available_date": available_date.isoformat(),
                    "updated_at": now,
                }
                if is_money_fund:
                    # 货基本金随加仓累加（复投收益不计入本金）
                    update_data["principal"] = float(new_principal)
                self.client.table("positions").update(update_data).eq("id", position["id"]).execute()
            else:
                insert_data = {
                    "user_id": user_id,
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "quantity": float(new_qty),
                    "cost_price": float(new_cost_price),
                    "confirm_date": today.isoformat(),
                    "available_date": available_date.isoformat(),
                    "created_at": now,
                    "updated_at": now,
                }
                if is_money_fund:
                    # 货基本金初始为申购净额（复投收益由 credit_money_fund_income() 折算成份额）
                    insert_data["principal"] = float(new_principal)
                self.client.table("positions").insert(insert_data).execute()

            # 6. 写流水
            self._write_trade_flow(user_id, fund_code, fund_name, "buy",
                                   amount, nav, actual_qty, actual_fee)

            # 7. 更新订单状态
            self.client.table("trade_orders").update({
                "status": "completed",
                "quantity": float(actual_qty),
                "price": float(nav),
                "fee": float(actual_fee),
                "updated_at": now,
            }).eq("id", order_id).execute()

            logger.info(f"申购确认: user={user_id}, code={fund_code}, "
                        f"qty={actual_qty}, nav={nav}, amount={amount}")

        elif direction == "sell":
            # --- 赎回确认 ---
            # 1. 获取持仓
            pos_result = (
                self.client.table("positions")
                .select("*")
                .eq("user_id", user_id)
                .eq("fund_code", fund_code)
                .execute()
            )
            if not pos_result.data:
                raise RuntimeError(f"用户 {user_id} 持仓 {fund_code} 不存在")
            position = pos_result.data[0]
            current_qty = Decimal(str(position["quantity"]))
            cost_price = Decimal(str(position["cost_price"]))

            # 2. 计算赎回费（按确认日净值，传入 rule 避免重复查询）
            nav = self._get_nav(fund_code)
            if nav is None or nav <= 0:
                nav = price
            redeem_amount = (quantity * nav).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # 2a. 货基特殊：收益已折算成份额（quantity），赎回金额 = 份额×1.0，
            #     即「本金部分 + 累计收益部分」全部兑付到现金。只按比例核减本金。
            # 货基净值恒 1.0000，卖出份额的金额本身含累计收益，无需像旧版那样
            # 单独计算收益兑付额；只需按「卖出份额 / 总份额」比例核减 principal。
            principal_portion = Decimal("0")
            principal_total = Decimal(str(position.get("principal", 0) or 0))
            if fund_code == MONEY_FUND_CODE and principal_total > 0 and current_qty > 0:
                principal_portion = (principal_total * quantity / current_qty).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                logger.info(
                    f"货基赎回核减本金: user={user_id}, code={fund_code}, "
                    f"卖出 {quantity}/{current_qty} 份, 核减本金 {principal_portion} 元"
                )

            # 持有天数
            confirm_date_str = position.get("confirm_date", "")
            hold_days = 0
            if confirm_date_str:
                try:
                    hold_start = date.fromisoformat(str(confirm_date_str))
                    hold_days = (today - hold_start).days
                except Exception:
                    hold_days = 0

            actual_fee = self._calc_redemption_fee(fund_code, redeem_amount, max(hold_days, 0), rule=rule)
            if actual_fee is None:
                actual_fee = Decimal("0")
            # 货基收益已含在份额里（quantity 已折算），无需再加 income_portion
            net_amount = redeem_amount - actual_fee

            # 3. 先扣持仓（先减份额再加钱，防止中间崩溃用户多拿钱）
            new_qty = current_qty - quantity
            if new_qty <= 0:
                self.client.table("positions").delete().eq("id", position["id"]).execute()
            else:
                update_data = {
                    "quantity": float(new_qty),
                    "updated_at": now,
                }
                if fund_code == MONEY_FUND_CODE:
                    # 同步按比例核减本金（仅货基需要维护该列）
                    update_data["principal"] = float(
                        (principal_total - principal_portion).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                    )
                self.client.table("positions").update(update_data).eq("id", position["id"]).execute()

            # 4. 现金入账
            account_result = (
                self.client.table("accounts")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            account = account_result.data[0]
            current_cash = Decimal(str(account["cash"]))
            new_cash = current_cash + net_amount

            self.client.table("accounts").update({
                "cash": float(new_cash),
                "updated_at": now,
            }).eq("user_id", user_id).execute()

            # 5. 计算盈亏
            if fund_code == MONEY_FUND_CODE:
                # 货基：卖出份额的成本 = 按比例核减的本金（收益已含在 net_amount 里）
                cost_of_sold = principal_portion
            else:
                cost_of_sold = (cost_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            trade_pnl = (net_amount - cost_of_sold).quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)

            # 6. 写流水（含盈亏）
            self._write_trade_flow(user_id, fund_code, fund_name, "sell",
                                   redeem_amount, nav, quantity, actual_fee,
                                   trade_pnl=trade_pnl)

            # 7. 更新订单状态

            self.client.table("trade_orders").update({
                "status": "completed",
                "amount": float(redeem_amount),
                "price": float(nav),
                "fee": float(actual_fee),
                "updated_at": now,
            }).eq("id", order_id).execute()

            logger.info(f"赎回确认: user={user_id}, code={fund_code}, "
                        f"qty={quantity}, amount={redeem_amount}, fee={actual_fee}, pnl={trade_pnl}")

    # ==================== 交易委托 ====================

    def _write_trade_order(self, user_id: str, fund_code: str, fund_name: str,
                           direction: str, amount: Decimal, price: Decimal,
                           quantity: Decimal, fee: Decimal, status: str,
                           confirm_date: Optional[str] = None) -> None:
        now = _now_iso()
        data = {
            "user_id": user_id,
            "fund_code": fund_code,
            "fund_name": fund_name,
            "direction": direction,
            "order_type": "market",
            "amount": float(amount),
            "price": float(price),
            "quantity": float(quantity),
            "fee": float(fee),
            "status": status,
            "reject_reason": None,
            "confirm_date": confirm_date,
            "created_at": now,
            "updated_at": now,
        }
        self.client.table("trade_orders").insert(data).execute()

    def _write_trade_flow(self, user_id: str, fund_code: str, fund_name: str,
                          direction: str, amount: Decimal, price: Decimal,
                          quantity: Decimal, fee: Decimal,
                          trade_pnl: Optional[Decimal] = None) -> None:
        now = _now_iso()
        data = {
            "user_id": user_id,
            "fund_code": fund_code,
            "fund_name": fund_name,
            "direction": direction,
            "amount": float(amount),
            "price": float(price),
            "quantity": float(quantity),
            "fee": float(fee),
            "trade_time": now,
        }
        if trade_pnl is not None:
            data["trade_pnl"] = float(trade_pnl)
        self.client.table("trade_flow").insert(data).execute()

    def query_trade_flow(self, user_id: str, fund_code: Optional[str] = None,
                         direction: Optional[str] = None,
                         page: int = 1, page_size: int = 20) -> dict:
        if not self.client:
            return {"total": 0, "page": page, "page_size": page_size, "total_pages": 0, "items": []}

        try:
            query = (
                self.client.table("trade_flow")
                .select("*", count="exact")
                .eq("user_id", user_id)
            )
            if fund_code:
                query = query.eq("fund_code", fund_code)
            if direction and direction in ("buy", "sell"):
                query = query.eq("direction", direction)

            offset = (page - 1) * page_size
            result = (
                query.order("trade_time", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
            )

            items = result.data or []
            total = result.count if hasattr(result, 'count') and result.count is not None else len(items)
            total_pages = max(1, (total + page_size - 1) // page_size)

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "items": items,
            }

        except Exception as e:
            logger.error(f"查询交易流水失败: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "total_pages": 0, "items": []}

    # ==================== 每日快照 ====================

    def take_snapshot(self, user_id: str, snapshot_date: Optional[date] = None) -> dict:
        if snapshot_date is None:
            snapshot_date = _beijing_date()

        try:
            summary = self.account_summary(user_id)
            snapshot_data = {
                "user_id": user_id,
                "snapshot_date": snapshot_date.isoformat(),
                "total_assets": summary["total_assets"],
                "cash": summary["cash"],
                "position_value": summary["position_value"],
                "total_pnl": summary["total_pnl"],
                "total_return_rate": summary["total_return_rate"],
                "created_at": _now_iso(),
            }

            existing = (
                self.client.table("account_snapshots")
                .select("*")
                .eq("user_id", user_id)
                .eq("snapshot_date", snapshot_date.isoformat())
                .execute()
            )

            if existing.data and len(existing.data) > 0:
                self.client.table("account_snapshots").update(snapshot_data).eq(
                    "id", existing.data[0]["id"]
                ).execute()
                logger.info(f"快照已更新: user={user_id}, date={snapshot_date}")
            else:
                self.client.table("account_snapshots").insert(snapshot_data).execute()
                logger.info(f"快照已创建: user={user_id}, date={snapshot_date}")

            return {
                "success": True,
                "message": "快照已保存",
                "data": {
                    "snapshot_date": snapshot_date.isoformat(),
                    "total_assets": summary["total_assets"],
                    "cash": summary["cash"],
                    "position_value": summary["position_value"],
                    "total_pnl": summary["total_pnl"],
                    "total_return_rate": summary["total_return_rate"],
                },
            }

        except Exception as e:
            logger.error(f"快照保存失败: {e}")
            return {"success": False, "message": f"快照保存失败: {str(e)}", "data": None}

    def get_daily_returns(self, user_id: str, days: int = 30) -> dict:
        if not self.client:
            return {"items": []}

        try:
            result = (
                self.client.table("account_snapshots")
                .select("*")
                .eq("user_id", user_id)
                .order("snapshot_date", desc=True)
                .limit(days + 1)
                .execute()
            )

            items = result.data or []
            items.sort(key=lambda x: x["snapshot_date"])

            returns = []
            for i, item in enumerate(items):
                daily_return = 0.0
                if i > 0:
                    prev_assets = float(items[i - 1]["total_assets"])
                    curr_assets = float(item["total_assets"])
                    if prev_assets > 0:
                        daily_return = (curr_assets - prev_assets) / prev_assets

                returns.append({
                    "date": item["snapshot_date"],
                    "total_assets": float(item["total_assets"]),
                    "cash": float(item["cash"]),
                    "position_value": float(item["position_value"]),
                    "total_pnl": float(item["total_pnl"]),
                    "total_return_rate": float(item["total_return_rate"]),
                    "daily_return": round(daily_return, 6),
                })

            return {"items": returns}

        except Exception as e:
            logger.error(f"查询每日收益率失败: {e}")
            return {"items": []}
