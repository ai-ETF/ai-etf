-- fund_fee_rules 加销售服务费列（C类基金必须）
-- 在 Supabase SQL Editor 执行

ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS sales_service_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0000;
COMMENT ON COLUMN fund_fee_rules.sales_service_fee_rate IS '销售服务费率（年化），A类=0，C类通常0.2%~0.4%';
