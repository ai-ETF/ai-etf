-- M1：基金主数据 / 交易规则拆分 + 净值三表 + 目录兼容视图
-- 设计依据：docs/20-设计/基金与交易/场外净值与基金元数据存储设计.md
--   §4.1 表定义 / §4.4 写入函数 / §4.5 权限 / §4.6 迁移与回滚
-- 本迁移**不改动** fund_fee_rules（M2 才删）；回填是一次性快照，重复执行仅 DO NOTHING。
-- 一次性迁移：CREATE TABLE 用 IF NOT EXISTS，但 ADD CONSTRAINT / CREATE VIEW 不做重复保护。

-- ============================================================================
-- 1. 表定义
-- ============================================================================

-- 净值明细：一行 = 一只基金的一个净值日
CREATE TABLE IF NOT EXISTS "public"."fund_nav" (
    "fund_code"       character varying(10) NOT NULL,
    "nav_date"        date NOT NULL,
    "unit_nav"        numeric(18,6),
    "accumulated_nav" numeric(18,6),
    "daily_growth"    numeric(10,4),          -- 百分数，-0.27 表示 -0.27%
    "source"          text NOT NULL,
    "first_seen_at"   timestamptz NOT NULL DEFAULT now(),
    "updated_at"      timestamptz NOT NULL DEFAULT now(),
    "revision_count"  integer NOT NULL DEFAULT 0,
    CONSTRAINT "fund_nav_pkey" PRIMARY KEY ("fund_code", "nav_date"),
    CONSTRAINT "fund_nav_unit_nav_positive"
        CHECK ("unit_nav" IS NULL OR "unit_nav" > 0),
    CONSTRAINT "fund_nav_accumulated_nav_positive"
        CHECK ("accumulated_nav" IS NULL OR "accumulated_nav" > 0),
    CONSTRAINT "fund_nav_revision_count_non_negative"
        CHECK ("revision_count" >= 0)
);

COMMENT ON TABLE "public"."fund_nav" IS '场外基金净值明细：一行=一只基金一个净值日，由多源适配器写入';
COMMENT ON COLUMN "public"."fund_nav"."daily_growth" IS '日增长率，百分数口径（-0.27 表示 -0.27%）';
COMMENT ON COLUMN "public"."fund_nav"."source" IS '写入该值的源名（server/sources 注册名）';
COMMENT ON COLUMN "public"."fund_nav"."revision_count" IS '被更正次数；每次改单位/累计净值 +1 并写 fund_nav_revision';

-- 每只基金一行：历史完整性 + 最新净值投影
CREATE TABLE IF NOT EXISTS "public"."fund_nav_state" (
    "fund_code"          character varying(10) PRIMARY KEY,
    "history_status"     text NOT NULL DEFAULT 'pending',
    "latest_nav_date"    date,
    "latest_unit_nav"    numeric(18,6),
    "history_start_date" date,
    "last_checked_at"    timestamptz,
    "last_success_at"    timestamptz,
    "last_error"         text,
    "last_error_at"      timestamptz,
    "updated_at"         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "fund_nav_state_status_check"
        CHECK ("history_status" IN ('pending', 'ready', 'partial', 'failed')),
    CONSTRAINT "fund_nav_state_latest_pair_check"
        CHECK (("latest_nav_date" IS NULL) = ("latest_unit_nav" IS NULL)),
    CONSTRAINT "fund_nav_state_latest_unit_nav_positive"
        CHECK ("latest_unit_nav" IS NULL OR "latest_unit_nav" > 0),
    CONSTRAINT "fund_nav_state_ready_has_latest_check"
        CHECK ("history_status" <> 'ready' OR "latest_nav_date" IS NOT NULL)
);

COMMENT ON TABLE "public"."fund_nav_state" IS '场外基金净值同步状态：历史完整性 + 最新净值投影（读路径四态判定的依据）';
COMMENT ON COLUMN "public"."fund_nav_state"."history_start_date" IS '该基金历史数据的最早净值日；用于缺口判定，未同步过为 NULL';

