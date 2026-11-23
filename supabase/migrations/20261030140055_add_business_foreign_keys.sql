-- ============================================================================
-- 交易 / 持仓 / 资金表补外键
--
-- 背景：
--   accounts / account_snapshots / positions / position_lots / trade_orders /
--   trade_flow / watchlist 一直没有 user_id 外键，交易表也没有 fund_code 外键。
--   结果是：注销漏表会留下孤儿数据；下单可以引用不存在的基金；误删基金不会报错。
--
-- 删除策略：
--   - user_id -> auth.users(id) ON DELETE CASCADE
--     删除 auth 用户时自动清理该用户的交易数据，避免 purge 漏表留下孤儿。
--   - fund_code -> fund(fund_code) ON DELETE RESTRICT
--     基金走 lifecycle_status='removed' 软删除；有交易历史的基金不允许硬删除。
--     watchlist 不建 fund_code 外键：自选允许关注任意代码（线上已有 5 条 588xxx/159558
--     等未入 fund 主数据的 ETF），且 watchlist 自带 fund_name、展示不依赖 fund 表。
--
-- 级联链一致性：
--   为了让 user_id CASCADE 能顺利删除订单，position_lots.order_id 和
--   trade_flow.order_id 一起改为 ON DELETE CASCADE；否则级联顺序可能被
--   RESTRICT / NO ACTION 挡住，出现“有时能删、有时报错”。
--
-- 执行前提：
--   存量必须先没有孤儿。本迁移按“先 NOT VALID，再 VALIDATE”执行；若某个
--   环境存在孤儿，VALIDATE 会失败并整体回滚，先修数据后再重跑。
--   本地执行时相关表均为 0 行。
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. 订单 → 流水 / 持仓批次：统一为 CASCADE
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."position_lots"
  DROP CONSTRAINT IF EXISTS "position_lots_order_id_fkey";
ALTER TABLE "public"."position_lots"
  ADD CONSTRAINT "position_lots_order_id_fkey"
  FOREIGN KEY ("order_id") REFERENCES "public"."trade_orders"("id")
  ON DELETE CASCADE NOT VALID;

ALTER TABLE "public"."trade_flow"
  DROP CONSTRAINT IF EXISTS "trade_flow_order_id_fkey";
ALTER TABLE "public"."trade_flow"
  ADD CONSTRAINT "trade_flow_order_id_fkey"
  FOREIGN KEY ("order_id") REFERENCES "public"."trade_orders"("id")
  ON DELETE CASCADE NOT VALID;

-- ----------------------------------------------------------------------------
-- 2. user_id -> auth.users(id)：注销自动清理
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."accounts"
  ADD CONSTRAINT "accounts_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id")
  ON DELETE CASCADE NOT VALID;

ALTER TABLE "public"."account_snapshots"
  ADD CONSTRAINT "account_snapshots_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id")
  ON DELETE CASCADE NOT VALID;

ALTER TABLE "public"."positions"
  ADD CONSTRAINT "positions_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id")
  ON DELETE CASCADE NOT VALID;

ALTER TABLE "public"."position_lots"
  ADD CONSTRAINT "position_lots_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id")
  ON DELETE CASCADE NOT VALID;

ALTER TABLE "public"."trade_orders"
  ADD CONSTRAINT "trade_orders_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id")
  ON DELETE CASCADE NOT VALID;

ALTER TABLE "public"."trade_flow"
  ADD CONSTRAINT "trade_flow_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id")
  ON DELETE CASCADE NOT VALID;

ALTER TABLE "public"."watchlist"
  ADD CONSTRAINT "watchlist_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id")
  ON DELETE CASCADE NOT VALID;

-- ----------------------------------------------------------------------------
-- 3. fund_code -> fund(fund_code)：保护交易历史
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."positions"
  ADD CONSTRAINT "positions_fund_code_fkey"
  FOREIGN KEY ("fund_code") REFERENCES "public"."fund"("fund_code")
  ON DELETE RESTRICT NOT VALID;

ALTER TABLE "public"."position_lots"
  ADD CONSTRAINT "position_lots_fund_code_fkey"
  FOREIGN KEY ("fund_code") REFERENCES "public"."fund"("fund_code")
  ON DELETE RESTRICT NOT VALID;

ALTER TABLE "public"."trade_orders"
  ADD CONSTRAINT "trade_orders_fund_code_fkey"
  FOREIGN KEY ("fund_code") REFERENCES "public"."fund"("fund_code")
  ON DELETE RESTRICT NOT VALID;

ALTER TABLE "public"."trade_flow"
  ADD CONSTRAINT "trade_flow_fund_code_fkey"
  FOREIGN KEY ("fund_code") REFERENCES "public"."fund"("fund_code")
  ON DELETE RESTRICT NOT VALID;

