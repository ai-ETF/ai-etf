-- 行为用例：confirm_buy_order / confirm_sell_order / 到账 / 拒单 / 租约回收 / 重算
-- 运行（本地 Supabase 栈，需已应用 supabase/migrations 最新迁移）：
--   docker exec -i supabase_db_ai-etf psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
--     < supabase/tests/order_confirm_rpc_test.sql
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

-- ---------------------------------------------------------------- 准备数据
SELECT gen_random_uuid() AS uid \gset
INSERT INTO accounts(user_id, cash, frozen_cash) VALUES (:'uid', 100000.00, 0);
INSERT INTO fund_nav(fund_code, nav_date, unit_nav, source) VALUES
  ('110020', '2026-10-29', 1.234500, 'test'),
  ('110020', '2026-10-30', 1.500000, 'test');

-- 买单：amount 1000, fee 1.50, net 998.50, nav 1.2345 → qty 808.82, residual 0.01
INSERT INTO trade_orders(id, user_id, fund_code, fund_name, direction, price, quantity, amount,
                         fee, status, accepted_date, confirm_date, available_date, fund_type)
VALUES ('11111111-1111-1111-1111-111111111111', :'uid', '110020', '测试基金', 'buy',
        1.2345, 0, 1000.00, 0, 'pending', '2026-10-29', '2026-10-30', '2026-11-03', 'of');
UPDATE accounts SET cash = cash - 1000, frozen_cash = frozen_cash + 1000 WHERE user_id = :'uid';

-- ---------------------------------------------------------------- 1. 买单确认
SELECT pg_temp.assert_eq(
  confirm_buy_order('11111111-1111-1111-1111-111111111111','w1',1.2345,1.50,998.50,808.82,0.01)->>'result',
  'completed', '买单确认返回 completed');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id='11111111-1111-1111-1111-111111111111'),
  'completed', '订单状态 completed');
SELECT pg_temp.assert_eq((SELECT attempt_count::text FROM trade_orders WHERE id='11111111-1111-1111-1111-111111111111'),
  '1', 'attempt_count=1');
SELECT pg_temp.assert_eq((SELECT cash::text FROM accounts WHERE user_id=:'uid'), '99000.01', '尾差回现金');
SELECT pg_temp.assert_eq((SELECT frozen_cash::text FROM accounts WHERE user_id=:'uid'), '0.00', '冻结清零');
SELECT pg_temp.assert_eq((SELECT quantity::text FROM positions WHERE user_id=:'uid' AND fund_code='110020'),
  '808.82', 'positions.quantity');
SELECT pg_temp.assert_eq((SELECT cost_price::text FROM positions WHERE user_id=:'uid' AND fund_code='110020'),
  '1.2345', 'positions.cost_price');
SELECT pg_temp.assert_eq((SELECT confirm_date::text FROM positions WHERE user_id=:'uid' AND fund_code='110020'),
  '2026-10-29', 'positions.confirm_date = max(nav_date) = 受理日');
SELECT pg_temp.assert_eq((SELECT available_date::text FROM positions WHERE user_id=:'uid' AND fund_code='110020'),
  '2026-11-03', 'positions.available_date');
SELECT pg_temp.assert_eq((SELECT nav_date::text FROM position_lots WHERE order_id='11111111-1111-1111-1111-111111111111'),
  '2026-10-29', 'lot.nav_date = accepted_date（方案 A）');
SELECT pg_temp.assert_eq((SELECT remaining_cost::text FROM position_lots WHERE order_id='11111111-1111-1111-1111-111111111111'),
  '998.50', 'lot.remaining_cost = 净申购额');
SELECT pg_temp.assert_eq((SELECT amount::text FROM trade_flow WHERE order_id='11111111-1111-1111-1111-111111111111'),
  '1000.00', 'trade_flow.amount = 订单金额');
-- 100000 现金 - 买入费 1.50 + 尾差 0.01 = 现金 99000.01 + 成本 998.50
SELECT pg_temp.assert_eq(
  ((SELECT cash + frozen_cash FROM accounts WHERE user_id=:'uid')
   + (SELECT COALESCE(SUM(remaining_cost),0) FROM position_lots WHERE user_id=:'uid'))::text,
  '99998.51', '买单完成后 现金+冻结+成本 与费用/尾差对账');