-- 更正日志：只追加，不更新、不删除（由 §4.5 的授权强制：只给 SELECT/INSERT）
CREATE TABLE IF NOT EXISTS "public"."fund_nav_revision" (
    "id"                  bigserial PRIMARY KEY,
    "fund_code"           character varying(10) NOT NULL,
    "nav_date"            date NOT NULL,
    "old_unit_nav"        numeric(18,6),
    "new_unit_nav"        numeric(18,6),
    "old_accumulated_nav" numeric(18,6),
    "new_accumulated_nav" numeric(18,6),
    "source"              text NOT NULL,
    "detected_at"         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "fund_nav_revision_changed_check"
        CHECK ("old_unit_nav" IS DISTINCT FROM "new_unit_nav"
            OR "old_accumulated_nav" IS DISTINCT FROM "new_accumulated_nav")
);

COMMENT ON TABLE "public"."fund_nav_revision" IS '净值更正审计：只追加；service_role 无 UPDATE/DELETE 权限';

-- 基金主数据：身份、静态描述、生命周期
CREATE TABLE IF NOT EXISTS "public"."fund" (
    "fund_code"           character varying(10) PRIMARY KEY,
    "fund_name"           character varying(100) NOT NULL,
    "ftype"               character varying(50),      -- 上游 FTYPE 描述，不等于交易分类
    "manager_company"     character varying(100),
    "fund_manager"        character varying(200),
    "tracking_index"      character varying(100),
    "tracking_index_code" character varying(20),
    "establish_date"      date,
    "net_asset_scale"     numeric(20,2),
    "risk_level_code"     character varying(10),      -- 上游 RISKLEVEL 原值
    "is_qdii"             boolean,                    -- 未知时 NULL，不伪造 false
    "qdii_reason"         text,                       -- 推导依据，与 is_qdii 同生同灭
    "metadata_source"     text NOT NULL,
    "lifecycle_status"    text NOT NULL DEFAULT 'active',
    "first_seen_at"       timestamptz NOT NULL DEFAULT now(),
    "synced_at"           timestamptz,
    "updated_at"          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "fund_lifecycle_status_check"
        CHECK ("lifecycle_status" IN ('active', 'removed')),
    CONSTRAINT "fund_qdii_pair_check"
        CHECK (("is_qdii" IS NULL) = ("qdii_reason" IS NULL)),
    CONSTRAINT "fund_scale_non_negative"
        CHECK ("net_asset_scale" IS NULL OR "net_asset_scale" >= 0)
);

COMMENT ON TABLE "public"."fund" IS '基金主数据：身份/静态描述/生命周期；不含准入与费率';
COMMENT ON COLUMN "public"."fund"."lifecycle_status" IS 'active=可交易；removed=下架（同步永不改写，需人工恢复）';
COMMENT ON COLUMN "public"."fund"."is_qdii" IS 'QDII 标记，由 classify_fund 规则推导；未知为 NULL';
COMMENT ON COLUMN "public"."fund"."qdii_reason" IS 'QDII 推导依据（命中的关键词或 FTYPE 原值）；与 is_qdii 同生同灭';

-- 交易规则：行存在 = 进入白名单
CREATE TABLE IF NOT EXISTS "public"."fund_trade_rule" (
    "fund_code"               character varying(10) PRIMARY KEY
        REFERENCES "public"."fund"("fund_code") ON DELETE RESTRICT,
    "fund_type"               character varying(4) NOT NULL DEFAULT 'of',
    "share_class"             character varying(1) NOT NULL,
    "management_fee_rate"     numeric(6,4) NOT NULL,
    "custody_fee_rate"        numeric(6,4) NOT NULL,
    "sales_service_fee_rate"  numeric(6,4) NOT NULL,
    "commission_rate"         numeric(6,4) NOT NULL,
    "min_purchase_amount"     numeric(18,2) NOT NULL,
    "max_purchase_amount"     numeric(18,2),
    "subscribe_status"        text,
    "purchase_fee_tiers"      jsonb,
    "redemption_fee_tiers"    jsonb NOT NULL,
    "confirm_delay"           integer NOT NULL,
    "redeem_settle_delay"     integer NOT NULL,
    "created_at"              timestamptz NOT NULL DEFAULT now(),
    "updated_at"              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT "fund_trade_rule_fund_type_check"
        CHECK ("fund_type" IN ('of', 'etf')),
    CONSTRAINT "fund_trade_rule_max_purchase_check"
        CHECK ("max_purchase_amount" IS NULL OR "max_purchase_amount" > 0)
);

