# Supabase 数据库文档

> 最后更新：2026-06-16
> 项目：AI-ETF 问答系统

---

## 一、数据库概览

共 13 张表：

| 分类 | 表名 | 用途 |
|------|------|------|
| **会话** | `chats` | 用户会话/聊天 |
| | `messages` | 对话消息 |
| | `message_chunks` | 消息关联的检索切片 |
| **文档** | `files` | 上传的原始文件记录 |
| | `documents` | 文档元数据和处理状态 |
| | `document_chunks` | 文档切片 + 向量嵌入 |
| **AI** | `ai_requests` | AI 请求日志 |
| **风险评估** | `risk_questionnaires` | 风险问卷题目 |
| | `user_risk_answers` | 用户风险答题记录 |
| | `user_risk_profiles` | 用户风险画像 |
| **市场** | `market_indicators` | 市场指标数据 |
| **资产配置** | `allocation_models` | 资产配置模型 |
| | `user_allocations` | 用户资产配置方案 |

---

## 二、表结构详解

### 2.1 chats — 会话表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `user_id` | uuid | NO | | 用户 ID |
| `title` | text | YES | | 会话标题 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |
| `created_at` | timestamptz | YES | now() | 创建时间 |
| `updated_at` | timestamptz | YES | now() | 更新时间 |

---

### 2.2 messages — 消息表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `chat_id` | uuid | NO | | 所属会话 ID |
| `user_id` | uuid | YES | | 用户 ID |
| `role` | text | NO | | 角色：`user` / `assistant` / `system` |
| `content` | text | NO | | 消息内容 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |
| `created_at` | timestamptz | YES | now() | 创建时间 |

---

### 2.3 message_chunks — 消息-切片关联表

记录消息检索时命中的文档切片，用于溯源和引用。

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `message_id` | uuid | NO | | 关联的消息 ID |
| `chunk_id` | uuid | NO | | 关联的文档切片 ID |
| `confidence` | numeric | YES | | 相关性置信度 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |

---

### 2.4 files — 文件表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `user_id` | uuid | NO | | 上传者 ID |
| `name` | text | NO | | 文件名 |
| `type` | text | NO | | 文件类型 |
| `parent_id` | uuid | YES | | 父文件夹 ID |
| `storage_path` | text | YES | | 存储路径 |
| `mime_type` | text | YES | | MIME 类型 |
| `size` | bigint | YES | | 文件大小（字节） |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |
| `created_at` | timestamptz | YES | now() | 创建时间 |
| `updated_at` | timestamptz | YES | now() | 更新时间 |

---

### 2.5 documents — 文档表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `file_id` | uuid | NO | | 关联的文件 ID |
| `user_id` | uuid | NO | | 文档所有者 |
| `status` | text | NO | | 处理状态：`processing` / `ready` / `failed` |
| `title` | text | YES | | 文档标题 |
| `doc_type` | text | YES | | 文档类型 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |
| `created_at` | timestamptz | YES | now() | 创建时间 |
| `updated_at` | timestamptz | YES | now() | 更新时间 |

---

### 2.6 document_chunks — 文档切片表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `document_id` | uuid | NO | | 所属文档 ID |
| `chunk_index` | integer | NO | | 切片序号 |
| `content` | text | NO | | 文本内容 |
| `embedding` | vector(768) | YES | | 向量嵌入 |
| `page_number` | integer | YES | | 页码 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |
| `created_at` | timestamptz | YES | now() | 创建时间 |
| `document_type` | text | YES | 'other' | 文档类型标签 |

**document_type 取值：** `prospectus` / `guide` / `strategy` / `other` / `etf_document_chunk` / `text_chunk`

---

### 2.7 ai_requests — AI 请求日志表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `prompt` | text | NO | | 请求 prompt |
| `status` | text | NO | 'pending' | 状态：`pending` / `completed` / `failed` |
| `response` | text | YES | | AI 响应 |
| `created_at` | timestamptz | YES | now() | 创建时间 |
| `updated_at` | timestamptz | YES | now() | 更新时间 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |

---

### 2.8 risk_questionnaires — 风险问卷表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `version` | text | NO | | 问卷版本 |
| `questions` | jsonb | NO | | 题目内容（JSON） |
| `is_active` | boolean | YES | true | 是否启用 |
| `created_at` | timestamptz | YES | now() | 创建时间 |
| `updated_at` | timestamptz | YES | now() | 更新时间 |

---