-- 幂等：重复调用
SELECT pg_temp.assert_eq(
  confirm_buy_order('11111111-1111-1111-1111-111111111111','w1',1.2345,1.50,998.50,808.82,0.01)->>'result',
  'already_terminal', '重复确认返回 already_terminal');
SELECT pg_temp.assert_eq((SELECT count(*)::text FROM trade_flow WHERE order_id='11111111-1111-1111-1111-111111111111'),
  '1', '没有生成第二条流水');

-- ---------------------------------------------------------------- 2. 净值缺失 / 不符 / accepted_date 缺失
INSERT INTO trade_orders(user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, available_date, fund_type)
VALUES (:'uid','110020','测试基金','buy',1.2,0,100,0,'pending','2026-10-28','2026-10-30','2026-11-03','of')
RETURNING id AS oid2 \gset
SELECT pg_temp.assert_eq(
  confirm_buy_order(:'oid2','w1',1.2,0.00,100.00,83.33,0.00)->>'result',
  'nav_unavailable', 'T 日净值缺失 → nav_unavailable');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id=:'oid2'), 'pending', '净值缺失不改状态');

-- 造出 T 日净值后再验 NAV_MISMATCH
INSERT INTO fund_nav(fund_code, nav_date, unit_nav, source) VALUES ('110020','2026-10-28',1.200000,'test');
SELECT pg_temp.assert_eq(
  confirm_buy_order(:'oid2','w1',1.2500,0.00,100.00,80.00,0.00)->>'result',
  'retryable', '净值与库中不一致 → retryable');
SELECT pg_temp.assert_eq(
  confirm_buy_order(:'oid2','w1',1.2500,0.00,100.00,80.00,0.00)->>'code',
  'NAV_MISMATCH', '错误码 NAV_MISMATCH');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id=:'oid2'), 'pending', 'NAV 不符订单仍 pending');
UPDATE accounts SET frozen_cash = frozen_cash + 100 WHERE user_id = :'uid';

INSERT INTO trade_orders(user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, available_date, fund_type)
VALUES (:'uid','110020','测试基金','buy',1.2,0,100,0,'pending',NULL,'2026-10-30','2026-11-03','of')
RETURNING id AS oid3 \gset
SELECT pg_temp.assert_eq(
  confirm_buy_order(:'oid3','w1',1.2,0.00,100.00,83.33,0.00)->>'result',
  'manual_review', 'accepted_date 缺失 → manual_review');
SELECT pg_temp.assert_eq((SELECT last_error_code FROM trade_orders WHERE id=:'oid3'),
  'ACCEPTED_DATE_MISSING', '错误码 ACCEPTED_DATE_MISSING');

-- ---------------------------------------------------------------- 3. 卖单
INSERT INTO trade_orders(id, user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, settle_date, fund_type)
VALUES ('22222222-2222-2222-2222-222222222222', :'uid','110020','测试基金','sell',
        1.5, 808.82, 0, 0, 'pending', '2026-10-30','2026-10-30','2026-11-04','of');
SELECT (SELECT id FROM position_lots WHERE order_id='11111111-1111-1111-1111-111111111111') AS lot1 \gset

-- 3.1 可赎回日未到 → retryable LOT_PLAN_STALE
SELECT pg_temp.assert_eq(
  confirm_sell_order('22222222-2222-2222-2222-222222222222','w1',1.5000,
    jsonb_build_array(jsonb_build_object('lot_id', :'lot1', 'quantity', 808.82, 'fee', 2.00)))->>'result',
  'retryable', 'lot 未到可赎回日 → retryable');
SELECT pg_temp.assert_eq(
  confirm_sell_order('22222222-2222-2222-2222-222222222222','w1',1.5000,
    jsonb_build_array(jsonb_build_object('lot_id', :'lot1', 'quantity', 808.82, 'fee', 2.00)))->>'code',
  'LOT_PLAN_STALE', '错误码 LOT_PLAN_STALE');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id='22222222-2222-2222-2222-222222222222'),
  'pending', '可赎回日未到不改状态');

