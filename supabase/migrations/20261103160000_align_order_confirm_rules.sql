-- ============================================================================
-- 订单确认对齐《基金订单确认规则（10:00 确认）》
--
-- 背景：旧实现里卖单的 confirm_date 等于受理日 T，赎回到账日按下单时的
-- `redeem_settle_delay`（境内 3 天 / QDII 7 天）算定；确认任务也只在夜间
-- 兜底跑，不等 10:00。新口径：
--
--   accepted_date  = T（成交净值日）
--   confirm_date   = T + confirm_delay 个交易日（普通 1、QDII 2），10:00 确认
--   settle_date    = 实际确认日 + 1 个交易日，10:00 入现金
--
-- 本迁移只做三件事：
--   1. confirm_runs 增加 skipped_time（因「未到 10:00」跳过的计数）
--   2. place_redeem_order 放宽日期校验：卖单允许 confirm_date > accepted_date
--   3. confirm_sell_order 接收实际到账日，确认时覆盖下单时的预估值
--   4. 回填存量 pending 卖单的 confirm_date / settle_date
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. 批次审计：skipped_time
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."confirm_runs"
  ADD COLUMN IF NOT EXISTS "skipped_time" integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN "public"."confirm_runs"."skipped_time" IS
  '因确认日当天尚未到 10:00 而跳过的订单数';

