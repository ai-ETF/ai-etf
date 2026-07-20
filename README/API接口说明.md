# API 接口说明

## 基础信息

- **服务地址**: `http://localhost:8000`
- **全局前缀**: `/api`
- **文档地址**: `http://localhost:8000/docs` (Swagger UI)

---

## 对话接口 `/chat`

### POST `/api/chat` — 同步对话

适用于不支持 SSE 的客户端，一次性返回完整响应。

**请求体**:
```json
{
  "user_id": "user123",
  "session_id": "可选，不传则创建新会话",
  "message": "我想买沪深300ETF，怎么选？"
}
```

**响应**:
```json
{
  "session_id": "uuid",
  "reply": "莱拉的回复内容",
  "data_status": { "brief_ready": true, "detail_ready": false },
  "should_end": false,
  "waiting_for_input": false
}
```

### POST `/api/chat/stream` — SSE 流式对话

逐 token 实时返回 LLM 生成内容，体验更流畅。

**请求体**: 同上

**响应**: Server-Sent Events 流，事件类型包括：
- `start`: 会话开始
- `response`: 逐 token 的响应片段
- `data_status`: 数据收集状态更新
- `end`: 会话结束

### GET `/api/chat/{session_id}/history` — 获取对话历史

返回指定会话的完整消息记录。

### DELETE `/api/chat/{session_id}` — 删除会话

清除会话状态和历史记录。

---

## 问答接口 `/ask` (已弃用)

### POST `/api/ask`

> ⚠️ 此接口已弃用，请使用 `/api/chat` 或 `/api/chat/stream`。

---

## 文档处理 `/upload`

### POST `/api/upload` — 上传文档

**请求体**:
```json
{
  "url": "https://example.com/document.pdf",
  "source": "optional_source_tag"
}
```

**响应**:
```json
{
  "success": true,
  "doc_id": "uuid"
}
```

### POST `/api/upload/process-file-from-edge` — Edge Function 文件处理

用于 Supabase Edge Function 调用的文件处理接口。

**请求体**:
```json
{
  "file_id": "uuid",
  "user_id": "user123",
  "download_url": "https://...",
  "doc_type": "etf_report",
  "parse_strategy": {}
}
```

### GET `/api/upload/health` — 健康检查

返回服务状态。

---

## 测试接口 `/test`

### GET `/api/test/hello`

简单测试接口，返回 `{"message": "Hello World"}`。

---

## 根路径

### GET `/`

返回 `{"Hello": "World"}`，用于验证服务是否启动。