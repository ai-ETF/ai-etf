-- 场外基金重构迁移脚本
-- 在 Supabase SQL Editor 执行
-- 注意：此脚本会删除旧表重建，仅适用于开发环境

-- ============================================================
-- 0. 删除旧表（开发环境，直接重建）
-- ============================================================
DROP TABLE IF EXISTS fund_fee_rules CASCADE;
DROP TABLE IF EXISTS trade_flow CASCADE;
DROP TABLE IF EXISTS trade_orders CASCADE;
DROP TABLE IF EXISTS positions CASCADE;
DROP TABLE IF EXISTS account_snapshots CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;

-- ============================================================
-- 1. accounts 表（加 frozen_cash）
-- ============================================================
CREATE TABLE accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE,
  cash DECIMAL(18,2) NOT NULL DEFAULT 100000.00,
  frozen_cash DECIMAL(18,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE accounts IS '用户资金账户';
COMMENT ON COLUMN accounts.cash IS '可用现金（元），初始 100,000';
COMMENT ON COLUMN accounts.frozen_cash IS '冻结资金（元），pending 订单锁定';

CREATE INDEX idx_accounts_user ON accounts(user_id);

-- ============================================================
-- 2. positions 表
-- ============================================================
CREATE TABLE positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100) NOT NULL DEFAULT '',
  quantity DECIMAL(18,2) NOT NULL DEFAULT 0,
  cost_price DECIMAL(18,4) NOT NULL DEFAULT 0,
  confirm_date DATE,
  available_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, fund_code)
);

COMMENT ON TABLE positions IS '用户基金持仓';
COMMENT ON COLUMN positions.quantity IS '持有份额';
COMMENT ON COLUMN positions.cost_price IS '加权平均成本价（元/份）';
COMMENT ON COLUMN positions.confirm_date IS '申购确认日期（T+1）';
COMMENT ON COLUMN positions.available_date IS '份额可赎回日期（T+2）';

CREATE INDEX idx_positions_user ON positions(user_id);
CREATE INDEX idx_positions_code ON positions(fund_code);

-- ============================================================
-- 3. trade_orders 表
-- ============================================================
CREATE TABLE trade_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100) NOT NULL DEFAULT '',
  direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
  order_type VARCHAR(10) NOT NULL DEFAULT 'market' CHECK (order_type IN ('market')),
  amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  price DECIMAL(18,4) NOT NULL DEFAULT 0,
  quantity DECIMAL(18,2) NOT NULL DEFAULT 0,
  fee DECIMAL(18,2) NOT NULL DEFAULT 0,
  status VARCHAR(10) NOT NULL DEFAULT 'completed'
    CHECK (status IN ('pending', 'completed', 'cancelled', 'rejected')),
  reject_reason TEXT,
  confirm_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE trade_orders IS '交易订单/委托记录';
COMMENT ON COLUMN trade_orders.direction IS '方向：buy-买入, sell-卖出';
COMMENT ON COLUMN trade_orders.amount IS '申购金额（元）';

CREATE INDEX idx_trade_orders_user ON trade_orders(user_id);
CREATE INDEX idx_trade_orders_created ON trade_orders(created_at DESC);

-- ============================================================
-- 4. trade_flow 表
-- ============================================================
CREATE TABLE trade_flow (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100) NOT NULL DEFAULT '',
  direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
  amount DECIMAL(18,2) NOT NULL,
  price DECIMAL(18,4) NOT NULL,
  quantity DECIMAL(18,2) NOT NULL,
  fee DECIMAL(18,2) NOT NULL DEFAULT 0,
  trade_time TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE trade_flow IS '交易流水（成交明细）';
COMMENT ON COLUMN trade_flow.amount IS '成交金额（元）';

CREATE INDEX idx_trade_flow_user ON trade_flow(user_id);
CREATE INDEX idx_trade_flow_user_time ON trade_flow(user_id, trade_time DESC);
CREATE INDEX idx_trade_flow_code ON trade_flow(fund_code);

-- ============================================================
-- 5. account_snapshots 表
-- ============================================================
CREATE TABLE account_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  snapshot_date DATE NOT NULL,
  total_assets DECIMAL(18,2) NOT NULL,
  cash DECIMAL(18,2) NOT NULL,
  position_value DECIMAL(18,2) NOT NULL DEFAULT 0,
  total_pnl DECIMAL(18,2) NOT NULL DEFAULT 0,
  total_return_rate DECIMAL(10,6) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, snapshot_date)
);

CREATE INDEX idx_snapshots_user ON account_snapshots(user_id);
CREATE INDEX idx_snapshots_user_date ON account_snapshots(user_id, snapshot_date DESC);

-- ============================================================
-- 6. fund_fee_rules 表（JSON 赎回档位）
-- ============================================================
CREATE TABLE fund_fee_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_code VARCHAR(10) NOT NULL UNIQUE,
  fund_name VARCHAR(100) NOT NULL,
  purchase_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0015,
  redemption_fee_tiers JSONB NOT NULL DEFAULT '[{"days":7,"rate":0.0150},{"days":30,"rate":0.0100},{"days":180,"rate":0.0050},{"days":365,"rate":0.0000}]',
  management_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.015,
  custody_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0025,
  min_purchase_amount DECIMAL(18,2) NOT NULL DEFAULT 10.00,
  confirm_delay INT NOT NULL DEFAULT 1,
  redeem_settle_delay INT NOT NULL DEFAULT 3,
  fund_type VARCHAR(4) NOT NULL DEFAULT 'of' CHECK (fund_type IN ('of', 'etf')),
  share_class VARCHAR(1) NOT NULL DEFAULT 'A',
  sales_service_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0000,
  commission_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0000,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE fund_fee_rules IS '基金手续费规则（仅覆盖被动指数/ETF联接基金）';
COMMENT ON COLUMN fund_fee_rules.purchase_fee_rate IS '申购费率（互联网渠道1折后）';
COMMENT ON COLUMN fund_fee_rules.redemption_fee_tiers IS '赎回费档位 JSON';
COMMENT ON COLUMN fund_fee_rules.confirm_delay IS '申购确认延迟天数 T+N，默认1=T+1';
COMMENT ON COLUMN fund_fee_rules.redeem_settle_delay IS '赎回到账延迟天数 T+N，默认3=T+3';
COMMENT ON COLUMN fund_fee_rules.fund_type IS '基金类型: of=场外开放式基金, etf=场内ETF';
COMMENT ON COLUMN fund_fee_rules.share_class IS '份额类别: A=A类, C=C类';
COMMENT ON COLUMN fund_fee_rules.sales_service_fee_rate IS '销售服务费率（年化），A类=0，C类通常0.2%~0.4%';
COMMENT ON COLUMN fund_fee_rules.commission_rate IS 'ETF券商佣金费率 (如 0.00025=万2.5)';

-- ============================================================
-- 7. 验证
-- ============================================================
SELECT '迁移完成' AS status;
