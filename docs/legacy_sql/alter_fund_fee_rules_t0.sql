-- fund_fee_rules 加 T+0/T+1 标记
-- 在 Supabase SQL Editor 执行

ALTER TABLE fund_fee_rules ADD COLUMN IF NOT EXISTS is_t0 BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN fund_fee_rules.is_t0 IS '是否支持T+0回转交易: true=T+0（当日可买卖）, false=T+1';

-- 标记已存在的 T+0 品种（按代码前缀）
-- 债券ETF、黄金ETF、跨境ETF（QDII）支持T+0
UPDATE fund_fee_rules SET is_t0 = TRUE
  WHERE fund_code LIKE '51%'  -- 沪市
    OR fund_code LIKE '15%'   -- 深市创业板/中小板
    OR fund_code LIKE '16%'   -- 深市LOF
    OR fund_code LIKE '58%';  -- 沪市科创板

-- 注意：目前仅 512890、510300 在表中，均为A股股票型ETF，is_t0=FALSE（默认值正确）