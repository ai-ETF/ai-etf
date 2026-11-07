-- ============================================================================
-- public.accounts 表
-- ============================================================================

BEGIN;

-- 1) 删表重建
DROP TABLE IF EXISTS public.accounts;

-- 2) 表结构
CREATE TABLE public.accounts (
    id                    uuid          NOT NULL DEFAULT gen_random_uuid(),
    user_id               uuid          NOT NULL,
    cash                  numeric(18,4) NOT NULL DEFAULT 100000.0000,
    frozen_cash           numeric(18,4) NOT NULL DEFAULT 0.0000,
    settling_cash         numeric(18,4) NOT NULL DEFAULT 0.0000,
    position_value        numeric(18,4) NOT NULL DEFAULT 0.0000,
    auto_invest_enabled   boolean       NOT NULL DEFAULT false,
    auto_invest_reserve   numeric(18,4) NOT NULL DEFAULT 0.0000,
    created_at            timestamptz   NOT NULL DEFAULT now(),
    updated_at            timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT accounts_pkey PRIMARY KEY (id),
    CONSTRAINT accounts_user_id_key UNIQUE (user_id),

    CONSTRAINT accounts_cash_nonnegative
        CHECK (cash >= 0),
    CONSTRAINT accounts_frozen_nonnegative
        CHECK (frozen_cash >= 0),
    CONSTRAINT accounts_settling_nonnegative
        CHECK (settling_cash >= 0),
    CONSTRAINT accounts_position_value_nonnegative
        CHECK (position_value >= 0),
    CONSTRAINT accounts_auto_invest_reserve_nonnegative
        CHECK (auto_invest_reserve >= 0),

    CONSTRAINT accounts_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE
);

-- 3) 权限：重建会被 Supabase default privileges 重新 GRANT ALL 给三个角色，
--    须显式收口到 service_role（后端唯一写入方）。
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.accounts FROM PUBLIC, anon, authenticated;
GRANT  ALL ON TABLE public.accounts TO service_role;

-- 4) updated_at 由 DB 统一维护
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_accounts_set_updated_at
    BEFORE UPDATE ON public.accounts
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

REVOKE ALL    ON FUNCTION public.set_updated_at() FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.set_updated_at() TO service_role;

-- 5) 新用户注册自动建账户（发放初始资金）
--    触发器挂在 auth.users（Supabase Auth 系统表）AFTER INSERT；函数以 SECURITY DEFINER
--    以 postgres 身份写 public.accounts，绕过 RLS。执行本迁移需对 auth.users 有 TRIGGER 权限。
--    初始资金不在函数里硬编码：只 INSERT (user_id)，由 cash 的列默认值发放。
--    业务常量共 3 处（列默认值、portfolio_service.INITIAL_CASH、
--    account_snapshot_service.INITIAL_CASH），调整初始资金须同步。
--    ON CONFLICT DO NOTHING 保证幂等（批量导入 / 重建均安全）。
--    本触发器是账户创建的唯一入口：下单链路（place_purchase_order 的
--    IF NOT FOUND THEN INSERT 分支）与 portfolio_service._ensure_account 的懒创建
--    在整体改造时删除，账户必然已存在，下单只需 SELECT ... FOR UPDATE；
--    账户不存在应抛业务异常，不再兜底建账户。
--    生命周期闭环：注册建账户 ↔ accounts_user_id_fkey ON DELETE CASCADE 注销清账户。
CREATE OR REPLACE FUNCTION public.provision_account_for_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.accounts (user_id) VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_auth_users_provision_account
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.provision_account_for_new_user();

REVOKE ALL    ON FUNCTION public.provision_account_for_new_user() FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.provision_account_for_new_user() TO service_role;

-- 6) 注释
COMMENT ON TABLE public.accounts IS
'用户账户主表。一个 auth.users 用户对应一行，完整表达当前资产状态：可用现金 cash、冻结资金 frozen_cash、在途赎回款 settling_cash、持仓估值 position_value，四者之和为总资产。全部金额保留 4 位小数。';

COMMENT ON COLUMN public.accounts.id IS
'账户代理主键，UUID。';

COMMENT ON COLUMN public.accounts.user_id IS
'所属用户 ID，关联 auth.users.id，ON DELETE CASCADE；UNIQUE 保证一用户一账户。';

COMMENT ON COLUMN public.accounts.cash IS
'可用现金余额，单位：元。DEFAULT 100000.0000 为初始资金，由注册触发器 trg_auth_users_provision_account 在 auth.users 插入时建账户并按本列默认值发放。CHECK >= 0。';

COMMENT ON COLUMN public.accounts.frozen_cash IS
'冻结资金余额，单位：元。pending 买单受理时由 cash 划入，确认或撤单时释放。计算口径：Σ 当前处于冻结状态的买入订单金额。CHECK >= 0。';

COMMENT ON COLUMN public.accounts.settling_cash IS
'在途赎回资金余额，单位：元。赎回已确认、份额已扣减但款项未到账的部分。计算口径：Σ trade_orders.net_amount（direction=sell AND status=settling）。CHECK >= 0。';

COMMENT ON COLUMN public.accounts.position_value IS
'当前基金持仓总估值，单位：元。计算口径：Σ(positions.quantity × 对应基金估值净值)，货基按净值 1.0000；含 pending 卖单未扣减份额，不含 pending 买单未建仓份额。CHECK >= 0。';

COMMENT ON COLUMN public.accounts.auto_invest_enabled IS
'余额自动理财开关。';

COMMENT ON COLUMN public.accounts.auto_invest_reserve IS
'余额自动理财预留现金，单位：元，numeric(18,4)（与其余金额统一 4 位）。启用时账户保留不参与自动申购的金额。CHECK >= 0。';

COMMENT ON COLUMN public.accounts.created_at IS
'账户首次初始化时间，NOT NULL，默认 now()。';

COMMENT ON COLUMN public.accounts.updated_at IS
'账户最后更新时间，NOT NULL，由触发器 trg_accounts_set_updated_at 在每次 UPDATE 时置为 now()，应用层无需再传。';

COMMIT;
