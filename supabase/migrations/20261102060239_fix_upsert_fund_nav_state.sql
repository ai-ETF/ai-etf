-- 修复 upsert_fund_nav_state：历史净值永远无法标记 ready
--
-- 现象：`_fill_history` 在合并完历史后调用本函数写 history_status='ready'，
-- 第 ② 段的 INSERT 列表里没有 latest_nav_date / latest_unit_nav，
-- PostgreSQL 会先用这条 proposed row 校验 CHECK
-- `fund_nav_state_ready_has_latest_check`（ready 必须带 latest），
-- 于是报 400 并回滚状态更新。状态永远停在 pending，
-- 详情接口每次请求都重新全量补齐历史（数秒），且异常被上层吞成空列表。
--
-- 改法：把 latest_* / history_start_date 一并放进第 ② 段的 INSERT 列，
-- 让 proposed row 满足 CHECK；ON CONFLICT DO UPDATE 仍然不覆盖 latest_*，
-- 保持「最新净值只前进」的既有语义。函数签名不变，ACL 不变。

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
        "last_error"      = COALESCE(EXCLUDED."last_error", s."last_error"),
        "last_error_at"   = CASE WHEN EXCLUDED."last_error" IS NOT NULL
                                 THEN EXCLUDED."last_error_at"
                                 ELSE s."last_error_at" END,
        "updated_at"      = now();
END;
$$;