CREATE OR REPLACE FUNCTION "public"."finish_confirm_run"(
  p_run_id uuid,
  p_status "text",
  p_counts jsonb,
  p_error "text" DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF p_status NOT IN ('succeeded','failed','skipped') THEN
    RAISE EXCEPTION 'invalid finish status: %', p_status USING ERRCODE = '22023';
  END IF;

  UPDATE "public"."confirm_runs" r
     SET "status"      = p_status,
         "finished_at" = now(),
         "duration_ms" = GREATEST(0, (EXTRACT(EPOCH FROM (now() - r."started_at")) * 1000)::integer),
         "error"       = p_error,
         "scanned"       = COALESCE((p_counts->>'scanned')::integer, r."scanned"),
         "confirmed"     = COALESCE((p_counts->>'confirmed')::integer, r."confirmed"),
         "rejected"      = COALESCE((p_counts->>'rejected')::integer, r."rejected"),
         "skipped_nav"   = COALESCE((p_counts->>'skipped_nav')::integer, r."skipped_nav"),
         "skipped_time"  = COALESCE((p_counts->>'skipped_time')::integer, r."skipped_time"),
         "retryable"     = COALESCE((p_counts->>'retryable')::integer, r."retryable"),
         "manual_review" = COALESCE((p_counts->>'manual_review')::integer, r."manual_review"),
         "settled"       = COALESCE((p_counts->>'settled')::integer, r."settled")
   WHERE r."run_id" = p_run_id AND r."status" = 'running';
END $$;

-- ----------------------------------------------------------------------------
-- 2. place_redeem_order：卖单确认日不再等于受理日
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
  --    confirm_date = 受理日 + confirm_delay 个交易日，可以晚于 accept_date；
  --    settle_date 是下单时的预估值（确认日 + 1 交易日），确认时会被实际值覆盖。
  IF p_quantity IS NULL OR p_quantity <= 0 THEN
    RETURN jsonb_build_object('result','invalid_amount');
  END IF;
  IF p_accepted_date IS NULL OR p_confirm_date IS NULL OR p_settle_date IS NULL
     OR p_confirm_date < p_accepted_date
     OR p_settle_date < p_confirm_date THEN
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
-- 3. confirm_sell_order：实际到账日由确认方传入
--
-- 旧签名没有 p_settle_date，调用方只能沿用下单时的预估到账日（境内 3 天 /
-- QDII 7 天）。新口径要求「实际确认日 + 1 个交易日」，确认发生顺延时到账日
-- 必须跟着顺延，因此改为确认时覆盖。签名变化必须 DROP 后重建。
-- ----------------------------------------------------------------------------
DROP FUNCTION IF EXISTS "public"."confirm_sell_order"(uuid, "text", numeric, jsonb, integer);

CREATE OR REPLACE FUNCTION "public"."confirm_sell_order"(
  p_order_id uuid,
  p_worker "text",
  p_nav numeric,
  p_plan jsonb,
  p_settle_date date,
  p_lease_seconds integer DEFAULT 300
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order      "public"."trade_orders"%ROWTYPE;
  v_db_nav     numeric(18,6);
  v_n          integer;
  v_distinct   integer;
  v_sum_qty    numeric;
  v_total_fee  numeric;
  v_bad        integer;
  v_gross      numeric;
  v_net        numeric;
  v_total_cost numeric;
  v_claimed    integer;
BEGIN
  SELECT * INTO v_order FROM "public"."trade_orders" WHERE "id" = p_order_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('result','not_found');
  END IF;

  IF v_order."status" IN ('completed','rejected','cancelled','settled') THEN
    RETURN jsonb_build_object('result','already_terminal','status',v_order."status");
  END IF;

  IF v_order."status" = 'processing'
     AND COALESCE(v_order."processing_by", '') <> COALESCE(p_worker, '')
     AND v_order."processing_at" > now() - make_interval(secs => p_lease_seconds) THEN
    RETURN jsonb_build_object('result','not_claimed','status',v_order."status");
  END IF;

  IF v_order."status" NOT IN ('pending','processing') THEN
    RETURN jsonb_build_object('result','not_claimed','status',v_order."status");
  END IF;

  IF v_order."direction" <> 'sell' THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'WRONG_DIRECTION',
             'confirm_sell_order 收到的订单方向不是 sell');
  END IF;

  IF v_order."accepted_date" IS NULL THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'ACCEPTED_DATE_MISSING',
             '订单缺少 accepted_date，无法确定成交净值日');
  END IF;
  IF v_order."confirm_date" IS NULL THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'CONFIRM_DATE_MISSING',
             '订单缺少 confirm_date');
  END IF;

  -- 净值校验：卖单成交净值日固定为 accepted_date，与确认日无关
  IF v_order."fund_code" = '000198' THEN
    IF ABS(p_nav - 1.0000) > 0.0001 THEN
      RETURN jsonb_build_object('result','retryable','code','NAV_MISMATCH');
    END IF;
  ELSE
    SELECT "unit_nav" INTO v_db_nav
    FROM "public"."fund_nav"
    WHERE "fund_code" = v_order."fund_code" AND "nav_date" = v_order."accepted_date";

    IF v_db_nav IS NULL THEN
      RETURN jsonb_build_object('result','nav_unavailable','nav_date',v_order."accepted_date");
    END IF;
    IF ABS(v_db_nav - p_nav) > 0.0001 THEN
      RETURN jsonb_build_object('result','retryable','code','NAV_MISMATCH');
    END IF;
  END IF;

  -- 实际到账日必须晚于成交净值日；确认方按「实际确认日 + 1 交易日」计算
  IF p_settle_date IS NULL THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'SETTLE_DATE_MISSING',
             '确认卖单必须提供实际到账日');
  END IF;
  IF p_settle_date <= v_order."accepted_date" THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'SETTLE_DATE_INVALID',
             '到账日必须晚于成交净值日');
  END IF;

  -- 计划结构校验
  IF p_plan IS NULL OR jsonb_typeof(p_plan) <> 'array' OR jsonb_array_length(p_plan) = 0 THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'INVALID_PLAN',
             'FIFO 计划为空或不是数组');
  END IF;

  SELECT COUNT(*),
         COUNT(DISTINCT (e->>'lot_id')),
         COALESCE(SUM((e->>'quantity')::numeric), 0),
         COALESCE(SUM(COALESCE((e->>'fee')::numeric, 0)), 0)
    INTO v_n, v_distinct, v_sum_qty, v_total_fee
  FROM jsonb_array_elements(p_plan) e;

  IF v_n <> v_distinct THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'INVALID_PLAN',
             'FIFO 计划里同一 lot 出现多次');
  END IF;

  IF v_sum_qty <> v_order."quantity" THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'INVALID_PLAN',
             'FIFO 计划份额之和与订单份额不一致');
  END IF;

  SELECT COUNT(*) INTO v_bad
  FROM jsonb_array_elements(p_plan) e
  WHERE (e->>'quantity')::numeric <= 0 OR COALESCE((e->>'fee')::numeric, 0) < 0;
  IF v_bad > 0 THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'INVALID_PLAN',
             'FIFO 计划存在非正份额或负费用');
  END IF;

  -- 按 FIFO 顺序加锁，避免两个卖单交叉加锁死锁
  PERFORM 1 FROM "public"."position_lots"
   WHERE "id" IN (SELECT (e->>'lot_id')::uuid FROM jsonb_array_elements(p_plan) e)
   ORDER BY "nav_date", "created_at", "id"
   FOR UPDATE;

  -- lot 存在且归属正确
  SELECT COUNT(*) INTO v_bad
  FROM jsonb_array_elements(p_plan) e
  LEFT JOIN "public"."position_lots" l ON l."id" = (e->>'lot_id')::uuid
  WHERE l."id" IS NULL
     OR l."user_id" <> v_order."user_id"
     OR l."fund_code" <> v_order."fund_code";
  IF v_bad > 0 THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'LOT_INCONSISTENT',
             'FIFO 计划引用了不存在或不属于该用户/基金的 lot');
  END IF;

  -- 剩余量与可赎回日
  SELECT COUNT(*) INTO v_bad
  FROM jsonb_array_elements(p_plan) e
  JOIN "public"."position_lots" l ON l."id" = (e->>'lot_id')::uuid
  WHERE l."remaining_qty" < (e->>'quantity')::numeric
     OR COALESCE(l."available_date", l."nav_date") > v_order."accepted_date";
  IF v_bad > 0 THEN
    RETURN jsonb_build_object('result','retryable','code','LOT_PLAN_STALE');
  END IF;

  -- 认领（放在所有业务校验之后）
  UPDATE "public"."trade_orders" SET
    "status"          = 'processing',
    "processing_at"   = now(),
    "processing_by"   = p_worker,
    "attempt_count"   = v_order."attempt_count" + 1,
    "last_attempt_at" = now(),
    "updated_at"      = now()
  WHERE "id" = p_order_id;

  -- 锁内重算成本并扣减 lot
  WITH plan AS (
    SELECT (e->>'lot_id')::uuid AS lot_id,
           (e->>'quantity')::numeric AS qty
    FROM jsonb_array_elements(p_plan) e
  ), costs AS (
    SELECT p."lot_id", p."qty",
           CASE WHEN l."remaining_qty" = p."qty" THEN l."remaining_cost"
                ELSE ROUND(l."remaining_cost" * p."qty" / l."remaining_qty", 2) END AS cost_i
    FROM plan p
    JOIN "public"."position_lots" l ON l."id" = p."lot_id"
  ), upd AS (
    UPDATE "public"."position_lots" l SET
      "remaining_qty"  = l."remaining_qty" - c."qty",
      "remaining_cost" = CASE WHEN l."remaining_qty" - c."qty" = 0 THEN 0
                              ELSE l."remaining_cost" - c."cost_i" END,
      "updated_at"     = now()
    FROM costs c
    WHERE l."id" = c."lot_id"
    RETURNING l."id"
  )
  SELECT COALESCE(SUM(c."cost_i"), 0) INTO v_total_cost
  FROM costs c;

  PERFORM 1 FROM "public"."positions"
   WHERE "user_id" = v_order."user_id" AND "fund_code" = v_order."fund_code"
   FOR UPDATE;

  PERFORM "public"."recalc_position_from_lots"(v_order."user_id", v_order."fund_code");

  v_gross := ROUND(v_order."quantity" * p_nav, 2);
  v_net   := v_gross - v_total_fee;

  INSERT INTO "public"."trade_flow"(
    "order_id","user_id","fund_code","fund_name","direction",
    "price","quantity","amount","fee","trade_pnl","trade_time")
  VALUES (
    v_order."id", v_order."user_id", v_order."fund_code", COALESCE(v_order."fund_name",''), 'sell',
    p_nav, v_order."quantity", v_gross, v_total_fee, v_gross - v_total_fee - v_total_cost, now());

  UPDATE "public"."trade_orders" SET
    "status"          = 'settling',
    "amount"          = v_gross,
    "fee"             = v_total_fee,
    "net_amount"      = v_net,
    "price"           = p_nav,
    "settle_date"     = p_settle_date,
    "processed_at"    = now(),
    "last_error_code" = NULL,
    "last_error_message" = NULL,
    "processing_at"   = NULL,
    "processing_by"   = NULL,
    "updated_at"      = now()
  WHERE "id" = p_order_id;

  RETURN jsonb_build_object(
    'result','settling','order_id',p_order_id,
    'amount',v_gross,'fee',v_total_fee,'net_amount',v_net,
    'settle_date',p_settle_date);
