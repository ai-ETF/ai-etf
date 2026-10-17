# 05-图与RAG

**被测模块**：`server/graphs/qa/graph.py`、`server/graphs/document/graph.py`、`server/services/qa_service.py`、`server/services/document_service.py`、`server/llm.py`
**测试文件**：`tests/integration/server/graphs/test_qa_graph_execution.py`、`test_document_graph_execution.py`、`tests/integration/server/rag/test_rag_pipeline.py`、`tests/integration/server/pipeline/test_upload_e2e.py`、`tests/integration/server/test_llm_eval.py`
**测试方法**：真实 `ainvoke` 图编排 + 本地 text2vec 嵌入 + 本地 Supabase/pgvector + mock reranker / mock 下载；LLM 直连测试用 `eval` marker，默认不跑

## 功能

- **QA 分析图**：规则快速通道（`comparison` / `factual_query` 意图命中规则直接返回，不触发 LLM）的 state 流转与返回结构；
- **文档分析图**：`classify_document_type → analyze_structure` 的图执行、类型分类、空输入不崩溃；
- **RAG 管线**：`QAService.handle_question` 的「嵌入 → 检索 → 提示词组装」完整链路；
- **上传管线**：`DocumentService.process_file_from_edge` 的「下载（替身）→ 建 documents → 图分析 → 分片嵌入 → 写 chunks → 状态 ready」。

> ⚠️ **范围说明**：按本项目既定范围，`graphs/` 下的图与追问链属于**草稿**，文档上传/分析属于**软工作业遗迹**，都不纳入测试设计与维护。本文只**登记现状**（这些用例已在仓库里、能跑），不据此扩展新用例，也不顺手修相关问题。

## 业务场景 / 预期结果 / 测试结果

### 一、QA 图规则快速通道（2 例）

**业务场景**：用户问「对比一下红利ETF和华泰柏瑞的差异」或「红利ETF的净值是多少」时，意图识别走规则、不打 LLM，结果必须稳定可复现。

| 场景 | 预期 |
|------|------|
| 「对比一下…差异」 | `intent=comparison`；`top_k > 0`；`output_format ∈ {text, table}`；`format_analysis` 非空 |
| 「净值是多少」 | `intent=factual_query`；`top_k > 0` |

**测试结果**：2 例全部通过。

### 二、文档分析图（2 例）

| 场景 | 预期 |
|------|------|
| 一段基金合同文本 | `document_type ∈ {etf_report, fund_prospectus, general_document}`；`confidence ∈ [0,1]`；含 `content_structure` / `suggested_chunk_strategy` |
| 空字符串 | 不崩溃，返回结构里仍有 `document_type` |

**测试结果**：2 例全部通过。

### 三、RAG 管线（1 例）

**业务场景**：用户提问 → 本地模型嵌入 → pgvector 检索 → reranker 打分（替身固定 0.9，不拒识）→ 组装提示词。

| 场景 | 预期 |
|------|------|
| 种入含「红利」的 chunk 后问「红利ETF适合什么样的投资者」 | 返回含 `prompt`；`top_chunks` 非空；`prompt` 里含「红利」 |

**测试结果**：1 例通过。

### 四、上传管线（1 例）

**业务场景**：Edge Function 把文件下载地址交给后端，后端下载、分析、分片、嵌入、落库。

| 场景 | 预期 |
|------|------|
| 处理一份文本文件 | `documents` 恰好 1 条且 `status='ready'`、id 与返回值一致；`document_chunks` ≥ 1 条；嵌入解析后为 768 维；content 非空 |

> 下载被替身成固定文本（`requests.get` 被 monkeypatch），出网守卫会拦住真实下载。

**测试结果**：1 例通过。

### 五、LLM 直连（2 例，`eval` marker，默认不跑）

| 场景 | 预期 |
|------|------|
| 创建真实 client | `model == "claude-sonnet-4-20250514"` |
| 真实流式回答 | 拼接结果非空；不含 `thinking` 等非文本块 |

**测试结果**：`-m integration` 跑法下不执行；单独 `-m eval` 且配置了 `ANTHROPIC_API_KEY` 才跑。**有成本、非确定性**，不进 CI。

## 覆盖边界

- 图的 **general 意图 / LLM tool-calling 路径**不在这里测（属 eval 范畴）；
- 追问链、Agent 循环、文档问答的完整对话流不在范围（草稿代码）；
- 上传只覆盖 `text/plain` 替身内容，PDF 解析、超大文件、失败重试都没有用例。
