


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "vector" WITH SCHEMA "public";






CREATE TYPE "public"."profile_source" AS ENUM (
    'questionnaire',
    'default',
    'manual',
    'system_inferred'
);


ALTER TYPE "public"."profile_source" OWNER TO "postgres";


COMMENT ON TYPE "public"."profile_source" IS '风险画像来源枚举：questionnaire(问卷填写)、default(默认值)、manual(人工设置)、system_inferred(系统推断)';



CREATE TYPE "public"."risk_level" AS ENUM (
    'conservative',
    'moderate',
    'aggressive'
);


ALTER TYPE "public"."risk_level" OWNER TO "postgres";


COMMENT ON TYPE "public"."risk_level" IS '用户风险等级枚举：conservative(保守型)、moderate(稳健型)、aggressive(进取型)';



CREATE OR REPLACE FUNCTION "public"."check_parent_is_folder"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
begin
  if new.parent_id is not null then
    if (select type from files where id = new.parent_id) != 'folder' then
      raise exception 'Parent must be a folder';
    end if;
  end if;
  return new;
end;
$$;


ALTER FUNCTION "public"."check_parent_is_folder"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."delete_chat_messages"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  -- 当 chats 表中的一行被删除时，OLD 代表被删除的那行数据
  -- 删除 messages 表中所有 chat_id 等于被删除会话 id 的记录
  DELETE FROM public.messages WHERE chat_id = OLD.id;
  -- 触发器函数需要返回被操作的行记录
  RETURN OLD;
END;
$$;


ALTER FUNCTION "public"."delete_chat_messages"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."delete_message_chunks_on_message_delete"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  DELETE FROM message_chunks WHERE message_id = OLD.id;
  RETURN OLD;
END;
$$;


ALTER FUNCTION "public"."delete_message_chunks_on_message_delete"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."delete_messages_on_chat_delete"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  DELETE FROM messages WHERE chat_id = OLD.id;
  RETURN OLD;
END;
$$;


ALTER FUNCTION "public"."delete_messages_on_chat_delete"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."delete_storage_object"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
begin
  if old.type = 'file' then
    perform
      storage.delete_object('user-files', old.storage_path);
  end if;
  return old;
end;
$$;


ALTER FUNCTION "public"."delete_storage_object"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."match_chunks"("query_embedding" "public"."vector", "match_count" integer DEFAULT 20, "document_id" "uuid" DEFAULT NULL::"uuid") RETURNS TABLE("chunk_id" "uuid", "document_id" "uuid", "document_name" "text", "document_type" "text", "chunk_index" integer, "page_number" integer, "content" "text", "similarity" real)
    LANGUAGE "sql" STABLE
    AS $$
  select
    dc.id as chunk_id,
    dc.document_id,
    NULL::text as document_name,
    dc.document_type,
    dc.chunk_index,
    dc.page_number,
    dc.content,
    (1 - (dc.embedding <=> query_embedding))::real as similarity
  from public.document_chunks dc
  where (document_id is null or dc.document_id = document_id)
  order by dc.embedding <=> query_embedding
  limit greatest(1, match_count);
$$;


ALTER FUNCTION "public"."match_chunks"("query_embedding" "public"."vector", "match_count" integer, "document_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."match_chunks_fts"("query_text" "text", "match_count" integer DEFAULT 20, "document_id" "uuid" DEFAULT NULL::"uuid") RETURNS TABLE("chunk_id" "uuid", "document_id" "uuid", "document_name" "text", "document_type" "text", "chunk_index" integer, "page_number" integer, "content" "text", "fts_score" real, "keyword_hits" integer)
    LANGUAGE "sql" STABLE
    AS $$
  with prepared as (
    select
      dc.id as chunk_id,
      dc.document_id,
      NULL::text as document_name,
      dc.document_type,
      dc.chunk_index,
      dc.page_number,
      dc.content,
      ts_rank_cd(
        to_tsvector('simple', coalesce(dc.content, '')),
        websearch_to_tsquery('simple', coalesce(query_text, ''))
      )::real as fts_score,
      (
        length(lower(coalesce(dc.content, ''))) -
        length(replace(lower(coalesce(dc.content, '')), lower(split_part(coalesce(query_text, ''), ' ', 1)), ''))
      )::integer as keyword_hits
    from public.document_chunks dc
    where (document_id is null or dc.document_id = document_id)
      and to_tsvector('simple', coalesce(dc.content, '')) @@ websearch_to_tsquery('simple', coalesce(query_text, ''))
  )
  select
    p.chunk_id,
    p.document_id,
    p.document_name,
    p.document_type,
    p.chunk_index,
    p.page_number,
    p.content,
    p.fts_score,
    greatest(1, p.keyword_hits) as keyword_hits
  from prepared p
  order by p.fts_score desc, p.chunk_index asc
  limit greatest(1, match_count);
$$;


ALTER FUNCTION "public"."match_chunks_fts"("query_text" "text", "match_count" integer, "document_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
begin
  new.updated_at = now();
  return new;
end;
$$;


ALTER FUNCTION "public"."set_updated_at"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."account_snapshots" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "snapshot_date" "date" NOT NULL,
    "total_assets" numeric(18,2) NOT NULL,
    "cash" numeric(18,2) NOT NULL,
    "position_value" numeric(18,2) DEFAULT 0 NOT NULL,
    "total_pnl" numeric(18,2) DEFAULT 0 NOT NULL,
    "total_return_rate" numeric(10,6) DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."account_snapshots" OWNER TO "postgres";


COMMENT ON TABLE "public"."account_snapshots" IS '每日资产快照';



CREATE TABLE IF NOT EXISTS "public"."accounts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "cash" numeric(18,2) DEFAULT 100000.00 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "frozen_cash" numeric(18,2) DEFAULT 0 NOT NULL,
    "auto_invest_enabled" boolean DEFAULT false NOT NULL,
    "auto_invest_reserve" numeric(18,2) DEFAULT 0.00 NOT NULL
);


ALTER TABLE "public"."accounts" OWNER TO "postgres";


COMMENT ON TABLE "public"."accounts" IS '用户资金账户';



COMMENT ON COLUMN "public"."accounts"."user_id" IS '用户ID（对应 auth.users）';



COMMENT ON COLUMN "public"."accounts"."cash" IS '可用现金（元），初始 100,000';



COMMENT ON COLUMN "public"."accounts"."frozen_cash" IS '冻结资金（元），pending 订单锁定';



COMMENT ON COLUMN "public"."accounts"."auto_invest_enabled" IS '余额理财开关：true=闲置现金自动申购货基';



COMMENT ON COLUMN "public"."accounts"."auto_invest_reserve" IS '余额理财预留金额：账户保留的现金，超出部分才自动理财';



CREATE TABLE IF NOT EXISTS "public"."ai_requests" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "prompt" "text" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text" NOT NULL,
    "response" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    CONSTRAINT "ai_requests_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'processing'::"text", 'completed'::"text", 'failed'::"text"])))
);