END $$;

-- ----------------------------------------------------------------------------
-- 4. 回填存量 pending 卖单
--
-- 旧卖单的 confirm_date = accepted_date，且到账日按 3/7 个交易日算定。
-- 新代码在确认时按「实际确认日 + 1 交易日」覆盖 settle_date，所以这里只
-- 需要把确认日改对，避免它们在 T 日就被扫到并确认。
-- 交易日历缺失/越界时回填不到，订单会保持原值；上线前需确认日历已加载。
-- ----------------------------------------------------------------------------
WITH pending_sell AS (
  SELECT o."id",
         o."accepted_date",
         COALESCE(
           NULLIF(o."fee_rule_snapshot"->>'confirm_delay', '')::integer,
           r."confirm_delay"
         ) AS delay
    FROM "public"."trade_orders" o
    LEFT JOIN "public"."fund_trade_rule" r ON r."fund_code" = o."fund_code"
   WHERE o."direction" = 'sell'
     AND o."status" = 'pending'
     AND o."accepted_date" IS NOT NULL
     AND o."confirm_date" = o."accepted_date"
), calc AS (
  SELECT p."id",
         p."accepted_date",
         (SELECT c."trade_date"
            FROM "public"."trading_calendar" c
           WHERE c."is_trading_day"
             AND c."trade_date" > p."accepted_date"
           ORDER BY c."trade_date"
           OFFSET (p.delay - 1) LIMIT 1) AS new_confirm_date
    FROM pending_sell p
   WHERE p.delay >= 1
), calc2 AS (
  SELECT c."id",
         c."new_confirm_date",
         (SELECT t."trade_date"
            FROM "public"."trading_calendar" t
           WHERE t."is_trading_day"
             AND t."trade_date" > c."new_confirm_date"
           ORDER BY t."trade_date"
           LIMIT 1) AS new_settle_date
    FROM calc c
   WHERE c."new_confirm_date" IS NOT NULL
)
UPDATE "public"."trade_orders" o
   SET "confirm_date" = c2."new_confirm_date",
       "settle_date"  = c2."new_settle_date",
       "updated_at"   = now()
  FROM calc2 c2
 WHERE o."id" = c2."id"
   AND c2."new_settle_date" IS NOT NULL
   AND (o."confirm_date" IS DISTINCT FROM c2."new_confirm_date"
        OR o."settle_date" IS DISTINCT FROM c2."new_settle_date");

