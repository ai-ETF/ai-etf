-- 基金风险等级表：四维评分 + 风险等级 + 中文标签
-- 与 fund_fee_rules 解耦，独立存储基金风控属性
-- 规则见 docs/交易风险提示/基金风险等级划分设计文档.md

CREATE TABLE public.fund_risk_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fund_code varchar(10) NOT NULL UNIQUE,
  breadth_score int NOT NULL CHECK (breadth_score IN (1, 2, 3)),
  volatility_score int NOT NULL CHECK (volatility_score IN (1, 2, 3)),
  market_score int NOT NULL CHECK (market_score IN (1, 3)),
  board_score int NOT NULL CHECK (board_score IN (1, 3)),
  risk_level text NOT NULL CHECK (risk_level IN ('moderate', 'aggressive', 'speculative')),
  risk_label text NOT NULL,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

ALTER TABLE public.fund_risk_profiles ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.fund_risk_profiles IS '基金风险等级表：四维评分+等级+中文标签（与 fund_fee_rules 解耦）';
COMMENT ON COLUMN public.fund_risk_profiles.breadth_score IS '指数广度得分：1=宽基跨行业, 2=单一行业, 3=窄基主题';
COMMENT ON COLUMN public.fund_risk_profiles.volatility_score IS '波动属性得分：1=大盘价值/防御, 2=消费/周期, 3=高成长/TMT/新能源';
COMMENT ON COLUMN public.fund_risk_profiles.market_score IS '市场属性得分：1=纯A股, 3=QDII跨境';
COMMENT ON COLUMN public.fund_risk_profiles.board_score IS '板块特征得分：1=主板为主, 3=科创/创业板';
COMMENT ON COLUMN public.fund_risk_profiles.risk_level IS '基金风险等级：moderate/aggressive/speculative';
COMMENT ON COLUMN public.fund_risk_profiles.risk_label IS '基金风险等级中文标签：中等风险/较高风险/高风险';

-- 种子数据（20 只白名单基金）
-- 来源：docs/legacy_sql/seed_fund_risk_levels.sql（fund_code+四维分+risk_level 一致）
-- risk_label 按 fund_risk_scores.RISK_LABELS 映射写死，避免运行时计算
INSERT INTO public.fund_risk_profiles
  (fund_code, breadth_score, volatility_score, market_score, board_score, risk_level, risk_label)
VALUES
  ('110020', 1, 1, 1, 1, 'moderate',     '中等风险'),   -- 易方达沪深300ETF联接A
  ('001594', 2, 1, 1, 1, 'moderate',     '中等风险'),   -- 天弘中证银行ETF联接A
  ('001595', 2, 1, 1, 1, 'moderate',     '中等风险'),   -- 天弘中证银行ETF联接C
  ('001631', 2, 2, 1, 1, 'aggressive',   '较高风险'),   -- 天弘中证食品饮料ETF联接A
  ('005223', 2, 2, 1, 1, 'aggressive',   '较高风险'),   -- 广发中证基建工程ETF联接A
  ('007817', 2, 3, 1, 1, 'aggressive',   '较高风险'),   -- 国泰中证全指通信设备ETF联接A
  ('007818', 2, 3, 1, 1, 'aggressive',   '较高风险'),   -- 国泰中证全指通信设备ETF联接C
  ('000071', 1, 2, 3, 1, 'aggressive',   '较高风险'),   -- 华夏恒生ETF联接A (QDII)
  ('006381', 1, 2, 3, 1, 'aggressive',   '较高风险'),   -- 华夏恒生ETF联接C (QDII)
  ('110031', 1, 1, 3, 1, 'aggressive',   '较高风险'),   -- 易方达恒生国企ETF联接A (QDII)
  ('005675', 1, 1, 3, 1, 'aggressive',   '较高风险'),   -- 易方达恒生国企ETF联接C (QDII)
  ('161831', 1, 2, 3, 1, 'aggressive',   '较高风险'),   -- 银华恒生中国企业ETF联接 (QDII)
  ('011608', 3, 3, 1, 3, 'speculative',  '高风险'),     -- 易方达科创50ETF联接A
  ('011609', 3, 3, 1, 3, 'speculative',  '高风险'),     -- 易方达科创50ETF联接C
  ('003765', 3, 3, 1, 3, 'speculative',  '高风险'),     -- 广发创业板ETF联接A
  ('003766', 3, 3, 1, 3, 'speculative',  '高风险'),     -- 广发创业板ETF联接C
  ('011102', 3, 3, 1, 1, 'speculative',  '高风险'),     -- 天弘中证光伏ETF联接A
  ('011103', 3, 3, 1, 1, 'speculative',  '高风险'),     -- 天弘中证光伏ETF联接C
  ('009067', 3, 3, 1, 1, 'speculative',  '高风险'),     -- 国泰中证新能源汽车ETF联接A
  ('009068', 3, 3, 1, 1, 'speculative',  '高风险')      -- 国泰中证新能源汽车ETF联接C
ON CONFLICT (fund_code) DO UPDATE SET
  breadth_score = EXCLUDED.breadth_score,
  volatility_score = EXCLUDED.volatility_score,
  market_score = EXCLUDED.market_score,
  board_score = EXCLUDED.board_score,
  risk_level = EXCLUDED.risk_level,
  risk_label = EXCLUDED.risk_label,
  updated_at = now();
