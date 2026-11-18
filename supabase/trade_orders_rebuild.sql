-- ============================================================================
-- public.trade_orders 表：负责订单生命周期，只储存 1 year。
-- ============================================================================

BEGIN;

CREATE TABLE public.trade_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,
    client_order_id text NOT NULL,
    fund_code varchar(10) NOT NULL
        REFERENCES public.fund(fund_code) ON DELETE RESTRICT,
    fund_name_snapshot varchar(100) NOT NULL,
    direction varchar(4) NOT NULL,

    amount numeric(18,2),   -- 申请金额仅申请时填写
    quantity numeric(18,2), -- 赎回份额仅赎回时填写
    fee_rule_snapshot jsonb,

    effective_trade_date date NOT NULL,
    expected_confirm_date date,
    settle_date date,

    status varchar(20) NOT NULL DEFAULT 'pending',
    settled_at timestamptz,
    reject_reason text,
    cancelled_at timestamptz,
    cancel_reason text,
    cancelled_by text,

    attempt_count integer NOT NULL DEFAULT 0,
    processing_at timestamptz,
    processing_by text,
    last_attempt_at timestamptz,
    last_error_code text,
    last_error_message text,
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT chk_trade_orders_direction
        CHECK (direction IN ('buy','sell')),
    CONSTRAINT chk_trade_orders_status
        CHECK (status IN ('pending','processing','completed','settling',
                          'settled','cancelled','rejected','manual_review')),
    CONSTRAINT chk_trade_orders_application
        CHECK (
            (direction = 'buy'
             AND amount IS NOT NULL AND amount > 0
             AND quantity IS NULL
             AND settle_date IS NULL AND settled_at IS NULL)
            OR
            (direction = 'sell'
             AND quantity IS NOT NULL AND quantity > 0
             AND amount IS NULL
             AND settle_date IS NOT NULL)
        ),
    CONSTRAINT chk_trade_orders_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT chk_trade_orders_fee_rule_snapshot
        CHECK (fee_rule_snapshot IS NULL
               OR jsonb_typeof(fee_rule_snapshot) = 'object'),
    CONSTRAINT chk_trade_orders_settled_at
        CHECK (
            (status = 'settled' AND direction = 'sell'
             AND settled_at IS NOT NULL)
            OR
            (status <> 'settled' AND settled_at IS NULL)
        ),
    CONSTRAINT chk_trade_orders_cancelled_at
        CHECK (
            (status = 'cancelled' AND cancelled_at IS NOT NULL)
            OR (status <> 'cancelled' AND cancelled_at IS NULL)
        ),
    CONSTRAINT chk_trade_orders_reject_reason
        CHECK (
            (status = 'rejected' AND reject_reason IS NOT NULL)
            OR (status <> 'rejected' AND reject_reason IS NULL)
        )
);

CREATE UNIQUE INDEX uq_trade_orders_client_order
    ON public.trade_orders (user_id, client_order_id);
CREATE INDEX idx_trade_orders_user        ON public.trade_orders (user_id);
CREATE INDEX idx_trade_orders_fund_code   ON public.trade_orders (fund_code);
CREATE INDEX idx_trade_orders_confirm_scan
    ON public.trade_orders (expected_confirm_date, id) WHERE status = 'pending';
CREATE INDEX idx_trade_orders_processing
    ON public.trade_orders (processing_at) WHERE status = 'processing';
CREATE INDEX idx_trade_orders_settle
    ON public.trade_orders (settle_date, id) WHERE status = 'settling';
CREATE INDEX idx_trade_orders_manual
    ON public.trade_orders (updated_at) WHERE status = 'manual_review';

CREATE OR REPLACE TRIGGER trg_trade_orders_set_updated_at
    BEFORE UPDATE ON public.trade_orders
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

COMMENT ON TABLE public.trade_orders IS
'基金交易订单主表。记录申购与赎回订单的申请信息、基金确认结果、订单状态、后台处理与时间审计。';

COMMENT ON COLUMN public.trade_orders.id IS
'订单唯一标识，UUID 主键。';

COMMENT ON COLUMN public.trade_orders.user_id IS
'所属用户 ID，关联 auth.users.id，ON DELETE CASCADE。';

COMMENT ON COLUMN public.trade_orders.client_order_id IS
'调用方幂等键，必填；与 user_id 组成唯一约束，防止重复提交。';

COMMENT ON COLUMN public.trade_orders.fund_code IS
'基金代码，关联 public.fund.fund_code，ON DELETE RESTRICT。';

COMMENT ON COLUMN public.trade_orders.fund_name_snapshot IS
'下单时的基金名称快照，避免基金更名影响历史订单展示。';

COMMENT ON COLUMN public.trade_orders.direction IS
'订单方向：buy 申购、sell 赎回。';

COMMENT ON COLUMN public.trade_orders.amount IS
'申购申请金额，单位：元，仅申购订单填写。';

COMMENT ON COLUMN public.trade_orders.quantity IS
'赎回申请份额，仅赎回订单填写。';

COMMENT ON COLUMN public.trade_orders.fee_rule_snapshot IS
'下单时冻结的费率规则快照，JSON 对象。';

COMMENT ON COLUMN public.trade_orders.effective_trade_date IS
'订单生效交易日／净值计价日；15:00 前下单为 T，之后为 T+1。';

COMMENT ON COLUMN public.trade_orders.expected_confirm_date IS
'预计基金确认日期。';

COMMENT ON COLUMN public.trade_orders.settle_date IS
'预计赎回资金到账日期，仅赎回订单使用。';

COMMENT ON COLUMN public.trade_orders.status IS
'订单状态：pending 待确认、processing 确认中、completed 买入完成、settling 卖出待收款、settled 已到账、cancelled 已撤销、rejected 已拒单、manual_review 人工复核。';

COMMENT ON COLUMN public.trade_orders.settled_at IS
'赎回资金实际到账时间，仅赎回订单记录。';

COMMENT ON COLUMN public.trade_orders.reject_reason IS
'拒单原因。';

COMMENT ON COLUMN public.trade_orders.cancelled_at IS
'订单撤销时间。';

COMMENT ON COLUMN public.trade_orders.cancel_reason IS
'订单撤销原因。';

COMMENT ON COLUMN public.trade_orders.cancelled_by IS
'撤销操作人／来源标识。';

COMMENT ON COLUMN public.trade_orders.attempt_count IS
'后台处理尝试次数。';

COMMENT ON COLUMN public.trade_orders.processing_at IS
'当前认领开始时间，租约起点。';

COMMENT ON COLUMN public.trade_orders.processing_by IS
'当前租约持有者／Worker 标识。';

COMMENT ON COLUMN public.trade_orders.last_attempt_at IS
'最近一次处理尝试开始时间。';

COMMENT ON COLUMN public.trade_orders.last_error_code IS
'最近一次错误信息代码。';

COMMENT ON COLUMN public.trade_orders.last_error_message IS
'最近一次错误信息详情。';

COMMENT ON COLUMN public.trade_orders.processed_at IS
'最近一次后台处理成功完成的时间。';

COMMENT ON COLUMN public.trade_orders.created_at IS
'订单创建时间。';

COMMENT ON COLUMN public.trade_orders.updated_at IS
'订单最后更新时间，由触发器 trg_trade_orders_set_updated_at 在每次 UPDATE 时置为 now()。';

COMMIT;
