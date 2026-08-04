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
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

logger = logging.getLogger(__name__)

INITIAL_CASH = Decimal("100000.00")
BEIJING_TZ = timezone(timedelta(hours=8))


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
        r = self.client.table("accounts").insert(insert_data).execute()
        if r.data and len(r.data) > 0:
            logger.info(f"新用户账户创建成功: user_id={user_id}")
            return r.data[0]
        raise RuntimeError("账户创建失败")

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
        """获取场外基金最新净值"""
        try:
            import akshare as ak
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                nav = latest.get("单位净值")
                if nav is not None:
                    return Decimal(str(float(nav)))
        except Exception as e:
            logger.warning(f"查询基金净值失败 ({fund_code}): {e}")
        return None

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
            self._write_trade_order(
                user_id, fund_code, fund_name, "buy", amount,
                Decimal("0"), Decimal("0"), fee, "pending",
                confirm_date=actual_confirm.isoformat(),
            )

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
            }

        except Exception as e:
            logger.error(f"申购失败: {e}", exc_info=True)
            return {"success": False, "message": f"申购失败: {str(e)}", "data": None}

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
                "total_return_rate": float(total_pnl.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
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

            confirmed = 0
            failed = 0
            for order in orders:
                try:
                    self._confirm_one_order(order, today)
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

    def _confirm_one_order(self, order: dict, today: date) -> None:
        """确认单笔 pending 订单"""
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

        from server.services.fund_fee_service import FundFeeService
        fee_svc = FundFeeService()
        # 只查一次 rule，向下传递
        rule = fee_svc.get_fee_rule(fund_code)

        if direction == "buy":
            # --- 申购确认 ---
            # 1. 获取当日净值
            nav = self._get_nav(fund_code)
            if nav is None or nav <= 0:
                nav = price  # 回退到订单中的价格

            # 2. 计算申购费和净金额（传入 rule 避免重复查询）
            fee_result = self._calc_purchase_fee(fund_code, amount, rule=rule)
            if fee_result:
                actual_fee = fee_result["fee"]
                net_amount = fee_result["net_amount"]
            else:
                actual_fee = fee
                net_amount = amount - fee

            # 3. 计算实际份额
            actual_qty = (net_amount / nav).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # 4. 解冻资金（扣减 frozen_cash）
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
                new_frozen = Decimal("0")

            self.client.table("accounts").update({
                "frozen_cash": float(new_frozen),
                "updated_at": now,
            }).eq("user_id", user_id).execute()

            # 5. 建仓（加权平均成本）
            pos_result = (
                self.client.table("positions")
                .select("*")
                .eq("user_id", user_id)
                .eq("fund_code", fund_code)
                .execute()
            )
            if pos_result.data and len(pos_result.data) > 0:
                position = pos_result.data[0]
                old_qty = Decimal(str(position["quantity"]))
                old_cost_price = Decimal(str(position["cost_price"]))
                total_cost_basis = old_qty * old_cost_price + net_amount
                new_qty = old_qty + actual_qty
                new_cost_price = (total_cost_basis / new_qty).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                ) if new_qty > 0 else nav
            else:
                position = None
                new_qty = actual_qty
                new_cost_price = (net_amount / actual_qty).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                ) if actual_qty > 0 else nav

            # 份额可赎回日（T+2）
            available_date = today
            for _ in range(2):
                available_date = self._next_trading_day(available_date)

            if position:
                self.client.table("positions").update({
                    "quantity": float(new_qty),
                    "cost_price": float(new_cost_price),
                    "confirm_date": today.isoformat(),
                    "available_date": available_date.isoformat(),
                    "updated_at": now,
                }).eq("id", position["id"]).execute()
            else:
                self.client.table("positions").insert({
                    "user_id": user_id,
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "quantity": float(new_qty),
                    "cost_price": float(new_cost_price),
                    "confirm_date": today.isoformat(),
                    "available_date": available_date.isoformat(),
                    "created_at": now,
                    "updated_at": now,
                }).execute()

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
            net_amount = redeem_amount - actual_fee

            # 3. 更新持仓
            new_qty = current_qty - quantity

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

            if new_qty <= 0:
                self.client.table("positions").delete().eq("id", position["id"]).execute()
            else:
                self.client.table("positions").update({
                    "quantity": float(new_qty),
                    "updated_at": now,
                }).eq("id", position["id"]).execute()

            # 5. 写流水
            self._write_trade_flow(user_id, fund_code, fund_name, "sell",
                                   redeem_amount, nav, quantity, actual_fee)

            # 6. 更新订单状态
            cost_of_sold = (cost_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            trade_pnl = (net_amount - cost_of_sold).quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)

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
            "reject_reason": f"确认日期: {confirm_date}" if confirm_date and status == "pending" else None,
            "confirm_date": confirm_date,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.client.table("trade_orders").insert(data).execute()
        except Exception as e:
            logger.error(f"写交易委托失败: {e}")

    def _write_trade_flow(self, user_id: str, fund_code: str, fund_name: str,
                          direction: str, amount: Decimal, price: Decimal,
                          quantity: Decimal, fee: Decimal) -> None:
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
        try:
            self.client.table("trade_flow").insert(data).execute()
        except Exception as e:
            logger.error(f"写交易流水失败: {e}")

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
