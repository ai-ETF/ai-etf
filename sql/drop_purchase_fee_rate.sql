-- 删除废弃的 purchase_fee_rate 单值字段
-- 所有基金的申购费率已迁移到 purchase_fee_tiers（JSONB 金额分档），
-- purchase_fee_rate 不再被任何代码引用，可以安全删除
-- 在 Supabase SQL Editor 执行

ALTER TABLE fund_fee_rules DROP COLUMN IF EXISTS purchase_fee_rate;

-- 验证
SELECT 'purchase_fee_rate 列已删除' AS status;
