"""
持仓交易核心服务

实现：
- 账户初始化（开仓时自动创建，初始资金 10 万）
- 买入建仓（校验现金→扣款→持仓加权平均成本→写流水）
- 卖出减仓（校验持仓→扣份额→算赎回费→入账→写流水）
- 交易流水分页查询
- 账户概况（现金/持仓市值/总资产/总盈亏/总收益率）
- 每日资产快照（支撑日收益率计算）
"""
import logging
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 初始资金
INITIAL_CASH = Decimal("100000.00")

# 北京时间时区
BEIJING_TZ = timezone(timedelta(hours=8))


def _beijing_now() -> datetime:
    """返回当前北京时间"""
    return datetime.now(BEIJING_TZ)


def _now_iso() -> str:
    """返回当前北京时间 ISO 字符串（用于数据库写入和 API 返回）"""
    return _beijing_now().isoformat()


def _now_utc_iso() -> str:
    """返回当前 UTC 时间 ISO 字符串（Supabase 兼容）"""
    return datetime.now(timezone.utc).isoformat()


def _parse_time(ts: str) -> datetime:
    """解析时间字符串为北京时间 datetime"""
    ts = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        dt = dt.astimezone(BEIJING_TZ)
    return dt.replace(tzinfo=None)


class PortfolioService:
    """持仓交易服务"""

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
        """
        确保用户有资金账户，不存在则自动创建（初始 10 万）。

        返回 accounts 表行。
        """
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

        # 创建新账户
        now = _now_iso()
        insert_data = {
            "user_id": user_id,
            "cash": float(INITIAL_CASH),
            "created_at": now,
            "updated_at": now,
        }
        r = self.client.table("accounts").insert(insert_data).execute()
        if r.data and len(r.data) > 0:
            logger.info(f"新用户账户创建成功: user_id={user_id}")
            return r.data[0]
        raise RuntimeError("账户创建失败")

    def get_account(self, user_id: str) -> Optional[dict]:
        """获取用户资金账户"""
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

    # ==================== 市场行情/价格获取 ====================

    def _get_fund_type(self, fund_code: str) -> str:
        """获取基金类型（otf=场外基金, etf=场内ETF）"""
        from server.services.fund_fee_service import FundFeeService
        svc = FundFeeService()
        return svc.get_fund_type(fund_code)

    def _get_current_price(self, fund_code: str, fund_type: str = None) -> Optional[Decimal]:
        """
        获取基金当前交易价格。

        按 fund_type 区分：
        - ETF：从实时行情缓存取（盘中实时价）
        - 场外基金：从 akshare 取最新净值
        """
        if fund_type is None:
            fund_type = self._get_fund_type(fund_code)

        if fund_type == 'etf':
            # ETF：实时行情价
            from server.services.finance_api_service import FinanceApiService
            svc = FinanceApiService()
            spot = svc.query_spot(fund_code)
            if spot and spot.get("price"):
                return Decimal(str(spot["price"]))
            # ETF 行情也取不到时降级到净值
            return self._get_fund_nav(fund_code)

        # 场外基金：净值
        price = self._get_fund_nav(fund_code)
        if price is not None:
            return price

        # 场外基金净值也取不到时降级到行情缓存
        from server.services.finance_api_service import FinanceApiService
        svc = FinanceApiService()
        spot = svc.query_spot(fund_code)
        if spot and spot.get("price"):
            return Decimal(str(spot["price"]))

        return None

    def _get_fund_nav(self, fund_code: str) -> Optional[Decimal]:
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

    def _get_fund_name(self, fund_code: str) -> str:
        """获取基金名称（优先从费率表取，其次行情缓存，最后返回 code）"""
        # 1. 优先从 fund_fee_rules 表取
        try:
            from server.services.fund_fee_service import FundFeeService
            fee_svc = FundFeeService()
            rule = fee_svc.get_fee_rule(fund_code)
            if rule and rule.get("fund_name"):
                return rule["fund_name"]
        except Exception:
            pass

        # 2. 尝试从行情缓存取
        try:
            from server.services.finance_api_service import FinanceApiService
            svc = FinanceApiService()
            spot = svc.query_spot(fund_code)
            if spot and spot.get("name"):
                return spot["name"]
        except Exception:
            pass

        # 3. 都取不到返回 code
        return fund_code

    # ==================== 手续费计算 ====================

    def _calc_trade_fee(self, fund_code: str, amount: Decimal, direction: str, hold_days: int = 0) -> dict:
        """
        统一费用计算，按 fund_type 自动选择模型。

        返回: {"fee": Decimal, "fee_type": str, "fund_type": str}
        """
        from server.services.fund_fee_service import FundFeeService
        svc = FundFeeService()
        result = svc.calc_fee_for_trade(fund_code, float(amount), direction, hold_days)
        return {
            "fee": Decimal(str(result["fee"])),
            "fee_type": result["fee_type"],
            "fund_type": result["fund_type"],
        }

    # ==================== 买入 ====================

    def buy(self, user_id: str, fund_code: str, quantity: Decimal, price: Optional[Decimal] = None) -> dict:
        """
        买入建仓/加仓（按 fund_type 自动选择场外/场内规则）。

        场外基金 (otf)：
        - 全天可提交，15:00 为界，15:00 后 pending
        - 成交价格为当日净值
        - 申购费（外扣法）

        场内 ETF (etf)：
        - 仅 9:30-11:30、13:00-15:00 可交易，非交易时段直接拒绝
        - 成交价格为盘中实时价
        - 100 份整数倍
        - 券商佣金（万2.5，最低5元）

        参数:
            user_id: 用户 ID
            fund_code: 基金代码
            quantity: 份额
            price: 成交单价（不传则自动取价）
        """
        try:
            now_beijing = _beijing_now()

            # 0. 判断基金类型
            fund_type = self._get_fund_type(fund_code)

            # 0a. ETF 交易时间校验（非交易时段直接拒绝）
            if fund_type == 'etf':
                from server.services.trading_calendar import is_etf_trading_time
                if not is_etf_trading_time(now_beijing):
                    return {
                        "success": False,
                        "message": "ETF 仅限交易日 9:30-11:30 和 13:00-15:00 交易",
                        "data": None,
                    }
                # ETF 数量校验：100 份整数倍
                if int(quantity) % 100 != 0:
                    return {
                        "success": False,
                        "message": "ETF 必须以 100 份（1 手）的整数倍交易",
                        "data": None,
                    }
                is_pending = False
                confirm_date = now_beijing.date()

            # 0b. 场外基金交易时间（15:00 截止，非交易时段 pending）
            else:
                from server.services.trading_calendar import is_trading_day, is_before_cutoff, get_confirmation_date
                is_trade_day = is_trading_day(now_beijing.date())
                before_cutoff = is_before_cutoff(now_beijing)
                confirm_date = get_confirmation_date(now_beijing)
                is_pending = not (is_trade_day and before_cutoff)

            # 1. 获取价格
            if price is None:
                price = self._get_current_price(fund_code, fund_type)
            if price is None or price <= 0:
                return {"success": False, "message": f"无法获取基金 {fund_code} 的当前价格", "data": None}

            fund_name = self._get_fund_name(fund_code)

            # 2. 计算金额与手续费
            amount = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            fee_result = self._calc_trade_fee(fund_code, amount, "buy")
            fee = fee_result["fee"]
            total_cost = amount + fee

            # 3. 校验最低申购金额（仅场外基金）
            if fund_type != 'etf':
                from server.services.fund_fee_service import FundFeeService
                fee_svc = FundFeeService()
                min_amount = Decimal(str(fee_svc.get_min_purchase_amount(fund_code)))
                if amount < min_amount:
                    return {
                        "success": False,
                        "message": f"申购金额 {float(amount):.2f} 元低于最低申购金额 {float(min_amount):.2f} 元",
                        "data": None,
                    }

            # 4. 校验可用现金
            account = self._ensure_account(user_id)
            cash = Decimal(str(account["cash"]))
            if cash < total_cost:
                return {
                    "success": False,
                    "message": f"可用现金不足：需 {float(total_cost):.2f} 元（含手续费 {float(fee):.2f} 元），实际可用 {float(cash):.2f} 元",
                    "data": None,
                }

            # 5. 扣款
            new_cash = cash - total_cost

            # 6. 更新持仓（加权平均成本，含手续费）
            position = self._get_position(user_id, fund_code)
            if position:
                old_qty = Decimal(str(position["quantity"]))
                old_cost_price = Decimal(str(position["cost_price"]))
                total_cost_basis = old_qty * old_cost_price + amount + fee
                new_qty = old_qty + quantity
                new_cost_price = (total_cost_basis / new_qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if new_qty > 0 else price
            else:
                new_qty = quantity
                new_cost_price = ((amount + fee) / quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

            now = _now_iso()

            # 7. 写数据库
            self.client.table("accounts").update({
                "cash": float(new_cash),
                "updated_at": now,
            }).eq("user_id", user_id).execute()

            if position:
                self.client.table("positions").update({
                    "quantity": float(new_qty),
                    "cost_price": float(new_cost_price),
                    "confirm_date": confirm_date.isoformat(),
                    "updated_at": now,
                }).eq("id", position["id"]).execute()
            else:
                self.client.table("positions").insert({
                    "user_id": user_id,
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "quantity": float(new_qty),
                    "cost_price": float(new_cost_price),
                    "confirm_date": confirm_date.isoformat(),
                    "created_at": now,
                    "updated_at": now,
                }).execute()

            # 8. 写交易委托与流水
            order_status = "pending" if is_pending else "completed"
            self._write_trade_order(
                user_id, fund_code, fund_name, "buy", price, quantity,
                amount, fee, order_status,
                confirm_date=confirm_date.isoformat() if is_pending else None,
            )
            self._write_trade_flow(user_id, fund_code, fund_name, "buy", price, quantity, amount, fee)

            # 9. 构造返回消息
            if is_pending:
                message = f"买入申请已提交，将于 {confirm_date.isoformat()}（下一交易日）按当日净值确认"
            else:
                message = "买入成功"

            logger.info(
                f"买入: user={user_id}, code={fund_code}, type={fund_type}, "
                f"price={price}, qty={quantity}, amount={amount}, fee={fee}, "
                f"new_qty={new_qty}, new_cost_price={new_cost_price}, status={order_status}"
            )

            return {
                "success": True,
                "message": message,
                "data": {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "fund_type": fund_type,
                    "price": float(price),
                    "quantity": float(quantity),
                    "amount": float(amount),
                    "fee": float(fee),
                    "total_cost": float(total_cost),
                    "position_qty": float(new_qty),
                    "cost_price": float(new_cost_price),
                    "cash_remaining": float(new_cash),
                    "trade_time": now,
                    "status": order_status,
                    "confirm_date": confirm_date.isoformat() if is_pending else now_beijing.date().isoformat(),
                },
            }

        except Exception as e:
            logger.error(f"买入失败: {e}", exc_info=True)
            return {"success": False, "message": f"买入失败: {str(e)}", "data": None}

    # ==================== 卖出 ====================

    def sell(self, user_id: str, fund_code: str, quantity: Decimal, price: Optional[Decimal] = None) -> dict:
        """
        卖出减仓/清仓（按 fund_type 自动选择场外/场内规则）。

        参数:
            user_id: 用户 ID
            fund_code: 基金代码
            quantity: 份额
            price: 成交单价（不传则自动取价）
        """
        try:
            now_beijing = _beijing_now()

            # 0. 判断基金类型
            fund_type = self._get_fund_type(fund_code)

            # 0a. ETF 交易时间校验
            if fund_type == 'etf':
                from server.services.trading_calendar import is_etf_trading_time
                if not is_etf_trading_time(now_beijing):
                    return {
                        "success": False,
                        "message": "ETF 仅限交易日 9:30-11:30 和 13:00-15:00 交易",
                        "data": None,
                    }
                if int(quantity) % 100 != 0:
                    return {
                        "success": False,
                        "message": "ETF 必须以 100 份（1 手）的整数倍交易",
                        "data": None,
                    }
                is_pending = False
                confirm_date = now_beijing.date()

            # 0b. 场外基金 15:00 截止
            else:
                from server.services.trading_calendar import is_trading_day, is_before_cutoff, get_confirmation_date
                is_trade_day = is_trading_day(now_beijing.date())
                before_cutoff = is_before_cutoff(now_beijing)
                confirm_date = get_confirmation_date(now_beijing)
                is_pending = not (is_trade_day and before_cutoff)

            # 1. 获取价格
            if price is None:
                price = self._get_current_price(fund_code, fund_type)
            if price is None or price <= 0:
                return {"success": False, "message": f"无法获取基金 {fund_code} 的当前价格", "data": None}

            fund_name = self._get_fund_name(fund_code)

            # 2. 校验持仓
            position = self._get_position(user_id, fund_code)
            if not position:
                return {"success": False, "message": f"未持有基金 {fund_code}，无法卖出", "data": None}

            current_qty = Decimal(str(position["quantity"]))
            if quantity > current_qty:
                return {
                    "success": False,
                    "message": f"可卖份额不足：需 {float(quantity)} 份，实际持有 {float(current_qty)} 份",
                    "data": None,
                }

            # 3. 计算费用
            cost_price = Decimal(str(position["cost_price"]))
            amount = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # ETF 无持有天数概念，场外基金按确认日算持有天数
            hold_days = 0
            if fund_type != 'etf':
                confirm_date_str = position.get("confirm_date", "")
                if confirm_date_str:
                    try:
                        hold_start = date.fromisoformat(str(confirm_date_str))
                        hold_days = (now_beijing.date() - hold_start).days
                    except Exception:
                        hold_days = 0
                else:
                    created_at = position.get("created_at", "")
                    if created_at:
                        try:
                            hold_start = _parse_time(created_at)
                            hold_days = (_beijing_now() - hold_start).days
                        except Exception:
                            hold_days = 0

            fee_result = self._calc_trade_fee(fund_code, amount, "sell", max(hold_days, 0))
            fee = fee_result["fee"]
            net_amount = amount - fee

            # 4. 更新持仓
            new_qty = current_qty - quantity
            now = _now_iso()

            # 5. 入账
            account = self._ensure_account(user_id)
            cash = Decimal(str(account["cash"]))
            new_cash = cash + net_amount

            self.client.table("accounts").update({
                "cash": float(new_cash),
                "updated_at": now,
            }).eq("user_id", user_id).execute()

            if new_qty == 0:
                self.client.table("positions").delete().eq("id", position["id"]).execute()
            else:
                self.client.table("positions").update({
                    "quantity": float(new_qty),
                    "updated_at": now,
                }).eq("id", position["id"]).execute()

            # 6. 写流水
            order_status = "pending" if is_pending else "completed"
            self._write_trade_order(
                user_id, fund_code, fund_name, "sell", price, quantity,
                amount, fee, order_status,
                confirm_date=confirm_date.isoformat() if is_pending else None,
            )
            self._write_trade_flow(user_id, fund_code, fund_name, "sell", price, quantity, amount, fee)

            # 7. 计算盈亏
            cost_of_sold = (cost_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            trade_pnl = (net_amount - cost_of_sold).quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)

            if is_pending:
                message = f"卖出申请已提交，将于 {confirm_date.isoformat()}（下一交易日）按当日净值确认"
            else:
                message = "卖出成功"

            logger.info(
                f"卖出: user={user_id}, code={fund_code}, type={fund_type}, "
                f"price={price}, qty={quantity}, amount={amount}, fee={fee}, "
                f"net={net_amount}, trade_pnl={trade_pnl}, new_qty={new_qty}, status={order_status}"
            )

            return {
                "success": True,
                "message": message,
                "data": {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "fund_type": fund_type,
                    "price": float(price),
                    "quantity": float(quantity),
                    "amount": float(amount),
                    "fee": float(fee),
                    "net_amount": float(net_amount),
                    "trade_pnl": float(trade_pnl),
                    "hold_days": max(hold_days, 0) if fund_type != 'etf' else 0,
                    "position_qty": float(new_qty),
                    "cost_price": float(cost_price) if new_qty > 0 else None,
                    "cash_remaining": float(new_cash),
                    "trade_time": now,
                    "status": order_status,
                    "confirm_date": confirm_date.isoformat() if is_pending else now_beijing.date().isoformat(),
                },
            }

        except Exception as e:
            logger.error(f"卖出失败: {e}", exc_info=True)
            return {"success": False, "message": f"卖出失败: {str(e)}", "data": None}

    # ==================== 持仓查询 ====================

    def _get_position(self, user_id: str, fund_code: str) -> Optional[dict]:
        """查询单只基金持仓"""
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
        """
        查询用户所有持仓（含市值、盈亏）。

        参数:
            user_id: 用户 ID
            include_quote: 是否计算实时市值和盈亏

        返回:
            {"total": int, "items": list, "total_pnl": float, "total_position_value": float}
        """
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
                fund_type = self._get_fund_type(item["fund_code"])
                item["fund_type"] = fund_type

                if include_quote:
                    market_price = self._get_current_price(item["fund_code"], fund_type)
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
        """
        获取账户概况。

        返回:
            {
                "cash": float,          # 可用现金
                "position_value": float, # 持仓市值
                "total_assets": float,   # 总资产 = 现金 + 持仓市值
                "total_pnl": float,      # 总盈亏 = 总资产 - 初始资金
                "total_return_rate": float, # 总收益率
                "position_count": int,   # 持仓基金数
            }
        """
        try:
            account = self.get_account(user_id)
            if not account:
                # 未创建账户 = 无交易
                return {
                    "cash": float(INITIAL_CASH),
                    "position_value": 0,
                    "total_assets": float(INITIAL_CASH),
                    "total_pnl": 0,
                    "total_return_rate": 0,
                    "position_count": 0,
                }

            cash = Decimal(str(account["cash"]))
            positions_data = self.list_positions(user_id, include_quote=True)
            position_value = Decimal(str(positions_data["total_position_value"]))
            total_assets = cash + position_value
            total_pnl = total_assets - INITIAL_CASH
            total_return_rate = (total_pnl / INITIAL_CASH) if INITIAL_CASH > 0 else Decimal("0")

            return {
                "cash": float(cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "position_value": float(position_value.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
                "total_assets": float(total_assets.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
                "total_pnl": float(total_pnl.quantize(Decimal("0.02"), rounding=ROUND_HALF_UP)),
                "total_return_rate": float(total_return_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
                "position_count": positions_data["total"],
            }

        except Exception as e:
            logger.error(f"账户概况查询失败: {e}", exc_info=True)
            return {"cash": 0, "position_value": 0, "total_assets": 0, "total_pnl": 0, "total_return_rate": 0, "position_count": 0}

    # ==================== 交易流水 ====================

    def _write_trade_order(self, user_id: str, fund_code: str, fund_name: str,
                           direction: str, price: Decimal, quantity: Decimal,
                           amount: Decimal, fee: Decimal, status: str,
                           reject_reason: Optional[str] = None,
                           confirm_date: Optional[str] = None) -> None:
        """写交易委托记录"""
        now = _now_iso()
        data = {
            "user_id": user_id,
            "fund_code": fund_code,
            "fund_name": fund_name,
            "direction": direction,
            "order_type": "market",
            "price": float(price),
            "quantity": float(quantity),
            "amount": float(amount),
            "fee": float(fee),
            "status": status,
            "reject_reason": reject_reason or (f"确认日期: {confirm_date}" if confirm_date else None),
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.client.table("trade_orders").insert(data).execute()
        except Exception as e:
            logger.error(f"写交易委托失败: {e}")

    def _write_trade_flow(self, user_id: str, fund_code: str, fund_name: str,
                          direction: str, price: Decimal, quantity: Decimal,
                          amount: Decimal, fee: Decimal) -> None:
        """写交易流水"""
        now = _now_iso()
        data = {
            "user_id": user_id,
            "fund_code": fund_code,
            "fund_name": fund_name,
            "direction": direction,
            "price": float(price),
            "quantity": float(quantity),
            "amount": float(amount),
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
        """
        分页查询交易流水。

        参数:
            user_id: 用户 ID
            fund_code: 基金代码（可选，过滤）
            direction: 方向 buy/sell（可选，过滤）
            page: 页码（从 1 开始）
            page_size: 每页条数

        返回:
            {"total": int, "page": int, "page_size": int, "total_pages": int, "items": list}
        """
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

            # 给每条流水加 fund_type
            for item in items:
                item["fund_type"] = self._get_fund_type(item["fund_code"])

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
        """
        对指定用户生成当日资产快照（幂等：同一天已存在则更新）。

        参数:
            user_id: 用户 ID
            snapshot_date: 快照日期（默认今天）

        返回:
            {"success": bool, "message": str, "data": dict}
        """
        if snapshot_date is None:
            snapshot_date = date.today()

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

            # UPSERT：同一天存在则更新
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
        """
        查询最近 N 天的每日收益率。

        返回:
            {"items": [{"date": str, "total_assets": float, "daily_return": float}, ...]}
        """
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