-- 3.2 计划份额与订单不符
UPDATE position_lots SET available_date = '2026-10-30' WHERE id = :'lot1';
SELECT pg_temp.assert_eq(
  confirm_sell_order('22222222-2222-2222-2222-222222222222','w1',1.5000,
    jsonb_build_array(jsonb_build_object('lot_id', :'lot1', 'quantity', 100, 'fee', 2.00)))->>'code',
  'INVALID_PLAN', '计划份额不符 → INVALID_PLAN');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id='22222222-2222-2222-2222-222222222222'),
  'manual_review', 'INVALID_PLAN 转人工');
-- 人工核对后重排，继续走正常路径
SELECT requeue_manual_review_order('22222222-2222-2222-2222-222222222222','admin','测试重排');

-- 3.3 正常卖出 → settling
SELECT pg_temp.assert_eq(
  confirm_sell_order('22222222-2222-2222-2222-222222222222','w1',1.5000,
    jsonb_build_array(jsonb_build_object('lot_id', :'lot1', 'quantity', 808.82, 'fee', 2.00)))->>'result',
  'settling', '卖单确认 → settling');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id='22222222-2222-2222-2222-222222222222'),
  'settling', '订单状态 settling');
SELECT pg_temp.assert_eq((SELECT amount::text FROM trade_orders WHERE id='22222222-2222-2222-2222-222222222222'),
  '1213.23', '卖单 amount = 成交金额');
SELECT pg_temp.assert_eq((SELECT net_amount::text FROM trade_orders WHERE id='22222222-2222-2222-2222-222222222222'),
  '1211.23', '卖单 net_amount = 应收');
SELECT pg_temp.assert_eq((SELECT quantity::text FROM positions WHERE user_id=:'uid' AND fund_code='110020'),
  '0.00', '份额清零');
SELECT pg_temp.assert_eq((SELECT remaining_qty::text FROM position_lots WHERE id=:'lot1'), '0.00', 'lot 剩余份额 0');
SELECT pg_temp.assert_eq((SELECT remaining_cost::text FROM position_lots WHERE id=:'lot1'), '0.00', 'lot 剩余成本 0');
SELECT pg_temp.assert_eq((SELECT trade_pnl::text FROM trade_flow WHERE order_id='22222222-2222-2222-2222-222222222222'),
  '212.73', 'trade_pnl = 1213.23-2.00-998.50');
SELECT pg_temp.assert_eq((SELECT cash::text FROM accounts WHERE user_id=:'uid'), '99000.01', 'settling 阶段现金不变');

SELECT pg_temp.assert_eq(
  reject_trade_order('22222222-2222-2222-2222-222222222222','w1','X','settling 不能拒绝')->>'result',
  'not_claimed', 'settling 状态拒绝被挡住');

-- ---------------------------------------------------------------- 4. 到账
SELECT pg_temp.assert_eq(
  settle_redeem_order('22222222-2222-2222-2222-222222222222','w1','2026-11-03')->>'result',
  'not_due', '未到到账日 → not_due');
SELECT pg_temp.assert_eq(
  settle_redeem_order('22222222-2222-2222-2222-222222222222','w1','2026-11-04')->>'result',
  'settled', '到账日当天 → settled');
SELECT pg_temp.assert_eq((SELECT cash::text FROM accounts WHERE user_id=:'uid'), '100211.24', '现金 += 应收');
SELECT pg_temp.assert_eq(
  settle_redeem_order('22222222-2222-2222-2222-222222222222','w1','2026-11-05')->>'result',
  'already_terminal', '重复到账幂等');

-- ---------------------------------------------------------------- 5. 拒绝
INSERT INTO trade_orders(user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, available_date, fund_type)
VALUES (:'uid','110020','测试基金','buy',1.2,0,500,0,'pending','2026-10-30','2026-10-30','2026-11-03','of')
RETURNING id AS oid5 \gset
UPDATE accounts SET frozen_cash = frozen_cash + 500 WHERE user_id = :'uid';
SELECT pg_temp.assert_eq(
  reject_trade_order(:'oid5','w1','NAV_UNAVAILABLE','净值长期缺失')->>'result',
  'rejected', '拒绝成功');