ALTER TABLE "public"."ai_requests" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."allocation_models" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "version" "text",
    "config" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."allocation_models" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."chats" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "title" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."chats" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."document_chunks" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "document_id" "uuid" NOT NULL,
    "chunk_index" integer NOT NULL,
    "content" "text" NOT NULL,
    "embedding" "public"."vector"(768),
    "page_number" integer,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "document_type" "text" DEFAULT 'other'::"text"
);


ALTER TABLE "public"."document_chunks" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."documents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "file_id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "status" "text" NOT NULL,
    "title" "text",
    "doc_type" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "documents_status_check" CHECK (("status" = ANY (ARRAY['processing'::"text", 'ready'::"text", 'failed'::"text"])))
);


ALTER TABLE "public"."documents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."files" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "name" "text" NOT NULL,
    "type" "text" NOT NULL,
    "parent_id" "uuid",
    "storage_path" "text",
    "mime_type" "text",
    "size" bigint,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "files_type_check" CHECK (("type" = ANY (ARRAY['folder'::"text", 'file'::"text"])))
);


ALTER TABLE "public"."files" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."fund_fee_rules" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "fund_code" character varying(10) NOT NULL,
    "fund_name" character varying(100) NOT NULL,
    "management_fee_rate" numeric(6,4) DEFAULT 0.015 NOT NULL,
    "custody_fee_rate" numeric(6,4) DEFAULT 0.0025 NOT NULL,
    "min_purchase_amount" numeric(18,2) DEFAULT 1.00 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "fund_type" character varying(4) DEFAULT 'otf'::character varying NOT NULL,
    "commission_rate" numeric(6,4) DEFAULT 0.00025 NOT NULL,
    "sales_service_fee_rate" numeric(6,4) DEFAULT 0.0000 NOT NULL,
    "redemption_fee_tiers" "jsonb" DEFAULT '[{"days": 7, "rate": 0.0150}, {"days": 30, "rate": 0.0100}, {"days": 180, "rate": 0.0050}, {"days": 365, "rate": 0.0000}]'::"jsonb" NOT NULL,
    "confirm_delay" integer DEFAULT 1 NOT NULL,
    "redeem_settle_delay" integer DEFAULT 3 NOT NULL,
    "share_class" character varying(1) DEFAULT 'A'::character varying NOT NULL,
    "purchase_fee_tiers" "jsonb",
    CONSTRAINT "fund_fee_rules_fund_type_check" CHECK ((("fund_type")::"text" = ANY ((ARRAY['of'::character varying, 'etf'::character varying])::"text"[])))
);


ALTER TABLE "public"."fund_fee_rules" OWNER TO "postgres";


COMMENT ON TABLE "public"."fund_fee_rules" IS '基金手续费规则（覆盖20只常用场外基金）';



COMMENT ON COLUMN "public"."fund_fee_rules"."fund_type" IS '基金类型: of=场外开放式基金, etf=场内ETF';



COMMENT ON COLUMN "public"."fund_fee_rules"."commission_rate" IS 'ETF券商佣金费率 (如 0.00025=万2.5)';



COMMENT ON COLUMN "public"."fund_fee_rules"."sales_service_fee_rate" IS '销售服务费率（年化），A类=0，C类通常0.2%~0.4%';



COMMENT ON COLUMN "public"."fund_fee_rules"."redemption_fee_tiers" IS '赎回费档位 JSON（新格式）';



COMMENT ON COLUMN "public"."fund_fee_rules"."confirm_delay" IS '申购确认延迟天数 T+N，默认1=T+1';



COMMENT ON COLUMN "public"."fund_fee_rules"."redeem_settle_delay" IS '赎回到账延迟天数 T+N，默认3=T+3';



COMMENT ON COLUMN "public"."fund_fee_rules"."share_class" IS '份额类别: A=A类, C=C类';



CREATE TABLE IF NOT EXISTS "public"."market_indicators" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "symbol" "text",
    "indicator_type" "text",
    "value" numeric,
    "as_of" "date",
    "source" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb"
);


ALTER TABLE "public"."market_indicators" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."message_chunks" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "message_id" "uuid" NOT NULL,
    "chunk_id" "uuid" NOT NULL,
    "confidence" numeric(5,4),
    "metadata" "jsonb" DEFAULT '{}'::"jsonb"
);


ALTER TABLE "public"."message_chunks" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."messages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "chat_id" "uuid" NOT NULL,
    "user_id" "uuid",
    "role" "text" NOT NULL,
    "content" "text" NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "messages_role_check" CHECK (("role" = ANY (ARRAY['user'::"text", 'assistant'::"text", 'system'::"text"])))
);


ALTER TABLE "public"."messages" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."positions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "fund_code" character varying(10) NOT NULL,
    "fund_name" character varying(100) DEFAULT ''::character varying NOT NULL,
    "quantity" numeric(18,2) DEFAULT 0 NOT NULL,
    "cost_price" numeric(18,4) DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "confirm_date" "date",
    "available_date" "date"
);


ALTER TABLE "public"."positions" OWNER TO "postgres";


COMMENT ON TABLE "public"."positions" IS '用户基金持仓';



COMMENT ON COLUMN "public"."positions"."quantity" IS '持有份额';



COMMENT ON COLUMN "public"."positions"."cost_price" IS '加权平均成本价（元/份）';



COMMENT ON COLUMN "public"."positions"."confirm_date" IS '申购确认日期（交易日15:00前为当日，否则为下一交易日）';



COMMENT ON COLUMN "public"."positions"."available_date" IS '份额可赎回日期（T+2）';



CREATE TABLE IF NOT EXISTS "public"."risk_questionnaires" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "version" "text" NOT NULL,
    "questions" "jsonb" NOT NULL,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "chk_questions_array" CHECK ((("jsonb_typeof"("questions") = 'array'::"text") AND ("jsonb_array_length"("questions") > 0)))
);


ALTER TABLE "public"."risk_questionnaires" OWNER TO "postgres";


COMMENT ON TABLE "public"."risk_questionnaires" IS '风险问卷模板表：存储不同版本的风险评估问卷模板';



COMMENT ON COLUMN "public"."risk_questionnaires"."id" IS '主键ID，唯一标识问卷模板';



COMMENT ON COLUMN "public"."risk_questionnaires"."version" IS '问卷版本号，唯一标识不同版本的问卷';



COMMENT ON COLUMN "public"."risk_questionnaires"."questions" IS '问卷题目集合，JSON数组格式，包含题目内容、选项、分值等信息';



COMMENT ON COLUMN "public"."risk_questionnaires"."is_active" IS '是否活跃版本：TRUE-当前使用版本，FALSE-废弃版本';



COMMENT ON COLUMN "public"."risk_questionnaires"."created_at" IS '模板创建时间';



COMMENT ON COLUMN "public"."risk_questionnaires"."updated_at" IS '模板最后更新时间';



COMMENT ON CONSTRAINT "chk_questions_array" ON "public"."risk_questionnaires" IS '检查约束：确保questions字段是非空的JSON数组（至少包含1道题目）';



