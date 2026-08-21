-- ================================================================
-- AI-ETF 持仓交易系统 — 完整迁移脚本
-- 在 Supabase SQL Editor 中执行
--
-- 包含：
--   1. fund_fee_rules 表加 fund_type + commission_rate（场内外基金区分）
--   2. positions 表加 confirm_date（场外基金申购确认日期）
--   3. trade_orders 表加 confirm_date（场外基金订单确认日期）
--   4. 标记已有 ETF 并更新费率规则
--   5. 插入 ETF 种子数据（512890、510300）
-- ================================================================

-- ============================================================
-- 1. fund_fee_rules: 添加基金类型列和佣金费率列
-- ============================================================
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS fund_type VARCHAR(4) NOT NULL DEFAULT 'otf'
  CHECK (fund_type IN ('otf', 'etf'));
COMMENT ON COLUMN fund_fee_rules.fund_type IS '基金类型: otf=场外基金, etf=场内ETF';

ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS commission_rate DECIMAL(6,4) NOT NULL DEFAULT 0.00025;
COMMENT ON COLUMN fund_fee_rules.commission_rate IS 'ETF券商佣金费率 (如 0.00025=万2.5), 最低5元';

-- ============================================================
-- 2. positions: 添加确认日期列
-- ============================================================
ALTER TABLE positions ADD COLUMN IF NOT EXISTS confirm_date DATE;
COMMENT ON COLUMN positions.confirm_date IS '申购确认日期（交易日15:00前为当日，否则为下一交易日）';

-- ============================================================
-- 3. trade_orders: 添加确认日期列
-- ============================================================
ALTER TABLE trade_orders ADD COLUMN IF NOT EXISTS confirm_date DATE;
COMMENT ON COLUMN trade_orders.confirm_date IS '场外基金订单确认日期：交易日15:00前为当日，15:00后/非交易日为下一个交易日';

-- ============================================================
-- 4. 更新赎回费率按2025年证监会新规
--    <7天=1.5%，7-30天=1.0%，30-180天=0.5%，≥180天=0%
-- ============================================================
UPDATE fund_fee_rules SET
  redemption_fee_rate_30d = 0.0100,
  redemption_fee_rate_1y  = 0.0050,
  redemption_fee_rate_over1y = 0.0000
WHERE redemption_fee_rate_30d = 0.0075;

-- ============================================================
-- 5. 标记已有 ETF（512890、510300）
-- ============================================================
-- 如果不存在则插入，存在则更新
INSERT INTO fund_fee_rules (fund_code, fund_name, fund_type, purchase_fee_rate, redemption_fee_rate_7d, redemption_fee_rate_30d, redemption_fee_rate_1y, redemption_fee_rate_over1y, commission_rate, management_fee_rate, custody_fee_rate, min_purchase_amount)
VALUES
  ('512890', '红利低波ETF华泰柏瑞',   'etf', 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.00025, 0.0050, 0.0010, 100.00),
  ('510300', '沪深300ETF华泰柏瑞',   'etf', 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.00025, 0.0050, 0.0010, 100.00)
ON CONFLICT (fund_code) DO UPDATE SET
  fund_type = EXCLUDED.fund_type,
  commission_rate = EXCLUDED.commission_rate,
  purchase_fee_rate = EXCLUDED.purchase_fee_rate,
  redemption_fee_rate_7d = EXCLUDED.redemption_fee_rate_7d,
  redemption_fee_rate_30d = EXCLUDED.redemption_fee_rate_30d,
  redemption_fee_rate_1y = EXCLUDED.redemption_fee_rate_1y,
  redemption_fee_rate_over1y = EXCLUDED.redemption_fee_rate_over1y,
  min_purchase_amount = EXCLUDED.min_purchase_amount,
  updated_at = NOW();

-- ============================================================
-- 6. 验证迁移结果
-- ============================================================
SELECT fund_code, fund_name, fund_type, commission_rate, min_purchase_amount
FROM fund_fee_rules
ORDER BY fund_code;