-- 冻结里另有测试手工注入的 100（oid2），所以剩 100
SELECT pg_temp.assert_eq((SELECT frozen_cash::text FROM accounts WHERE user_id=:'uid'), '100.00', '拒绝退回冻结');
-- 拒绝把冻结的 500 退回现金
SELECT pg_temp.assert_eq((SELECT cash::text FROM accounts WHERE user_id=:'uid'), '100711.24', '拒绝后冻结退回现金');


-- ---------------------------------------------------------------- 6. 冻结不足 → 转人工
INSERT INTO trade_orders(user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, available_date, fund_type)
VALUES (:'uid','110020','测试基金','buy',1.2,0,300,0,'pending','2026-10-30','2026-10-30','2026-11-03','of')
RETURNING id AS oid6 \gset
SELECT pg_temp.assert_eq(
  reject_trade_order(:'oid6','w1','X','冻结不足')->>'result',
  'manual_review', '冻结不足 → manual_review');
SELECT pg_temp.assert_eq((SELECT last_error_code FROM trade_orders WHERE id=:'oid6'),
  'FROZEN_CASH_INSUFFICIENT', '错误码 FROZEN_CASH_INSUFFICIENT');

-- ---------------------------------------------------------------- 7. 人工重排
SELECT pg_temp.assert_eq(
  requeue_manual_review_order(:'oid6','admin','核对后重排')->>'result',
  'requeued', '人工重排成功');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id=:'oid6'), 'pending', '重排后 pending');
SELECT pg_temp.assert_eq((SELECT attempt_count::text FROM trade_orders WHERE id=:'oid6'), '0', '重排清零 attempt_count');
SELECT pg_temp.assert_eq(
  requeue_manual_review_order(:'oid6','admin','再排一次')->>'result',
  'not_claimed', '非 manual_review 不可重排');

-- ---------------------------------------------------------------- 8. 租约与并发
SELECT pg_temp.assert_eq(
  (SELECT count(*)::text FROM confirm_runs WHERE status='running'), '0', '初始无 running');
SELECT acquire_confirm_run('sync','w1') IS NOT NULL AS got \gset
SELECT pg_temp.assert_eq(:'got', 't', '第一轮拿到 run');
SELECT pg_temp.assert_eq(acquire_confirm_run('sync','w2') IS NULL::text, 'true', '第二轮被单飞挡住');
SELECT pg_temp.assert_eq((SELECT count(*)::text FROM confirm_runs WHERE status='running'), '1', '只有一条 running');
SELECT heartbeat_confirm_run((SELECT run_id FROM confirm_runs WHERE status='running'));
SELECT finish_confirm_run((SELECT run_id FROM confirm_runs WHERE status='running'), 'succeeded',
  jsonb_build_object('scanned',3,'confirmed',1));
SELECT pg_temp.assert_eq((SELECT status FROM confirm_runs ORDER BY started_at DESC LIMIT 1), 'succeeded', '批次状态 succeeded');
SELECT pg_temp.assert_eq((SELECT scanned::text FROM confirm_runs ORDER BY started_at DESC LIMIT 1), '3', '批次计数落库');
-- 已结束的批次不能被改回
SELECT finish_confirm_run((SELECT run_id FROM confirm_runs ORDER BY started_at DESC LIMIT 1), 'failed',
  '{}'::jsonb, 'late');
SELECT pg_temp.assert_eq((SELECT status FROM confirm_runs ORDER BY started_at DESC LIMIT 1), 'succeeded', '结束态不可覆盖');

-- 过期租约 → 回收
INSERT INTO trade_orders(user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, available_date, fund_type,
                         processing_at, processing_by, attempt_count)
VALUES (:'uid','110020','测试基金','buy',1.2,0,100,0,'processing','2026-10-30','2026-10-30','2026-11-03','of',
        now() - interval '10 minutes','dead-worker',1)
RETURNING id AS oid8 \gset
INSERT INTO trade_orders(user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, available_date, fund_type,
                         processing_at, processing_by, attempt_count)
VALUES (:'uid','110020','测试基金','buy',1.2,0,100,0,'processing','2026-10-30','2026-10-30','2026-11-03','of',
        now() - interval '10 minutes','dead-worker',4)