### 2.9 user_risk_answers — 用户风险答题表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `user_id` | uuid | NO | | 用户 ID |
| `questionnaire_id` | uuid | NO | | 关联问卷 ID |
| `answers` | jsonb | NO | | 答题内容（JSON） |
| `is_completed` | boolean | YES | true | 是否完成 |
| `session_id` | text | YES | | 会话 ID |
| `created_at` | timestamptz | YES | now() | 创建时间 |

---

### 2.10 user_risk_profiles — 用户风险画像表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `user_id` | uuid | NO | | 用户 ID |
| `answer_id` | uuid | YES | | 关联答题记录 ID |
| `risk_level` | enum | NO | | 风险等级 |
| `confidence_score` | numeric | YES | | 置信度 |
| `dimension_scores` | jsonb | NO | '{}' | 各维度得分 |
| `ai_summary` | jsonb | YES | | AI 生成的摘要 |
| `source` | enum | NO | | 来源 |
| `model_version` | text | NO | | 模型版本 |
| `is_active` | boolean | YES | true | 是否生效 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |
| `created_at` | timestamptz | YES | now() | 创建时间 |
| `expires_at` | timestamptz | YES | | 过期时间 |
| `total_score` | numeric | YES | | 总分 |
| `weighted_scores` | jsonb | YES | '{}' | 加权得分 |

---

### 2.11 market_indicators — 市场指标表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `symbol` | text | YES | | 标的代码 |
| `indicator_type` | text | YES | | 指标类型 |
| `value` | numeric | YES | | 指标值 |
| `as_of` | date | YES | | 数据日期 |
| `source` | text | YES | | 数据来源 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |

---

### 2.12 allocation_models — 资产配置模型表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `version` | text | YES | | 模型版本 |
| `config` | jsonb | NO | | 配置内容 |
| `created_at` | timestamptz | YES | now() | 创建时间 |

---

### 2.13 user_allocations — 用户资产配置表

| 列名 | 类型 | 可空 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | uuid | NO | gen_random_uuid() | 主键 |
| `user_id` | uuid | NO | | 用户 ID |
| `model_id` | uuid | NO | | 关联配置模型 ID |
| `allocation` | jsonb | NO | | 配置方案 |
| `over_allocated` | boolean | YES | | 是否超配 |
| `metadata` | jsonb | YES | '{}' | 扩展元数据 |
| `created_at` | timestamptz | YES | now() | 创建时间 |

---

## 三、数据库函数 (RPC)

### 3.1 match_chunks — 向量相似度检索

```sql
match_chunks(query_embedding vector(768), match_count integer DEFAULT 20, document_id uuid DEFAULT NULL)
```

返回：chunk_id, document_id, document_name, document_type, chunk_index, page_number, content, similarity

**代码引用：** `server/storage/embedding_repo.py:115`

### 3.2 match_chunks_fts — 全文检索

```sql
match_chunks_fts(query_text text, match_count integer DEFAULT 20, document_id uuid DEFAULT NULL)
```

返回：chunk_id, document_id, document_name, document_type, chunk_index, page_number, content, fts_score, keyword_hits

**代码引用：** `server/storage/embedding_repo.py:187`

---

## 四、表关系图

```
chats
│ id (PK)
│ user_id
│
├─── messages
│    │ id (PK)
│    │ chat_id (FK → chats.id)
│    │ user_id
│    │ role, content
│    │
│    └─── message_chunks
│         │ id (PK)
│         │ message_id (FK → messages.id)
│         │ chunk_id (FK → document_chunks.id)
│         └─── confidence
│
files
│ id (PK)
│ user_id
│
├─── documents
│    │ id (PK)
│    │ file_id (FK → files.id)
│    │ user_id
│    │
│    └─── document_chunks
│         │ id (PK)
│         │ document_id (FK → documents.id)
│         │ content, embedding vector(768)
│         └─── document_type
│
risk_questionnaires
│ id (PK)
│
├─── user_risk_answers
│    │ id (PK)
│    │ questionnaire_id (FK)
│    │ user_id
│    │
│    └─── user_risk_profiles
│         │ id (PK)
│         │ answer_id (FK)
│         │ user_id, risk_level
│         └─── dimension_scores
│
allocation_models
│ id (PK)
│
└─── user_allocations
     │ id (PK)
     │ model_id (FK)
     │ user_id
     └─── allocation
```

---

## 五、触发器

### 5.1 级联删除触发器

