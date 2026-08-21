-- 基金四维风险评分 + 风险等级 数据填充
-- 前置条件：已执行 alter_fund_fee_rules_risk_level.sql（列已添加）
-- 见 docs/基金风险等级划分设计文档.md
--
-- 维度说明：
--   breadth_score:    指数广度 (1=宽基跨行业, 2=单一行业, 3=窄基主题)
--   volatility_score: 波动属性 (1=大盘价值/防御, 2=消费/周期, 3=高成长/TMT/新能源)
--   market_score:     市场属性 (1=纯A股, 3=QDII跨境)
--   board_score:      板块特征 (1=主板为主, 3=科创/创业板)
--   risk_level:       风险等级 (moderate/aggressive/speculative)
--
-- 总分→等级映射：4-5=moderate, 6-7=aggressive, 8-12=speculative

UPDATE fund_fee_rules SET breadth_score=1, volatility_score=1, market_score=1, board_score=1, risk_level='moderate'     WHERE fund_code='110020';  -- 易方达沪深300ETF联接A
UPDATE fund_fee_rules SET breadth_score=2, volatility_score=1, market_score=1, board_score=1, risk_level='moderate'     WHERE fund_code='001594';  -- 天弘中证银行ETF联接A
UPDATE fund_fee_rules SET breadth_score=2, volatility_score=1, market_score=1, board_score=1, risk_level='moderate'     WHERE fund_code='001595';  -- 天弘中证银行ETF联接C
UPDATE fund_fee_rules SET breadth_score=2, volatility_score=2, market_score=1, board_score=1, risk_level='aggressive'   WHERE fund_code='001631';  -- 天弘中证食品饮料ETF联接A
UPDATE fund_fee_rules SET breadth_score=2, volatility_score=2, market_score=1, board_score=1, risk_level='aggressive'   WHERE fund_code='005223';  -- 广发中证基建工程ETF联接A
UPDATE fund_fee_rules SET breadth_score=2, volatility_score=3, market_score=1, board_score=1, risk_level='aggressive'   WHERE fund_code='007817';  -- 国泰中证全指通信设备ETF联接A
UPDATE fund_fee_rules SET breadth_score=2, volatility_score=3, market_score=1, board_score=1, risk_level='aggressive'   WHERE fund_code='007818';  -- 国泰中证全指通信设备ETF联接C
UPDATE fund_fee_rules SET breadth_score=1, volatility_score=2, market_score=3, board_score=1, risk_level='aggressive'   WHERE fund_code='000071';  -- 华夏恒生ETF联接A (QDII)
UPDATE fund_fee_rules SET breadth_score=1, volatility_score=2, market_score=3, board_score=1, risk_level='aggressive'   WHERE fund_code='006381';  -- 华夏恒生ETF联接C (QDII)
UPDATE fund_fee_rules SET breadth_score=1, volatility_score=1, market_score=3, board_score=1, risk_level='aggressive'   WHERE fund_code='110031';  -- 易方达恒生国企ETF联接A (QDII)
UPDATE fund_fee_rules SET breadth_score=1, volatility_score=1, market_score=3, board_score=1, risk_level='aggressive'   WHERE fund_code='005675';  -- 易方达恒生国企ETF联接C (QDII)
UPDATE fund_fee_rules SET breadth_score=1, volatility_score=2, market_score=3, board_score=1, risk_level='aggressive'   WHERE fund_code='161831';  -- 银华恒生中国企业ETF联接 (QDII)
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=3, risk_level='speculative'  WHERE fund_code='011608';  -- 易方达科创50ETF联接A
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=3, risk_level='speculative'  WHERE fund_code='011609';  -- 易方达科创50ETF联接C
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=3, risk_level='speculative'  WHERE fund_code='003765';  -- 广发创业板ETF联接A
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=3, risk_level='speculative'  WHERE fund_code='003766';  -- 广发创业板ETF联接C
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=1, risk_level='speculative'  WHERE fund_code='011102';  -- 天弘中证光伏ETF联接A
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=1, risk_level='speculative'  WHERE fund_code='011103';  -- 天弘中证光伏ETF联接C
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=1, risk_level='speculative'  WHERE fund_code='009067';  -- 国泰中证新能源汽车ETF联接A
UPDATE fund_fee_rules SET breadth_score=3, volatility_score=3, market_score=1, board_score=1, risk_level='speculative'  WHERE fund_code='009068';  -- 国泰中证新能源汽车ETF联接C
