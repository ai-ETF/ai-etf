-- 补齐 upsert_fund_nav_state 对 history_start_date 的维护
--
-- 第一版修复让第 ② 段能写 history_status='ready'，但第 ① 段的
-- 「最新净值只前进」WHERE 在日期相等时不会执行 UPDATE，
-- 而第 ② 段的 ON CONFLICT 又只刷 last_checked_*，于是
-- history_start_date 永远补不上（ready + start_date=NULL）。
-- `FundNavService.get_nav_on` 在 start_date 为空时会返回
-- history_start_unknown，影响订单确认取净值。
--
-- 改法：第 ② 段 ON CONFLICT 时也维护 history_start_date，
-- 与第 ① 段一致取「更早者」，NULL 不覆盖已有值。
-- 签名与 ACL 不变。

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

    -- ② 每轮都刷：不动现有 latest_*；history_status 为 NULL 表示本轮不改状态。
    -- INSERT 列必须带上 latest_*，否则 ready 状态的 proposed row 会先撞
    -- fund_nav_state_ready_has_latest_check（ON CONFLICT 之前的约束校验）。
    INSERT INTO "fund_nav_state" AS s
        ("fund_code", "history_status", "latest_nav_date", "latest_unit_nav",
         "history_start_date", "last_checked_at", "last_success_at",
         "last_error", "last_error_at", "updated_at")
    VALUES ("p_fund_code", COALESCE("p_history_status", 'pending'),
            "p_latest_nav_date", "p_latest_unit_nav", "p_history_start_date",
            now(),
            CASE WHEN "p_got_data" THEN now() END,
            "p_error",
            CASE WHEN "p_error" IS NOT NULL THEN now() END,
            now())
    ON CONFLICT ("fund_code") DO UPDATE SET
        "last_checked_at" = now(),
        "last_success_at" = COALESCE(EXCLUDED."last_success_at", s."last_success_at"),
        "history_status"  = COALESCE("p_history_status", s."history_status"),
        "history_start_date" = CASE
            WHEN EXCLUDED."history_start_date" IS NULL THEN s."history_start_date"
            WHEN s."history_start_date" IS NULL THEN EXCLUDED."history_start_date"
            ELSE LEAST(s."history_start_date", EXCLUDED."history_start_date")
        END,
        "last_error"      = COALESCE(EXCLUDED."last_error", s."last_error"),
        "last_error_at"   = CASE WHEN EXCLUDED."last_error" IS NOT NULL
                                 THEN EXCLUDED."last_error_at"
                                 ELSE s."last_error_at" END,
        "updated_at"      = now();
END;
$$;

-- 回填：已经 ready 但起始日为空的状态行，用库内最早净值补齐。
-- 只处理 ready 行，pending/partial 的历史可能不完整，等补齐流程自己写。
UPDATE "public"."fund_nav_state" AS s
SET "history_start_date" = x."min_date",
    "updated_at" = now()
FROM (
    SELECT "fund_code", MIN("nav_date") AS "min_date"
    FROM "public"."fund_nav"
    GROUP BY "fund_code"
) AS x
WHERE x."fund_code" = s."fund_code"
  AND s."history_status" = 'ready'
  AND s."history_start_date" IS NULL;