CREATE TABLE IF NOT EXISTS "public"."trade_flow" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "fund_code" character varying(10) NOT NULL,
    "fund_name" character varying(100) DEFAULT ''::character varying NOT NULL,
    "direction" character varying(4) NOT NULL,
    "price" numeric(18,4) NOT NULL,
    "quantity" numeric(18,2) NOT NULL,
    "amount" numeric(18,2) NOT NULL,
    "fee" numeric(18,2) DEFAULT 0 NOT NULL,
    "trade_time" timestamp with time zone DEFAULT "now"(),
    "trade_pnl" numeric(18,2),
    CONSTRAINT "trade_flow_direction_check" CHECK ((("direction")::"text" = ANY ((ARRAY['buy'::character varying, 'sell'::character varying])::"text"[])))
);


ALTER TABLE "public"."trade_flow" OWNER TO "postgres";


COMMENT ON TABLE "public"."trade_flow" IS '交易流水（成交明细）';



CREATE TABLE IF NOT EXISTS "public"."trade_orders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "fund_code" character varying(10) NOT NULL,
    "fund_name" character varying(100) DEFAULT ''::character varying NOT NULL,
    "direction" character varying(4) NOT NULL,
    "order_type" character varying(10) DEFAULT 'market'::character varying NOT NULL,
    "price" numeric(18,4) NOT NULL,
    "quantity" numeric(18,2) NOT NULL,
    "amount" numeric(18,2) NOT NULL,
    "fee" numeric(18,2) DEFAULT 0 NOT NULL,
    "status" character varying(10) DEFAULT 'completed'::character varying NOT NULL,
    "reject_reason" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "confirm_date" "date",
    "fund_type" character varying(4) DEFAULT 'of'::character varying,
    CONSTRAINT "trade_orders_direction_check" CHECK ((("direction")::"text" = ANY ((ARRAY['buy'::character varying, 'sell'::character varying])::"text"[]))),
    CONSTRAINT "trade_orders_fund_type_check" CHECK ((("fund_type")::"text" = ANY ((ARRAY['of'::character varying, 'etf'::character varying])::"text"[]))),
    CONSTRAINT "trade_orders_order_type_check" CHECK ((("order_type")::"text" = ANY ((ARRAY['market'::character varying, 'limit'::character varying])::"text"[]))),
    CONSTRAINT "trade_orders_status_check" CHECK ((("status")::"text" = ANY ((ARRAY['pending'::character varying, 'completed'::character varying, 'cancelled'::character varying, 'rejected'::character varying, 'reserved'::character varying])::"text"[])))
);


ALTER TABLE "public"."trade_orders" OWNER TO "postgres";


COMMENT ON TABLE "public"."trade_orders" IS '交易订单/委托记录';



COMMENT ON COLUMN "public"."trade_orders"."direction" IS '方向：buy-买入, sell-卖出';



COMMENT ON COLUMN "public"."trade_orders"."status" IS '状态：pending-待确认, completed-已完成, cancelled-已撤销, rejected-已拒绝, reserved-预约待执行';



COMMENT ON COLUMN "public"."trade_orders"."confirm_date" IS '场外基金订单确认日期：交易日15:00前为当日，15:00后/非交易日为下一个交易日';



COMMENT ON COLUMN "public"."trade_orders"."fund_type" IS '基金类型: of=场外开放式基金, etf=场内ETF';



CREATE TABLE IF NOT EXISTS "public"."user_allocations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "model_id" "uuid" NOT NULL,
    "allocation" "jsonb" NOT NULL,
    "over_allocated" boolean,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."user_allocations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."user_risk_answers" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "questionnaire_id" "uuid" NOT NULL,
    "answers" "jsonb" NOT NULL,
    "is_completed" boolean DEFAULT true,
    "session_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "chk_answers_object" CHECK (("jsonb_typeof"("answers") = 'object'::"text"))
);


ALTER TABLE "public"."user_risk_answers" OWNER TO "postgres";


COMMENT ON TABLE "public"."user_risk_answers" IS '用户问卷答案表：存储用户填写风险问卷的答案记录';



COMMENT ON COLUMN "public"."user_risk_answers"."id" IS '主键ID，唯一标识用户答题记录';



COMMENT ON COLUMN "public"."user_risk_answers"."user_id" IS '用户ID，关联用户表的主键';



COMMENT ON COLUMN "public"."user_risk_answers"."questionnaire_id" IS '关联的问卷模板ID，关联risk_questionnaires表';



COMMENT ON COLUMN "public"."user_risk_answers"."answers" IS '用户答题结果，JSON对象格式，key为题目ID，value为用户选择的答案/分值';



COMMENT ON COLUMN "public"."user_risk_answers"."is_completed" IS '是否已完成：TRUE-完整提交，FALSE-中途退出未提交';



COMMENT ON COLUMN "public"."user_risk_answers"."session_id" IS '答题会话ID，用于标识同一次答题过程';



COMMENT ON COLUMN "public"."user_risk_answers"."created_at" IS '答题记录创建/提交时间';



COMMENT ON CONSTRAINT "chk_answers_object" ON "public"."user_risk_answers" IS '检查约束：确保answers字段是JSON对象（符合题目ID:答案的键值对格式）';



CREATE TABLE IF NOT EXISTS "public"."user_risk_profiles" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "answer_id" "uuid",
    "risk_level" "public"."risk_level" NOT NULL,
    "confidence_score" numeric(3,2),
    "dimension_scores" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "ai_summary" "jsonb",
    "source" "public"."profile_source" NOT NULL,
    "model_version" "text" NOT NULL,
    "is_active" boolean DEFAULT true,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "expires_at" timestamp with time zone,
    "total_score" numeric(3,2),
    "weighted_scores" "jsonb" DEFAULT '{}'::"jsonb",
    CONSTRAINT "chk_confidence_score_range" CHECK ((("confidence_score" IS NULL) OR (("confidence_score" >= (0)::numeric) AND ("confidence_score" <= (1)::numeric))))
);


ALTER TABLE "public"."user_risk_profiles" OWNER TO "postgres";


COMMENT ON TABLE "public"."user_risk_profiles" IS '用户风险画像表：存储用户的风险评估结果（核心表）';



COMMENT ON COLUMN "public"."user_risk_profiles"."id" IS '主键ID，唯一标识一条风险画像记录';



COMMENT ON COLUMN "public"."user_risk_profiles"."user_id" IS '用户ID，关联用户表的主键';



COMMENT ON COLUMN "public"."user_risk_profiles"."answer_id" IS '关联的答题记录ID，来源为questionnaire时该字段非空';



COMMENT ON COLUMN "public"."user_risk_profiles"."risk_level" IS '用户风险等级，取值为risk_level枚举类型';



COMMENT ON COLUMN "public"."user_risk_profiles"."confidence_score" IS '画像置信度分数：0-1之间，数值越高表示画像越准确';



COMMENT ON COLUMN "public"."user_risk_profiles"."dimension_scores" IS '5个维度的详细分数，JSON对象格式（如风险承受力、投资经验等维度）';



COMMENT ON COLUMN "public"."user_risk_profiles"."ai_summary" IS 'AI可读摘要，JSON对象格式，包含用户风险总结和提示词';



COMMENT ON COLUMN "public"."user_risk_profiles"."source" IS '画像来源，取值为profile_source枚举类型';



