-- 20只 ETF 联接基金完整费率配置
-- 数据源：天天基金网 fundf10.eastmoney.com，截至 2026-08-04
-- 申购费率：互联网渠道（天天基金）1折后，支持金额分档
--   purchase_fee_tiers: JSON 金额分档，包含多档费率和固定费用
--     格式：[{"amount":金额分界点,"rate":费率,"fixed_fee":固定费用null,"inclusive":bool}]
--   purchase_fee_rate: 旧字段（回退值），保留但不作为主要计算来源
-- 赎回费率：严格按基金官方合同完整分档
--   redemption_fee_tiers: JSON 档位
--     格式：[{"days":天数,"rate":费率,"inclusive":bool}]
--     inclusive=false（默认）: hold_days < days 时命中
--     inclusive=true: hold_days <= days 或 hold_days >= days 时命中（最后一档）
-- 管理费/托管费：A/C 份额一致，每日净值内计提，申赎不单独收取
-- 销售服务费：A类=0，C类单独列出（每日净值内计提）
-- fund_type: of=场外开放式基金, etf=场内ETF
-- share_class: A=A类份额, C=C类份额
-- confirm_delay: A股联接=1(T+1), QDII=2(T+2)
-- redeem_settle_delay: A股联接=3(T+3), QDII=7(T+7)

INSERT INTO fund_fee_rules (fund_code, fund_name, fund_type, share_class, purchase_fee_rate, purchase_fee_tiers, redemption_fee_tiers, management_fee_rate, custody_fee_rate, sales_service_fee_rate, min_purchase_amount, confirm_delay, redeem_settle_delay)
VALUES
-- ========== 1. 易方达沪深300ETF联接A (110020) ==========
('110020', '易方达沪深300ETF联接A', 'of', 'A',
 0.0012,
 '[
   {"amount":1000000,"rate":0.0012},
   {"amount":5000000,"rate":0.0008},
   {"amount":10000000,"rate":0.0002},
   {"amount":10000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":365,"rate":0.0050},
   {"days":730,"rate":0.0025},
   {"days":730,"rate":0.0000,"inclusive":true}
 ]',
 0.0015, 0.0005, 0.0000, 10.00, 1, 3),

-- ========== 2. 天弘中证银行ETF联接A (001594) ==========
('001594', '天弘中证银行ETF联接A', 'of', 'A',
 0.0010,
 '[
   {"amount":5000000,"rate":0.0010},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0030},
   {"days":30,"rate":0.0005,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0000, 10.00, 1, 3),

-- ========== 3. 天弘中证食品饮料ETF联接A (001631) ==========
('001631', '天弘中证食品饮料ETF联接A', 'of', 'A',
 0.0010,
 '[
   {"amount":5000000,"rate":0.0010},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0030},
   {"days":30,"rate":0.0005,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0000, 10.00, 1, 3),

-- ========== 4. 广发中证基建工程ETF联接A (005223) ==========
('005223', '广发中证基建工程ETF联接A', 'of', 'A',
 0.0010,
 '[
   {"amount":500000,"rate":0.0010},
   {"amount":1000000,"rate":0.0007},
   {"amount":5000000,"rate":0.0005},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0010},
   {"days":30,"rate":0.0000,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0000, 10.00, 1, 3),

-- ========== 5. 国泰中证全指通信设备ETF联接A (007817) ==========
('007817', '国泰中证全指通信设备ETF联接A', 'of', 'A',
 0.0010,
 '[
   {"amount":500000,"rate":0.0010},
   {"amount":1000000,"rate":0.0006},
   {"amount":1000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0075},
   {"days":180,"rate":0.0050},
   {"days":180,"rate":0.0000,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0000, 1.00, 1, 3),

-- ========== 6. 天弘中证银行ETF联接C (001595) ==========
('001595', '天弘中证银行ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":7,"rate":0.0000,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0025, 10.00, 1, 3),

-- ========== 7. 国泰中证全指通信设备ETF联接C (007818) ==========
('007818', '国泰中证全指通信设备ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0010},
   {"days":30,"rate":0.0000,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0030, 10.00, 1, 3),

-- ========== 8. 易方达上证科创50联接A (011608) ==========
('011608', '易方达科创50ETF联接A', 'of', 'A',
 0.0006,
 '[
   {"amount":1000000,"rate":0.0006},
   {"amount":5000000,"rate":0.0003},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0050},
   {"days":180,"rate":0.0010},
   {"days":180,"rate":0.0000,"inclusive":true}
 ]',
 0.0015, 0.0005, 0.0000, 10.00, 1, 3),

-- ========== 9. 易方达上证科创50联接C (011609) ==========
('011609', '易方达科创50ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":7,"rate":0.0000,"inclusive":true}
 ]',
 0.0015, 0.0005, 0.0010, 10.00, 1, 3),

-- ========== 10. 广发创业板ETF联接A (003765) ==========
('003765', '广发创业板ETF联接A', 'of', 'A',
 0.0012,
 '[
   {"amount":1000000,"rate":0.0012},
   {"amount":5000000,"rate":0.0008},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":365,"rate":0.0050},
   {"days":730,"rate":0.0030},
   {"days":730,"rate":0.0000,"inclusive":true}
 ]',
 0.0015, 0.0005, 0.0000, 10.00, 1, 3),

