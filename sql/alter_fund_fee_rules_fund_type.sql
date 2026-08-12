-- 场内外基金区分：fund_fee_rules 表加 fund_type 和 commission_rate 列
-- 在 Supabase SQL Editor 执行

-- 1. 添加基金类型列（otf=场外基金, etf=场内ETF）
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS fund_type VARCHAR(4) NOT NULL DEFAULT 'otf'
  CHECK (fund_type IN ('otf', 'etf'));

COMMENT ON COLUMN fund_fee_rules.fund_type IS '基金类型: otf=场外基金, etf=场内ETF';

-- 2. 添加券商佣金费率列（仅 ETF 使用）
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS commission_rate DECIMAL(6,4) NOT NULL DEFAULT 0.00025;

COMMENT ON COLUMN fund_fee_rules.commission_rate IS 'ETF券商佣金费率 (如 0.00025=万2.5), 最低5元';

-- 3. 标记已有 ETF
UPDATE fund_fee_rules SET fund_type = 'etf', commission_rate = 0.00025
  WHERE fund_code IN ('512890', '510300');

-- 4. ETF 的申购/赎回费率设为 0（ETF 不使用申购赎回费）
UPDATE fund_fee_rules SET
  purchase_fee_rate = 0,
  redemption_fee_rate_7d = 0,
  redemption_fee_rate_30d = 0,
  redemption_fee_rate_1y = 0,
  redemption_fee_rate_over1y = 0
WHERE fund_type = 'etf';

-- 5. ETF 最低购买金额改为 100 元（对应 100 份起购）
UPDATE fund_fee_rules SET min_purchase_amount = 100.00 WHERE fund_type = 'etf';