-- 在 Supabase SQL Editor 执行该脚本，创建 FTS/BM25 风格检索函数
-- 用法：select * from match_chunks_fts('南方标普 管理费 托管费', 20, null);

-- 0. 给 document_chunks 表加 document_type 列（如果还没有的话）
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS document_type TEXT DEFAULT 'other';

-- 1. 更新 FTS 检索函数，返回 document_type
DROP FUNCTION IF EXISTS public.match_chunks_fts(text, integer, uuid);
create or replace function public.match_chunks_fts(
  query_text text,
  match_count integer default 20,
  document_id uuid default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  document_name text,
  document_type text,
  chunk_index integer,
  page_number integer,
  content text,
  fts_score real,
  keyword_hits integer
)
language sql
stable
as $$
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

-- 2. 更新向量检索函数，返回 document_type
DROP FUNCTION IF EXISTS public.match_chunks(vector(768), integer, uuid);
create or replace function public.match_chunks(
  query_embedding vector(768),
  match_count integer default 20,
  document_id uuid default null
)
returns table (
  chunk_id uuid,
  document_id uuid,
  document_name text,
  document_type text,
  chunk_index integer,
  page_number integer,
  content text,
  similarity real
)
language sql
stable
as $$
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
