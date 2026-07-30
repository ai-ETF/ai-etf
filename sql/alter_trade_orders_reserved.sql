-- ETF 预约功能：trade_orders 表扩展
-- 在 Supabase SQL Editor 执行

-- 1. 扩展 status 约束，新增 'reserved'（预约待执行）
ALTER TABLE trade_orders DROP CONSTRAINT IF EXISTS trade_orders_status_check;
ALTER TABLE trade_orders ADD CONSTRAINT trade_orders_status_check
  CHECK (status IN ('pending', 'completed', 'cancelled', 'rejected', 'reserved'));

COMMENT ON COLUMN trade_orders.status IS '状态：pending-待确认, completed-已完成, cancelled-已撤销, rejected-已拒绝, reserved-预约待执行';

-- 2. 新增 fund_type 列（区分场外/场内）
ALTER TABLE trade_orders ADD COLUMN IF NOT EXISTS fund_type VARCHAR(4) DEFAULT 'otf'
  CHECK (fund_type IN ('otf', 'etf'));

COMMENT ON COLUMN trade_orders.fund_type IS '基金类型: otf=场外基金, etf=场内ETF';

-- 3. 给已有订单回填 fund_type（按代码前缀判断）
UPDATE trade_orders SET fund_type = 'etf'
  WHERE fund_code LIKE '51%' OR fund_code LIKE '15%' OR fund_code LIKE '16%' OR fund_code LIKE '58%';

-- 4. 新增索引（调度器按状态查询预约单）
CREATE INDEX IF NOT EXISTS idx_trade_orders_status ON trade_orders(status);
