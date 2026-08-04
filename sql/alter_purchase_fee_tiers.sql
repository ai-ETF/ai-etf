-- 场外基金费率规则升级迁移脚本
-- 1. 新增 purchase_fee_tiers JSONB 字段（申购费金额分档）
-- 2. 删除旧的赎回费列（已被 redemption_fee_tiers JSONB 替代）
-- 在 Supabase SQL Editor 执行

-- ============================================================
-- 1. 新增 purchase_fee_tiers 列
-- ============================================================
ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS purchase_fee_tiers JSONB;

COMMENT ON COLUMN fund_fee_rules.purchase_fee_tiers IS '申购费金额分档。JSON数组，按 amount 升序。每项: {"amount": 金额上限(元), "rate": 费率, "inclusive": bool}。NULL表示使用 purchase_fee_rate 单一费率（向后兼容）。';

-- 从旧字段迁移数据（将 purchase_fee_rate 转为单一档位 <100万元）
UPDATE fund_fee_rules
SET purchase_fee_tiers = jsonb_build_array(
    jsonb_build_object('amount', 1000000, 'rate', purchase_fee_rate)
)
WHERE purchase_fee_tiers IS NULL;

-- ============================================================
-- 2. 删除旧的赎回费列（不再被任何代码引用）
-- ============================================================
ALTER TABLE fund_fee_rules DROP COLUMN IF EXISTS redemption_fee_rate_7d;
ALTER TABLE fund_fee_rules DROP COLUMN IF EXISTS redemption_fee_rate_30d;
ALTER TABLE fund_fee_rules DROP COLUMN IF EXISTS redemption_fee_rate_1y;
ALTER TABLE fund_fee_rules DROP COLUMN IF EXISTS redemption_fee_rate_over1y;

-- ============================================================
-- 3. 验证
-- ============================================================
SELECT fund_code, fund_name, purchase_fee_tiers, redemption_fee_tiers
FROM fund_fee_rules
ORDER BY fund_code;
