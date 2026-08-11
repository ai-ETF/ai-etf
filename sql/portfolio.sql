-- 模拟场外基金持仓交易系统 - 建表脚本
-- 在 Supabase SQL Editor 中执行

-- ============================================================
-- 1. accounts 表：用户账户（现金 + 冻结金）
-- ============================================================
CREATE TABLE IF NOT EXISTS accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE,
  cash DECIMAL(18,2) NOT NULL DEFAULT 100000.00,
  frozen_cash DECIMAL(18,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE accounts IS '用户资金账户';
COMMENT ON COLUMN accounts.user_id IS '用户ID（对应 auth.users）';
COMMENT ON COLUMN accounts.cash IS '可用现金（元），初始 100,000';
COMMENT ON COLUMN accounts.frozen_cash IS '冻结资金（元），pending 订单锁定';

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
  confirm_date DATE,                      -- 份额确认日期
  available_date DATE,                    -- 份额可赎回日期
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, fund_code)
);

COMMENT ON TABLE positions IS '用户基金持仓';
COMMENT ON COLUMN positions.quantity IS '持有份额';
COMMENT ON COLUMN positions.cost_price IS '加权平均成本价（元/份）';
COMMENT ON COLUMN positions.confirm_date IS '申购确认日期（T+1）';
COMMENT ON COLUMN positions.available_date IS '份额可赎回日期（T+2）';

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
  direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
  order_type VARCHAR(10) NOT NULL DEFAULT 'market' CHECK (order_type IN ('market')),
  amount DECIMAL(18,2) NOT NULL DEFAULT 0,    -- 申购金额（买入）/ 卖出总价
  price DECIMAL(18,4) NOT NULL DEFAULT 0,
  quantity DECIMAL(18,2) NOT NULL DEFAULT 0,  -- 份额（确认后填入）
  fee DECIMAL(18,2) NOT NULL DEFAULT 0,
  status VARCHAR(10) NOT NULL DEFAULT 'completed'
    CHECK (status IN ('pending', 'completed', 'cancelled', 'rejected')),
  reject_reason TEXT,
  confirm_date DATE,                          -- 份额确认日期
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE trade_orders IS '交易订单/委托记录';
COMMENT ON COLUMN trade_orders.direction IS '方向：buy-买入, sell-卖出';
COMMENT ON COLUMN trade_orders.amount IS '申购金额（元）';
COMMENT ON COLUMN trade_orders.status IS '状态：pending-待确认, completed-已完成, cancelled-已撤销, rejected-已拒绝';

CREATE INDEX IF NOT EXISTS idx_trade_orders_user ON trade_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_trade_orders_created ON trade_orders(created_at DESC);

-- ============================================================
-- 4. trade_flow 表：交易流水（成交明细）
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_flow (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fund_code VARCHAR(10) NOT NULL,
  fund_name VARCHAR(100) NOT NULL DEFAULT '',
  direction VARCHAR(4) NOT NULL CHECK (direction IN ('buy', 'sell')),
  amount DECIMAL(18,2) NOT NULL,             -- 成交金额
  price DECIMAL(18,4) NOT NULL,
  quantity DECIMAL(18,2) NOT NULL,
  fee DECIMAL(18,2) NOT NULL DEFAULT 0,
  trade_time TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE trade_flow IS '交易流水（成交明细）';
COMMENT ON COLUMN trade_flow.amount IS '成交金额（元）';

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
  created_at TIMESTAMPTZ DEFAULT NOW(),
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
  -- 费率
  purchase_fee_tiers JSONB NOT NULL DEFAULT '[{"rate": 0.0015, "amount": 1000000}]',
  -- 赎回费档位 JSON：{"tiers":[{"days":7,"rate":0.015},{...}]}
  redemption_fee_tiers JSONB NOT NULL DEFAULT '[{"days":7,"rate":0.0150},{"days":30,"rate":0.0100},{"days":180,"rate":0.0050},{"days":365,"rate":0.0000}]',
  -- 管理费率（年化）
  management_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.015,
  -- 托管费率（年化）
  custody_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0025,
  -- 最低申购金额（元）
  min_purchase_amount DECIMAL(18,2) NOT NULL DEFAULT 10.00,
  -- 确认延迟天数
  confirm_delay INT NOT NULL DEFAULT 1,
  -- 可赎回到账延迟天数
  redeem_settle_delay INT NOT NULL DEFAULT 3,
  -- 基金类型：of=场外开放式基金, etf=场内ETF
  fund_type VARCHAR(4) NOT NULL DEFAULT 'of' CHECK (fund_type IN ('of', 'etf')),
  -- 份额类别：A=A类, C=C类
  share_class VARCHAR(1) NOT NULL DEFAULT 'A',
  -- 销售服务费率（年化），A类=0，C类必须查询
  sales_service_fee_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0000,
  -- ETF券商佣金费率
  commission_rate DECIMAL(6,4) NOT NULL DEFAULT 0.0000,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE fund_fee_rules IS '基金手续费规则（仅覆盖被动指数/ETF联接基金）';
COMMENT ON COLUMN fund_fee_rules.purchase_fee_tiers IS '申购费金额分档 JSON。格式: [{"amount":金额,"rate":费率,"fixed_fee":固定费,"inclusive":bool}]. 不提供amount表示匹配所有金额';
COMMENT ON COLUMN fund_fee_rules.redemption_fee_tiers IS '赎回费档位 JSON，含 days 和 rate';
COMMENT ON COLUMN fund_fee_rules.min_purchase_amount IS '最低申购金额（元），默认10元';
COMMENT ON COLUMN fund_fee_rules.confirm_delay IS '申购确认延迟天数（T+N），默认1=T+1';
COMMENT ON COLUMN fund_fee_rules.redeem_settle_delay IS '赎回到账延迟天数（T+N），默认3=T+3';
COMMENT ON COLUMN fund_fee_rules.fund_type IS '基金类型: of=场外开放式基金, etf=场内ETF';
COMMENT ON COLUMN fund_fee_rules.share_class IS '份额类别: A=A类, C=C类';
COMMENT ON COLUMN fund_fee_rules.sales_service_fee_rate IS '销售服务费率（年化），A类=0，C类通常0.2%~0.4%';
COMMENT ON COLUMN fund_fee_rules.commission_rate IS 'ETF券商佣金费率 (如 0.00025=万2.5)';