RETURNING id AS oid9 \gset
SELECT reap_stale_processing(300, 5)->>'released' AS r1 \gset
SELECT pg_temp.assert_eq(:'r1','1','回收 1 条回 pending');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id=:'oid8'),'pending','过期订单回 pending');
SELECT pg_temp.assert_eq((SELECT attempt_count::text FROM trade_orders WHERE id=:'oid8'),'2','attempt_count +1');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id=:'oid9'),'manual_review','达到上限转人工');
SELECT pg_temp.assert_eq((SELECT last_error_code FROM trade_orders WHERE id=:'oid9'),'LEASE_EXPIRED_MAX_ATTEMPTS','上限错误码');

-- 未过期的 processing 不能被回收
INSERT INTO trade_orders(user_id, fund_code, fund_name, direction, price, quantity, amount, fee,
                         status, accepted_date, confirm_date, available_date, fund_type,
                         processing_at, processing_by, attempt_count)
VALUES (:'uid','110020','测试基金','buy',1.2,0,100,0,'processing','2026-10-30','2026-10-30','2026-11-03','of',
        now(),'alive-worker',1)
RETURNING id AS oid10 \gset
SELECT pg_temp.assert_eq(reap_stale_processing(300,5)->>'released','0','活跃租约不被回收');
SELECT pg_temp.assert_eq((SELECT status FROM trade_orders WHERE id=:'oid10'),'processing','活跃订单保持 processing');

-- ---------------------------------------------------------------- 9. 货基收益复投 幂等
-- 期初持仓：positions 与 initial lot 一起建（lot 是事实来源）
INSERT INTO positions(user_id, fund_code, fund_name, quantity, cost_price, principal)
VALUES (:'uid','000198','天弘余额宝',1000.00,1.0000,1000.00);
INSERT INTO position_lots(user_id, fund_code, fund_name, source, source_ref, nav_date,
                          quantity, remaining_qty, cost_price, remaining_cost)
VALUES (:'uid','000198','天弘余额宝','initial','initial','2026-10-01',1000.00,1000.00,1.0000,1000.00);
SELECT pg_temp.assert_eq(
  credit_money_fund_income_atomic(:'uid','000198',0.55,'2026-10-30')->>'result',
  'credited','收益入账');
SELECT pg_temp.assert_eq(
  credit_money_fund_income_atomic(:'uid','000198',0.55,'2026-10-30')->>'result',
  'already_credited','同日重复入账幂等');
SELECT pg_temp.assert_eq((SELECT quantity::text FROM positions WHERE user_id=:'uid' AND fund_code='000198'),
  '1000.55','份额合并');
SELECT pg_temp.assert_eq((SELECT principal::text FROM positions WHERE user_id=:'uid' AND fund_code='000198'),
  '1000.00','收益不改本金');
SELECT pg_temp.assert_eq((SELECT cost_price::text FROM positions WHERE user_id=:'uid' AND fund_code='000198'),
  '1.0000','货基成本价恒 1.0000');
SELECT pg_temp.assert_eq(
  credit_money_fund_income_atomic(:'uid','000198',0,'2026-10-31')->>'result',
  'no_income','零收益不入账');
SELECT pg_temp.assert_eq(
  credit_money_fund_income_atomic(:'uid','000001',0.5,'2026-10-30')->>'result',
  'no_position','无持仓不入账');

-- ---------------------------------------------------------------- 10. 资金守恒
-- 口径：现金 + 冻结 + 剩余成本 = 初始资金 - 已扣费用 + 已实现盈亏 + 尾差退现
-- （成本基数为净申购额，不含费，所以买入费要从等式右边的盈亏里单独扣）
SELECT pg_temp.assert_eq(
  ((SELECT cash + frozen_cash FROM accounts WHERE user_id=:'uid')
   + (SELECT COALESCE(SUM(remaining_cost),0) FROM position_lots WHERE user_id=:'uid'))::text,
  -- 100000 - 买入费 1.50 - 卖出费 2.00 + 尾差 0.01 + 已实现 214.73(1213.23-998.50)
  -- + 测试手工注入的 1600（oid2 冻结 100、oid5 冻结 500 且已退回现金、000198 期初成本 1000）
  '101811.24',
  '现金 + 冻结 + 剩余成本 与费用/盈亏对账');

ROLLBACK;
