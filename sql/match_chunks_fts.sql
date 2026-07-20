-- ============================================================
-- 在 Supabase SQL Editor 执行该脚本，创建 FTS/BM25 风格检索函数
-- 用法：select * from match_chunks_fts('南方标普 管理费 托管费', 20, null);
-- ============================================================

-- 0. 给 document_chunks 表加 document_type 列（如果还没有的话）
-- 用途：区分文档类型（如 prospectus/年报/公告 等），默认 'other'
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS document_type TEXT DEFAULT 'other';

-- ============================================================
-- 1. 全文检索函数 match_chunks_fts
--    原理：利用 PostgreSQL 内置的全文搜索引擎（tsvector + tsquery），
--    对 document_chunks 的 content 字段做关键词匹配，
--    并按 ts_rank_cd 算出的相关性分数降序返回结果。
-- ============================================================
-- 先删除旧函数，避免参数变更导致 create or replace 失败
DROP FUNCTION IF EXISTS public.match_chunks_fts(text, integer, uuid);

create or replace function public.match_chunks_fts(
  query_text text,          -- 用户输入的检索关键词，如 '南方标普 管理费'
  match_count integer default 20,  -- 最多返回多少条匹配结果，默认 20
  document_id uuid default null    -- 可选：限定在某个文档内搜索，null 表示搜全部文档
)
returns table (             -- 函数返回一张虚拟表，包含以下列：
  chunk_id uuid,            --   片段的唯一 ID
  document_id uuid,         --   所属文档的 ID
  document_name text,       --   所属文档名称（当前填充 NULL，由调用方后续关联查询补全）
  document_type text,       --   文档类型（prospectus / annual_report / other 等）
  chunk_index integer,      --   片段在原文档中的顺序序号（从 0 开始）
  page_number integer,      --   片段所在原文的页码
  content text,             --   片段的实际文本内容
  fts_score real,           --   全文检索相关性得分（越高越相关）
  keyword_hits integer      --   关键词命中次数（最少为 1）
)
language sql                -- 纯 SQL 函数，无过程化逻辑
stable                      -- 标记为 stable：同一事务内对相同参数返回相同结果，允许查询优化
as $$
  -- 第一层 CTE：prepared —— 对每个片段计算 FTS 分数和关键词命中数
  with prepared as (
    select
      dc.id as chunk_id,                                      -- 片段 ID
      dc.document_id,                                          -- 所属文档 ID
      NULL::text as document_name,                             -- 文档名暂填 NULL
      dc.document_type,                                        -- 文档类型
      dc.chunk_index,                                          -- 片段序号
      dc.page_number,                                          -- 页码
      dc.content,                                              -- 原文内容
      -- ts_rank_cd：基于 cover density 的排序算法，衡量查询词在文本中的邻近程度
      -- to_tsvector('simple', ...)：把文本转成可搜索的词向量，'simple' 不做词干提取，适合中文
      -- websearch_to_tsquery('simple', ...)：把用户输入的搜索串转成 tsquery，支持引号短语、OR 等
      ts_rank_cd(
        to_tsvector('simple', coalesce(dc.content, '')),
        websearch_to_tsquery('simple', coalesce(query_text, ''))
      )::real as fts_score,                                    -- 转为 real 类型供返回
      -- keyword_hits：粗略计算第一个搜索关键词在文本中出现的次数
      -- 原理：原文长度 - 去掉该关键词后的长度 = 关键词占用的总字符数
      -- 注意：这只是对空格分割的第一个词做了统计，是一个简化估算
      (
        length(lower(coalesce(dc.content, ''))) -
        length(replace(lower(coalesce(dc.content, '')), lower(split_part(coalesce(query_text, ''), ' ', 1)), ''))
      )::integer as keyword_hits
    from public.document_chunks dc
    -- 如果传入了 document_id，则只在该文档内搜索；否则搜全表
    where (document_id is null or dc.document_id = document_id)
      -- @@ 是 tsvector 匹配 tsquery 的操作符，只保留真正包含搜索词的片段
      and to_tsvector('simple', coalesce(dc.content, '')) @@ websearch_to_tsquery('simple', coalesce(query_text, ''))
  )
  -- 第二层：从 CTE 中选出最终结果
  select
    p.chunk_id,
    p.document_id,
    p.document_name,
    p.document_type,
    p.chunk_index,
    p.page_number,
    p.content,
    p.fts_score,
    -- greatest(1, ...) 保证 keyword_hits 至少为 1（因为能进结果集说明至少命中一次）
    greatest(1, p.keyword_hits) as keyword_hits
  from prepared p
  -- 先按相关性分数从高到低排，分数相同的再按片段顺序排
  order by p.fts_score desc, p.chunk_index asc
  -- 限制返回条数，greatest(1, ...) 保证至少返回 1 条
  limit greatest(1, match_count);
$$;

-- ============================================================
-- 2. 向量相似度检索函数 match_chunks
--    原理：利用 pgvector 扩展的余弦距离操作符 <=>，
--    将查询文本的 embedding 向量与数据库中存储的 embedding 比较，
--    返回语义上最接近的文档片段。
-- ============================================================
-- 先删除旧签名，避免参数变更导致 create or replace 失败
DROP FUNCTION IF EXISTS public.match_chunks(vector(768), integer, uuid);

create or replace function public.match_chunks(
  query_embedding vector(768),    -- 查询文本经 Embedding 模型编码后的 768 维向量
  match_count integer default 20, -- 最多返回多少条匹配结果，默认 20
  document_id uuid default null   -- 可选：限定在某个文档内搜索
)
returns table (                   -- 函数返回一张虚拟表，包含以下列：
  chunk_id uuid,                   --   片段的唯一 ID
  document_id uuid,                --   所属文档的 ID
  document_name text,              --   所属文档名称（当前填充 NULL）
  document_type text,              --   文档类型
  chunk_index integer,             --   片段序号
  page_number integer,             --   页码
  content text,                    --   片段文本内容
  similarity real                  --   相似度得分（1 = 完全相同，0 = 无关）
)
language sql                       -- 纯 SQL 函数
stable                             -- stable 标记，允许查询优化器缓存结果
as $$
  select
    dc.id as chunk_id,                                      -- 片段 ID
    dc.document_id,                                          -- 所属文档 ID
    NULL::text as document_name,                             -- 文档名暂填 NULL
    dc.document_type,                                        -- 文档类型
    dc.chunk_index,                                          -- 片段序号
    dc.page_number,                                          -- 页码
    dc.content,                                              -- 原文内容
    -- <=> 是 pgvector 的余弦距离操作符，值域 [0, 2]
    -- 1 - 余弦距离 = 余弦相似度，值域 [-1, 1]，语义上越高越相似
    (1 - (dc.embedding <=> query_embedding))::real as similarity
  from public.document_chunks dc
  -- 如果传入了 document_id，则只在该文档内搜索；否则搜全表
  where (document_id is null or dc.document_id = document_id)
  -- 按余弦距离从小到大（即相似度从高到低）排序
  order by dc.embedding <=> query_embedding
  -- 限制返回条数，greatest(1, ...) 保证至少返回 1 条
  limit greatest(1, match_count);
$$;
