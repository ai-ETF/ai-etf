# 01-存储与pgvector

**被测模块**：`server/storage/supabase_client.py`、`server/storage/embedding_repo.py`、`server/rag/retriever.py`
**测试文件**：`tests/integration/server/test_smoke.py`、`tests/integration/server/storage/test_embedding_repo_pgvector.py`
**测试方法**：本地 Supabase 栈（Postgres + pgvector）+ service_role 客户端 + 本地 text2vec 嵌入模型（`TRANSFORMERS_OFFLINE=1`，不出网）+ 合成 UUID 数据 + 定向清理（`purge_user_data` / 按 `user_id` 删除）

## 功能

这一层验证「代码 ↔ 真实数据库」的边界：真实 SQL 能不能写进去、能不能查回来，而不是用替身模拟出来的假结果。共两块：

1. **冒烟与安全护栏**：连得上本地库、出网守卫真的会拦、写入读回后清理干净。
2. **向量存储与检索**：`document_chunks` 写入真实 768 维向量；稠密检索（pgvector 余弦距离）、稀疏检索（FTS + 中文降级 ilike）、双路 RRF 融合。

> 数据库目标由 `tests/integration/conftest.py:82-90` 强制断言：URL 里不含 `127.0.0.1` / `localhost` 就**直接退出整个测试会话**，防止误连生产库。

## 业务场景 / 预期结果 / 测试结果

### 一、冒烟：连通性、出网守卫、读写清理（3 例）

**业务场景**：跑任何业务断言之前，先证明「测试基建本身是可信的」——库连对了、网真的断了、数据清理后真的没有了。

**预期结果**

| 场景 | 预期 |
|------|------|
| 查询 `fund_fee_rules` | 可查询且 `count >= 20`（种子数据已灌入） |
| 尝试连接 `huggingface.co:443` | 抛 `RuntimeError`，文案含「禁止出网」 |
| 写入一条 `watchlist` → 读回 → 删除 | 读回一致；删除后该用户 `count == 0`；清理失败必须抛错 |

**测试结果**：3 例全部通过。

### 二、`EmbeddingRepo.match_by_vector` —— 稠密检索（1 例）

**业务场景**：文档切成 chunk 后写入真实向量；用户用一句话提问时，应按语义相似度召回最相关的 chunk，而不是按字面匹配。

**预期结果**

| 场景 | 预期 |
|------|------|
| 两个 chunk（红利ETF / 债券基金），查询「红利ETF的股息率是多少」 | 至少返回 1 条；第 1 条 content 含「红利」；`similarity` 落在 `[0, 1]` |

**测试结果**：1 例通过。

### 三、`EmbeddingRepo.match_by_keywords` —— 稀疏检索（1 例）

**业务场景**：关键词检索走 Postgres FTS。中文在 `simple` 配置下不会被切分，FTS 会返回空；实现里做了「FTS 为空时降级 ilike」的兜底，这条用例就是钉住这个兜底。

**预期结果**

| 场景 | 预期 |
|------|------|
| 文档含「沪深300」，查询关键词「沪深300」 | 至少返回 1 条；结果里有 content 含「沪深300」 |

**测试结果**：1 例通过。

### 四、`Retriever.retrieve` —— 双路融合（1 例）

**业务场景**：问答检索同时走稠密 + 稀疏两路，再用 RRF 融合排序；调用方拿到的结果必须带统一的字段结构。

**预期结果**

| 场景 | 预期 |
|------|------|
| 同时传查询向量与查询文本 | 至少返回 1 条；结果含 `chunk_id` / `content` / `similarity` |

**测试结果**：1 例通过。

## 覆盖边界与已知情况

- 规划里的 `test_retriever_hybrid.py`、`test_chat_repo_cascade.py`、`test_document_repo.py` **尚未落地**；目前融合逻辑由上面第 4 条覆盖，级联删除没有集成用例。
- 嵌入模型走本地缓存，第一次跑要先有模型文件；CI 上如果没有缓存，这一层会慢或直接失败（见 `06-环境与CI.md`）。
- `document_chunks.embedding` 经 `supabase-py` 读回来是 JSON 字符串，断言前要 `json.loads`（`test_upload_e2e.py:80-85` 有同样处理）。
