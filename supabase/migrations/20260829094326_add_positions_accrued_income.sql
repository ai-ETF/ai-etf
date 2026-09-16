-- 持仓表新增 accrued_income：货币基金累计收益（元）
-- 真实货基收益机制：净值恒 1.0000，每日按「万份收益」计息并复投。
-- 本系统模拟为：收益累加到本列（份额不增加），持仓市值 = 本金份额 + 累计收益。
-- 非货基持仓该列恒为 0（仅货基由 credit_money_fund_income 每日累加、赎回时按比例兑付核减）。
ALTER TABLE public.positions
  ADD COLUMN accrued_income numeric NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.positions.accrued_income IS '货币基金累计收益（元），非货基持仓恒为0；由每日万份收益入账累加';
