-- 清理旧基金代码 + 更新赎回费档位
-- 4只基金代码已更正，需要：1. 删除旧代码记录 2. 确认新代码由 seed.sql 插入
-- 在 Supabase SQL Editor 执行（在 alter_purchase_fee_tiers.sql 和 fund_fee_rules_seed.sql 之前执行）

-- ============================================================
-- 1. 删除代码错误的旧记录
-- ============================================================
DELETE FROM fund_fee_rules WHERE fund_code = '001632';  -- 旧：食品饮料C，已换为 001631（A类）
DELETE FROM fund_fee_rules WHERE fund_code = '003745';  -- 旧：广发多元新兴股票，已换为 005223（基建工程联接A）
DELETE FROM fund_fee_rules WHERE fund_code = '012859';  -- 旧：天弘利率债C，已换为 011102（光伏联接A）
DELETE FROM fund_fee_rules WHERE fund_code = '012860';  -- 旧：易方达标普500C，已换为 011103（光伏联接C）

-- ============================================================
-- 2. 检查是否有持仓/订单引用旧代码
-- ============================================================
-- 如果以下查询返回数据，需要先处理关联记录
SELECT 'trade_orders' AS table_name, fund_code, count(*)
FROM trade_orders WHERE fund_code IN ('001632','003745','012859','012860')
GROUP BY fund_code;

SELECT 'positions' AS table_name, fund_code, count(*)
FROM positions WHERE fund_code IN ('001632','003745','012859','012860')
GROUP BY fund_code;

SELECT 'trade_flow' AS table_name, fund_code, count(*)
FROM trade_flow WHERE fund_code IN ('001632','003745','012859','012860')
GROUP BY fund_code;
