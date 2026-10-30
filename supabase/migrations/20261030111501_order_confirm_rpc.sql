-- ============================================================================
-- 订单确认重写 · P1b：确认侧与下单侧 RPC
--
-- 设计来源：docs/20-设计/基金与交易/订单确认-实现方案.md §3.6
-- 约定：
--   1. 全部 plpgsql + SECURITY DEFINER + SET search_path = public, pg_temp
--   2. 预期内业务失败返回 jsonb {result:...}，不抛异常；约束冲突等非预期错误照常抛
--   3. 成交净值日 = trade_orders.accepted_date（方案 A，见需求文档 §7 D8）
--   4. 只授予 service_role，不扩大 anon/authenticated 的权限面
--   5. 状态迁移触发器（§3.3.7）不在本文件，等灰度后期单独上线
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 内部工具：按 lot 汇总 positions（§3.3.2）
-- 调用方必须先 `SELECT ... FOR UPDATE` 锁住 positions 行，再另起语句调用本函数。
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."recalc_position_from_lots"(
  p_user_id uuid,
  p_fund_code character varying
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  UPDATE "public"."positions" p SET
    "quantity"       = q.qty,
    "cost_price"     = CASE WHEN p."fund_code" = '000198' THEN 1.0000
                            WHEN q.qty > 0 THEN ROUND(q.cost / q.qty, 4)
                            ELSE 0 END,
    "principal"      = CASE WHEN p."fund_code" = '000198' THEN q.cost ELSE 0 END,
    "confirm_date"   = q.max_nav_date,
    "available_date" = q.max_available_date,
    "updated_at"     = now()
  FROM (
    SELECT COALESCE(SUM("remaining_qty"), 0)  AS qty,
           COALESCE(SUM("remaining_cost"), 0) AS cost,
           MAX("nav_date")                    AS max_nav_date,
           MAX("available_date")              AS max_available_date
    FROM "public"."position_lots"
    WHERE "user_id" = p_user_id AND "fund_code" = p_fund_code
  ) q
  WHERE p."user_id" = p_user_id AND p."fund_code" = p_fund_code;
END $$;

REVOKE ALL ON FUNCTION "public"."recalc_position_from_lots"(uuid, character varying)
  FROM PUBLIC, "anon", "authenticated";

-- ----------------------------------------------------------------------------
-- 3.6.1 acquire_confirm_run / heartbeat_confirm_run / finish_confirm_run
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."acquire_confirm_run"(
  p_trigger "text",
  p_worker "text",
  p_lease_seconds integer DEFAULT 1800
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_run_id uuid;
  v_busy   boolean := false;
BEGIN
  IF p_trigger NOT IN ('sync','fallback','startup','manual') THEN
    RAISE EXCEPTION 'invalid trigger_source: %', p_trigger
      USING ERRCODE = '22023';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtext('confirm_run_acquire'));

  SELECT r."run_id" INTO v_run_id
  FROM "public"."confirm_runs" r
  WHERE r."status" = 'running'
  FOR UPDATE;

  IF v_run_id IS NOT NULL THEN
    IF (SELECT "heartbeat_at" FROM "public"."confirm_runs" WHERE "run_id" = v_run_id)
         > now() - make_interval(secs => p_lease_seconds) THEN
      RETURN NULL;  -- busy：上一轮还活着
    END IF;

    -- 租约过期：把上一轮标记失败，再开新一轮
    UPDATE "public"."confirm_runs"
       SET "status" = 'failed',
           "error" = 'lease_expired',
           "finished_at" = now(),
           "duration_ms" = GREATEST(0, (EXTRACT(EPOCH FROM (now() - "started_at")) * 1000)::integer)
     WHERE "run_id" = v_run_id;
  END IF;

  INSERT INTO "public"."confirm_runs" ("trigger_source", "status", "worker")
  VALUES (p_trigger, 'running', p_worker)
  RETURNING "run_id" INTO v_run_id;

  RETURN v_run_id;
EXCEPTION
  WHEN unique_violation THEN
    -- uq_confirm_runs_running 兜底：并发下另一个 worker 抢先
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION "public"."heartbeat_confirm_run"(p_run_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  UPDATE "public"."confirm_runs"
     SET "heartbeat_at" = now()
   WHERE "run_id" = p_run_id AND "status" = 'running';
END $$;

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
         "retryable"     = COALESCE((p_counts->>'retryable')::integer, r."retryable"),
         "manual_review" = COALESCE((p_counts->>'manual_review')::integer, r."manual_review"),
         "settled"       = COALESCE((p_counts->>'settled')::integer, r."settled")
   WHERE r."run_id" = p_run_id AND r."status" = 'running';
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.2 reap_stale_processing
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."reap_stale_processing"(
  p_lease_seconds integer DEFAULT 300,
  p_max_attempts integer DEFAULT 5
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_result jsonb;
BEGIN
  WITH stale AS (
    SELECT o."id", o."attempt_count" + 1 AS next_attempt
    FROM "public"."trade_orders" o
    WHERE o."status" = 'processing'
      AND o."processing_at" < now() - make_interval(secs => p_lease_seconds)
    FOR UPDATE SKIP LOCKED
  ), upd AS (
    UPDATE "public"."trade_orders" o SET
      "attempt_count"  = s.next_attempt,
      "status"         = CASE WHEN s.next_attempt >= p_max_attempts THEN 'manual_review' ELSE 'pending' END,
      "last_error_code" = CASE WHEN s.next_attempt >= p_max_attempts THEN 'LEASE_EXPIRED_MAX_ATTEMPTS' ELSE 'LEASE_EXPIRED' END,
      "last_attempt_at" = now(),
      "processing_at"   = NULL,
      "processing_by"   = NULL,
      "updated_at"      = now()
    FROM stale s
    WHERE o."id" = s."id"
    RETURNING o."status"
  )
  SELECT jsonb_build_object(
           'released', COUNT(*) FILTER (WHERE "status" = 'pending'),
           'manual',   COUNT(*) FILTER (WHERE "status" = 'manual_review')
         )
    INTO v_result
  FROM upd;

  RETURN v_result;
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.6 mark_order_manual_review
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."mark_order_manual_review"(
  p_order_id uuid,
  p_worker "text",
  p_code "text",
  p_message "text"
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order "public"."trade_orders"%ROWTYPE;
BEGIN
  SELECT * INTO v_order FROM "public"."trade_orders" WHERE "id" = p_order_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('result','not_found');
  END IF;

  IF v_order."status" IN ('completed','rejected','cancelled','settled') THEN
    RETURN jsonb_build_object('result','already_terminal','status',v_order."status");
  END IF;

  -- settling 不能转人工：份额已扣、应收已生成，重排会重复扣份额
  IF v_order."status" = 'settling' THEN
    RETURN jsonb_build_object('result','not_claimed','status',v_order."status");
  END IF;

  UPDATE "public"."trade_orders" SET
    "status"            = 'manual_review',
    "last_error_code"   = p_code,
    "last_error_message" = p_message,
    "processing_at"     = NULL,
    "processing_by"     = NULL,
    "updated_at"        = now()
  WHERE "id" = p_order_id;

  RETURN jsonb_build_object('result','manual_review','order_id',p_order_id,'code',p_code);
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.5 reject_trade_order
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."reject_trade_order"(
  p_order_id uuid,
  p_worker "text",
  p_code "text",
  p_message "text",
  p_lease_seconds integer DEFAULT 300
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order "public"."trade_orders"%ROWTYPE;
  v_unfrozen integer;
BEGIN
  SELECT * INTO v_order FROM "public"."trade_orders" WHERE "id" = p_order_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('result','not_found');
  END IF;

  IF v_order."status" IN ('completed','rejected','cancelled','settled') THEN
    RETURN jsonb_build_object('result','already_terminal','status',v_order."status");
  END IF;

  -- settling 已扣份额、已生成应收，撤销必须走反向冲正（本期不做）
  IF v_order."status" NOT IN ('pending','processing','manual_review') THEN
    RETURN jsonb_build_object('result','not_claimed','status',v_order."status");
  END IF;

  IF v_order."status" = 'processing'
     AND COALESCE(v_order."processing_by", '') <> COALESCE(p_worker, '')
     AND v_order."processing_at" > now() - make_interval(secs => p_lease_seconds) THEN
    RETURN jsonb_build_object('result','not_claimed','status',v_order."status");
  END IF;

  IF v_order."direction" = 'buy' THEN
    UPDATE "public"."accounts"
       SET "frozen_cash" = "frozen_cash" - v_order."amount",
           "cash"        = "cash" + v_order."amount",
           "updated_at"  = now()
     WHERE "user_id" = v_order."user_id"
       AND "frozen_cash" >= v_order."amount";
    GET DIAGNOSTICS v_unfrozen = ROW_COUNT;

    IF v_unfrozen = 0 THEN
      -- 冻结资金不足以退款：转人工，不退款
      RETURN "public"."mark_order_manual_review"(
               p_order_id, p_worker, 'FROZEN_CASH_INSUFFICIENT',
               '冻结资金小于订单金额，拒绝退款，转人工核对');
    END IF;
  END IF;

  UPDATE "public"."trade_orders" SET
    "status"             = 'rejected',
    "reject_reason"      = COALESCE(p_message, p_code),
    "last_error_code"    = p_code,
    "last_error_message" = p_message,
    "processed_at"       = now(),
    "processing_at"      = NULL,
    "processing_by"      = NULL,
    "updated_at"         = now()
  WHERE "id" = p_order_id;

  RETURN jsonb_build_object('result','rejected','order_id',p_order_id,'code',p_code);
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.3 confirm_buy_order
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."confirm_buy_order"(
  p_order_id uuid,
  p_worker "text",
  p_nav numeric,
  p_fee numeric,
  p_net_amount numeric,
  p_quantity numeric,
  p_residual numeric,
  p_lease_seconds integer DEFAULT 300
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order    "public"."trade_orders"%ROWTYPE;
  v_db_nav   numeric(18,6);
  v_claimed  integer;
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

  IF v_order."direction" <> 'buy' THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'WRONG_DIRECTION',
             'confirm_buy_order 收到的订单方向不是 buy');
  END IF;

  -- 成交净值日 = 受理日 T（方案 A）；缺失不能用 confirm_date 顶替
  IF v_order."accepted_date" IS NULL THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'ACCEPTED_DATE_MISSING',
             '订单缺少 accepted_date，无法确定成交净值日');
  END IF;
  IF v_order."confirm_date" IS NULL THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'CONFIRM_DATE_MISSING',
             '订单缺少 confirm_date');
  END IF;
  IF v_order."available_date" IS NULL THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'AVAILABLE_DATE_MISSING',
             '订单缺少 available_date，存量由回填脚本补齐，不猜测');
  END IF;

  -- 净值校验：货基恒 1.0000；其余读 accepted_date 当日
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

  -- 金额校验
  IF p_fee < 0 OR p_net_amount <= 0 OR p_quantity <= 0 OR p_residual < 0
     OR ABS(p_net_amount - (p_quantity * p_nav + p_residual)) > 0.01
     OR ABS(v_order."amount" - (p_net_amount + p_fee)) > 0.01 THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'INVALID_AMOUNTS',
             '费用/净额/份额/尾差之间的恒等式不成立');
  END IF;

  -- 认领
  UPDATE "public"."trade_orders" SET
    "status"          = 'processing',
    "processing_at"   = now(),
    "processing_by"   = p_worker,
    "attempt_count"   = v_order."attempt_count" + 1,
    "last_attempt_at" = now(),
    "updated_at"      = now()
  WHERE "id" = p_order_id;

  -- 解冻
  UPDATE "public"."accounts"
     SET "frozen_cash" = "frozen_cash" - v_order."amount",
         "updated_at"  = now()
   WHERE "user_id" = v_order."user_id"
     AND "frozen_cash" >= v_order."amount";
  GET DIAGNOSTICS v_claimed = ROW_COUNT;
  IF v_claimed = 0 THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'FROZEN_CASH_INSUFFICIENT',
             '冻结资金小于订单金额，不补偿，转人工');
  END IF;

  -- 锁 positions（不存在则建）
  INSERT INTO "public"."positions" ("user_id","fund_code","fund_name")
  VALUES (v_order."user_id", v_order."fund_code", COALESCE(v_order."fund_name",''))
  ON CONFLICT ("user_id","fund_code") DO NOTHING;

  PERFORM 1 FROM "public"."positions"
   WHERE "user_id" = v_order."user_id" AND "fund_code" = v_order."fund_code"
   FOR UPDATE;

  -- 插入 lot：日期取自订单已落库字段
  INSERT INTO "public"."position_lots"(
    "order_id","user_id","fund_code","fund_name","source","source_ref",
    "nav_date","available_date","quantity","remaining_qty","cost_price","remaining_cost")
  VALUES (
    v_order."id", v_order."user_id", v_order."fund_code", COALESCE(v_order."fund_name",''),
    'order', NULL,
    v_order."accepted_date", v_order."available_date",
    p_quantity, p_quantity, ROUND(p_net_amount / p_quantity, 4), p_net_amount);

  PERFORM "public"."recalc_position_from_lots"(v_order."user_id", v_order."fund_code");

  -- 尾差回现金
  UPDATE "public"."accounts"
     SET "cash" = "cash" + p_residual, "updated_at" = now()
   WHERE "user_id" = v_order."user_id";

  -- 流水
  INSERT INTO "public"."trade_flow"(
    "order_id","user_id","fund_code","fund_name","direction",
    "price","quantity","amount","fee","trade_time")
  VALUES (
    v_order."id", v_order."user_id", v_order."fund_code", COALESCE(v_order."fund_name",''), 'buy',
    p_nav, p_quantity, v_order."amount", p_fee, now());

  -- 订单终态
  UPDATE "public"."trade_orders" SET
    "status"          = 'completed',
    "price"           = p_nav,
    "fee"             = p_fee,
    "quantity"        = p_quantity,
    "net_amount"      = p_net_amount,
    "processed_at"    = now(),
    "last_error_code" = NULL,
    "last_error_message" = NULL,
    "processing_at"   = NULL,
    "processing_by"   = NULL,
    "updated_at"      = now()
  WHERE "id" = p_order_id;

  RETURN jsonb_build_object(
    'result','completed','order_id',p_order_id,
    'nav',p_nav,'fee',p_fee,'quantity',p_quantity,'residual',p_residual);
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.4 confirm_sell_order
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."confirm_sell_order"(
  p_order_id uuid,
  p_worker "text",
  p_nav numeric,
  p_plan jsonb,
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

  -- 净值校验：卖单 accepted_date 与 confirm_date 恒等
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

  IF v_order."settle_date" IS NULL THEN
    RETURN "public"."mark_order_manual_review"(p_order_id, p_worker, 'SETTLE_DATE_MISSING',
             '卖单缺少 settle_date，到账日以下单时落库的字段为准');
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
    "processed_at"    = now(),
    "last_error_code" = NULL,
    "last_error_message" = NULL,
    "processing_at"   = NULL,
    "processing_by"   = NULL,
    "updated_at"      = now()
  WHERE "id" = p_order_id;

  RETURN jsonb_build_object(
    'result','settling','order_id',p_order_id,
    'amount',v_gross,'fee',v_total_fee,'net_amount',v_net,'settle_date',v_order."settle_date");
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.7 settle_redeem_order
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."settle_redeem_order"(
  p_order_id uuid,
  p_worker "text",
  p_today date
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order "public"."trade_orders"%ROWTYPE;
BEGIN
  SELECT * INTO v_order FROM "public"."trade_orders" WHERE "id" = p_order_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('result','not_found');
  END IF;

  IF v_order."status" = 'settled' THEN
    RETURN jsonb_build_object('result','already_terminal','status',v_order."status");
  END IF;
  IF v_order."status" <> 'settling' THEN
    RETURN jsonb_build_object('result','not_claimed','status',v_order."status");
  END IF;

  IF v_order."settle_date" IS NULL OR v_order."settle_date" > p_today THEN
    RETURN jsonb_build_object('result','not_due','settle_date',v_order."settle_date");
  END IF;

  -- 应收缺失：保持 settling，补齐后重调；不能转 manual_review 再重排（会重复扣份额）
  IF v_order."net_amount" IS NULL THEN
    RETURN jsonb_build_object('result','manual_review','order_id',p_order_id,
                              'code','NET_AMOUNT_MISSING');
  END IF;

  UPDATE "public"."accounts"
     SET "cash" = "cash" + v_order."net_amount", "updated_at" = now()
   WHERE "user_id" = v_order."user_id";
  IF NOT FOUND THEN
    RAISE EXCEPTION 'account not found for user % when settling order %',
      v_order."user_id", p_order_id;
  END IF;

  UPDATE "public"."trade_orders" SET
    "status"       = 'settled',
    "settled_at"   = now(),
    "processed_at" = now(),
    "processing_at" = NULL,
    "processing_by" = NULL,
    "updated_at"   = now()
  WHERE "id" = p_order_id;

  RETURN jsonb_build_object('result','settled','order_id',p_order_id,'net_amount',v_order."net_amount");
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.8 credit_money_fund_income_atomic
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."credit_money_fund_income_atomic"(
  p_user_id uuid,
  p_fund_code character varying,
  p_income numeric,
  p_income_date date
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_inserted integer;
BEGIN
  IF p_income IS NULL OR p_income <= 0 THEN
    RETURN jsonb_build_object('result','no_income');
  END IF;

  PERFORM 1 FROM "public"."positions"
   WHERE "user_id" = p_user_id AND "fund_code" = p_fund_code
   FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('result','no_position');
  END IF;

  INSERT INTO "public"."position_lots"(
    "order_id","user_id","fund_code","fund_name","source","source_ref",
    "nav_date","available_date","quantity","remaining_qty","cost_price","remaining_cost")
  SELECT NULL, p_user_id, p_fund_code, p."fund_name", 'income', p_income_date::text,
         p_income_date, p_income_date, p_income, p_income, 0, 0
  FROM "public"."positions" p
  WHERE p."user_id" = p_user_id AND p."fund_code" = p_fund_code
  ON CONFLICT ("user_id","fund_code","source","source_ref") WHERE "source" <> 'order'
  DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;

  IF v_inserted = 0 THEN
    RETURN jsonb_build_object('result','already_credited');
  END IF;

  PERFORM "public"."recalc_position_from_lots"(p_user_id, p_fund_code);

  RETURN jsonb_build_object('result','credited','qty_added',p_income);
END $$;

-- ----------------------------------------------------------------------------
-- 3.6.9 requeue_manual_review_order（管理员）
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION "public"."requeue_manual_review_order"(
  p_order_id uuid,
  p_admin "text",
  p_reason "text"
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_order "public"."trade_orders"%ROWTYPE;
BEGIN
  SELECT * INTO v_order FROM "public"."trade_orders" WHERE "id" = p_order_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('result','not_found');
  END IF;

  IF v_order."status" <> 'manual_review' THEN
    RETURN jsonb_build_object('result','not_claimed','status',v_order."status");
  END IF;

  UPDATE "public"."trade_orders" SET
    "status"             = 'pending',
    "attempt_count"      = 0,
    "last_error_code"    = NULL,
    "last_error_message" = COALESCE('requeued by ' || COALESCE(p_admin,'?') || ': ' || COALESCE(p_reason,''), p_reason),
    "processing_at"      = NULL,
    "processing_by"      = NULL,
    "updated_at"         = now()
  WHERE "id" = p_order_id;

  RETURN jsonb_build_object('result','requeued','order_id',p_order_id);
END $$;

-- ----------------------------------------------------------------------------
-- 权限：只给 service_role
-- ----------------------------------------------------------------------------
REVOKE ALL ON FUNCTION "public"."acquire_confirm_run"("text","text",integer) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."heartbeat_confirm_run"(uuid) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."finish_confirm_run"(uuid,"text",jsonb,"text") FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."reap_stale_processing"(integer,integer) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."mark_order_manual_review"(uuid,"text","text","text") FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."reject_trade_order"(uuid,"text","text","text",integer) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."confirm_buy_order"(uuid,"text",numeric,numeric,numeric,numeric,numeric,integer) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."confirm_sell_order"(uuid,"text",numeric,jsonb,integer) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."settle_redeem_order"(uuid,"text",date) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."credit_money_fund_income_atomic"(uuid,character varying,numeric,date) FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."requeue_manual_review_order"(uuid,"text","text") FROM PUBLIC, "anon", "authenticated";

GRANT EXECUTE ON FUNCTION "public"."acquire_confirm_run"("text","text",integer) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."heartbeat_confirm_run"(uuid) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."finish_confirm_run"(uuid,"text",jsonb,"text") TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."reap_stale_processing"(integer,integer) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."mark_order_manual_review"(uuid,"text","text","text") TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."reject_trade_order"(uuid,"text","text","text",integer) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."confirm_buy_order"(uuid,"text",numeric,numeric,numeric,numeric,numeric,integer) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."confirm_sell_order"(uuid,"text",numeric,jsonb,integer) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."settle_redeem_order"(uuid,"text",date) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."credit_money_fund_income_atomic"(uuid,character varying,numeric,date) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."requeue_manual_review_order"(uuid,"text","text") TO "service_role";