-- ========== 11. 广发创业板ETF联接C (003766) ==========
('003766', '广发创业板ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.00125},
   {"days":30,"rate":0.0000,"inclusive":true}
 ]',
 0.0015, 0.0005, 0.0020, 10.00, 1, 3),

-- ========== 12. 华夏恒生ETF联接A (000071) QDII ==========
('000071', '华夏恒生ETF联接A', 'of', 'A',
 0.0012,
 '[
   {"amount":1000000,"rate":0.0012},
   {"amount":5000000,"rate":0.0009},
   {"amount":10000000,"rate":0.0006},
   {"amount":10000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":7,"rate":0.0050,"inclusive":true}
 ]',
 0.0060, 0.0015, 0.0000, 10.00, 2, 7),

-- ========== 13. 华夏恒生ETF联接C (006381) QDII ==========
('006381', '华夏恒生ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":7,"rate":0.0000,"inclusive":true}
 ]',
 0.0060, 0.0015, 0.0030, 10.00, 2, 7),

-- ========== 14. 易方达恒生国企ETF联接A (110031) QDII ==========
('110031', '易方达恒生国企ETF联接A', 'of', 'A',
 0.0012,
 '[
   {"amount":1000000,"rate":0.0012},
   {"amount":2000000,"rate":0.0008},
   {"amount":5000000,"rate":0.0005},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":365,"rate":0.0050},
   {"days":730,"rate":0.0025},
   {"days":730,"rate":0.0000,"inclusive":true}
 ]',
 0.0060, 0.0015, 0.0000, 10.00, 2, 7),

-- ========== 15. 易方达恒生国企ETF联接C (005675) QDII ==========
('005675', '易方达恒生国企ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":7,"rate":0.0000,"inclusive":true}
 ]',
 0.0060, 0.0015, 0.0025, 10.00, 2, 7),

-- ========== 16. 银华恒生中国企业ETF联接 (161831) QDII-LOF ==========
('161831', '银华恒生中国企业ETF联接', 'of', 'A',
 0.0012,
 '[
   {"amount":500000,"rate":0.0012},
   {"amount":1000000,"rate":0.0008},
   {"amount":5000000,"rate":0.0005},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":365,"rate":0.0050},
   {"days":730,"rate":0.0020},
   {"days":730,"rate":0.0000,"inclusive":true}
 ]',
 0.0100, 0.0020, 0.0000, 10.00, 2, 7),

-- ========== 17. 天弘中证光伏ETF联接A (011102) ==========
('011102', '天弘中证光伏ETF联接A', 'of', 'A',
 0.0010,
 '[
   {"amount":5000000,"rate":0.0010},
   {"amount":5000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0030},
   {"days":30,"rate":0.0005,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0000, 10.00, 1, 3),

-- ========== 18. 天弘中证光伏ETF联接C (011103) ==========
('011103', '天弘中证光伏ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":7,"rate":0.0000,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0020, 10.00, 1, 3),

-- ========== 19. 国泰中证新能源汽车ETF联接A (009067) ==========
('009067', '国泰中证新能源汽车ETF联接A', 'of', 'A',
 0.0010,
 '[
   {"amount":500000,"rate":0.0010},
   {"amount":1000000,"rate":0.0006},
   {"amount":1000000,"rate":0,"fixed_fee":1000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0075},
   {"days":180,"rate":0.0050},
   {"days":180,"rate":0.0000,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0000, 1.00, 1, 3),

-- ========== 20. 国泰中证新能源汽车ETF联接C (009068) ==========
('009068', '国泰中证新能源汽车ETF联接C', 'of', 'C',
 0.0000,
 '[
   {"amount":999999999,"rate":0.0000,"inclusive":true}
 ]',
 '[
   {"days":7,"rate":0.0150},
   {"days":30,"rate":0.0010},
   {"days":30,"rate":0.0000,"inclusive":true}
 ]',
 0.0050, 0.0010, 0.0030, 10.00, 1, 3)

ON CONFLICT (fund_code) DO UPDATE SET
  fund_name = EXCLUDED.fund_name,
  fund_type = EXCLUDED.fund_type,
  share_class = EXCLUDED.share_class,
  purchase_fee_rate = EXCLUDED.purchase_fee_rate,
  purchase_fee_tiers = EXCLUDED.purchase_fee_tiers,
  redemption_fee_tiers = EXCLUDED.redemption_fee_tiers,
  management_fee_rate = EXCLUDED.management_fee_rate,
  custody_fee_rate = EXCLUDED.custody_fee_rate,
  sales_service_fee_rate = EXCLUDED.sales_service_fee_rate,
  min_purchase_amount = EXCLUDED.min_purchase_amount,
  confirm_delay = EXCLUDED.confirm_delay,
  redeem_settle_delay = EXCLUDED.redeem_settle_delay,
  updated_at = NOW();
