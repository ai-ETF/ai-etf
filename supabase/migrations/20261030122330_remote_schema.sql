-- Migration unit 1: schema_changes
-- Transaction mode: transactional
-- Boundary reason: default

SET check_function_bodies = false;

DROP EXTENSION pg_net;

ALTER TABLE public.fund_fee_rules
  DROP CONSTRAINT fund_fee_rules_fund_type_check;

ALTER TABLE public.trade_flow
  DROP CONSTRAINT trade_flow_direction_check;

ALTER TABLE public.trade_orders
  DROP CONSTRAINT trade_orders_direction_check;

ALTER TABLE public.trade_orders
  DROP CONSTRAINT trade_orders_fund_type_check;

ALTER TABLE public.trade_orders
  DROP CONSTRAINT trade_orders_order_type_check;

CREATE ROLE supabase_privileged_role;

GRANT supabase_privileged_role TO postgres;

CREATE OR REPLACE FUNCTION public.check_parent_is_folder()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  AS $function$
begin
  if new.parent_id is not null then
    if (select type from files where id = new.parent_id) != 'folder' then
      raise exception 'Parent must be a folder';
    end if;
  end if;
  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION public.delete_chat_messages()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  AS $function$
BEGIN
  -- 当 chats 表中的一行被删除时，OLD 代表被删除的那行数据
  -- 删除 messages 表中所有 chat_id 等于被删除会话 id 的记录
  DELETE FROM public.messages WHERE chat_id = OLD.id;
  -- 触发器函数需要返回被操作的行记录
  RETURN OLD;
END;
$function$;

CREATE OR REPLACE FUNCTION public.delete_message_chunks_on_message_delete()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  AS $function$
BEGIN
  DELETE FROM message_chunks WHERE message_id = OLD.id;
  RETURN OLD;
END;
$function$;

CREATE OR REPLACE FUNCTION public.delete_messages_on_chat_delete()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  AS $function$
BEGIN
  DELETE FROM messages WHERE chat_id = OLD.id;
  RETURN OLD;
END;
$function$;

CREATE OR REPLACE FUNCTION public.delete_storage_object()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  AS $function$
begin
  if old.type = 'file' then
    perform
      storage.delete_object('user-files', old.storage_path);
  end if;
  return old;
end;
$function$;

CREATE OR REPLACE FUNCTION public.match_chunks_fts (
  query_text  text,
  match_count integer DEFAULT 20,
  document_id uuid    DEFAULT NULL::uuid
)
  RETURNS TABLE (
    chunk_id      uuid,
    document_id   uuid,
    document_name text,
    document_type text,
    chunk_index   integer,
    page_number   integer,
    content       text,
    fts_score     real,
    keyword_hits  integer
  )
  LANGUAGE sql
  STABLE
  AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION public.match_chunks (
  query_embedding public.vector,
  match_count     integer       DEFAULT 20,
  document_id     uuid          DEFAULT NULL::uuid
)
  RETURNS TABLE (
    chunk_id      uuid,
    document_id   uuid,
    document_name text,
    document_type text,
    chunk_index   integer,
    page_number   integer,
    content       text,
    similarity    real
  )
  LANGUAGE sql
  STABLE
  AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION public.set_updated_at()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  AS $function$
begin
  new.updated_at = now();
  return new;
end;
$function$;

ALTER TABLE public.fund_fee_rules
  ADD CONSTRAINT fund_fee_rules_fund_type_check CHECK (fund_type::text = ANY (ARRAY['of'::character varying, 'etf'::character varying]::text[]));

ALTER TABLE public.fund_risk_profiles
  VALIDATE CONSTRAINT fund_risk_profiles_fund_code_fkey;

ALTER TABLE public.trade_flow
  ADD CONSTRAINT trade_flow_direction_check CHECK (direction::text = ANY (ARRAY['buy'::character varying, 'sell'::character varying]::text[]));

ALTER TABLE public.trade_orders
  ADD CONSTRAINT trade_orders_direction_check CHECK (direction::text = ANY (ARRAY['buy'::character varying, 'sell'::character varying]::text[]));

ALTER TABLE public.trade_orders
  ADD CONSTRAINT trade_orders_fund_type_check CHECK (fund_type::text = ANY (ARRAY['of'::character varying, 'etf'::character varying]::text[]));

ALTER TABLE public.trade_orders
  ADD CONSTRAINT trade_orders_order_type_check CHECK (order_type::text = ANY (ARRAY['market'::character varying, 'limit'::character varying]::text[]));
