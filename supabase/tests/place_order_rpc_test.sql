-- 行为用例：place_purchase_order / place_redeem_order（幂等、额度、可赎份额）
-- 运行（本地 Supabase 栈，需已应用 supabase/migrations 最新迁移）：
--   docker exec -i supabase_db_ai-etf psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
--     < supabase/tests/place_order_rpc_test.sql
-- 全程一个事务 + ROLLBACK：不落任何数据；断言失败时 RAISE EXCEPTION 直接中止。
-- 口径见 docs/20-设计/基金与交易/订单确认-实现方案.md §5.2。
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

SELECT gen_random_uuid() AS uid \gset
INSERT INTO accounts(user_id, cash, frozen_cash) VALUES (:'uid', 1000.00, 0);

-- 1. 正常申购
SELECT place_purchase_order(
  :'uid','110020','测试基金',300.00,0.45,299.55,1.2345,
  '2026-10-30','2026-11-02','2026-11-04',
  '{"confirm_delay":1}'::jsonb, NULL, 'ck-1')->>'result' AS r1 \gset
SELECT pg_temp.assert_eq(:'r1','placed','首次申购 placed');
SELECT pg_temp.assert_eq((SELECT cash::text FROM accounts WHERE user_id=:'uid'),'700.00','现金扣减');
SELECT pg_temp.assert_eq((SELECT frozen_cash::text FROM accounts WHERE user_id=:'uid'),'300.00','冻结增加');
SELECT pg_temp.assert_eq((SELECT status||'/'||direction FROM trade_orders WHERE user_id=:'uid'),'pending/buy','订单 pending/buy');
SELECT pg_temp.assert_eq((SELECT net_amount::text FROM trade_orders WHERE user_id=:'uid'),'299.55','net_amount 落库');
SELECT pg_temp.assert_eq((SELECT client_order_id FROM trade_orders WHERE user_id=:'uid'),'ck-1','client_order_id 落库');

-- 2. 幂等：同键重复提交
SELECT place_purchase_order(
  :'uid','110020','测试基金',300.00,0.45,299.55,1.2345,
  '2026-10-30','2026-11-02','2026-11-04',
  '{"confirm_delay":1}'::jsonb, NULL, 'ck-1')->>'result' AS r2 \gset
SELECT pg_temp.assert_eq(:'r2','existing','同键重复申购返回 existing');
SELECT pg_temp.assert_eq((SELECT cash::text FROM accounts WHERE user_id=:'uid'),'700.00','幂等不重复扣款');
SELECT pg_temp.assert_eq((SELECT count(*)::text FROM trade_orders WHERE user_id=:'uid'),'1','只有一张订单');

-- 3. 幂等键冲突（同键不同基金）
SELECT place_purchase_order(
  :'uid','110021','另一只',100.00,0.15,99.85,1.0,
  '2026-10-30','2026-11-02','2026-11-04','{}'::jsonb, NULL, 'ck-1')->>'result' AS r3 \gset
SELECT pg_temp.assert_eq(:'r3','idempotency_conflict','同键不同基金 → 冲突');

-- 4. 日期守卫
SELECT place_purchase_order(
  :'uid','110020','测试基金',100.00,0.15,99.85,1.0,
  '2026-11-02','2026-10-30','2026-11-04','{}'::jsonb, NULL, NULL)->>'result' AS r4 \gset
SELECT pg_temp.assert_eq(:'r4','invalid_dates','确认日早于受理日 → invalid_dates');

-- 5. 金额恒等式
SELECT place_purchase_order(
  :'uid','110020','测试基金',100.00,0.15,50.00,1.0,
  '2026-10-30','2026-11-02','2026-11-04','{}'::jsonb, NULL, NULL)->>'result' AS r5 \gset
SELECT pg_temp.assert_eq(:'r5','invalid_amount','amount <> net + fee → invalid_amount');

-- 6. 余额不足
SELECT place_purchase_order(
  :'uid','110020','测试基金',800.00,1.20,798.80,1.0,
  '2026-10-30','2026-11-02','2026-11-04','{}'::jsonb, NULL, NULL)->>'result' AS r6 \gset
SELECT pg_temp.assert_eq(:'r6','insufficient_cash','余额不足 → insufficient_cash');
SELECT pg_temp.assert_eq((SELECT cash::text FROM accounts WHERE user_id=:'uid'),'700.00','拒单不动资金');

-- 7. 单日额度
SELECT place_purchase_order(
  :'uid','110021','另一只',500.00,0.00,500.00,1.0,
  '2026-10-30','2026-11-02','2026-11-04','{}'::jsonb, 400.00, NULL)->>'result' AS r7 \gset
