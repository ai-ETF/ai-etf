-- ============================================================================
-- 订单确认重写 · B1：增量 schema
--
-- 设计来源：docs/20-设计/基金与交易/订单确认-数据结构.md §3.3
-- 原则：
--   1. 只加不删；不改基线、不改已 push 的迁移
--   2. 所有 CHECK 先 NOT VALID，存量盘点通过后再单独 VALIDATE
--   3. 本文件只改结构，不含任何用户业务数据（交易/持仓/聊天）
--   4. 状态迁移触发器（§3.3.7）不在此文件，等新 Runner 灰度稳定后单独上线
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. trade_orders：新增列
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."trade_orders"
  ADD COLUMN IF NOT EXISTS "accepted_date"      "date",
  ADD COLUMN IF NOT EXISTS "settle_date"        "date",
  ADD COLUMN IF NOT EXISTS "net_amount"         numeric(18,2),
  ADD COLUMN IF NOT EXISTS "estimated_nav"      numeric(18,4),
  ADD COLUMN IF NOT EXISTS "fee_rule_snapshot"  "jsonb",
  ADD COLUMN IF NOT EXISTS "available_date"     "date",
  ADD COLUMN IF NOT EXISTS "processing_at"      timestamp with time zone,
  ADD COLUMN IF NOT EXISTS "processing_by"      "text",
  ADD COLUMN IF NOT EXISTS "attempt_count"      integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS "last_attempt_at"    timestamp with time zone,
  ADD COLUMN IF NOT EXISTS "last_error_code"    "text",
  ADD COLUMN IF NOT EXISTS "last_error_message" "text",
  ADD COLUMN IF NOT EXISTS "processed_at"       timestamp with time zone,
  ADD COLUMN IF NOT EXISTS "settled_at"         timestamp with time zone,
  ADD COLUMN IF NOT EXISTS "client_order_id"    "text";

COMMENT ON COLUMN "public"."trade_orders"."accepted_date"      IS '受理日 T（15:00 前为当日，否则下一交易日）；买卖双方的成交净值日';
COMMENT ON COLUMN "public"."trade_orders"."settle_date"        IS '赎回到账日 = T + redeem_settle_delay 个交易日';
COMMENT ON COLUMN "public"."trade_orders"."net_amount"         IS '净额：买 = amount - fee；卖 = amount - fee（应收）';
COMMENT ON COLUMN "public"."trade_orders"."estimated_nav"      IS '下单时的预估净值，仅展示，不参与确认取价';
COMMENT ON COLUMN "public"."trade_orders"."fee_rule_snapshot"  IS '下单时的费率/周期快照，确认时只读它，不再查 fund_catalog';
COMMENT ON COLUMN "public"."trade_orders"."available_date"     IS '买单份额可赎回日 = confirm_date + redeem_available_delay 个交易日';
COMMENT ON COLUMN "public"."trade_orders"."processing_at"      IS '认领时间（租约起点）';
COMMENT ON COLUMN "public"."trade_orders"."processing_by"      IS '认领 worker 标识 hostname:pid:run_id';
COMMENT ON COLUMN "public"."trade_orders"."attempt_count"      IS '确认尝试次数；净值类跳过不计次';
COMMENT ON COLUMN "public"."trade_orders"."last_error_code"    IS '最近一次错误码，见 §3.11 错误分类';
COMMENT ON COLUMN "public"."trade_orders"."processed_at"       IS '实际确认时间（审计），不等于成交净值日';
COMMENT ON COLUMN "public"."trade_orders"."settled_at"         IS '实际到账时间';
COMMENT ON COLUMN "public"."trade_orders"."client_order_id"    IS '调用方幂等键，同一用户下唯一';

-- ----------------------------------------------------------------------------
-- 2. trade_orders：状态约束扩宽
--    status 原为 varchar(10)，manual_review 有 13 个字符，必须先扩宽。
--    先删 CHECK 再改类型，避免改类型时被旧约束卡住。
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."trade_orders" DROP CONSTRAINT IF EXISTS "trade_orders_status_check";
ALTER TABLE "public"."trade_orders" ALTER COLUMN "status" TYPE character varying(20);
ALTER TABLE "public"."trade_orders"
  ADD CONSTRAINT "trade_orders_status_check"
  CHECK ("status" IN ('pending','processing','completed','cancelled',
                      'rejected','reserved','settling','settled','manual_review'));

COMMENT ON COLUMN "public"."trade_orders"."status" IS
  '状态：pending-待确认, processing-确认中, completed-买入完成, settling-卖出待收款, settled-已收款, rejected-已拒绝, cancelled-已撤销, reserved-预约, manual_review-待人工';

