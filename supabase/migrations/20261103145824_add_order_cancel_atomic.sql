-- ============================================================================
-- 撤单：审计字段 + 原子撤单 RPC
--
-- 业务规则见 docs/10-需求/基金订单确认规则.md §5：
--   受理日 15:00 前可撤；15:00 整及之后不可撤。
--
-- 原子性：
--   整个撤单在一个数据库事务内完成——订单行锁 → 同 user:fund advisory 锁
--   → 买入时账户行锁 → 冻结资金退回 → 订单置 cancelled。
--   任一步失败整体回滚，不存在「钱退了但订单没撤」或「订单撤了但钱没退」。
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. 审计字段
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."trade_orders"
  ADD COLUMN IF NOT EXISTS "cancelled_at"  timestamp with time zone,
  ADD COLUMN IF NOT EXISTS "cancel_reason" "text",
  ADD COLUMN IF NOT EXISTS "cancelled_by"  "text";

COMMENT ON COLUMN "public"."trade_orders"."cancelled_at"  IS '实际撤单时间（审计）';
COMMENT ON COLUMN "public"."trade_orders"."cancel_reason" IS '撤单原因，用户撤单固定为 user_cancelled';
COMMENT ON COLUMN "public"."trade_orders"."cancelled_by"  IS '发起撤单的主体（用户 ID 或 admin）';

-- ----------------------------------------------------------------------------
-- 2. 原子撤单
--
-- 状态口径：
--   pending       → cancelled（唯一入口）
--   cancelled     → 幂等返回 already_cancelled
--   其他状态      → not_cancellable（processing/manual_review/settling/终态都不可撤）
--
-- 资金/份额：
--   买入：frozen_cash -= amount、cash += amount；冻结不足则转 manual_review，不部分退款
--   卖出：不动物资。可赎份额按「pending/processing/manual_review 卖单合计」动态扣减，
--         状态改为 cancelled 后自动恢复。
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."cancel_trade_order"(
  p_order_id uuid,
  p_user_id uuid,
  p_reason "text" DEFAULT 'user_cancelled',
  p_now timestamp with time zone DEFAULT now()
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order      "public"."trade_orders"%ROWTYPE;
  v_account    "public"."accounts"%ROWTYPE;
  v_deadline   timestamp with time zone;
BEGIN
  -- 1. 锁订单。归属不符按 not_found 处理，不泄露订单是否存在。
  SELECT * INTO v_order
    FROM "public"."trade_orders"
   WHERE "id" = p_order_id
   FOR UPDATE;

  IF NOT FOUND OR v_order."user_id" <> p_user_id THEN
    RETURN jsonb_build_object('result', 'not_found');
  END IF;

  -- 2. 幂等：重复撤单返回同一结果，不重复退款
  IF v_order."status" = 'cancelled' THEN
    RETURN jsonb_build_object(
      'result', 'already_cancelled',
      'order_id', v_order."id",
      'status', v_order."status");
  END IF;

  -- 3. 只有 pending 可撤
  IF v_order."status" <> 'pending' THEN
    RETURN jsonb_build_object(
      'result', 'not_cancellable',
      'order_id', v_order."id",
      'status', v_order."status");
  END IF;

  -- 4. 没有受理日就无法判定 15:00 截止，不猜
  IF v_order."accepted_date" IS NULL THEN
    RETURN jsonb_build_object(
      'result', 'accepted_date_missing',
      'order_id', v_order."id");
  END IF;

  -- 5. 撤单截止 = 受理日当天 15:00（Asia/Shanghai）
  v_deadline := (v_order."accepted_date"::timestamp
                 AT TIME ZONE 'Asia/Shanghai') + interval '15 hours';

  IF p_now >= v_deadline THEN
    RETURN jsonb_build_object(
      'result', 'cancel_window_closed',
      'order_id', v_order."id",
      'deadline', v_deadline);
  END IF;

  -- 6. 与下单串行化：同一 user:fund 的额度/可赎份额计算必须看到撤单后的状态。
  --    锁顺序：订单行锁 → advisory 锁 → 账户行锁（买入），与 place_* 不冲突。
  PERFORM pg_advisory_xact_lock(
    hashtext(v_order."user_id"::text || ':' || v_order."fund_code"));

  -- 7. 买入撤单：原子退回冻结资金
  IF v_order."direction" = 'buy' THEN
    SELECT * INTO v_account
      FROM "public"."accounts"
     WHERE "user_id" = v_order."user_id"
     FOR UPDATE;

    IF NOT FOUND OR v_account."frozen_cash" < v_order."amount" THEN
      -- 冻结资金不足以退款：不部分退款，转人工核对，整个事务只落状态
      UPDATE "public"."trade_orders"
         SET "status"             = 'manual_review',
             "last_error_code"    = 'FROZEN_CASH_INSUFFICIENT',
             "last_error_message" = '撤单时冻结资金不足，未退款，转人工核对',
             "updated_at"         = now()
       WHERE "id" = v_order."id";

      RETURN jsonb_build_object(
        'result', 'manual_review',
        'order_id', v_order."id",
        'code', 'FROZEN_CASH_INSUFFICIENT');
    END IF;

    UPDATE "public"."accounts"
       SET "frozen_cash" = "frozen_cash" - v_order."amount",
           "cash"        = "cash" + v_order."amount",
           "updated_at"  = now()
     WHERE "user_id" = v_order."user_id";
  END IF;

  -- 8. 置终态。卖出无需释放份额：占用口径已排除 cancelled。
  UPDATE "public"."trade_orders"
     SET "status"             = 'cancelled',
         "cancelled_at"       = p_now,
         "cancel_reason"      = COALESCE(p_reason, 'user_cancelled'),
         "cancelled_by"       = p_user_id::text,
         "updated_at"         = now()
   WHERE "id" = v_order."id";

  RETURN jsonb_build_object(
    'result', 'cancelled',
    'order_id', v_order."id",
    'direction', v_order."direction",
    'refunded_amount',
      CASE WHEN v_order."direction" = 'buy' THEN v_order."amount" ELSE 0 END,
    'released_quantity',
      CASE WHEN v_order."direction" = 'sell' THEN v_order."quantity" ELSE 0 END,
    'cancel_deadline', v_deadline);
END $$;

REVOKE ALL ON FUNCTION "public"."cancel_trade_order"(uuid, uuid, "text", timestamp with time zone)
  FROM PUBLIC, "anon", "authenticated";
GRANT EXECUTE ON FUNCTION "public"."cancel_trade_order"(uuid, uuid, "text", timestamp with time zone)
  TO "service_role";