-- ----------------------------------------------------------------------------
-- 4. 子表索引
--    Postgres 不会为外键自动建子表索引；父表删除时若没有索引会全表扫。
--    position_lots 现有的 FIFO 索引带 remaining_qty > 0 条件，不能用于外键检查，
--    因此额外补完整索引。
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS "idx_trade_orders_fund_code"
  ON "public"."trade_orders" ("fund_code");

CREATE INDEX IF NOT EXISTS "idx_position_lots_user_id"
  ON "public"."position_lots" ("user_id");

CREATE INDEX IF NOT EXISTS "idx_position_lots_fund_code"
  ON "public"."position_lots" ("fund_code");

-- ----------------------------------------------------------------------------
-- 5. 存量校验
--    本迁移执行环境（本地）相关表为 0 行；其他环境有孤儿时这里会失败并回滚。
-- ----------------------------------------------------------------------------
ALTER TABLE "public"."position_lots"       VALIDATE CONSTRAINT "position_lots_order_id_fkey";
ALTER TABLE "public"."trade_flow"          VALIDATE CONSTRAINT "trade_flow_order_id_fkey";

ALTER TABLE "public"."accounts"            VALIDATE CONSTRAINT "accounts_user_id_fkey";
ALTER TABLE "public"."account_snapshots"   VALIDATE CONSTRAINT "account_snapshots_user_id_fkey";
ALTER TABLE "public"."positions"           VALIDATE CONSTRAINT "positions_user_id_fkey";
ALTER TABLE "public"."position_lots"       VALIDATE CONSTRAINT "position_lots_user_id_fkey";
ALTER TABLE "public"."trade_orders"        VALIDATE CONSTRAINT "trade_orders_user_id_fkey";
ALTER TABLE "public"."trade_flow"          VALIDATE CONSTRAINT "trade_flow_user_id_fkey";
ALTER TABLE "public"."watchlist"           VALIDATE CONSTRAINT "watchlist_user_id_fkey";

ALTER TABLE "public"."positions"           VALIDATE CONSTRAINT "positions_fund_code_fkey";
ALTER TABLE "public"."position_lots"       VALIDATE CONSTRAINT "position_lots_fund_code_fkey";
ALTER TABLE "public"."trade_orders"        VALIDATE CONSTRAINT "trade_orders_fund_code_fkey";
ALTER TABLE "public"."trade_flow"          VALIDATE CONSTRAINT "trade_flow_fund_code_fkey";

-- ----------------------------------------------------------------------------
-- 6. purge_user_data：补 position_lots，并调整删除顺序
--    user_id 已经是 CASCADE，理论上删 auth 用户会自动清理；但后端仍先调用
--    purge_user_data，显式删除更可控，也不依赖 auth 用户的删除路径。
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.purge_user_data(p_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_deleted integer;
BEGIN
    -- 1) 会话：先 messages（级联 message_chunks），再 chats
    DELETE FROM public.messages WHERE user_id = p_user_id;
    DELETE FROM public.chats WHERE user_id = p_user_id;

    -- 2) 文档：先 documents（级联 document_chunks）；
    --    files 因自引用 parent_id（files_parent_id_fkey，无级联）需逐层删叶子节点
    DELETE FROM public.documents WHERE user_id = p_user_id;
    LOOP
        DELETE FROM public.files
        WHERE user_id = p_user_id
          AND id NOT IN (
              SELECT parent_id FROM public.files
              WHERE user_id = p_user_id AND parent_id IS NOT NULL
          );
        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        EXIT WHEN v_deleted = 0;
    END LOOP;

    -- 3) 风险画像：先 profiles（fk_risk_profiles_answer 指向 answers），再 answers
    DELETE FROM public.user_risk_profiles WHERE user_id = p_user_id;
    DELETE FROM public.user_risk_answers WHERE user_id = p_user_id;

    -- 4) 其余平级表
    DELETE FROM public.user_allocations WHERE user_id = p_user_id;
    DELETE FROM public.watchlist WHERE user_id = p_user_id;

    -- 5) 交易数据：先删批次，再删流水/订单，最后删持仓
    DELETE FROM public.position_lots WHERE user_id = p_user_id;
    DELETE FROM public.trade_flow WHERE user_id = p_user_id;
    DELETE FROM public.trade_orders WHERE user_id = p_user_id;
    DELETE FROM public.positions WHERE user_id = p_user_id;

    -- 6) 账户：先快照再账户
    DELETE FROM public.account_snapshots WHERE user_id = p_user_id;
    DELETE FROM public.accounts WHERE user_id = p_user_id;
END;
$$;

COMMENT ON FUNCTION public.purge_user_data(uuid) IS
  '注销账号：单事务清理用户全部业务数据；交易批次先于订单删除';

GRANT EXECUTE ON FUNCTION public.purge_user_data(uuid) TO service_role;