COMMENT ON TABLE "public"."fund_trade_rule" IS '基金交易规则：行存在=进入白名单；费率/申购状态/确认与赎回周期';

ALTER TABLE "public"."fund"             ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."fund_trade_rule"  ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."fund_nav"         ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."fund_nav_state"   ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."fund_nav_revision" ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 2. 从 fund_fee_rules 回填（主数据 → 交易规则，顺序固定：外键依赖）
-- ============================================================================

-- 主数据：身份/名称来自旧表；QDII 依据来自既有风险画像
INSERT INTO "public"."fund" (
    "fund_code", "fund_name", "metadata_source", "is_qdii", "qdii_reason")
SELECT r."fund_code", r."fund_name", 'migration:fund_fee_rules',
       CASE p."market_score" WHEN 3 THEN true WHEN 1 THEN false END,
       CASE p."market_score"
            WHEN 3 THEN 'migrated: market_score=3'
            WHEN 1 THEN 'migrated: market_score=1' END
FROM "public"."fund_fee_rules" r
LEFT JOIN "public"."fund_risk_profiles" p ON p."fund_code" = r."fund_code"
ON CONFLICT ("fund_code") DO NOTHING;

-- 交易规则：旧表的准入/费率字段整体搬过来。
-- created_at / updated_at 在旧表是「有默认值但可空」，目标表是 NOT NULL，故 COALESCE。
INSERT INTO "public"."fund_trade_rule" (
    "fund_code", "fund_type", "share_class", "management_fee_rate",
    "custody_fee_rate", "sales_service_fee_rate", "commission_rate",
    "min_purchase_amount", "max_purchase_amount", "subscribe_status",
    "purchase_fee_tiers", "redemption_fee_tiers",
    "confirm_delay", "redeem_settle_delay", "created_at", "updated_at")
SELECT "fund_code", "fund_type", "share_class", "management_fee_rate",
       "custody_fee_rate", "sales_service_fee_rate", "commission_rate",
       "min_purchase_amount", "max_purchase_amount", "subscribe_status",
       "purchase_fee_tiers", "redemption_fee_tiers",
       "confirm_delay", "redeem_settle_delay",
       COALESCE("created_at", now()), COALESCE("updated_at", now())
FROM "public"."fund_fee_rules"
ON CONFLICT ("fund_code") DO NOTHING;

-- ============================================================================
-- 3. 风险画像补外键
--    旧库理论上两表代码集合一致；空库（migrations 先于 seed 执行）会出现
--    「有画像、无主数据」，此时外键以 NOT VALID 建立：只约束新写入，不阻塞迁移。
--    数据补齐后执行 ALTER TABLE ... VALIDATE CONSTRAINT 收紧。
-- ============================================================================

DO $$
DECLARE
    v_orphans text;
BEGIN
    SELECT string_agg(p."fund_code", ', ' ORDER BY p."fund_code")
      INTO v_orphans
      FROM "public"."fund_risk_profiles" p
      LEFT JOIN "public"."fund" f ON f."fund_code" = p."fund_code"
     WHERE f."fund_code" IS NULL;

    IF v_orphans IS NOT NULL THEN
        RAISE WARNING 'fund_risk_profiles 存在无主数据画像，外键将以 NOT VALID 建立: %', v_orphans;
    END IF;
END
$$;

ALTER TABLE "public"."fund_risk_profiles"
    ADD CONSTRAINT "fund_risk_profiles_fund_code_fkey"
    FOREIGN KEY ("fund_code") REFERENCES "public"."fund"("fund_code")
    ON DELETE RESTRICT NOT VALID;