COMMENT ON COLUMN "public"."user_risk_profiles"."model_version" IS '生成该画像的算法/模型版本号，用于追踪版本迭代';



COMMENT ON COLUMN "public"."user_risk_profiles"."is_active" IS '是否为当前生效的画像：TRUE-当前使用，FALSE-历史画像';



COMMENT ON COLUMN "public"."user_risk_profiles"."metadata" IS '扩展元数据：存储非核心的额外信息，便于扩展';



COMMENT ON COLUMN "public"."user_risk_profiles"."created_at" IS '画像创建时间';



COMMENT ON COLUMN "public"."user_risk_profiles"."expires_at" IS '画像过期时间：NULL表示永久有效，非NULL表示到期后失效';



COMMENT ON COLUMN "public"."user_risk_profiles"."total_score" IS '加权总分：1.0-3.0，用于确定风险等级';



COMMENT ON COLUMN "public"."user_risk_profiles"."weighted_scores" IS '加权后的各维度分数，JSON对象格式';



COMMENT ON CONSTRAINT "chk_confidence_score_range" ON "public"."user_risk_profiles" IS '检查约束：确保置信度分数在0-1之间（NULL表示无分数）';



CREATE TABLE IF NOT EXISTS "public"."watchlist" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "fund_code" character varying(10) NOT NULL,
    "fund_name" character varying(100),
    "sort_order" integer DEFAULT 0,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."watchlist" OWNER TO "postgres";


COMMENT ON TABLE "public"."watchlist" IS '用户自选股/关注列表';



COMMENT ON COLUMN "public"."watchlist"."user_id" IS '用户ID';



COMMENT ON COLUMN "public"."watchlist"."fund_code" IS '基金代码（如512890）';



COMMENT ON COLUMN "public"."watchlist"."fund_name" IS '基金名称（冗余存储）';



COMMENT ON COLUMN "public"."watchlist"."sort_order" IS '排序顺序';



ALTER TABLE ONLY "public"."account_snapshots"
    ADD CONSTRAINT "account_snapshots_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."account_snapshots"
    ADD CONSTRAINT "account_snapshots_user_id_snapshot_date_key" UNIQUE ("user_id", "snapshot_date");



ALTER TABLE ONLY "public"."accounts"
    ADD CONSTRAINT "accounts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."accounts"
    ADD CONSTRAINT "accounts_user_id_key" UNIQUE ("user_id");



ALTER TABLE ONLY "public"."ai_requests"
    ADD CONSTRAINT "ai_requests_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."allocation_models"
    ADD CONSTRAINT "allocation_models_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."chats"
    ADD CONSTRAINT "chats_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."document_chunks"
    ADD CONSTRAINT "document_chunks_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."files"
    ADD CONSTRAINT "files_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."fund_fee_rules"
    ADD CONSTRAINT "fund_fee_rules_fund_code_key" UNIQUE ("fund_code");



ALTER TABLE ONLY "public"."fund_fee_rules"
    ADD CONSTRAINT "fund_fee_rules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."market_indicators"
    ADD CONSTRAINT "market_indicators_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."message_chunks"
    ADD CONSTRAINT "message_chunks_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."positions"
    ADD CONSTRAINT "positions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."positions"
    ADD CONSTRAINT "positions_user_id_fund_code_key" UNIQUE ("user_id", "fund_code");



ALTER TABLE ONLY "public"."risk_questionnaires"
    ADD CONSTRAINT "risk_questionnaires_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."trade_flow"
    ADD CONSTRAINT "trade_flow_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."trade_orders"
    ADD CONSTRAINT "trade_orders_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_risk_answers"
    ADD CONSTRAINT "uniq_user_questionnaire" UNIQUE ("user_id", "questionnaire_id");



COMMENT ON CONSTRAINT "uniq_user_questionnaire" ON "public"."user_risk_answers" IS '唯一约束：一个用户只能对同一个问卷模板提交一份答案';



ALTER TABLE ONLY "public"."user_allocations"
    ADD CONSTRAINT "user_allocations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_risk_answers"
    ADD CONSTRAINT "user_risk_answers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_risk_profiles"
    ADD CONSTRAINT "user_risk_profiles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."watchlist"
    ADD CONSTRAINT "watchlist_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."watchlist"
    ADD CONSTRAINT "watchlist_user_id_fund_code_key" UNIQUE ("user_id", "fund_code");



CREATE INDEX "idx_accounts_user" ON "public"."accounts" USING "btree" ("user_id");



CREATE INDEX "idx_ai_requests_created_at" ON "public"."ai_requests" USING "btree" ("created_at");



CREATE INDEX "idx_ai_requests_status" ON "public"."ai_requests" USING "btree" ("status");



CREATE INDEX "idx_chunks_document_id" ON "public"."document_chunks" USING "btree" ("document_id");



CREATE INDEX "idx_chunks_embedding" ON "public"."document_chunks" USING "ivfflat" ("embedding" "public"."vector_cosine_ops");



CREATE INDEX "idx_documents_file_id" ON "public"."documents" USING "btree" ("file_id");



CREATE INDEX "idx_documents_status" ON "public"."documents" USING "btree" ("status");



CREATE INDEX "idx_documents_user_id" ON "public"."documents" USING "btree" ("user_id");



CREATE INDEX "idx_files_parent_id" ON "public"."files" USING "btree" ("parent_id");



CREATE INDEX "idx_files_type" ON "public"."files" USING "btree" ("type");



CREATE INDEX "idx_files_user_id" ON "public"."files" USING "btree" ("user_id");



CREATE INDEX "idx_message_chunks_chunk_id" ON "public"."message_chunks" USING "btree" ("chunk_id");



CREATE INDEX "idx_message_chunks_message_id" ON "public"."message_chunks" USING "btree" ("message_id");



CREATE INDEX "idx_messages_chat_id" ON "public"."messages" USING "btree" ("chat_id");



CREATE INDEX "idx_messages_created_at" ON "public"."messages" USING "btree" ("created_at");



CREATE INDEX "idx_positions_code" ON "public"."positions" USING "btree" ("fund_code");



CREATE INDEX "idx_positions_user" ON "public"."positions" USING "btree" ("user_id");



CREATE INDEX "idx_questionnaires_active" ON "public"."risk_questionnaires" USING "btree" ("is_active", "version");



COMMENT ON INDEX "public"."idx_questionnaires_active" IS '索引：快速筛选活跃/非活跃的问卷模板，结合版本号查询';



CREATE INDEX "idx_risk_profiles_user_active" ON "public"."user_risk_profiles" USING "btree" ("user_id", "is_active");



COMMENT ON INDEX "public"."idx_risk_profiles_user_active" IS '索引：快速查询指定用户当前生效/失效的风险画像';



CREATE INDEX "idx_snapshots_user" ON "public"."account_snapshots" USING "btree" ("user_id");



CREATE INDEX "idx_snapshots_user_date" ON "public"."account_snapshots" USING "btree" ("user_id", "snapshot_date" DESC);



CREATE INDEX "idx_trade_flow_code" ON "public"."trade_flow" USING "btree" ("fund_code");



CREATE INDEX "idx_trade_flow_user" ON "public"."trade_flow" USING "btree" ("user_id");