-- ----------------------------------------------------------------------------
-- 3. trade_orders：索引
-- ----------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS "uq_trade_orders_client_order"
  ON "public"."trade_orders" ("user_id", "client_order_id")
  WHERE "client_order_id" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "idx_trade_orders_confirm_scan"
  ON "public"."trade_orders" ("confirm_date", "id")
  WHERE "status" = 'pending';

CREATE INDEX IF NOT EXISTS "idx_trade_orders_settle"
  ON "public"."trade_orders" ("settle_date", "id")
  WHERE "status" = 'settling';

CREATE INDEX IF NOT EXISTS "idx_trade_orders_processing"
  ON "public"."trade_orders" ("processing_at")
  WHERE "status" = 'processing';

CREATE INDEX IF NOT EXISTS "idx_trade_orders_manual"
  ON "public"."trade_orders" ("updated_at")
  WHERE "status" = 'manual_review';

-- 金额/份额非负：先 NOT VALID，盘点存量无脏数据后再 VALIDATE
ALTER TABLE "public"."trade_orders"
  ADD CONSTRAINT "trade_orders_amount_nonnegative" CHECK ("amount" >= 0) NOT VALID;
ALTER TABLE "public"."trade_orders"
  ADD CONSTRAINT "trade_orders_fee_nonnegative" CHECK ("fee" >= 0) NOT VALID;
ALTER TABLE "public"."trade_orders"
  ADD CONSTRAINT "trade_orders_quantity_nonnegative" CHECK ("quantity" >= 0) NOT VALID;

-- ----------------------------------------------------------------------------
-- 4. position_lots：持仓批次（FIFO 的事实来源）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS "public"."position_lots" (
  "id"              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "order_id"        uuid REFERENCES "public"."trade_orders"("id") ON DELETE RESTRICT,
  "user_id"         uuid NOT NULL,
  "fund_code"       character varying(10) NOT NULL,
  "fund_name"       character varying(100) NOT NULL DEFAULT '',
  "source"          "text" NOT NULL CHECK ("source" IN ('order','initial','income')),
  "source_ref"      "text",
  "nav_date"        "date" NOT NULL,
  "available_date"  "date",
  "quantity"        numeric(18,2) NOT NULL CHECK ("quantity" > 0),
  "remaining_qty"   numeric(18,2) NOT NULL
                    CHECK ("remaining_qty" >= 0 AND "remaining_qty" <= "quantity"),
  "cost_price"      numeric(18,4) NOT NULL CHECK ("cost_price" >= 0),
  "remaining_cost"  numeric(18,2) NOT NULL CHECK ("remaining_cost" >= 0),
  "created_at"      timestamp with time zone NOT NULL DEFAULT now(),
  "updated_at"      timestamp with time zone NOT NULL DEFAULT now()
);

COMMENT ON TABLE  "public"."position_lots" IS '持仓批次：一笔买入/期初/货基收益形成一个 lot，FIFO 与持有期的事实来源';
COMMENT ON COLUMN "public"."position_lots"."nav_date"       IS '成交净值日：买单 = trade_orders.accepted_date(受理日 T)；期初 = positions.confirm_date 近似；收益 = 入账日';
COMMENT ON COLUMN "public"."position_lots"."source"         IS 'order-订单确认, initial-存量迁移, income-货基收益复投';
COMMENT ON COLUMN "public"."position_lots"."source_ref"     IS '幂等键：initial 固定 initial；income 为入账日 ISO';
COMMENT ON COLUMN "public"."position_lots"."remaining_cost" IS '剩余成本（净申购额，不含费）；货基为剩余本金';

-- 一笔订单最多一个 lot
CREATE UNIQUE INDEX IF NOT EXISTS "uq_position_lots_order"
  ON "public"."position_lots" ("order_id") WHERE "order_id" IS NOT NULL;
-- 期初/收益 lot 的幂等键（迁移脚本可重复执行）
CREATE UNIQUE INDEX IF NOT EXISTS "uq_position_lots_source"
  ON "public"."position_lots" ("user_id", "fund_code", "source", "source_ref")
  WHERE "source" <> 'order';
-- FIFO 扫描
CREATE INDEX IF NOT EXISTS "idx_position_lots_fifo"
  ON "public"."position_lots" ("user_id", "fund_code", "nav_date", "created_at", "id")
  WHERE "remaining_qty" > 0;

-- ----------------------------------------------------------------------------
-- 5. confirm_runs：确认批次审计 + 单飞
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS "public"."confirm_runs" (
  "run_id"          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "trigger_source"  "text" NOT NULL
                    CHECK ("trigger_source" IN ('sync','fallback','startup','manual')),
  "status"          "text" NOT NULL
                    CHECK ("status" IN ('running','succeeded','failed','skipped')),
  "worker"          "text" NOT NULL,
  "started_at"      timestamp with time zone NOT NULL DEFAULT now(),
  "heartbeat_at"    timestamp with time zone NOT NULL DEFAULT now(),
  "finished_at"     timestamp with time zone,
  "scanned"         integer NOT NULL DEFAULT 0,
  "confirmed"       integer NOT NULL DEFAULT 0,
  "rejected"        integer NOT NULL DEFAULT 0,
  "skipped_nav"     integer NOT NULL DEFAULT 0,
  "retryable"       integer NOT NULL DEFAULT 0,
  "manual_review"   integer NOT NULL DEFAULT 0,
  "settled"         integer NOT NULL DEFAULT 0,
  "error"           "text",
  "duration_ms"     integer
);