-- 没有孤儿时立刻收紧（等价于迁移前就满足约束的常规路径）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM "public"."fund_risk_profiles" p
          LEFT JOIN "public"."fund" f ON f."fund_code" = p."fund_code"
         WHERE f."fund_code" IS NULL
    ) THEN
        ALTER TABLE "public"."fund_risk_profiles"
            VALIDATE CONSTRAINT "fund_risk_profiles_fund_code_fkey";
    END IF;
END
$$;

-- ============================================================================
-- 4. 目录兼容视图：原 fund_fee_rules 的读路径，内连接 = 白名单语义
--    security_invoker 需要 PostgreSQL 15+（本地/线上均为 17）
-- ============================================================================

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
       r."purchase_fee_tiers", r."redemption_fee_tiers"
FROM "public"."fund" f
JOIN "public"."fund_trade_rule" r ON r."fund_code" = f."fund_code"
WHERE f."lifecycle_status" = 'active';

COMMENT ON VIEW "public"."fund_catalog" IS '兼容旧 fund_fee_rules 读路径的目录视图：主数据 JOIN 交易规则，仅 active';

-- ============================================================================
-- 5. 写入函数
-- ============================================================================

-- 5.1 主数据 + 交易规则 + 风险画像：一次 RPC、一个事务
CREATE OR REPLACE FUNCTION "public"."upsert_fund_catalog"(
    "funds" jsonb, "trade_rules" jsonb, "risk_profiles" jsonb)
RETURNS TABLE ("funds_written" integer, "rules_written" integer, "risk_written" integer)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    r        jsonb;
    n_funds  integer := 0;
    n_rules  integer := 0;
    n_risk   integer := 0;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('fund_catalog_upsert'));

    FOR r IN SELECT * FROM jsonb_array_elements(COALESCE("funds", '[]'::jsonb)) LOOP
        INSERT INTO "fund" (
            "fund_code", "fund_name", "ftype", "manager_company", "fund_manager",
            "tracking_index", "tracking_index_code", "establish_date",
            "net_asset_scale", "risk_level_code", "is_qdii", "qdii_reason",
            "metadata_source", "synced_at", "updated_at")
        VALUES (
            r->>'fund_code', r->>'fund_name', r->>'ftype', r->>'manager_company',
            r->>'fund_manager', r->>'tracking_index', r->>'tracking_index_code',
            (NULLIF(r->>'establish_date', ''))::date,
            (NULLIF(r->>'net_asset_scale', ''))::numeric,
            r->>'risk_level_code', (NULLIF(r->>'is_qdii', ''))::boolean, r->>'qdii_reason',
            r->>'metadata_source', now(), now())
        ON CONFLICT ("fund_code") DO UPDATE SET
            "fund_name"           = EXCLUDED."fund_name",
            "ftype"               = EXCLUDED."ftype",
            "manager_company"     = EXCLUDED."manager_company",
            "fund_manager"        = EXCLUDED."fund_manager",
            "tracking_index"      = EXCLUDED."tracking_index",
            "tracking_index_code" = EXCLUDED."tracking_index_code",
            "establish_date"      = EXCLUDED."establish_date",
            "net_asset_scale"     = EXCLUDED."net_asset_scale",
            "risk_level_code"     = EXCLUDED."risk_level_code",
            "is_qdii"             = EXCLUDED."is_qdii",
            "qdii_reason"         = EXCLUDED."qdii_reason",
            "metadata_source"     = EXCLUDED."metadata_source",
            "synced_at"           = now(),
            "updated_at"          = now();
        -- lifecycle_status / first_seen_at 不在同步范围内
        n_funds := n_funds + 1;
    END LOOP;

    FOR r IN SELECT * FROM jsonb_array_elements(COALESCE("trade_rules", '[]'::jsonb)) LOOP
        INSERT INTO "fund_trade_rule" (
            "fund_code", "fund_type", "share_class", "management_fee_rate",
            "custody_fee_rate", "sales_service_fee_rate", "commission_rate",
            "min_purchase_amount", "max_purchase_amount", "subscribe_status",
            "purchase_fee_tiers", "redemption_fee_tiers",
            "confirm_delay", "redeem_settle_delay", "updated_at")
        VALUES (
            r->>'fund_code', r->>'fund_type', r->>'share_class',
            (r->>'management_fee_rate')::numeric,
            (r->>'custody_fee_rate')::numeric,
            (r->>'sales_service_fee_rate')::numeric,
            (r->>'commission_rate')::numeric,
            (r->>'min_purchase_amount')::numeric,
            (NULLIF(r->>'max_purchase_amount', ''))::numeric,
            r->>'subscribe_status',
            r->'purchase_fee_tiers', r->'redemption_fee_tiers',
            (r->>'confirm_delay')::integer,
            (r->>'redeem_settle_delay')::integer, now())
        ON CONFLICT ("fund_code") DO UPDATE SET
            "fund_type"               = EXCLUDED."fund_type",
            "share_class"             = EXCLUDED."share_class",
            "management_fee_rate"     = EXCLUDED."management_fee_rate",
            "custody_fee_rate"        = EXCLUDED."custody_fee_rate",
            "sales_service_fee_rate"  = EXCLUDED."sales_service_fee_rate",
            "commission_rate"         = EXCLUDED."commission_rate",
            "min_purchase_amount"     = EXCLUDED."min_purchase_amount",
            "max_purchase_amount"     = EXCLUDED."max_purchase_amount",
            "subscribe_status"        = EXCLUDED."subscribe_status",
            "purchase_fee_tiers"      = EXCLUDED."purchase_fee_tiers",
            "redemption_fee_tiers"    = EXCLUDED."redemption_fee_tiers",
            "confirm_delay"           = EXCLUDED."confirm_delay",
            "redeem_settle_delay"     = EXCLUDED."redeem_settle_delay",
            "updated_at"              = now();
        n_rules := n_rules + 1;
    END LOOP;

    FOR r IN SELECT * FROM jsonb_array_elements(COALESCE("risk_profiles", '[]'::jsonb)) LOOP
        INSERT INTO "fund_risk_profiles" (
            "fund_code", "breadth_score", "volatility_score",
            "market_score", "board_score", "risk_level", "risk_label", "updated_at")
        VALUES (
            r->>'fund_code', (r->>'breadth_score')::integer,
            (r->>'volatility_score')::integer, (r->>'market_score')::integer,
            (r->>'board_score')::integer, r->>'risk_level', r->>'risk_label', now())
        ON CONFLICT ("fund_code") DO UPDATE SET
            "breadth_score"    = EXCLUDED."breadth_score",
            "volatility_score" = EXCLUDED."volatility_score",
            "market_score"     = EXCLUDED."market_score",
            "board_score"      = EXCLUDED."board_score",
            "risk_level"       = EXCLUDED."risk_level",
            "risk_label"       = EXCLUDED."risk_label",
            "updated_at"       = now();
        n_risk := n_risk + 1;
    END LOOP;

    RETURN QUERY SELECT n_funds, n_rules, n_risk;
