-- 补齐已有旧表缺失列 + 修复 fund_type 约束（一次性执行）
-- 在 Supabase SQL Editor 执行，每条用 IF NOT EXISTS 安全执行
-- fund_type: of=场外开放式基金, etf=场内ETF
-- share_class: A=A类份额, C=C类份额

-- 1. accounts: 加 frozen_cash（pending 资金冻结）
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS frozen_cash DECIMAL(18,2) NOT NULL DEFAULT 0;
COMMENT ON COLUMN accounts.frozen_cash IS '冻结资金（元），pending 订单锁定';

-- 2. positions: 加 available_date（份额可赎回日期）
ALTER TABLE positions ADD COLUMN IF NOT EXISTS available_date DATE;
COMMENT ON COLUMN positions.available_date IS '份额可赎回日期（T+2）';

-- 3. fund_fee_rules: 先删除旧的错误约束
ALTER TABLE fund_fee_rules DROP CONSTRAINT IF EXISTS fund_fee_rules_fund_type_check;

-- 4. fund_fee_rules: 加 fund_type 列（不设 CHECK 约束，后面统一改）
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS fund_type VARCHAR(4) NOT NULL DEFAULT 'of';

-- 5. fund_fee_rules: 加 share_class（份额类别 A/C）
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS share_class VARCHAR(1) NOT NULL DEFAULT 'A';
COMMENT ON COLUMN fund_fee_rules.share_class IS '份额类别: A=A类, C=C类';

-- 6. fund_fee_rules: 加 sales_service_fee_rate（C类销售服务费）
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS sales_service_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0000;
COMMENT ON COLUMN fund_fee_rules.sales_service_fee_rate IS '销售服务费率（年化），A类=0，C类通常0.2%~0.4%';

-- 7. fund_fee_rules: 加 commission_rate（ETF佣金）
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS commission_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0000;
COMMENT ON COLUMN fund_fee_rules.commission_rate IS 'ETF券商佣金费率 (如 0.00025=万2.5)';

-- 8. fund_fee_rules: 加新格式列
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS redemption_fee_tiers JSONB NOT NULL DEFAULT '[{"days":7,"rate":0.0150},{"days":30,"rate":0.0100},{"days":180,"rate":0.0050},{"days":365,"rate":0.0000}]';
COMMENT ON COLUMN fund_fee_rules.redemption_fee_tiers IS '赎回费档位 JSON（新格式）';

ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS confirm_delay INT NOT NULL DEFAULT 1;
COMMENT ON COLUMN fund_fee_rules.confirm_delay IS '申购确认延迟天数 T+N，默认1=T+1';

ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS redeem_settle_delay INT NOT NULL DEFAULT 3;
COMMENT ON COLUMN fund_fee_rules.redeem_settle_delay IS '赎回到账延迟天数 T+N，默认3=T+3';

-- 9. 修正 fund_type 的 CHECK 约束和注释
ALTER TABLE fund_fee_rules ADD CONSTRAINT fund_fee_rules_fund_type_check CHECK (fund_type IN ('of', 'etf'));
COMMENT ON COLUMN fund_fee_rules.fund_type IS '基金类型: of=场外开放式基金, etf=场内ETF';

-- 验证
SELECT '补齐完成' AS status;