SELECT pg_temp.assert_eq(:'r7','limit_exceeded','超过单日额度 → limit_exceeded');
-- 额度内可以再买
SELECT place_purchase_order(
  :'uid','110021','另一只',50.00,0.00,50.00,1.0,
  '2026-10-30','2026-11-02','2026-11-04','{}'::jsonb, 400.00, NULL)->>'result' AS r8 \gset
SELECT pg_temp.assert_eq(:'r8','placed','额度内可申购');

-- 8. 赎回：在途申购挡住
SELECT place_redeem_order(
  :'uid','110020','测试基金',10,'2026-10-30','2026-10-30','2026-11-04',
  '{}'::jsonb, NULL)->>'result' AS r9 \gset
SELECT pg_temp.assert_eq(:'r9','pending_purchase','有在途申购 → pending_purchase');

-- 清掉在途买单，造 lot
UPDATE trade_orders SET status='completed' WHERE user_id=:'uid';
INSERT INTO position_lots(user_id, fund_code, fund_name, source, source_ref, nav_date,
  available_date, quantity, remaining_qty, cost_price, remaining_cost)
VALUES (:'uid','110020','测试基金','initial','initial','2026-10-01','2026-10-10',
  100.00,100.00,1.0000,100.00);

-- 9. 可赎份额不足
SELECT place_redeem_order(
  :'uid','110020','测试基金',150,'2026-10-30','2026-10-30','2026-11-04',
  '{}'::jsonb, NULL)->>'result' AS r10 \gset
SELECT pg_temp.assert_eq(:'r10','insufficient_shares','超过可赎份额 → insufficient_shares');

-- 10. 正常赎回
SELECT place_redeem_order(
  :'uid','110020','测试基金',40,'2026-10-30','2026-10-30','2026-11-04',
  '{"redeem_settle_delay":2}'::jsonb, 'rk-1')->>'result' AS r11 \gset
SELECT pg_temp.assert_eq(:'r11','placed','赎回 placed');
SELECT pg_temp.assert_eq((SELECT status||'/'||quantity::text||'/'||amount::text||'/'||price::text
  FROM trade_orders WHERE client_order_id='rk-1'),'pending/40.00/0.00/0.0000','赎单金额净值为 0 待确认回填');
SELECT pg_temp.assert_eq((SELECT settle_date::text FROM trade_orders WHERE client_order_id='rk-1'),
  '2026-11-04','settle_date 落库');

-- 11. 在途卖单占用可赎份额
SELECT place_redeem_order(
  :'uid','110020','测试基金',80,'2026-10-30','2026-10-30','2026-11-04',
  '{}'::jsonb, NULL)->>'available' AS avail \gset
SELECT pg_temp.assert_eq(:'avail','60.00','在途卖单占用份额（100-40）');

-- 11b. 已确认（settling）的卖单不再重复占用份额（lot 已扣减）
UPDATE trade_orders SET status='settling' WHERE client_order_id='rk-1';
-- 模拟确认已扣减 lot（真实路径由 confirm_sell_order 完成）：100 -> 60
UPDATE position_lots SET remaining_qty=60, remaining_cost=60
 WHERE user_id=:'uid' AND fund_code='110020';
-- 用 61 > 60 触发 insufficient_shares，从而拿到 RPC 计算的可用额度
SELECT place_redeem_order(
  :'uid','110020','测试基金',61,'2026-10-30','2026-10-30','2026-11-04',
  '{}'::jsonb, NULL)->>'available' AS avail_s \gset
SELECT pg_temp.assert_eq(:'avail_s','60.00','settling 卖单不重复占用（lot 已扣至 60）');
UPDATE trade_orders SET status='pending' WHERE client_order_id='rk-1';

-- 12. 未到可赎回日的 lot 不计入
UPDATE position_lots SET available_date='2026-11-05' WHERE user_id=:'uid' AND fund_code='110020';
SELECT place_redeem_order(
  :'uid','110020','测试基金',10,'2026-10-30','2026-10-30','2026-11-04',
  '{}'::jsonb, NULL)->>'available' AS avail2 \gset
SELECT pg_temp.assert_eq(:'avail2','-40.00','未到可赎回日 → 可用额度为负，赎回被拒');

-- 13. 卖单幂等
SELECT place_redeem_order(
  :'uid','110020','测试基金',40,'2026-10-30','2026-10-30','2026-11-04',
  '{"redeem_settle_delay":2}'::jsonb, 'rk-1')->>'result' AS r13 \gset
SELECT pg_temp.assert_eq(:'r13','existing','卖单同键重复 → existing');

ROLLBACK;
