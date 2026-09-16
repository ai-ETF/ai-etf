-- 货基改为真实复投：份额(quantity) 逐日增长，本金独立记录在 principal。
-- 背景：上一版用 accrued_income 列单独累计收益（份额不变，单利）。
-- 真实货基净值恒 1.0000，每日万份收益按净值 1.0 折算成份额加进去（复投），份额逐日增长。
-- 本迁移：
--   1. 新增 principal（累计投入本金，元）
--   2. 回填货基持仓：本金=份额×成本价；份额折算到 NAV 1.0 并并入已累计收益；成本价归 1.0
--      公式说明：旧口径下 市值=份额×成本价+已累计收益（accrued_income）。
--                新口径 NAV=1.0，市值=份额，故 新份额=份额×成本价+accrued_income。
--   3. 删除 accrued_income（已被 quantity 取代，不再需要）
-- 非货基持仓 principal 恒为 0（仅货基申购/赎回/每日收益维护该列）。

-- 1. 新增本金列
ALTER TABLE public.positions ADD COLUMN principal numeric(18,2) NOT NULL DEFAULT 0;
COMMENT ON COLUMN public.positions.principal IS '货基累计投入本金（元）；非货基持仓恒为0，由申购累加、赎回按比例核减';

-- 2. 回填货基持仓
UPDATE public.positions
   SET principal  = ROUND(quantity * cost_price, 2),
       quantity   = ROUND(quantity * cost_price + COALESCE(accrued_income, 0), 2),
       cost_price = 1.0000
 WHERE fund_code = '000198';

-- 3. 删除 accrued_income（已被 quantity 取代）
ALTER TABLE public.positions DROP COLUMN accrued_income;
