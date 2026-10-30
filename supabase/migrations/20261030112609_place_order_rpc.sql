-- ============================================================================
-- 订单确认重写 · P2a：下单侧原子写入 RPC
--
-- 设计来源：docs/20-设计/基金与交易/订单确认-实现方案.md §3.4
-- 为什么必须有这一层：下单若是「读账户 → 内存改 → 写回」两次独立请求，
-- 两个并发申购会互相覆盖 cash/frozen_cash，确认侧再严谨也只能判成数据不一致。
--
-- 约定：
--   1. SECURITY DEFINER + SET search_path = public, pg_temp
--   2. 预期内业务失败返回 jsonb {result:...}，不抛异常
--   3. 应用层仍负责白名单/ETF 拦截/申购状态/金额上下限/净值预估/风险提示，
--      RPC 只做资金与额度的原子校验，避免两套业务规则漂移
--   4. 同一 user:fund 用 advisory 事务锁串行化，保证额度统计与冻结不互相穿插
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 3.4.1 place_purchase_order
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."place_purchase_order"(
  p_user_id uuid,
  p_fund_code character varying,
  p_fund_name character varying,
  p_amount numeric,
  p_fee numeric,
  p_net_amount numeric,
  p_estimated_nav numeric,
  p_accepted_date date,
  p_confirm_date date,
  p_available_date date,
  p_fee_snapshot jsonb,
  p_max_purchase_amount numeric DEFAULT NULL,
  p_client_order_id "text" DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order      "public"."trade_orders"%ROWTYPE;
  v_existing   "public"."trade_orders"%ROWTYPE;
  v_account    "public"."accounts"%ROWTYPE;
  v_used       numeric;
  v_created    "public"."trade_orders"%ROWTYPE;
BEGIN
  -- 1. 同一用户同一基金串行化：额度统计与冻结必须基于同一时刻的账户快照
  PERFORM pg_advisory_xact_lock(hashtext(p_user_id::text || ':' || p_fund_code));

  -- 2. 幂等
  IF p_client_order_id IS NOT NULL THEN
    SELECT * INTO v_existing FROM "public"."trade_orders"
     WHERE "user_id" = p_user_id AND "client_order_id" = p_client_order_id;
    IF FOUND THEN
      IF v_existing."fund_code" = p_fund_code AND v_existing."direction" = 'buy' THEN
        RETURN jsonb_build_object('result','existing','order',to_jsonb(v_existing));
      END IF;
      RETURN jsonb_build_object('result','idempotency_conflict',
                                'existing_order_id',v_existing."id");
    END IF;
  END IF;

  -- 3. 入口校验（失败不写任何数据）
  IF p_amount IS NULL OR p_amount <= 0 OR p_fee IS NULL OR p_fee < 0 THEN
    RETURN jsonb_build_object('result','invalid_amount');
  END IF;
  IF ABS(p_amount - (p_net_amount + p_fee)) > 0.01 THEN
    RETURN jsonb_build_object('result','invalid_amount',
                              'detail','amount <> net + fee');
  END IF;
  IF p_accepted_date IS NULL OR p_confirm_date IS NULL OR p_available_date IS NULL
     OR p_confirm_date < p_accepted_date OR p_available_date < p_confirm_date THEN
    RETURN jsonb_build_object('result','invalid_dates');
  END IF;

  -- 4. 锁账户（两个不同基金的并发首单可能同时建账户）
  SELECT * INTO v_account FROM "public"."accounts"
   WHERE "user_id" = p_user_id FOR UPDATE;
  IF NOT FOUND THEN
    INSERT INTO "public"."accounts" ("user_id") VALUES (p_user_id)
    ON CONFLICT ("user_id") DO NOTHING;
    SELECT * INTO v_account FROM "public"."accounts"
     WHERE "user_id" = p_user_id FOR UPDATE;
  END IF;

  -- 5. 资金校验
  IF v_account."cash" < p_amount THEN
    RETURN jsonb_build_object('result','insufficient_cash','cash',v_account."cash");
  END IF;

  -- 6. 单日额度（manual_review 仍可能成交，必须计入）
  IF p_max_purchase_amount IS NOT NULL THEN
    SELECT COALESCE(SUM("amount"), 0) INTO v_used
      FROM "public"."trade_orders"
     WHERE "user_id" = p_user_id
       AND "fund_code" = p_fund_code
       AND "direction" = 'buy'
       AND "accepted_date" = p_accepted_date
       AND "status" IN ('pending','processing','completed','manual_review');

    IF v_used + p_amount > p_max_purchase_amount THEN
      RETURN jsonb_build_object('result','limit_exceeded',
                                'used',v_used,'limit',p_max_purchase_amount);
    END IF;
  END IF;

  -- 7. 原子冻结
  UPDATE "public"."accounts"
     SET "cash"        = "cash" - p_amount,
         "frozen_cash" = "frozen_cash" + p_amount,
         "updated_at"  = now()
   WHERE "user_id" = p_user_id;

  -- 8. 落单：份额/成交价在确认时回填
  INSERT INTO "public"."trade_orders"(
    "user_id","fund_code","fund_name","direction","order_type",
    "price","quantity","amount","fee","net_amount","status",
    "accepted_date","confirm_date","available_date","estimated_nav",
    "fee_rule_snapshot","client_order_id")
  VALUES (
    p_user_id, p_fund_code, COALESCE(p_fund_name,''), 'buy', 'market',
    COALESCE(p_estimated_nav, 0), 0, p_amount, p_fee, p_net_amount, 'pending',
    p_accepted_date, p_confirm_date, p_available_date, p_estimated_nav,
    p_fee_snapshot, p_client_order_id)
  RETURNING * INTO v_created;

  RETURN jsonb_build_object('result','placed','order',to_jsonb(v_created));
END $$;

-- ----------------------------------------------------------------------------
-- 3.4.2 place_redeem_order
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."place_redeem_order"(
  p_user_id uuid,
  p_fund_code character varying,
  p_fund_name character varying,
  p_quantity numeric,
  p_accepted_date date,
  p_confirm_date date,
  p_settle_date date,
  p_fee_snapshot jsonb,
  p_client_order_id "text" DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_existing    "public"."trade_orders"%ROWTYPE;
  v_created     "public"."trade_orders"%ROWTYPE;
  v_pending_buy integer;
  v_available   numeric;
BEGIN
  -- 1. 同一 user:fund 串行化：可赎份额的计算与占用必须原子
  PERFORM pg_advisory_xact_lock(hashtext(p_user_id::text || ':' || p_fund_code));

  -- 2. 幂等
  IF p_client_order_id IS NOT NULL THEN
    SELECT * INTO v_existing FROM "public"."trade_orders"
     WHERE "user_id" = p_user_id AND "client_order_id" = p_client_order_id;
    IF FOUND THEN
      IF v_existing."fund_code" = p_fund_code AND v_existing."direction" = 'sell' THEN
        RETURN jsonb_build_object('result','existing','order',to_jsonb(v_existing));
      END IF;
      RETURN jsonb_build_object('result','idempotency_conflict',
                                'existing_order_id',v_existing."id");
    END IF;
  END IF;

  -- 3. 入口校验
  IF p_quantity IS NULL OR p_quantity <= 0 THEN
    RETURN jsonb_build_object('result','invalid_amount');
  END IF;
  IF p_accepted_date IS NULL OR p_confirm_date IS NULL OR p_settle_date IS NULL
     OR p_confirm_date <> p_accepted_date
     OR p_settle_date < p_accepted_date THEN
    RETURN jsonb_build_object('result','invalid_dates');
  END IF;

  -- 4. 在途申购挡住赎回（沿用现有业务规则；放开需先改这里）
  SELECT COUNT(*) INTO v_pending_buy FROM "public"."trade_orders"
   WHERE "user_id" = p_user_id AND "fund_code" = p_fund_code
     AND "direction" = 'buy'
     AND "status" IN ('pending','processing');
  IF v_pending_buy > 0 THEN
    RETURN jsonb_build_object('result','pending_purchase','count',v_pending_buy);
  END IF;

  -- 5. 可赎份额 = 已到可赎回日的 lot 余额 - 在途卖单占用的份额
  --    只扣「尚未扣减 lot」的卖单状态：确认卖单（confirm_sell_order）在同一事务里
  --    已经把 remaining_qty 扣掉并置为 settling，再扣一次会让用户的可赎份额凭空少一截。
  SELECT COALESCE(SUM("remaining_qty"), 0) INTO v_available
    FROM "public"."position_lots"
   WHERE "user_id" = p_user_id AND "fund_code" = p_fund_code
     AND "remaining_qty" > 0
     AND COALESCE("available_date", "nav_date") <= p_accepted_date;

  v_available := v_available - (
    SELECT COALESCE(SUM("quantity"), 0) FROM "public"."trade_orders"
     WHERE "user_id" = p_user_id AND "fund_code" = p_fund_code
       AND "direction" = 'sell'
       AND "status" IN ('pending','processing','manual_review'));

  IF p_quantity > v_available THEN
    RETURN jsonb_build_object('result','insufficient_shares','available',v_available);
  END IF;

  -- 6. 落单：金额与净值在确认时回填
  INSERT INTO "public"."trade_orders"(
    "user_id","fund_code","fund_name","direction","order_type",
    "price","quantity","amount","fee","status",
    "accepted_date","confirm_date","settle_date",
    "fee_rule_snapshot","client_order_id")
  VALUES (
    p_user_id, p_fund_code, COALESCE(p_fund_name,''), 'sell', 'market',
    0, p_quantity, 0, 0, 'pending',
    p_accepted_date, p_confirm_date, p_settle_date,
    p_fee_snapshot, p_client_order_id)
  RETURNING * INTO v_created;

  RETURN jsonb_build_object('result','placed','order',to_jsonb(v_created));
END $$;

-- ----------------------------------------------------------------------------
-- 权限：只给 service_role
-- ----------------------------------------------------------------------------
REVOKE ALL ON FUNCTION "public"."place_purchase_order"(
  uuid,character varying,character varying,numeric,numeric,numeric,numeric,
  date,date,date,jsonb,numeric,"text") FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."place_redeem_order"(
  uuid,character varying,character varying,numeric,
  date,date,date,jsonb,"text") FROM PUBLIC, "anon", "authenticated";

GRANT EXECUTE ON FUNCTION "public"."place_purchase_order"(
  uuid,character varying,character varying,numeric,numeric,numeric,numeric,
  date,date,date,jsonb,numeric,"text") TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."place_redeem_order"(
  uuid,character varying,character varying,numeric,
  date,date,date,jsonb,"text") TO "service_role";
