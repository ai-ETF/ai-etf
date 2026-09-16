-- accounts 表增加余额理财开关和预留金额
-- 在 Supabase SQL Editor 执行

-- 1. 自动理财开关（默认关闭，用户需手动开启）
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS auto_invest_enabled BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN accounts.auto_invest_enabled IS '余额理财开关：true=闲置现金自动申购货基';

-- 2. 预留金额（超过此金额的部分才会被自动转入货基，默认 0 = 全部转入）
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS auto_invest_reserve DECIMAL(18,2) NOT NULL DEFAULT 0.00;
COMMENT ON COLUMN accounts.auto_invest_reserve IS '余额理财预留金额：账户保留的现金，超出部分才自动理财';
