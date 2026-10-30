-- 行为用例：reconcile_orders()（《执行机制》§9.3 十条不变量）
-- 运行（本地 Supabase 栈，需已应用 supabase/migrations 最新迁移）：
--   docker exec -i supabase_db_ai-etf psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
--     < supabase/tests/reconcile_orders_test.sql
-- 全程一个事务 + ROLLBACK：先清空交易类表造「干净基线」，再逐项植入脏数据断言命中，
-- 不落任何数据、不改真实数据（DELETE/DDL 全在事务内）。
\set ON_ERROR_STOP on
BEGIN;

CREATE OR REPLACE FUNCTION pg_temp.assert_eq(p_actual text, p_expected text, p_msg text)
RETURNS void AS $$
BEGIN
  IF p_actual IS DISTINCT FROM p_expected THEN
    RAISE EXCEPTION 'FAIL %: expected [%], got [%]', p_msg, p_expected, p_actual;
  END IF;
  RAISE NOTICE 'ok   %', p_msg;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION pg_temp.rc(p_name text) RETURNS bigint AS $$
  SELECT COALESCE((c ->> 'count')::bigint, -1)
    FROM jsonb_array_elements(reconcile_orders() -> 'checks') c
   WHERE c ->> 'name' = p_name
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION pg_temp.rc_failed() RETURNS bigint AS $$
  SELECT (reconcile_orders() ->> 'failed_checks')::bigint
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION pg_temp.rc_rows() RETURNS bigint AS $$
  SELECT (reconcile_orders() ->> 'rows_total')::bigint
$$ LANGUAGE sql;

-- ---------------------------------------------------------------- 干净基线
DELETE FROM trade_flow;
DELETE FROM position_lots;
DELETE FROM positions;
DELETE FROM trade_orders;
DELETE FROM accounts;

SELECT pg_temp.assert_eq(pg_temp.rc_failed()::text, '0', '干净基线：failed_checks = 0');
SELECT pg_temp.assert_eq(pg_temp.rc_rows()::text,   '0', '干净基线：rows_total = 0');

-- ---------------------------------------------------------------- 植入脏数据
-- 非负约束与流水唯一索引挡住「坏数据」的构造，事务内临时摘掉（ROLLBACK 后恢复）
ALTER TABLE "public"."accounts" DROP CONSTRAINT "accounts_cash_nonnegative";
ALTER TABLE "public"."accounts" DROP CONSTRAINT "accounts_frozen_nonnegative";
DROP INDEX "public"."uq_trade_flow_order";

SELECT gen_random_uuid() AS u1, gen_random_uuid() AS u2, gen_random_uuid() AS u3,
       gen_random_uuid() AS u4, gen_random_uuid() AS u5, gen_random_uuid() AS u6 \gset

-- 1) 负余额
INSERT INTO accounts(user_id, cash, frozen_cash) VALUES (:'u1', -5, 0);

-- 2) 冻结资金 0，但有一笔 50 的 pending 买单
INSERT INTO accounts(user_id, cash, frozen_cash) VALUES (:'u2', 100, 0);
INSERT INTO trade_orders(user_id, fund_code, direction, price, quantity, amount, status)
VALUES (:'u2', '110020', 'buy', 0, 0, 50, 'pending');

-- 3 + 9) completed 买单两条流水（唯一索引已摘）
SELECT gen_random_uuid() AS o_dup \gset
INSERT INTO trade_orders(id, user_id, fund_code, direction, price, quantity, amount, net_amount, fee, status)
VALUES (:'o_dup', :'u3', '110020', 'buy', 1.5, 100, 100, 100, 0, 'completed');
INSERT INTO trade_flow(user_id, fund_code, direction, price, quantity, amount, fee, order_id)
VALUES (:'u3', '110020', 'buy', 1.5, 100, 100, 0, :'o_dup'),
       (:'u3', '110020', 'buy', 1.5, 100, 100, 0, :'o_dup');

-- 4) 持仓 100，lot 只剩 80（成本价仍对得上，只命中份额差异）
INSERT INTO positions(user_id, fund_code, quantity, cost_price) VALUES (:'u3', '110020', 100, 1.5);
INSERT INTO position_lots(user_id, fund_code, source, nav_date, quantity, remaining_qty, cost_price, remaining_cost)
VALUES (:'u3', '110020', 'initial', CURRENT_DATE, 100, 80, 1.5, 120);

