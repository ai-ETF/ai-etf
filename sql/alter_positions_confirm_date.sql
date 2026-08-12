-- 1. positions 表加 confirm_date 列（场外基金申购确认日期）
ALTER TABLE positions ADD COLUMN IF NOT EXISTS confirm_date DATE;

COMMENT ON COLUMN positions.confirm_date IS '申购确认日期（交易日15:00前为当日，否则为下一交易日）';

-- 2. 更新 fund_fee_rules 的赎回费率按2025年新规（<7天=1.5%，7-30天=1.0%，30-180天=0.5%，≥180天=0%）
UPDATE fund_fee_rules SET
  redemption_fee_rate_30d = 0.0100,  -- 7-30天 1.0%
  redemption_fee_rate_1y  = 0.0050,  -- 30-180天 0.5%
  redemption_fee_rate_over1y = 0.0000
WHERE redemption_fee_rate_30d = 0.0075;