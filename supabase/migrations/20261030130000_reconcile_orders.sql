-- ============================================================================
-- 订单确认重写 · P4：只读对账 RPC
--
-- 设计来源：docs/20-设计/基金与交易/订单确认-执行机制.md §9.3（期望 0 行）
-- 用途：`server/scripts/order_ops.py reconcile` 经 PostgREST 调用，
--       不写任何业务数据；脚本按 total 决定退出码。
-- 为什么放在 RPC 而不是脚本里拼 SQL：脚本只有 PostgREST 通道，没有 psql 能力；
--       且对账口径必须与服务端 schema 同源，避免脚本里硬编码表结构。
-- ============================================================================

CREATE OR REPLACE FUNCTION "public"."reconcile_orders"()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_limit   constant integer := 201;  -- 多取 1 行用于判断「是否还有更多」
  v_shown   constant integer := 200;
  v_checks  jsonb := '[]'::jsonb;
  v_item    jsonb;
  v_rows    jsonb;
  v_count   bigint;
BEGIN
  -- 1. 负余额
  WITH x AS (
    SELECT "user_id", "cash", "frozen_cash" FROM "public"."accounts"
     WHERE "cash" < 0 OR "frozen_cash" < 0
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'negative_balance', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 2. 冻结资金 != 未完成买单金额合计
  WITH x AS (
    SELECT a."user_id", a."frozen_cash",
           COALESCE(SUM(o."amount") FILTER (
             WHERE o."direction" = 'buy'
               AND o."status" IN ('pending','processing','manual_review')), 0) AS expected
      FROM "public"."accounts" a
      LEFT JOIN "public"."trade_orders" o ON o."user_id" = a."user_id"
     GROUP BY a."user_id", a."frozen_cash"
    HAVING a."frozen_cash" <> COALESCE(SUM(o."amount") FILTER (
             WHERE o."direction" = 'buy'
               AND o."status" IN ('pending','processing','manual_review')), 0)
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'frozen_cash_mismatch', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 3. completed 买单的流水条数 != 1
  WITH x AS (
    SELECT o."id", COUNT(f."id") AS flows
      FROM "public"."trade_orders" o
      LEFT JOIN "public"."trade_flow" f ON f."order_id" = o."id"
     WHERE o."direction" = 'buy' AND o."status" = 'completed'
     GROUP BY o."id"
    HAVING COUNT(f."id") <> 1
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'buy_flow_count', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 4. 持仓份额 != lot 剩余份额汇总（positions 是 lot 的读模型）
  WITH x AS (
    SELECT p."user_id", p."fund_code", p."quantity",
           COALESCE(SUM(l."remaining_qty"), 0) AS lot_qty
      FROM "public"."positions" p
      LEFT JOIN "public"."position_lots" l
        ON l."user_id" = p."user_id" AND l."fund_code" = p."fund_code"
     GROUP BY p."user_id", p."fund_code", p."quantity"
    HAVING ABS(p."quantity" - COALESCE(SUM(l."remaining_qty"), 0)) > 0.01
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'lot_quantity_mismatch', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 5a. 普通基金成本均价 != lot 剩余成本 / 剩余份额
  WITH x AS (
    SELECT p."user_id", p."fund_code", p."cost_price",
           ROUND(COALESCE(SUM(l."remaining_cost"), 0)
                 / NULLIF(COALESCE(SUM(l."remaining_qty"), 0), 0), 4) AS lot_cost_price
      FROM "public"."positions" p
      LEFT JOIN "public"."position_lots" l
        ON l."user_id" = p."user_id" AND l."fund_code" = p."fund_code"
     WHERE p."fund_code" <> '000198'
     GROUP BY p."user_id", p."fund_code", p."cost_price"
    HAVING ABS(p."cost_price" - ROUND(COALESCE(SUM(l."remaining_cost"), 0)
                 / NULLIF(COALESCE(SUM(l."remaining_qty"), 0), 0), 4)) > 0.0001
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'cost_price_mismatch', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 5b. 货基本金 != lot 剩余成本
  WITH x AS (
    SELECT p."user_id", p."fund_code", p."principal",
           COALESCE(SUM(l."remaining_cost"), 0) AS lot_cost
      FROM "public"."positions" p
      LEFT JOIN "public"."position_lots" l
        ON l."user_id" = p."user_id" AND l."fund_code" = p."fund_code"
     WHERE p."fund_code" = '000198'
     GROUP BY p."user_id", p."fund_code", p."principal"
    HAVING ABS(COALESCE(p."principal", 0) - COALESCE(SUM(l."remaining_cost"), 0)) > 0.01
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'money_fund_principal_mismatch', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 6. 负份额
  WITH x AS (
    SELECT "user_id", "fund_code", "quantity" FROM "public"."positions"
     WHERE "quantity" < 0
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'negative_quantity', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 7. 买入金额恒等式：amount = net_amount + fee
  WITH x AS (
    SELECT "id", "amount", "net_amount", "fee" FROM "public"."trade_orders"
     WHERE "direction" = 'buy' AND "status" IN ('completed','settling','settled')
       AND ABS("amount" - (COALESCE("net_amount", 0) + COALESCE("fee", 0))) > 0.01
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'buy_amount_identity', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 8. 卖出金额恒等式：amount = quantity × price，net_amount = amount - fee
  WITH x AS (
    SELECT "id", "amount", "net_amount", "fee", "quantity", "price" FROM "public"."trade_orders"
     WHERE "direction" = 'sell' AND "status" IN ('settling','settled')
       AND (ABS("amount" - "quantity" * "price") > 0.01
            OR ABS(COALESCE("net_amount", 0) - ("amount" - COALESCE("fee", 0))) > 0.01)
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'sell_amount_identity', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 9. 同一订单多条流水（唯一索引已阻止，巡检兜底）
  WITH x AS (
    SELECT "order_id", COUNT(*) AS flows FROM "public"."trade_flow"
     WHERE "order_id" IS NOT NULL
     GROUP BY "order_id" HAVING COUNT(*) > 1
     LIMIT v_limit
  ), y AS (SELECT * FROM x LIMIT v_shown)
  SELECT COALESCE(jsonb_agg(to_jsonb(y)), '[]'::jsonb), (SELECT count(*) FROM x) INTO v_rows, v_count FROM y;
  v_checks := v_checks || jsonb_build_object(
    'name', 'duplicate_flow_order', 'count', LEAST(v_count, v_shown), 'truncated', v_count > v_shown, 'rows', v_rows);

  -- 汇总：total = 有差异的检查项数，rows_total = 差异行数合计
  SELECT COALESCE(SUM((c ->> 'count')::bigint), 0) INTO v_count
    FROM jsonb_array_elements(v_checks) AS c;

  RETURN jsonb_build_object(
    'checked_at', now(),
    'checks', v_checks,
    'failed_checks', (SELECT count(*) FROM jsonb_array_elements(v_checks) AS c
                       WHERE (c ->> 'count')::bigint > 0),
    'rows_total', v_count
  );
END $$;

COMMENT ON FUNCTION "public"."reconcile_orders"() IS
  '只读对账（《执行机制》§9.3 十条不变量）；clean 数据集 failed_checks=0、rows_total=0';

REVOKE ALL ON FUNCTION "public"."reconcile_orders"() FROM PUBLIC, "anon", "authenticated";
GRANT EXECUTE ON FUNCTION "public"."reconcile_orders"() TO "service_role";