-- 5a) 成本均价 2.0，lot 算出来 1.5
INSERT INTO positions(user_id, fund_code, quantity, cost_price) VALUES (:'u4', '161725', 10, 2.0);
INSERT INTO position_lots(user_id, fund_code, source, nav_date, quantity, remaining_qty, cost_price, remaining_cost)
VALUES (:'u4', '161725', 'initial', CURRENT_DATE, 10, 10, 1.5, 15);

-- 5b) 货基本金 100，lot 剩余成本 95
INSERT INTO positions(user_id, fund_code, quantity, cost_price, principal) VALUES (:'u5', '000198', 100, 1.0, 100);
INSERT INTO position_lots(user_id, fund_code, source, nav_date, quantity, remaining_qty, cost_price, remaining_cost)
VALUES (:'u5', '000198', 'initial', CURRENT_DATE, 100, 100, 1.0, 95);

-- 6) 负份额（同时会让 lot 汇总差异 +1，见下方断言）
INSERT INTO positions(user_id, fund_code, quantity, cost_price) VALUES (:'u6', '110020', -1, 0);

-- 7) 买入金额恒等式 100 <> 90 + 0（配一条流水，避免连坐 3）
SELECT gen_random_uuid() AS o_amt \gset
INSERT INTO trade_orders(id, user_id, fund_code, direction, price, quantity, amount, net_amount, fee, status)
VALUES (:'o_amt', :'u4', '161725', 'buy', 2.0, 5, 100, 90, 0, 'completed');
INSERT INTO trade_flow(user_id, fund_code, direction, price, quantity, amount, fee, order_id)
VALUES (:'u4', '161725', 'buy', 2.0, 5, 100, 0, :'o_amt');

-- 8) 卖出净额恒等式 10 - 0 <> 5
INSERT INTO trade_orders(user_id, fund_code, direction, price, quantity, amount, net_amount, fee, status)
VALUES (:'u5', '000198', 'sell', 1.0, 10, 10, 5, 0, 'settling');

-- ---------------------------------------------------------------- 断言
SELECT pg_temp.assert_eq(pg_temp.rc('negative_balance')::text,               '1', '命中：负余额');
SELECT pg_temp.assert_eq(pg_temp.rc('frozen_cash_mismatch')::text,           '1', '命中：冻结与未完成买单不符');
SELECT pg_temp.assert_eq(pg_temp.rc('buy_flow_count')::text,                 '1', '命中：completed 买单流水数 != 1');
SELECT pg_temp.assert_eq(pg_temp.rc('lot_quantity_mismatch')::text,          '2', '命中：lot 汇总 != 持仓（含负份额那行）');
SELECT pg_temp.assert_eq(pg_temp.rc('cost_price_mismatch')::text,            '1', '命中：成本均价 != lot 均价');
SELECT pg_temp.assert_eq(pg_temp.rc('money_fund_principal_mismatch')::text,  '1', '命中：货基本金 != lot 剩余成本');
SELECT pg_temp.assert_eq(pg_temp.rc('negative_quantity')::text,              '1', '命中：负份额');
SELECT pg_temp.assert_eq(pg_temp.rc('buy_amount_identity')::text,            '1', '命中：买入金额恒等式');
SELECT pg_temp.assert_eq(pg_temp.rc('sell_amount_identity')::text,           '1', '命中：卖出金额恒等式');
SELECT pg_temp.assert_eq(pg_temp.rc('duplicate_flow_order')::text,           '1', '命中：同单多流水');

SELECT pg_temp.assert_eq(pg_temp.rc_failed()::text, '10', '十条检查项全部命中');
SELECT pg_temp.assert_eq(pg_temp.rc_rows()::text,   '11', '差异行合计 11');

-- 单行明细可用性：命中项必须带 rows，且 rows 是数组
SELECT pg_temp.assert_eq(
  (SELECT jsonb_typeof(c -> 'rows')
     FROM jsonb_array_elements(reconcile_orders() -> 'checks') c
    WHERE c ->> 'name' = 'negative_balance'),
  'array', '命中项带 rows 数组');

ROLLBACK;
\echo '✅ reconcile_orders 行为用例全部通过（已 ROLLBACK）'
