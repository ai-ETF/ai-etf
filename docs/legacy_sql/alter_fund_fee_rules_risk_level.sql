-- 基金四维风险评分 + 风险等级
-- 见 docs/基金风险等级划分设计文档.md

ALTER TABLE fund_fee_rules
ADD COLUMN IF NOT EXISTS breadth_score    INT,
ADD COLUMN IF NOT EXISTS volatility_score INT,
ADD COLUMN IF NOT EXISTS market_score     INT,
ADD COLUMN IF NOT EXISTS board_score      INT,
ADD COLUMN IF NOT EXISTS risk_level       TEXT;

-- 维度分约束
ALTER TABLE fund_fee_rules
ADD CONSTRAINT chk_breadth_score    CHECK (breadth_score    IN (1, 2, 3)),
ADD CONSTRAINT chk_volatility_score CHECK (volatility_score IN (1, 2, 3)),
ADD CONSTRAINT chk_market_score     CHECK (market_score     IN (1, 3)),
ADD CONSTRAINT chk_board_score      CHECK (board_score      IN (1, 3)),
ADD CONSTRAINT chk_risk_level       CHECK (risk_level       IN ('moderate', 'aggressive', 'speculative'));

COMMENT ON COLUMN fund_fee_rules.breadth_score    IS '指数广度得分：1=宽基跨行业, 2=单一行业, 3=窄基主题';
COMMENT ON COLUMN fund_fee_rules.volatility_score IS '波动属性得分：1=大盘价值/防御, 2=消费/周期, 3=高成长/TMT/新能源';
COMMENT ON COLUMN fund_fee_rules.market_score     IS '市场属性得分：1=纯A股, 3=QDII跨境';
COMMENT ON COLUMN fund_fee_rules.board_score      IS '板块特征得分：1=主板为主, 3=科创/创业板';
COMMENT ON COLUMN fund_fee_rules.risk_level       IS '基金风险等级：moderate/aggressive/speculative';