END;
$$;

COMMENT ON FUNCTION "public"."upsert_fund_catalog"(jsonb, jsonb, jsonb)
    IS '主数据/交易规则/风险画像同事务 upsert；返回各表写入行数';

-- 5.2 净值合并：新增 / 更正 / 幂等，更正同时写审计
CREATE OR REPLACE FUNCTION "public"."merge_fund_nav"("rows" jsonb)
RETURNS TABLE ("inserted" integer, "updated" integer, "revised" integer)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    r           jsonb;
    v_code      varchar(10);
    v_date      date;
    v_unit      numeric(18,6);
    v_acc       numeric(18,6);
    v_growth    numeric(10,4);
    v_source    text;
    old_unit    numeric(18,6);
    old_acc     numeric(18,6);
    v_missing   text;
    n_inserted  integer := 0;
    n_updated   integer := 0;
    n_revised   integer := 0;
BEGIN
    -- 合并是低频写；串行化比并发冲突处理更简单、更可预测。
    PERFORM pg_advisory_xact_lock(hashtext('fund_nav_merge'));

    -- Q-D21：不建外键到 fund，但代码拼错必须整批报错，不能静默落库
    SELECT string_agg(DISTINCT e->>'fund_code', ', ' ORDER BY e->>'fund_code')
      INTO v_missing
      FROM jsonb_array_elements(COALESCE("rows", '[]'::jsonb)) AS t(e)
     WHERE NOT EXISTS (
         SELECT 1 FROM "fund" f WHERE f."fund_code" = e->>'fund_code');

    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'merge_fund_nav: fund_code 不存在于 fund: %', v_missing;
    END IF;

    -- Q-D22：同批重复 (fund_code, nav_date) 先按出现顺序保留最后一条，
    -- 否则第二次会读到刚插入的行并生成一条「假更正」，污染审计与 revision_count
    FOR r IN
        SELECT DISTINCT ON (e->>'fund_code', e->>'nav_date') e
          FROM jsonb_array_elements(COALESCE("rows", '[]'::jsonb))
               WITH ORDINALITY AS t(e, ord)
         ORDER BY e->>'fund_code', e->>'nav_date', ord DESC
    LOOP
        v_code   := r->>'fund_code';
        v_date   := (r->>'nav_date')::date;
        v_unit   := (r->>'unit_nav')::numeric;
        v_acc    := (r->>'accumulated_nav')::numeric;
        v_growth := (r->>'daily_growth')::numeric;
        v_source := r->>'source';

        SELECT "unit_nav", "accumulated_nav"
          INTO old_unit, old_acc
          FROM "fund_nav"
         WHERE "fund_code" = v_code AND "nav_date" = v_date;

        IF NOT FOUND THEN
            INSERT INTO "fund_nav"
                ("fund_code", "nav_date", "unit_nav", "accumulated_nav",
                 "daily_growth", "source")
            VALUES (v_code, v_date, v_unit, v_acc, v_growth, v_source);
            n_inserted := n_inserted + 1;
        ELSIF old_unit IS DISTINCT FROM v_unit
           OR old_acc  IS DISTINCT FROM v_acc THEN
            INSERT INTO "fund_nav_revision"
                ("fund_code", "nav_date", "old_unit_nav", "new_unit_nav",
                 "old_accumulated_nav", "new_accumulated_nav", "source")
            VALUES (v_code, v_date, old_unit, v_unit, old_acc, v_acc, v_source);

            UPDATE "fund_nav"
               SET "unit_nav"        = v_unit,
                   "accumulated_nav" = v_acc,
                   "daily_growth"    = v_growth,
                   "source"          = v_source,
                   "updated_at"      = now(),
                   "revision_count"  = "revision_count" + 1
             WHERE "fund_code" = v_code AND "nav_date" = v_date;

            n_updated := n_updated + 1;
            n_revised := n_revised + 1;
        END IF;
        -- 数值未变化：不写主表、不写更正、不刷新 updated_at
    END LOOP;

    RETURN QUERY SELECT n_inserted, n_updated, n_revised;
