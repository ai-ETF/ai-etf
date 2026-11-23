-- A 股交易日历缓存：逐日快照 + 单行状态 + 事务性整表替换函数
--
-- 设计依据：docs/20-设计/基金与交易/交易日历缓存.md §4.2
-- 取数仍由 server/sources 的 SinaTradeDateSource 完成；本迁移只负责持久化。
--
-- 为什么整表替换要写成数据库函数：
--   应用只使用 Supabase PostgREST 客户端，每次 DELETE / INSERT 都是独立 HTTP
--   请求，客户端无法跨调用开事务。若先 DELETE 再分批 INSERT，中途失败会留下
--   空表或半份快照，违反文档「失败整体回滚」的约束。把「删旧 + 展开自然日 +
--   写新 + 更新 state」放进一个 plpgsql 函数，单次调用即单事务。
--
-- 数据量：源当前返回约 8800 个交易日（1990-12-19 → 2026-12-31），展开成自然日
--   约 1.3 万行；一年一次人工刷新，主键即查询路径，无需额外索引。

CREATE TABLE IF NOT EXISTS "public"."trading_calendar" (
    "trade_date"     date PRIMARY KEY,
    "is_trading_day" boolean NOT NULL,
    "source"         text NOT NULL,
    "updated_at"     timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE "public"."trading_calendar" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE "public"."trading_calendar" IS
  'A 股交易日历逐日表：源覆盖区间内每个自然日一行，is_trading_day=false 表示周末/节假日';
COMMENT ON COLUMN "public"."trading_calendar"."source" IS
  '这一行由哪个日历源产出（当前为 sina_trade_date），便于审计';

CREATE TABLE IF NOT EXISTS "public"."trading_calendar_state" (
    "id"              boolean PRIMARY KEY DEFAULT true CHECK (id),
    "coverage_start"  date,
    "coverage_end"    date,
    "last_success_at" timestamptz,
    "last_error"      text,
    "last_error_at"   timestamptz,
    "updated_at"      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE "public"."trading_calendar_state" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE "public"."trading_calendar_state" IS
  '交易日历缓存状态：单行，记录覆盖区间与最后一次成功/失败';

-- 整表替换：p_trading_days 是源返回的交易日集合（ISO 日期数组），
-- 函数内展开为 [min, max] 的自然日，连同 state 一起在单事务内替换。
-- 入参为空直接报错，不做「保留旧数据」的兜底 —— 旧快照由调用方保持不动。
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

    -- 整表替换：表语义是「最后一次成功快照」，不与旧行做并集。
    DELETE FROM public.trading_calendar;

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

COMMENT ON FUNCTION "public"."replace_trading_calendar"(date[], text) IS
  '事务性整表替换交易日历：展开自然日写入 trading_calendar，并更新 trading_calendar_state';

REVOKE ALL ON FUNCTION "public"."replace_trading_calendar"(date[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION "public"."replace_trading_calendar"(date[], text) TO service_role;