-- 回填不完整的存量卖单：上限 14 天内仍会被 Runner 扫到并确认，但时间口径是旧的。
-- 这里只告警，不阻断迁移；上线前应确认 trading_calendar 已加载。
DO $$
DECLARE
  v_left integer;
BEGIN
  SELECT count(*) INTO v_left
    FROM "public"."trade_orders"
   WHERE "direction" = 'sell'
     AND "status" = 'pending'
     AND "accepted_date" IS NOT NULL
     AND "confirm_date" = "accepted_date";
  IF v_left > 0 THEN
    RAISE WARNING '仍有 % 笔 pending 卖单未回填 confirm_date（交易日历可能未加载）', v_left;
  END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 5. 列注释对齐新口径（旧注释仍写着 confirm_date = T、settle_date = T+3/7）
-- ----------------------------------------------------------------------------
COMMENT ON COLUMN "public"."trade_orders"."accepted_date"
  IS '受理日 T：成交净值日。交易日 15:00 前为当日，15:00 后/非交易日为下一个交易日';
COMMENT ON COLUMN "public"."trade_orders"."confirm_date"
  IS '确认日 = T + confirm_delay 个交易日（普通 1、QDII 2），当日 10:00 执行确认';
COMMENT ON COLUMN "public"."trade_orders"."settle_date"
  IS '赎回到账日 = 实际确认日 + 1 个交易日，当日 10:00 入现金；确认顺延时随之覆盖';

-- ----------------------------------------------------------------------------
-- 权限：只给 service_role
-- ----------------------------------------------------------------------------
REVOKE ALL ON FUNCTION "public"."place_redeem_order"(
  uuid,character varying,character varying,numeric,
  date,date,date,jsonb,"text") FROM PUBLIC, "anon", "authenticated";

GRANT EXECUTE ON FUNCTION "public"."place_redeem_order"(
  uuid,character varying,character varying,numeric,
  date,date,date,jsonb,"text") TO "service_role";

REVOKE ALL ON FUNCTION "public"."confirm_sell_order"(
  uuid,"text",numeric,jsonb,date,integer) FROM PUBLIC, "anon", "authenticated";

GRANT EXECUTE ON FUNCTION "public"."confirm_sell_order"(
  uuid,"text",numeric,jsonb,date,integer) TO "service_role";

-- PostgREST 缓存重载（新增/删除函数后需要）
NOTIFY pgrst, 'reload schema';
