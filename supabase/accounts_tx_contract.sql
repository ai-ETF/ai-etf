-- ============================================================================
-- public.accounts 资金写入契约（骨架 / NOT IMPLEMENTED）
--
-- 目的：先冻结「事务名 + 签名 + 业务口径」，函数体留待实现。
--       对应 CLAUDE.md「契约优先」：接口先定，冻结后不做破坏性修改。
-- 状态：函数体用 RAISE EXCEPTION 快速失败，避免空壳被误调用时
--       静默返回 void 而产生错误的资金状态（CLAUDE.md：禁止默认值兜底）。
-- 依赖：实现需要 trade_orders（状态机 / net_amount）、positions、
--       fund_nav / fund_nav_state、position_lots，属于后续表审计范围。
--       审完那些表回来填函数体，本文件的事务名与签名不动。
--
-- 命名：一律用 account_* 新名字，绝不 CREATE OR REPLACE 覆盖现有 RPC。
--       现有事务名：place_purchase_order / place_redeem_order /
--       confirm_buy_order / confirm_sell_order / settle_redeem_order /
--       cancel_trade_order / reject_trade_order /
--       credit_money_fund_income_atomic / recalc_position_from_lots，
--       它们当前直接 UPDATE accounts；用同名空壳会覆盖实现、直接破坏线上。
--       整体改造方向：由这些 RPC 调用本组 account_* 函数，
--       accounts 的资金变更只经由此处，收敛写入口（单一职责）。
-- 权限：仅 service_role 可执行；调用方在单事务内调用，函数不自行 COMMIT。
--       不需要 SECURITY DEFINER（service_role 已持有 accounts 的全部权限）。
-- 幂等：p_order_id 为幂等键，同一订单同一状态迁移只允许调用一次；
--       实现内须校验订单状态，防重复执行产生副作用。
-- 关联：账户懒创建的下线改造见 retire_lazy_account_creation.sql，
--       不在本文件登记（本文件只冻结 account_* 资金事务契约）。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) frozen_cash：买单受理冻结
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.account_freeze_purchase_cash(
    p_user_id uuid, p_order_id uuid, p_amount numeric
) RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- TODO 实现：UPDATE accounts SET cash = cash - p_amount,
    --            frozen_cash = frozen_cash + p_amount WHERE user_id = p_user_id
    --            AND cash >= p_amount；ROW_COUNT = 0 时抛业务异常。
    RAISE EXCEPTION 'not implemented: account_freeze_purchase_cash (order=%)', p_order_id;
END;
$$;

COMMENT ON FUNCTION public.account_freeze_purchase_cash(uuid, uuid, numeric) IS
'买单受理：冻结申购资金。资金流向 cash -= p_amount、frozen_cash += p_amount，总资产不变。调用方 place_purchase_order。幂等键 p_order_id，同一订单只调用一次；实现须校验订单仍为 pending 且 cash >= p_amount。依赖 trade_orders。';

-- ---------------------------------------------------------------------------
-- 2) frozen_cash：撤单 / 受理被拒，解冻退回
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.account_unfreeze_purchase_cash(
    p_user_id uuid, p_order_id uuid, p_amount numeric
) RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- TODO 实现：frozen_cash -= p_amount、cash += p_amount，
    --            并校验 frozen_cash >= p_amount。
    RAISE EXCEPTION 'not implemented: account_unfreeze_purchase_cash (order=%)', p_order_id;
END;
$$;

COMMENT ON FUNCTION public.account_unfreeze_purchase_cash(uuid, uuid, numeric) IS
'买单撤单 / 受理被拒：解冻并退回资金。资金流向 frozen_cash -= p_amount、cash += p_amount，总资产不变。调用方 cancel_trade_order / reject_trade_order。幂等键 p_order_id；实现须校验 frozen_cash >= p_amount 与订单状态。依赖 trade_orders。';

-- ---------------------------------------------------------------------------
-- 3) frozen_cash：买单确认，解冻换份额
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.account_confirm_purchase_cash(
    p_user_id uuid, p_order_id uuid, p_amount numeric
) RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- TODO 实现：frozen_cash -= p_amount；份额与费用由 positions / position_lots
    --            侧落账，费用使总资产减少。
    RAISE EXCEPTION 'not implemented: account_confirm_purchase_cash (order=%)', p_order_id;