END;
$$;

COMMENT ON FUNCTION "public"."merge_fund_nav"(jsonb)
    IS '净值合并：新增/更正/幂等；值变化时写 fund_nav_revision；不更新 fund_nav_state';

-- 5.3 同步状态：两条受保护语句，单事务；状态更新不在 merge_fund_nav 内
CREATE OR REPLACE FUNCTION "public"."upsert_fund_nav_state"(
    "p_fund_code" text,
    "p_history_status" text DEFAULT NULL,
    "p_latest_nav_date" date DEFAULT NULL,
    "p_latest_unit_nav" numeric DEFAULT NULL,
    "p_history_start_date" date DEFAULT NULL,
    "p_got_data" boolean DEFAULT false,
    "p_error" text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    IF "p_fund_code" IS NULL OR "p_fund_code" = '' THEN
        RAISE EXCEPTION 'fund_code 不能为空';
    END IF;
    IF "p_history_status" IS NOT NULL
       AND "p_history_status" NOT IN ('pending', 'ready', 'partial', 'failed') THEN
        RAISE EXCEPTION '非法 history_status: %', "p_history_status";
    END IF;

    -- ① 只前进：更旧或相同的日期不覆盖
    IF "p_latest_nav_date" IS NOT NULL THEN
        INSERT INTO "fund_nav_state" AS s
            ("fund_code", "latest_nav_date", "latest_unit_nav",
             "history_start_date", "history_status", "updated_at")
        VALUES ("p_fund_code", "p_latest_nav_date", "p_latest_unit_nav",
                "p_history_start_date", COALESCE("p_history_status", 'pending'), now())
        ON CONFLICT ("fund_code") DO UPDATE SET
            "latest_nav_date"    = EXCLUDED."latest_nav_date",
            "latest_unit_nav"    = EXCLUDED."latest_unit_nav",
            "history_start_date" = LEAST(
                COALESCE(s."history_start_date", EXCLUDED."history_start_date"),
                EXCLUDED."history_start_date"),
            "updated_at"         = now()
        WHERE EXCLUDED."latest_nav_date" > s."latest_nav_date"
           OR s."latest_nav_date" IS NULL;
    END IF;

    -- ② 每轮都刷：不动 latest_*；history_status 为 NULL 表示本轮不改状态
    INSERT INTO "fund_nav_state" AS s
        ("fund_code", "history_status", "last_checked_at", "last_success_at",
         "last_error", "last_error_at", "updated_at")
    VALUES ("p_fund_code", COALESCE("p_history_status", 'pending'), now(),
            CASE WHEN "p_got_data" THEN now() END,
            "p_error",
            CASE WHEN "p_error" IS NOT NULL THEN now() END,
            now())
    ON CONFLICT ("fund_code") DO UPDATE SET
        "last_checked_at" = now(),
        "last_success_at" = COALESCE(EXCLUDED."last_success_at", s."last_success_at"),
        "history_status"  = COALESCE("p_history_status", s."history_status"),
        "last_error"      = COALESCE(EXCLUDED."last_error", s."last_error"),
        "last_error_at"   = CASE WHEN EXCLUDED."last_error" IS NOT NULL
                                 THEN EXCLUDED."last_error_at"
                                 ELSE s."last_error_at" END,
        "updated_at"      = now();
END;
$$;

COMMENT ON FUNCTION "public"."upsert_fund_nav_state"(text, text, date, numeric, date, boolean, text)
    IS '净值同步状态：latest_* 只前进 + 每轮刷新检查时间/错误；p_history_status 为 NULL 表示不改状态';

-- ============================================================================
-- 6. 授权：只给 service_role（基线 DEFAULT PRIVILEGES 会给 anon/authenticated 自动授权）
-- ============================================================================

REVOKE ALL ON "public"."fund", "public"."fund_trade_rule",
               "public"."fund_risk_profiles", "public"."fund_nav",
               "public"."fund_nav_state", "public"."fund_nav_revision"
  FROM "anon", "authenticated";

GRANT SELECT, INSERT, UPDATE, DELETE ON
      "public"."fund", "public"."fund_trade_rule",
      "public"."fund_risk_profiles", "public"."fund_nav",
      "public"."fund_nav_state"
  TO "service_role";

-- 更正日志只追加：授权层面就不给 UPDATE / DELETE
GRANT SELECT, INSERT ON "public"."fund_nav_revision" TO "service_role";
REVOKE ALL ON SEQUENCE "public"."fund_nav_revision_id_seq" FROM "anon", "authenticated";
GRANT USAGE, SELECT ON SEQUENCE "public"."fund_nav_revision_id_seq" TO "service_role";

REVOKE ALL ON "public"."fund_catalog" FROM "anon", "authenticated";
GRANT SELECT ON "public"."fund_catalog" TO "service_role";

REVOKE ALL ON FUNCTION "public"."upsert_fund_catalog"(jsonb, jsonb, jsonb)
    FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."merge_fund_nav"(jsonb)
    FROM PUBLIC, "anon", "authenticated";
REVOKE ALL ON FUNCTION "public"."upsert_fund_nav_state"(text, text, date, numeric, date, boolean, text)
    FROM PUBLIC, "anon", "authenticated";

GRANT EXECUTE ON FUNCTION "public"."upsert_fund_catalog"(jsonb, jsonb, jsonb) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."merge_fund_nav"(jsonb) TO "service_role";
GRANT EXECUTE ON FUNCTION "public"."upsert_fund_nav_state"(text, text, date, numeric, date, boolean, text) TO "service_role";