CREATE INDEX "idx_trade_flow_user_time" ON "public"."trade_flow" USING "btree" ("user_id", "trade_time" DESC);



CREATE INDEX "idx_trade_orders_created" ON "public"."trade_orders" USING "btree" ("created_at" DESC);



CREATE INDEX "idx_trade_orders_status" ON "public"."trade_orders" USING "btree" ("status");



CREATE INDEX "idx_trade_orders_user" ON "public"."trade_orders" USING "btree" ("user_id");



CREATE INDEX "idx_user_answers_questionnaire" ON "public"."user_risk_answers" USING "btree" ("questionnaire_id");



COMMENT ON INDEX "public"."idx_user_answers_questionnaire" IS '索引：按问卷ID快速检索该问卷的所有用户答题记录';



CREATE INDEX "idx_user_answers_user" ON "public"."user_risk_answers" USING "btree" ("user_id");



COMMENT ON INDEX "public"."idx_user_answers_user" IS '索引：按用户ID快速检索该用户的所有答题记录';



CREATE INDEX "idx_watchlist_code" ON "public"."watchlist" USING "btree" ("fund_code");



CREATE INDEX "idx_watchlist_user" ON "public"."watchlist" USING "btree" ("user_id");



CREATE UNIQUE INDEX "uniq_active_profile_per_user" ON "public"."user_risk_profiles" USING "btree" ("user_id") WHERE ("is_active" = true);



COMMENT ON INDEX "public"."uniq_active_profile_per_user" IS '唯一索引：强制一个用户只能有一条生效的风险画像记录';



CREATE UNIQUE INDEX "uniq_questionnaires_version" ON "public"."risk_questionnaires" USING "btree" ("version");



COMMENT ON INDEX "public"."uniq_questionnaires_version" IS '唯一索引：确保问卷版本号不重复';



CREATE OR REPLACE TRIGGER "trigger_delete_message_chunks" BEFORE DELETE ON "public"."messages" FOR EACH ROW EXECUTE FUNCTION "public"."delete_message_chunks_on_message_delete"();



CREATE OR REPLACE TRIGGER "trigger_delete_messages" BEFORE DELETE ON "public"."chats" FOR EACH ROW EXECUTE FUNCTION "public"."delete_messages_on_chat_delete"();



ALTER TABLE ONLY "public"."chats"
    ADD CONSTRAINT "chats_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."document_chunks"
    ADD CONSTRAINT "document_chunks_document_id_fkey" FOREIGN KEY ("document_id") REFERENCES "public"."documents"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_file_id_fkey" FOREIGN KEY ("file_id") REFERENCES "public"."files"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."files"
    ADD CONSTRAINT "files_parent_id_fkey" FOREIGN KEY ("parent_id") REFERENCES "public"."files"("id");



ALTER TABLE ONLY "public"."files"
    ADD CONSTRAINT "files_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."user_risk_profiles"
    ADD CONSTRAINT "fk_risk_profiles_answer" FOREIGN KEY ("answer_id") REFERENCES "public"."user_risk_answers"("id");



COMMENT ON CONSTRAINT "fk_risk_profiles_answer" ON "public"."user_risk_profiles" IS '外键约束：风险画像关联到对应的答题记录（若来源为问卷）';



ALTER TABLE ONLY "public"."user_risk_answers"
    ADD CONSTRAINT "fk_user_answers_questionnaire" FOREIGN KEY ("questionnaire_id") REFERENCES "public"."risk_questionnaires"("id");



COMMENT ON CONSTRAINT "fk_user_answers_questionnaire" ON "public"."user_risk_answers" IS '外键约束：答题记录关联到对应的问卷模板';



ALTER TABLE ONLY "public"."message_chunks"
    ADD CONSTRAINT "message_chunks_chunk_id_fkey" FOREIGN KEY ("chunk_id") REFERENCES "public"."document_chunks"("id");



ALTER TABLE ONLY "public"."message_chunks"
    ADD CONSTRAINT "message_chunks_message_id_fkey" FOREIGN KEY ("message_id") REFERENCES "public"."messages"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_chat_id_fkey" FOREIGN KEY ("chat_id") REFERENCES "public"."chats"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."user_allocations"
    ADD CONSTRAINT "user_allocations_model_id_fkey" FOREIGN KEY ("model_id") REFERENCES "public"."allocation_models"("id");



ALTER TABLE ONLY "public"."user_allocations"
    ADD CONSTRAINT "user_allocations_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."user_risk_answers"
    ADD CONSTRAINT "user_risk_answers_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON UPDATE RESTRICT;



ALTER TABLE ONLY "public"."user_risk_profiles"
    ADD CONSTRAINT "user_risk_profiles_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON UPDATE RESTRICT;



ALTER TABLE "public"."account_snapshots" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."accounts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."ai_requests" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."allocation_models" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."chats" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "chats_delete_own" ON "public"."chats" FOR DELETE USING (("user_id" = "auth"."uid"()));



CREATE POLICY "chats_insert_own" ON "public"."chats" FOR INSERT WITH CHECK (("user_id" = "auth"."uid"()));



CREATE POLICY "chats_select_own" ON "public"."chats" FOR SELECT USING (("user_id" = "auth"."uid"()));



CREATE POLICY "chats_update_own" ON "public"."chats" FOR UPDATE USING (("user_id" = "auth"."uid"()));



ALTER TABLE "public"."document_chunks" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."documents" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "documents_delete_own" ON "public"."documents" FOR DELETE USING (("user_id" = "auth"."uid"()));



CREATE POLICY "documents_insert_own" ON "public"."documents" FOR INSERT WITH CHECK (("user_id" = "auth"."uid"()));



CREATE POLICY "documents_select_via_files" ON "public"."documents" FOR SELECT USING (("user_id" = "auth"."uid"()));



CREATE POLICY "documents_update_own" ON "public"."documents" FOR UPDATE USING (("user_id" = "auth"."uid"()));



ALTER TABLE "public"."files" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "files_delete_own" ON "public"."files" FOR DELETE USING (("user_id" = "auth"."uid"()));



CREATE POLICY "files_insert_own" ON "public"."files" FOR INSERT WITH CHECK (("user_id" = "auth"."uid"()));



CREATE POLICY "files_select_own" ON "public"."files" FOR SELECT USING (("user_id" = "auth"."uid"()));



CREATE POLICY "files_update_own" ON "public"."files" FOR SELECT USING (("user_id" = "auth"."uid"()));



