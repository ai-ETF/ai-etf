-- ============================================================================
-- public.trade_flow 表
-- ============================================================================

BEGIN;

CREATE TABLE public.trade_flow (
    id          uuid          NOT NULL DEFAULT gen_random_uuid(),
    user_id     uuid          NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,
    fund_code   varchar(10)   NOT NULL
        REFERENCES public.fund(fund_code) ON DELETE RESTRICT,
    fund_name   varchar(100)  NOT NULL DEFAULT ''::character varying,
    direction   varchar(4)    NOT NULL,
    price       numeric(18,4) NOT NULL,
    quantity    numeric(18,2) NOT NULL,
    amount      numeric(18,2) NOT NULL,
    fee         numeric(18,2) NOT NULL DEFAULT 0,
    trade_pnl   numeric(18,2),  -- 本笔实现的盈亏，赎回时写
    trade_time  timestamptz   NOT NULL DEFAULT now(),
    order_id    uuid
        REFERENCES public.trade_orders(id) ON DELETE SET NULL,

    CONSTRAINT trade_flow_pkey PRIMARY KEY (id),
    CONSTRAINT trade_flow_direction_check
        CHECK (direction IN ('buy','sell')),
    CONSTRAINT trade_flow_price_check
        CHECK (price > 0),
    CONSTRAINT trade_flow_quantity_check
        CHECK (quantity > 0),
    CONSTRAINT trade_flow_amount_check
        CHECK (amount >= 0),
    CONSTRAINT trade_flow_fee_check
        CHECK (fee >= 0)
);

CREATE UNIQUE INDEX uq_trade_flow_order
    ON public.trade_flow (order_id)
    WHERE order_id IS NOT NULL;
CREATE INDEX idx_trade_flow_user      ON public.trade_flow (user_id);
CREATE INDEX idx_trade_flow_code      ON public.trade_flow (fund_code);
CREATE INDEX idx_trade_flow_user_time ON public.trade_flow (user_id, trade_time DESC);

COMMENT ON TABLE public.trade_flow IS
'交易流水（成交明细）。记录每笔基金成交的净值、份额、金额、费用与已实现盈亏。';

COMMENT ON COLUMN public.trade_flow.id IS
'流水唯一标识，UUID 主键。';

COMMENT ON COLUMN public.trade_flow.user_id IS
'所属用户 ID，关联 auth.users.id，ON DELETE CASCADE。';

COMMENT ON COLUMN public.trade_flow.fund_code IS
'基金代码，关联 public.fund.fund_code，ON DELETE RESTRICT。';

COMMENT ON COLUMN public.trade_flow.fund_name IS
'成交时的基金名称。';

COMMENT ON COLUMN public.trade_flow.direction IS
'成交方向：buy 申购、sell 赎回。';

COMMENT ON COLUMN public.trade_flow.price IS
'成交单位净值。';

COMMENT ON COLUMN public.trade_flow.quantity IS
'成交份额。';

COMMENT ON COLUMN public.trade_flow.amount IS
'成交总额，单位：元。';

COMMENT ON COLUMN public.trade_flow.fee IS
'手续费，单位：元。';

COMMENT ON COLUMN public.trade_flow.trade_pnl IS
'本笔已实现盈亏，单位：元；按 FIFO 成本计算，赎回时记录。';

COMMENT ON COLUMN public.trade_flow.trade_time IS
'成交时间。';

COMMENT ON COLUMN public.trade_flow.order_id IS
'来源订单，关联 public.trade_orders.id；订单清除后置 NULL，一条订单最多一条流水。';

COMMIT;
