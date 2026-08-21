-- trade_flow 表增加 trade_pnl 字段，记录卖出盈亏
ALTER TABLE trade_flow ADD COLUMN IF NOT EXISTS trade_pnl DECIMAL(18,2);
