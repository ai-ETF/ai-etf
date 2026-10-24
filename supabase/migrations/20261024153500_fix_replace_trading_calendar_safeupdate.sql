-- 修正 replace_trading_calendar：
--   1. Supabase 启用 pg_safeupdate 后，函数内 `DELETE FROM public.trading_calendar`
--      因缺少 WHERE 被拒绝（SQLSTATE 21000），整表替换无法执行；
--      改为 `WHERE true`，语义不变（本就要求整表清空）。
--   2. 新建函数时 Supabase 的默认权限会给 anon/authenticated 显式授予 EXECUTE，
--      原迁移的 REVOKE ... FROM PUBLIC 收不回这些显式授权。这里显式收回，
--      只保留 service_role（应用侧使用 service role key 调用）。

CREATE OR REPLACE FUNCTION "public"."replace_trading_calendar"(
    "p_trading_days" date[],
    "p_source"       text
)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_start         date;
    v_end           date;
    v_trading_count integer;
    v_rows          integer;
BEGIN
    IF p_source IS NULL OR btrim(p_source) = '' THEN
        RAISE EXCEPTION 'p_source 不能为空';
    END IF;
    IF p_trading_days IS NULL OR cardinality(p_trading_days) = 0 THEN
        RAISE EXCEPTION 'p_trading_days 不能为空';
    END IF;

    SELECT min(d), max(d), count(DISTINCT d)
      INTO v_start, v_end, v_trading_count
      FROM unnest(p_trading_days) AS d;

    IF v_start IS NULL OR v_end IS NULL THEN
        RAISE EXCEPTION 'p_trading_days 含空值';
    END IF;

    -- pg_safeupdate 要求 DELETE 必须带 WHERE；表语义仍是「最后一次成功快照」，
    -- 不与旧行做并集，因此 WHERE true 等价于整表清空。
    DELETE FROM public.trading_calendar WHERE true;

    INSERT INTO public.trading_calendar (trade_date, is_trading_day, source)
    SELECT days.d,
           (td.d IS NOT NULL),
           p_source
      FROM (
            SELECT generate_series(v_start::timestamp, v_end::timestamp, interval '1 day')::date AS d
           ) AS days
      LEFT JOIN (
            SELECT DISTINCT d FROM unnest(p_trading_days) AS d
           ) AS td
             ON td.d = days.d;

    GET DIAGNOSTICS v_rows = ROW_COUNT;

    INSERT INTO public.trading_calendar_state
        (id, coverage_start, coverage_end, last_success_at, last_error, last_error_at, updated_at)
    VALUES
        (true, v_start, v_end, now(), NULL, NULL, now())
    ON CONFLICT (id) DO UPDATE
       SET coverage_start  = EXCLUDED.coverage_start,
           coverage_end    = EXCLUDED.coverage_end,
           last_success_at = EXCLUDED.last_success_at,
           last_error      = NULL,
           last_error_at   = NULL,
           updated_at      = now();

    RETURN jsonb_build_object(
        'coverage_start', v_start,
        'coverage_end',   v_end,
        'rows',           v_rows,
        'trading_days',   v_trading_count,
        'source',         p_source
    );
END;
$$;

REVOKE ALL ON FUNCTION "public"."replace_trading_calendar"(date[], text) FROM PUBLIC;
REVOKE ALL ON FUNCTION "public"."replace_trading_calendar"(date[], text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION "public"."replace_trading_calendar"(date[], text) TO service_role;
