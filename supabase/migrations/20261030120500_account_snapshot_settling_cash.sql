-- ============================================================================
-- 订单确认重写 · P3：资产快照记录在途赎回款
--
-- 设计来源：docs/20-设计/基金与交易/订单确认-业务规则.md §3.9 第 7 条
-- 为什么需要：卖出确认后份额已从 positions 扣减，但现金要到 settle_date 才入账。
-- 若不记录 settling_cash，快照里的总资产会在「确认 → 到账」之间凭空下降一段。
--
-- 回填口径：存量快照该列为 0，不回填（当时确实没有在途赎回的记账口径）。
-- ============================================================================

ALTER TABLE "public"."account_snapshots"
  ADD COLUMN IF NOT EXISTS "settling_cash" numeric(18,2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN "public"."account_snapshots"."settling_cash"
  IS '快照日当天的在途赎回款（trade_orders.status=settling 的 net_amount 合计）';