END;
$$;

COMMENT ON FUNCTION public.account_confirm_purchase_cash(uuid, uuid, numeric) IS
'买单确认：解冻冻结资金并换为持仓份额。资金流向 frozen_cash -= p_amount（份额按 net_amount / 确认净值建仓，费用由 positions / position_lots 侧体现，总资产因费用减少）。调用方 confirm_buy_order。幂等键 p_order_id。依赖 trade_orders / positions / position_lots / fund_nav。';

-- ---------------------------------------------------------------------------
-- 4) settling_cash：卖出确认，登记在途赎回款
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.account_accrue_settling_cash(
    p_user_id uuid, p_order_id uuid, p_amount numeric
) RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- TODO 实现：settling_cash += p_amount（p_amount = trade_orders.net_amount），
    --            份额已由 positions 侧扣减。
    RAISE EXCEPTION 'not implemented: account_accrue_settling_cash (order=%)', p_order_id;
END;
$$;

COMMENT ON FUNCTION public.account_accrue_settling_cash(uuid, uuid, numeric) IS
'卖出确认：登记在途赎回款。份额已从 positions 扣减，settling_cash += p_amount（= trade_orders.net_amount，已扣赎回费），总资产不变，避免确认→到账之间资产凭空下降。调用方 confirm_sell_order。幂等键 p_order_id；实现须校验订单状态与 p_amount > 0。依赖 trade_orders / positions。';

-- ---------------------------------------------------------------------------
-- 5) settling_cash：赎回到账，转可用现金
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.account_settle_redemption_cash(
    p_user_id uuid, p_order_id uuid, p_amount numeric
) RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- TODO 实现：settling_cash -= p_amount、cash += p_amount，
    --            并校验 settling_cash >= p_amount。
    RAISE EXCEPTION 'not implemented: account_settle_redemption_cash (order=%)', p_order_id;
END;
$$;

COMMENT ON FUNCTION public.account_settle_redemption_cash(uuid, uuid, numeric) IS
'赎回到账：在途款转为可用现金。资金流向 settling_cash -= p_amount、cash += p_amount，总资产不变（内部转移）。调用方 settle_redeem_order。幂等键 p_order_id；实现须校验 settling_cash >= p_amount 与订单状态 settling。依赖 trade_orders。';

-- ---------------------------------------------------------------------------
-- 6) position_value：持仓 / 净值变动后重算
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.account_refresh_position_value(
    p_user_id uuid
) RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- TODO 实现：按 Σ(positions.quantity × 估值净值) 回写 position_value；
    --            货基按 1.0000，含 pending 卖单份额、不含 pending 买单份额。
    RAISE EXCEPTION 'not implemented: account_refresh_position_value (user=%)', p_user_id;
END;
$$;

COMMENT ON FUNCTION public.account_refresh_position_value(uuid) IS
'重算持仓估值：建仓 / 加减仓 / 净值更新 / 货基收益入账后，按 Σ(positions.quantity × 对应基金估值净值) 回写 position_value（货基按净值 1.0000；含 pending 卖单未扣减份额，不含 pending 买单未建仓份额）。调用方 recalc_position_from_lots / credit_money_fund_income_atomic / 净值刷新任务。无订单幂等键，按 p_user_id 全量重算，天然幂等。依赖 positions / fund_nav / fund_nav_state / position_lots。';

-- ---------------------------------------------------------------------------
-- 权限：仅 service_role
-- ---------------------------------------------------------------------------
REVOKE ALL ON FUNCTION
    public.account_freeze_purchase_cash(uuid, uuid, numeric),
    public.account_unfreeze_purchase_cash(uuid, uuid, numeric),
    public.account_confirm_purchase_cash(uuid, uuid, numeric),
    public.account_accrue_settling_cash(uuid, uuid, numeric),
    public.account_settle_redemption_cash(uuid, uuid, numeric),
    public.account_refresh_position_value(uuid)
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
    public.account_freeze_purchase_cash(uuid, uuid, numeric),
    public.account_unfreeze_purchase_cash(uuid, uuid, numeric),
    public.account_confirm_purchase_cash(uuid, uuid, numeric),
    public.account_accrue_settling_cash(uuid, uuid, numeric),
    public.account_settle_redemption_cash(uuid, uuid, numeric),
    public.account_refresh_position_value(uuid)
TO service_role;
