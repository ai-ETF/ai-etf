-- ============================================================
-- 修正 trade_orders.fund_type 取值漂移：otf → of
--
-- 背景：
--   trade_orders.fund_type 由 alter_trade_orders_reserved.sql 新增时
--   默认值为 'otf'，而主表 fund_fee_rules.fund_type 已统一为 'of'。
--   两张表对「场外基金」这一概念用了两种写法，导致线上数据不一致。
--
-- 注意：应用代码没有读取字面量 'otf'（portfolio_service.py 判断的是
--   主表 fund_fee_rules.fund_type == 'etf'），故本脚本只改数据与约束，
--   不需要同步改代码。
--
-- 在 Supabase SQL Editor 执行
-- ============================================================

-- 1. 删除 fund_type 列上的旧 CHECK 约束
--    用动态查找约束名，避免历史手工操作导致名称不是默认的
--    trade_orders_fund_type_check 而删不到。
DO $$
DECLARE
  cname text;
BEGIN
  SELECT con.conname INTO cname
  FROM pg_constraint con
  JOIN pg_attribute att
    ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
  WHERE con.conrelid = 'trade_orders'::regclass
    AND con.contype = 'c'
    AND att.attname = 'fund_type';
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE trade_orders DROP CONSTRAINT %I', cname);
  END IF;
END $$;

-- 2. 已有数据 otf → of
UPDATE trade_orders SET fund_type = 'of' WHERE fund_type = 'otf';

-- 3. 默认值同步修正，避免新订单再次写入 otf
ALTER TABLE trade_orders ALTER COLUMN fund_type SET DEFAULT 'of';

-- 4. 加回新 CHECK 约束（值域统一为 of/etf）
ALTER TABLE trade_orders ADD CONSTRAINT trade_orders_fund_type_check
  CHECK (fund_type IN ('of', 'etf'));

-- 5. 更新列注释
COMMENT ON COLUMN trade_orders.fund_type IS '基金类型: of=场外开放式基金, etf=场内ETF';

-- 6. 验证（应只剩 of，且无 otf）
SELECT fund_type, count(*) FROM trade_orders GROUP BY fund_type;