删除 chat 时自动清理关联的 messages 和 message_chunks，保证数据一致性。

**触发器链路：**

```
DELETE chats → 触发 trigger_delete_messages → DELETE messages
                                                    ↓
                                         触发 trigger_delete_message_chunks → DELETE message_chunks
```

**触发器函数：**

| 函数名 | 绑定表 | 触发时机 | 作用 |
|--------|--------|----------|------|
| `delete_messages_on_chat_delete()` | chats | BEFORE DELETE | 删除关联的 messages |
| `delete_message_chunks_on_message_delete()` | messages | BEFORE DELETE | 删除关联的 message_chunks |

**SQL 脚本：** `sql/triggers_cascade.sql`

---

## 六、RLS 权限策略

### 6.1 概述

RLS（Row Level Security）按 `user_id` 隔离数据访问，确保用户只能操作自己的数据。

**注意：** `service_role key` 会绕过 RLS，后台服务不受影响。前端用户通过 `anon key` 访问时 RLS 生效。

### 6.2 策略清单

| 表 | 策略 | 操作 | 隔离方式 |
|----|------|------|----------|
| chats | 用户查看自己的会话 | SELECT | `auth.uid() = user_id` |
| chats | 用户创建自己的会话 | INSERT | `auth.uid() = user_id` |
| chats | 用户更新自己的会话 | UPDATE | `auth.uid() = user_id` |
| chats | 用户删除自己的会话 | DELETE | `auth.uid() = user_id` |
| messages | 用户查看自己的消息 | SELECT | 通过 chat_id 关联 chats.user_id |
| messages | 用户创建自己的消息 | INSERT | 通过 chat_id 关联 chats.user_id |
| messages | 用户删除自己的消息 | DELETE | 通过 chat_id 关联 chats.user_id |
| files | 用户查看自己的文件 | SELECT | `auth.uid() = user_id` |
| files | 用户创建自己的文件 | INSERT | `auth.uid() = user_id` |
| files | 用户删除自己的文件 | DELETE | `auth.uid() = user_id` |
| documents | 用户查看自己的文档 | SELECT | `auth.uid() = user_id` |
| documents | 用户创建自己的文档 | INSERT | `auth.uid() = user_id` |
| documents | 用户删除自己的文档 | DELETE | `auth.uid() = user_id` |
| document_chunks | 用户查看自己文档的切片 | SELECT | 通过 document_id 关联 documents.user_id |
| document_chunks | 用户创建自己文档的切片 | INSERT | 通过 document_id 关联 documents.user_id |
| document_chunks | 用户删除自己文档的切片 | DELETE | 通过 document_id 关联 documents.user_id |

**SQL 脚本：** `sql/rls_policies.sql`

---

## 七、代码覆盖情况

| 表 | 有代码操作吗 | 说明 |
|----|-------------|------|
| `chats` | ❌ 无 | 有表无代码 |
| `messages` | ❌ 无 | 有表无代码 |
| `message_chunks` | ❌ 无 | 有表无代码 |
| `files` | ✅ 有 | data_pipeline.py |
| `documents` | ✅ 有 | document_service.py, data_pipeline.py |
| `document_chunks` | ✅ 有 | embedding_repo.py, document_repo.py |
| `ai_requests` | ❌ 无 | 有表无代码 |
| `risk_questionnaires` | ❌ 无 | 有表无代码 |
| `user_risk_answers` | ❌ 无 | 有表无代码 |
| `user_risk_profiles` | ❌ 无 | 有表无代码 |
| `market_indicators` | ❌ 无 | 有表无代码 |
| `allocation_models` | ❌ 无 | 有表无代码 |
| `user_allocations` | ❌ 无 | 有表无代码 |

---

## 八、已知问题

| # | 问题 | 影响 | 优先级 | 状态 |
|---|------|------|--------|------|
| 1 | `chats`/`messages` 表已有但无服务端代码 | 验收 2 核心缺口 | 高 | 非本任务范围（前后端负责） |
| 2 | 无触发器，删除 chat 时 messages 不会自动级联删除 | 数据一致性风险 | 高 | ✅ 已修复 |
| 3 | 无 RLS 策略，使用 service_role key 绕过权限 | 安全风险 | 中 | ✅ 已修复 |
| 4 | document_type 取值不统一 | 检索过滤可能遗漏 | 中 | 待处理 |
| 5 | 13 张表中只有 3 张有代码操作 | 大量表闲置 | 低（按需开发） | 非本任务范围 |