ALTER TABLE "public"."fund_fee_rules" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."market_indicators" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."message_chunks" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."messages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."positions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."risk_questionnaires" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."trade_flow" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."trade_orders" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."user_allocations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."user_risk_answers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."user_risk_profiles" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."watchlist" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "用户创建自己文档的切片" ON "public"."document_chunks" FOR INSERT WITH CHECK (("document_id" IN ( SELECT "documents"."id"
   FROM "public"."documents"
  WHERE ("documents"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户创建自己消息的切片" ON "public"."message_chunks" FOR INSERT WITH CHECK (("message_id" IN ( SELECT "m"."id"
   FROM ("public"."messages" "m"
     JOIN "public"."chats" "c" ON (("c"."id" = "m"."chat_id")))
  WHERE ("c"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户创建自己的会话" ON "public"."chats" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "用户创建自己的文件" ON "public"."files" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "用户创建自己的文档" ON "public"."documents" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "用户创建自己的消息" ON "public"."messages" FOR INSERT WITH CHECK (("chat_id" IN ( SELECT "chats"."id"
   FROM "public"."chats"
  WHERE ("chats"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户创建自己的资产配置" ON "public"."user_allocations" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "用户创建自己的风险画像" ON "public"."user_risk_profiles" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "用户创建自己的风险答题" ON "public"."user_risk_answers" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "用户删除自己文档的切片" ON "public"."document_chunks" FOR DELETE USING (("document_id" IN ( SELECT "documents"."id"
   FROM "public"."documents"
  WHERE ("documents"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户删除自己消息的切片" ON "public"."message_chunks" FOR DELETE USING (("message_id" IN ( SELECT "m"."id"
   FROM ("public"."messages" "m"
     JOIN "public"."chats" "c" ON (("c"."id" = "m"."chat_id")))
  WHERE ("c"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户删除自己的会话" ON "public"."chats" FOR DELETE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户删除自己的文件" ON "public"."files" FOR DELETE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户删除自己的文档" ON "public"."documents" FOR DELETE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户删除自己的消息" ON "public"."messages" FOR DELETE USING (("chat_id" IN ( SELECT "chats"."id"
   FROM "public"."chats"
  WHERE ("chats"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户删除自己的资产配置" ON "public"."user_allocations" FOR DELETE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户删除自己的风险画像" ON "public"."user_risk_profiles" FOR DELETE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户删除自己的风险答题" ON "public"."user_risk_answers" FOR DELETE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户更新自己的会话" ON "public"."chats" FOR UPDATE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户更新自己的资产配置" ON "public"."user_allocations" FOR UPDATE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户更新自己的风险画像" ON "public"."user_risk_profiles" FOR UPDATE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户更新自己的风险答题" ON "public"."user_risk_answers" FOR UPDATE USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户查看自己文档的切片" ON "public"."document_chunks" FOR SELECT USING (("document_id" IN ( SELECT "documents"."id"
   FROM "public"."documents"
  WHERE ("documents"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户查看自己消息的切片" ON "public"."message_chunks" FOR SELECT USING (("message_id" IN ( SELECT "m"."id"
   FROM ("public"."messages" "m"
     JOIN "public"."chats" "c" ON (("c"."id" = "m"."chat_id")))
  WHERE ("c"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户查看自己的会话" ON "public"."chats" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户查看自己的文件" ON "public"."files" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户查看自己的文档" ON "public"."documents" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户查看自己的消息" ON "public"."messages" FOR SELECT USING (("chat_id" IN ( SELECT "chats"."id"
   FROM "public"."chats"
  WHERE ("chats"."user_id" = "auth"."uid"()))));



CREATE POLICY "用户查看自己的资产配置" ON "public"."user_allocations" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户查看自己的风险画像" ON "public"."user_risk_profiles" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "用户查看自己的风险答题" ON "public"."user_risk_answers" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "认证用户可查看AI请求日志" ON "public"."ai_requests" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));



CREATE POLICY "认证用户可查看市场指标" ON "public"."market_indicators" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));



CREATE POLICY "认证用户可查看资产配置模型" ON "public"."allocation_models" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));



CREATE POLICY "认证用户可查看风险问卷" ON "public"."risk_questionnaires" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));





ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";


GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_in"("cstring", "oid", integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_in"("cstring", "oid", integer) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_in"("cstring", "oid", integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_in"("cstring", "oid", integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_out"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_out"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_out"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_out"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_recv"("internal", "oid", integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_recv"("internal", "oid", integer) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_recv"("internal", "oid", integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_recv"("internal", "oid", integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_send"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_send"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_send"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_send"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_typmod_in"("cstring"[]) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_typmod_in"("cstring"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_typmod_in"("cstring"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_typmod_in"("cstring"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_in"("cstring", "oid", integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_in"("cstring", "oid", integer) TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_in"("cstring", "oid", integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_in"("cstring", "oid", integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_out"("public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_out"("public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_out"("public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_out"("public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_recv"("internal", "oid", integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_recv"("internal", "oid", integer) TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_recv"("internal", "oid", integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_recv"("internal", "oid", integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_send"("public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_send"("public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_send"("public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_send"("public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_typmod_in"("cstring"[]) TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_typmod_in"("cstring"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_typmod_in"("cstring"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_typmod_in"("cstring"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_in"("cstring", "oid", integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_in"("cstring", "oid", integer) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_in"("cstring", "oid", integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_in"("cstring", "oid", integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_out"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_out"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_out"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_out"("public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_recv"("internal", "oid", integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_recv"("internal", "oid", integer) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_recv"("internal", "oid", integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_recv"("internal", "oid", integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_send"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_send"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_send"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_send"("public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_typmod_in"("cstring"[]) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_typmod_in"("cstring"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_typmod_in"("cstring"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_typmod_in"("cstring"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_halfvec"(real[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(real[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(real[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(real[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(real[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(real[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(real[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(real[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_vector"(real[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_vector"(real[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_vector"(real[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_vector"(real[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_halfvec"(double precision[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(double precision[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(double precision[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(double precision[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(double precision[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(double precision[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(double precision[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(double precision[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_vector"(double precision[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_vector"(double precision[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_vector"(double precision[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_vector"(double precision[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_halfvec"(integer[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(integer[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(integer[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(integer[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(integer[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(integer[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(integer[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(integer[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_vector"(integer[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_vector"(integer[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_vector"(integer[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_vector"(integer[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_halfvec"(numeric[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(numeric[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(numeric[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_halfvec"(numeric[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(numeric[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(numeric[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(numeric[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_sparsevec"(numeric[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."array_to_vector"(numeric[], integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."array_to_vector"(numeric[], integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."array_to_vector"(numeric[], integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."array_to_vector"(numeric[], integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_to_float4"("public"."halfvec", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_to_float4"("public"."halfvec", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_to_float4"("public"."halfvec", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_to_float4"("public"."halfvec", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec"("public"."halfvec", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec"("public"."halfvec", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec"("public"."halfvec", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec"("public"."halfvec", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_to_sparsevec"("public"."halfvec", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_to_sparsevec"("public"."halfvec", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_to_sparsevec"("public"."halfvec", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_to_sparsevec"("public"."halfvec", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_to_vector"("public"."halfvec", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_to_vector"("public"."halfvec", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_to_vector"("public"."halfvec", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_to_vector"("public"."halfvec", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_to_halfvec"("public"."sparsevec", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_to_halfvec"("public"."sparsevec", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_to_halfvec"("public"."sparsevec", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_to_halfvec"("public"."sparsevec", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec"("public"."sparsevec", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec"("public"."sparsevec", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec"("public"."sparsevec", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec"("public"."sparsevec", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_to_vector"("public"."sparsevec", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_to_vector"("public"."sparsevec", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_to_vector"("public"."sparsevec", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_to_vector"("public"."sparsevec", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_to_float4"("public"."vector", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_to_float4"("public"."vector", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_to_float4"("public"."vector", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_to_float4"("public"."vector", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_to_halfvec"("public"."vector", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_to_halfvec"("public"."vector", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_to_halfvec"("public"."vector", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_to_halfvec"("public"."vector", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_to_sparsevec"("public"."vector", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_to_sparsevec"("public"."vector", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_to_sparsevec"("public"."vector", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_to_sparsevec"("public"."vector", integer, boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector"("public"."vector", integer, boolean) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector"("public"."vector", integer, boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."vector"("public"."vector", integer, boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector"("public"."vector", integer, boolean) TO "service_role";

























































































































































GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."binary_quantize"("public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."check_parent_is_folder"() TO "anon";
GRANT ALL ON FUNCTION "public"."check_parent_is_folder"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."check_parent_is_folder"() TO "service_role";



GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."cosine_distance"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."delete_chat_messages"() TO "anon";
GRANT ALL ON FUNCTION "public"."delete_chat_messages"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."delete_chat_messages"() TO "service_role";



GRANT ALL ON FUNCTION "public"."delete_message_chunks_on_message_delete"() TO "anon";
GRANT ALL ON FUNCTION "public"."delete_message_chunks_on_message_delete"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."delete_message_chunks_on_message_delete"() TO "service_role";



GRANT ALL ON FUNCTION "public"."delete_messages_on_chat_delete"() TO "anon";
GRANT ALL ON FUNCTION "public"."delete_messages_on_chat_delete"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."delete_messages_on_chat_delete"() TO "service_role";



GRANT ALL ON FUNCTION "public"."delete_storage_object"() TO "anon";
GRANT ALL ON FUNCTION "public"."delete_storage_object"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."delete_storage_object"() TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_accum"(double precision[], "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_accum"(double precision[], "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_accum"(double precision[], "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_accum"(double precision[], "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_add"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_add"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_add"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_add"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_avg"(double precision[]) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_avg"(double precision[]) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_avg"(double precision[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_avg"(double precision[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_cmp"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_cmp"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_cmp"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_cmp"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_combine"(double precision[], double precision[]) TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_combine"(double precision[], double precision[]) TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_combine"(double precision[], double precision[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_combine"(double precision[], double precision[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_concat"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_concat"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_concat"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_concat"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_eq"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_eq"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_eq"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_eq"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_ge"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_ge"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_ge"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_ge"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_gt"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_gt"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_gt"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_gt"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_l2_squared_distance"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_l2_squared_distance"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_l2_squared_distance"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_l2_squared_distance"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_le"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_le"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_le"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_le"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_lt"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_lt"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_lt"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_lt"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_mul"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_mul"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_mul"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_mul"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_ne"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_ne"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_ne"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_ne"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_negative_inner_product"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_negative_inner_product"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_negative_inner_product"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_negative_inner_product"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_spherical_distance"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_spherical_distance"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_spherical_distance"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_spherical_distance"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."halfvec_sub"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."halfvec_sub"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."halfvec_sub"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."halfvec_sub"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."hamming_distance"(bit, bit) TO "postgres";
GRANT ALL ON FUNCTION "public"."hamming_distance"(bit, bit) TO "anon";
GRANT ALL ON FUNCTION "public"."hamming_distance"(bit, bit) TO "authenticated";
GRANT ALL ON FUNCTION "public"."hamming_distance"(bit, bit) TO "service_role";



GRANT ALL ON FUNCTION "public"."hnsw_bit_support"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."hnsw_bit_support"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."hnsw_bit_support"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."hnsw_bit_support"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."hnsw_halfvec_support"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."hnsw_halfvec_support"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."hnsw_halfvec_support"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."hnsw_halfvec_support"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."hnsw_sparsevec_support"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."hnsw_sparsevec_support"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."hnsw_sparsevec_support"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."hnsw_sparsevec_support"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."hnswhandler"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."hnswhandler"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."hnswhandler"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."hnswhandler"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."inner_product"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."inner_product"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."inner_product"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."inner_product"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."ivfflat_bit_support"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."ivfflat_bit_support"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."ivfflat_bit_support"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."ivfflat_bit_support"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."ivfflat_halfvec_support"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."ivfflat_halfvec_support"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."ivfflat_halfvec_support"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."ivfflat_halfvec_support"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."ivfflathandler"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."ivfflathandler"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."ivfflathandler"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."ivfflathandler"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."jaccard_distance"(bit, bit) TO "postgres";
GRANT ALL ON FUNCTION "public"."jaccard_distance"(bit, bit) TO "anon";
GRANT ALL ON FUNCTION "public"."jaccard_distance"(bit, bit) TO "authenticated";
GRANT ALL ON FUNCTION "public"."jaccard_distance"(bit, bit) TO "service_role";



GRANT ALL ON FUNCTION "public"."l1_distance"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l1_distance"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l1_distance"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l1_distance"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_distance"("public"."halfvec", "public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."halfvec", "public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."halfvec", "public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."halfvec", "public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_distance"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_distance"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_distance"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_norm"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_norm"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_norm"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_norm"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_norm"("public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_norm"("public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_norm"("public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_norm"("public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."l2_normalize"("public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."match_chunks"("query_embedding" "public"."vector", "match_count" integer, "document_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."match_chunks"("query_embedding" "public"."vector", "match_count" integer, "document_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."match_chunks"("query_embedding" "public"."vector", "match_count" integer, "document_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."match_chunks_fts"("query_text" "text", "match_count" integer, "document_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."match_chunks_fts"("query_text" "text", "match_count" integer, "document_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."match_chunks_fts"("query_text" "text", "match_count" integer, "document_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_cmp"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_cmp"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_cmp"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_cmp"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_eq"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_eq"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_eq"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_eq"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_ge"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_ge"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_ge"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_ge"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_gt"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_gt"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_gt"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_gt"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_l2_squared_distance"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_l2_squared_distance"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_l2_squared_distance"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_l2_squared_distance"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_le"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_le"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_le"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_le"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_lt"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_lt"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_lt"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_lt"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_ne"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_ne"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_ne"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_ne"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sparsevec_negative_inner_product"("public"."sparsevec", "public"."sparsevec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sparsevec_negative_inner_product"("public"."sparsevec", "public"."sparsevec") TO "anon";
GRANT ALL ON FUNCTION "public"."sparsevec_negative_inner_product"("public"."sparsevec", "public"."sparsevec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sparsevec_negative_inner_product"("public"."sparsevec", "public"."sparsevec") TO "service_role";



GRANT ALL ON FUNCTION "public"."subvector"("public"."halfvec", integer, integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."subvector"("public"."halfvec", integer, integer) TO "anon";
GRANT ALL ON FUNCTION "public"."subvector"("public"."halfvec", integer, integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."subvector"("public"."halfvec", integer, integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."subvector"("public"."vector", integer, integer) TO "postgres";
GRANT ALL ON FUNCTION "public"."subvector"("public"."vector", integer, integer) TO "anon";
GRANT ALL ON FUNCTION "public"."subvector"("public"."vector", integer, integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."subvector"("public"."vector", integer, integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_accum"(double precision[], "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_accum"(double precision[], "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_accum"(double precision[], "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_accum"(double precision[], "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_add"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_add"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_add"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_add"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_avg"(double precision[]) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_avg"(double precision[]) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_avg"(double precision[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_avg"(double precision[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_cmp"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_cmp"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_cmp"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_cmp"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_combine"(double precision[], double precision[]) TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_combine"(double precision[], double precision[]) TO "anon";
GRANT ALL ON FUNCTION "public"."vector_combine"(double precision[], double precision[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_combine"(double precision[], double precision[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_concat"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_concat"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_concat"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_concat"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_dims"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_dims"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_dims"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_dims"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_dims"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_dims"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_dims"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_dims"("public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_eq"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_eq"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_eq"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_eq"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_ge"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_ge"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_ge"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_ge"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_gt"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_gt"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_gt"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_gt"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_l2_squared_distance"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_l2_squared_distance"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_l2_squared_distance"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_l2_squared_distance"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_le"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_le"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_le"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_le"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_lt"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_lt"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_lt"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_lt"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_mul"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_mul"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_mul"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_mul"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_ne"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_ne"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_ne"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_ne"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_negative_inner_product"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_negative_inner_product"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_negative_inner_product"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_negative_inner_product"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_norm"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_norm"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_norm"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_norm"("public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_spherical_distance"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_spherical_distance"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_spherical_distance"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_spherical_distance"("public"."vector", "public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."vector_sub"("public"."vector", "public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."vector_sub"("public"."vector", "public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."vector_sub"("public"."vector", "public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."vector_sub"("public"."vector", "public"."vector") TO "service_role";












GRANT ALL ON FUNCTION "public"."avg"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."avg"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."avg"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."avg"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."avg"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."avg"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."avg"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."avg"("public"."vector") TO "service_role";



GRANT ALL ON FUNCTION "public"."sum"("public"."halfvec") TO "postgres";
GRANT ALL ON FUNCTION "public"."sum"("public"."halfvec") TO "anon";
GRANT ALL ON FUNCTION "public"."sum"("public"."halfvec") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sum"("public"."halfvec") TO "service_role";



GRANT ALL ON FUNCTION "public"."sum"("public"."vector") TO "postgres";
GRANT ALL ON FUNCTION "public"."sum"("public"."vector") TO "anon";
GRANT ALL ON FUNCTION "public"."sum"("public"."vector") TO "authenticated";
GRANT ALL ON FUNCTION "public"."sum"("public"."vector") TO "service_role";









GRANT ALL ON TABLE "public"."account_snapshots" TO "anon";
GRANT ALL ON TABLE "public"."account_snapshots" TO "authenticated";
GRANT ALL ON TABLE "public"."account_snapshots" TO "service_role";



GRANT ALL ON TABLE "public"."accounts" TO "anon";
GRANT ALL ON TABLE "public"."accounts" TO "authenticated";
GRANT ALL ON TABLE "public"."accounts" TO "service_role";



GRANT ALL ON TABLE "public"."ai_requests" TO "anon";
GRANT ALL ON TABLE "public"."ai_requests" TO "authenticated";
GRANT ALL ON TABLE "public"."ai_requests" TO "service_role";



GRANT ALL ON TABLE "public"."allocation_models" TO "anon";
GRANT ALL ON TABLE "public"."allocation_models" TO "authenticated";
GRANT ALL ON TABLE "public"."allocation_models" TO "service_role";



GRANT ALL ON TABLE "public"."chats" TO "anon";
GRANT ALL ON TABLE "public"."chats" TO "authenticated";
GRANT ALL ON TABLE "public"."chats" TO "service_role";



GRANT ALL ON TABLE "public"."document_chunks" TO "anon";
GRANT ALL ON TABLE "public"."document_chunks" TO "authenticated";
GRANT ALL ON TABLE "public"."document_chunks" TO "service_role";



GRANT ALL ON TABLE "public"."documents" TO "anon";
GRANT ALL ON TABLE "public"."documents" TO "authenticated";
GRANT ALL ON TABLE "public"."documents" TO "service_role";



GRANT ALL ON TABLE "public"."files" TO "anon";
GRANT ALL ON TABLE "public"."files" TO "authenticated";
GRANT ALL ON TABLE "public"."files" TO "service_role";



GRANT ALL ON TABLE "public"."fund_fee_rules" TO "anon";
GRANT ALL ON TABLE "public"."fund_fee_rules" TO "authenticated";
GRANT ALL ON TABLE "public"."fund_fee_rules" TO "service_role";



GRANT ALL ON TABLE "public"."market_indicators" TO "anon";
GRANT ALL ON TABLE "public"."market_indicators" TO "authenticated";
GRANT ALL ON TABLE "public"."market_indicators" TO "service_role";



GRANT ALL ON TABLE "public"."message_chunks" TO "anon";
GRANT ALL ON TABLE "public"."message_chunks" TO "authenticated";
GRANT ALL ON TABLE "public"."message_chunks" TO "service_role";



GRANT ALL ON TABLE "public"."messages" TO "anon";
GRANT ALL ON TABLE "public"."messages" TO "authenticated";
GRANT ALL ON TABLE "public"."messages" TO "service_role";



GRANT ALL ON TABLE "public"."positions" TO "anon";
GRANT ALL ON TABLE "public"."positions" TO "authenticated";
GRANT ALL ON TABLE "public"."positions" TO "service_role";



GRANT ALL ON TABLE "public"."risk_questionnaires" TO "anon";
GRANT ALL ON TABLE "public"."risk_questionnaires" TO "authenticated";
GRANT ALL ON TABLE "public"."risk_questionnaires" TO "service_role";



GRANT ALL ON TABLE "public"."trade_flow" TO "anon";
GRANT ALL ON TABLE "public"."trade_flow" TO "authenticated";
GRANT ALL ON TABLE "public"."trade_flow" TO "service_role";



GRANT ALL ON TABLE "public"."trade_orders" TO "anon";
GRANT ALL ON TABLE "public"."trade_orders" TO "authenticated";
GRANT ALL ON TABLE "public"."trade_orders" TO "service_role";



GRANT ALL ON TABLE "public"."user_allocations" TO "anon";
GRANT ALL ON TABLE "public"."user_allocations" TO "authenticated";
GRANT ALL ON TABLE "public"."user_allocations" TO "service_role";



GRANT ALL ON TABLE "public"."user_risk_answers" TO "anon";
GRANT ALL ON TABLE "public"."user_risk_answers" TO "authenticated";
GRANT ALL ON TABLE "public"."user_risk_answers" TO "service_role";



GRANT ALL ON TABLE "public"."user_risk_profiles" TO "anon";
GRANT ALL ON TABLE "public"."user_risk_profiles" TO "authenticated";
GRANT ALL ON TABLE "public"."user_risk_profiles" TO "service_role";



GRANT ALL ON TABLE "public"."watchlist" TO "anon";
GRANT ALL ON TABLE "public"."watchlist" TO "authenticated";
GRANT ALL ON TABLE "public"."watchlist" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";
