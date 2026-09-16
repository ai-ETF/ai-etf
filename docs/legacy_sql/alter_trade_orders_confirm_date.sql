-- 给 trade_orders 表添加 confirm_date 列（场外基金交易时间规则）
ALTER TABLE trade_orders ADD COLUMN IF NOT EXISTS confirm_date DATE;

COMMENT ON COLUMN trade_orders.confirm_date IS '场外基金订单确认日期：交易日15:00前为当日，15:00后/非交易日为下一个交易日';