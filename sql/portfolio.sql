-- 模拟持仓交易系统 - 建表脚本
-- 在 Supabase SQL Editor 中执行

-- ============================================================
-- 1. accounts 表：用户账户（现金）
-- ============================================================
CREATE TABLE IF NOT EXISTS accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE,
  cash DECIMAL(18,2) NOT NULL DEFAULT 100000.00,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE accounts IS '用户资金账户';
COMMENT ON COLUMN accounts.user_id IS '用户ID（对应 auth.users）';
COMMENT ON COLUMN accounts.cash IS '可用现金（元），初始 100,000';

CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);

-- ============================================================
-- 2. positions 表：持仓
-- ============================================================
CREATE TABLE IF NOT EXISTS positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100) NOT NULL DEFAULT '',
  quantity DECIMAL(18,2) NOT NULL DEFAULT 0,
  cost_price DECIMAL(18,4) NOT NULL DEFAULT 0,
  confirm_date DATE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  UNIQUE(user_id, fund_code)
);

COMMENT ON TABLE positions IS '用户基金持仓';
COMMENT ON COLUMN positions.quantity IS '持有份额';
COMMENT ON COLUMN positions.cost_price IS '加权平均成本价（元/份）';
COMMENT ON COLUMN positions.confirm_date IS '申购确认日期（交易日15:00前为当日，否则为下一交易日）';

CREATE INDEX IF NOT EXISTS idx_positions_user ON positions(user_id);
CREATE INDEX IF NOT EXISTS idx_positions_code ON positions(fund_code);

-- ============================================================
-- 3. trade_orders 表：交易委托记录
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100) NOT NULL DEFAULT '',
  fund_type VARCHAR(4) NOT NULL DEFAULT 'otf' CHECK (fund_type IN ('otf', 'etf')),
  direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
  order_type VARCHAR(10) NOT NULL DEFAULT 'market' CHECK (order_type IN ('market', 'limit')),
  price DECIMAL(18,4) NOT NULL DEFAULT 0,
  quantity DECIMAL(18,2) NOT NULL,
  amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  fee DECIMAL(18,2) NOT NULL DEFAULT 0,
  status VARCHAR(10) NOT NULL DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'cancelled', 'rejected', 'reserved')),
  reject_reason TEXT,
  confirm_date DATE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE trade_orders IS '交易订单/委托记录';
COMMENT ON COLUMN trade_orders.direction IS '方向：buy-买入, sell-卖出';
COMMENT ON COLUMN trade_orders.fund_type IS '基金类型: otf=场外基金, etf=场内ETF';
COMMENT ON COLUMN trade_orders.status IS '状态：pending-待确认, completed-已完成, cancelled-已撤销, rejected-已拒绝, reserved-预约待执行';
COMMENT ON COLUMN trade_orders.confirm_date IS '场外基金订单确认日期：交易日15:00前为当日，15:00后/非交易日为下一个交易日';

CREATE INDEX IF NOT EXISTS idx_trade_orders_user ON trade_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_trade_orders_created ON trade_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_orders_status ON trade_orders(status);

-- ============================================================
-- 4. trade_flow 表：交易流水（成交明细）
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_flow (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100) NOT NULL DEFAULT '',
  direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
  price DECIMAL(18,4) NOT NULL,
  quantity DECIMAL(18,2) NOT NULL,
  amount DECIMAL(18,2) NOT NULL,
  fee DECIMAL(18,2) NOT NULL DEFAULT 0,
  trade_time TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE trade_flow IS '交易流水（成交明细）';

CREATE INDEX IF NOT EXISTS idx_trade_flow_user ON trade_flow(user_id);
CREATE INDEX IF NOT EXISTS idx_trade_flow_user_time ON trade_flow(user_id, trade_time DESC);
CREATE INDEX IF NOT EXISTS idx_trade_flow_code ON trade_flow(fund_code);

-- ============================================================
-- 5. account_snapshots 表：每日资产快照
-- ============================================================
CREATE TABLE IF NOT EXISTS account_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  total_assets DECIMAL(18,2) NOT NULL,
  cash DECIMAL(18,2) NOT NULL,
  position_value DECIMAL(18,2) NOT NULL DEFAULT 0,
  total_pnl DECIMAL(18,2) NOT NULL DEFAULT 0,
  total_return_rate DECIMAL(10,6) NOT NULL DEFAULT 0,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  UNIQUE(user_id, snapshot_date)
);

COMMENT ON TABLE account_snapshots IS '每日资产快照';

CREATE INDEX IF NOT EXISTS idx_snapshots_user ON account_snapshots(user_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_user_date ON account_snapshots(user_id, snapshot_date DESC);

-- ============================================================
-- 6. fund_fee_rules 表：基金手续费规则配置
-- ============================================================
CREATE TABLE IF NOT EXISTS fund_fee_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_code VARCHAR(10) NOT NULL UNIQUE,
  fund_name VARCHAR(100) NOT NULL,
  -- 基金类型
  fund_type VARCHAR(4) NOT NULL DEFAULT 'otf' CHECK (fund_type IN ('otf', 'etf')),
  -- 申购费率
  purchase_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0015,
  -- 赎回费率（持有<7天）
  redemption_fee_rate_7d DECIMAL(6,4) NOT NULL DEFAULT 0.015,
  -- 赎回费率（持有7-30天）
  redemption_fee_rate_30d DECIMAL(6,4) NOT NULL DEFAULT 0.0075,
  -- 赎回费率（持有30-365天）
  redemption_fee_rate_1y DECIMAL(6,4) NOT NULL DEFAULT 0.005,
  -- 赎回费率（持有>365天）
  redemption_fee_rate_over1y DECIMAL(6,4) NOT NULL DEFAULT 0,
  -- 管理费率（年化）
  management_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.015,
  -- 托管费率（年化）
  custody_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0025,
  -- ETF 券商佣金费率
  commission_rate DECIMAL(6,4) NOT NULL DEFAULT 0.00025,
  -- 最低申购金额
  min_purchase_amount DECIMAL(18,2) NOT NULL DEFAULT 1.00,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE fund_fee_rules IS '基金手续费规则（覆盖20只常用场外基金+ETF）';
COMMENT ON COLUMN fund_fee_rules.fund_type IS '基金类型: otf=场外基金, etf=场内ETF';
COMMENT ON COLUMN fund_fee_rules.purchase_fee_rate IS '申购费率（如0.0015=0.15%）';
COMMENT ON COLUMN fund_fee_rules.redemption_fee_rate_7d IS '赎回费率 持有<7天';
COMMENT ON COLUMN fund_fee_rules.redemption_fee_rate_30d IS '赎回费率 持有7-30天';
COMMENT ON COLUMN fund_fee_rules.redemption_fee_rate_1y IS '赎回费率 持有30-365天';
COMMENT ON COLUMN fund_fee_rules.redemption_fee_rate_over1y IS '赎回费率 持有>365天';
COMMENT ON COLUMN fund_fee_rules.commission_rate IS 'ETF券商佣金费率 (如 0.00025=万2.5), 最低5元';