COMMENT ON TABLE "public"."confirm_runs" IS '订单确认批次审计；status=running 的部分唯一索引即单飞约束';

-- 单飞：同一时刻只允许一个 running
CREATE UNIQUE INDEX IF NOT EXISTS "uq_confirm_runs_running"
  ON "public"."confirm_runs" ("status") WHERE "status" = 'running';
CREATE INDEX IF NOT EXISTS "idx_confirm_runs_started"
  ON "public"."confirm_runs" ("started_at" DESC);

-- ----------------------------------------------------------------------------
-- 6. trade_flow.order_id：一笔订单只允许一条流水
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."trade_flow"
  ADD COLUMN IF NOT EXISTS "order_id" uuid REFERENCES "public"."trade_orders"("id");

COMMENT ON COLUMN "public"."trade_flow"."order_id" IS '来源订单；存量流水为 NULL（不回溯）';

CREATE UNIQUE INDEX IF NOT EXISTS "uq_trade_flow_order"
  ON "public"."trade_flow" ("order_id") WHERE "order_id" IS NOT NULL;

-- ----------------------------------------------------------------------------
-- 7. fund_trade_rule：可赎回延迟；同步到兼容视图（只能在末尾追加列）
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."fund_trade_rule"
  ADD COLUMN IF NOT EXISTS "redeem_available_delay" integer NOT NULL DEFAULT 2;

ALTER TABLE "public"."fund_trade_rule"
  DROP CONSTRAINT IF EXISTS "fund_trade_rule_redeem_available_delay_check";
ALTER TABLE "public"."fund_trade_rule"
  ADD CONSTRAINT "fund_trade_rule_redeem_available_delay_check"
  CHECK ("redeem_available_delay" >= 0);

COMMENT ON COLUMN "public"."fund_trade_rule"."redeem_available_delay" IS
  '份额确认后多少个交易日可赎回；默认 2（多数联接基金不额外锁 T+2，见订单确认设计 §7 U8）';

CREATE OR REPLACE VIEW "public"."fund_catalog"
WITH (security_invoker = true) AS
SELECT f."fund_code", f."fund_name", f."ftype", f."manager_company",
       f."fund_manager", f."tracking_index", f."tracking_index_code",
       f."establish_date", f."net_asset_scale", f."risk_level_code",
       f."is_qdii", f."qdii_reason", f."lifecycle_status",
       r."fund_type", r."share_class", r."min_purchase_amount",
       r."max_purchase_amount", r."subscribe_status", r."confirm_delay",
       r."redeem_settle_delay", r."management_fee_rate", r."custody_fee_rate",
       r."sales_service_fee_rate", r."commission_rate",
       r."purchase_fee_tiers", r."redemption_fee_tiers",
       r."redeem_available_delay"
FROM "public"."fund" f
JOIN "public"."fund_trade_rule" r ON r."fund_code" = f."fund_code"
WHERE f."lifecycle_status" = 'active';

-- ----------------------------------------------------------------------------
-- 8. accounts：非负约束（NOT VALID，盘点后再 VALIDATE）
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."accounts"
  DROP CONSTRAINT IF EXISTS "accounts_cash_nonnegative";
ALTER TABLE "public"."accounts"
  ADD CONSTRAINT "accounts_cash_nonnegative" CHECK ("cash" >= 0) NOT VALID;

ALTER TABLE "public"."accounts"
  DROP CONSTRAINT IF EXISTS "accounts_frozen_nonnegative";
ALTER TABLE "public"."accounts"
  ADD CONSTRAINT "accounts_frozen_nonnegative" CHECK ("frozen_cash" >= 0) NOT VALID;

-- ----------------------------------------------------------------------------
-- 9. 权限：新表只给 service_role
--    存量交易表给过 anon/authenticated 的 ALL 授权，但 RLS 已启用且无 policy，
--    实际只有 service_role 能读写；新表不再扩大授权面。
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."position_lots" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."confirm_runs"  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON "public"."position_lots" FROM "anon", "authenticated";
REVOKE ALL ON "public"."confirm_runs"  FROM "anon", "authenticated";

GRANT SELECT, INSERT, UPDATE, DELETE ON "public"."position_lots" TO "service_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON "public"."confirm_runs"  TO "service_role";
