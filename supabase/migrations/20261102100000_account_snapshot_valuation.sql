-- ============================================================================
-- 账户日终估值与快照：补全分项 + 有效性/来源/审计字段
--
-- 设计来源：docs/20-设计/基金与交易/账户日终估值与快照.md
-- 原则：
--   1. 只加不删；不改基线、不改已 push 的迁移
--   2. 旧快照统一标 legacy，不参与新口径的日收益
--   3. 新增列先带默认值回填存量，再删掉 status/source 的默认值，强制新写入显式给值
-- ============================================================================

ALTER TABLE public.account_snapshots
  ADD COLUMN IF NOT EXISTS frozen_cash numeric(18,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'legacy',
  ADD COLUMN IF NOT EXISTS invalid_reason text,
  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'legacy',
  ADD COLUMN IF NOT EXISTS position_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS valuation_at timestamptz,
  ADD COLUMN IF NOT EXISTS nav_coverage jsonb,
  ADD COLUMN IF NOT EXISTS money_fund_income_date date;

COMMENT ON COLUMN public.account_snapshots.frozen_cash
  IS '快照日冻结资金（pending 买单锁定），总资产分项之一';
COMMENT ON COLUMN public.account_snapshots.status
  IS '快照状态：valid-有效（参与日收益）, invalid-无效（缺净值等）, legacy-上线前旧口径';
COMMENT ON COLUMN public.account_snapshots.invalid_reason
  IS '无效原因，多条用 "; " 分隔';
COMMENT ON COLUMN public.account_snapshots.source
  IS '快照来源：scheduled-每日任务, manual-手动入口, backfill-回补, legacy-上线前旧口径';
COMMENT ON COLUMN public.account_snapshots.position_count
  IS '快照时的持仓只数（quantity > 0）';
COMMENT ON COLUMN public.account_snapshots.valuation_at
  IS '实际完成估值的时刻（可能晚于 snapshot_date）';
COMMENT ON COLUMN public.account_snapshots.nav_coverage
  IS '每只持仓的估值明细：fund_code/quantity/nav_date/unit_nav/value';
COMMENT ON COLUMN public.account_snapshots.money_fund_income_date
  IS '本次估值包含到的货基收益日；T 日收益 lot 未入账时为空';

ALTER TABLE public.account_snapshots
  DROP CONSTRAINT IF EXISTS account_snapshots_status_check;
ALTER TABLE public.account_snapshots
  ADD CONSTRAINT account_snapshots_status_check
  CHECK (status IN ('valid', 'invalid', 'legacy'));

ALTER TABLE public.account_snapshots
  DROP CONSTRAINT IF EXISTS account_snapshots_source_check;
ALTER TABLE public.account_snapshots
  ADD CONSTRAINT account_snapshots_source_check
  CHECK (source IN ('scheduled', 'manual', 'backfill', 'legacy'));

-- 存量行已由 ADD COLUMN 的默认值标为 legacy；这里再显式落一次，保证迁移可重复执行。
UPDATE public.account_snapshots
   SET status = 'legacy', source = 'legacy'
 WHERE status = 'legacy' AND source = 'legacy';

-- 之后的新写入必须显式给出 status/source，避免默认值掩盖漏传。
ALTER TABLE public.account_snapshots
  ALTER COLUMN status DROP DEFAULT,
  ALTER COLUMN source DROP DEFAULT;

CREATE INDEX IF NOT EXISTS idx_snapshots_user_status_date
  ON public.account_snapshots (user_id, status, snapshot_date DESC);
