# API 接口说明

## 基础信息

- **服务地址**: `http://localhost:8000`
- **全局前缀**: `/api`（部分路由使用）
- **文档地址**: `http://localhost:8000/docs` (Swagger UI)

---

## 根路径

### GET `/`

简单验证服务是否启动，返回 `{"Hello": "World"}`。

---

## 测试接口 `/test`

### GET `/api/test/hello`

快速验证服务是否正常。

**响应**:
```json
{
  "message": "Hello World"
}
```

---

## 对话接口

### POST `/api/secure-chat` — 流式对话（需 JWT 认证）

带 JWT 认证的 LLM 对话，SSE 流式返回。user_id 从 JWT token 中自动读取，不从请求体获取。

**请求体**:
```json
{
  "question": "我想买沪深300ETF，怎么选？",
  "chat_id": "可选，不传则自动创建新会话"
}
```

**认证方式**: `Authorization: Bearer <access_token>`

**SSE 事件**:
- `token`: LLM 生成的 token
- `done`: 生成结束，附带 `chat_id`
- `error`: 错误

### POST `/api/secure-chat/login` — 登录获取 JWT

**请求体**:
```json
{
  "email": "user@example.com",
  "password": "your_password"
}
```

**响应**:
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "user_id": "uuid",
  "expires_in": 3600
}
```

### GET `/api/secure-chat/chats` — 获取会话列表（需 JWT）

返回当前用户的所有会话。

### GET `/api/secure-chat/chats/{chat_id}/messages` — 获取会话消息（需 JWT）

返回指定会话的完整消息历史。

### DELETE `/api/secure-chat/chats/{chat_id}` — 删除会话（需 JWT）

删除会话及其所有消息。

### POST `/api/simple-chat` — 简单对话（无认证、无历史）

单轮对话，SSE 流式返回，无会话管理。

**请求体**:
```json
{
  "question": "你好，请介绍一下自己"
}
```

**SSE 事件**:
- `token`: LLM 生成的 token
- `done`: 生成结束
- `error`: 错误

---

## 问答接口 `/ask` (已弃用)

### POST `/api/ask`

> ⚠️ 此接口已弃用，请使用 `/api/secure-chat` 或 `/api/simple-chat`。

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

## 自选股管理 `/api/watchlist`（需 JWT 认证）

所有接口（除 `/health` 外）需在 Header 中携带 `Authorization: Bearer <token>`。

### POST `/api/watchlist/add` — 添加自选股

**请求体**:
```json
{
  "fund_code": "512890",
  "fund_name": "可选，不传则自动获取"
}
```

### DELETE `/api/watchlist/remove` — 移除自选股

**请求体**:
```json
{
  "fund_code": "512890"
}
```

### GET `/api/watchlist/list?include_quote=true` — 查询自选股列表

`include_quote` 可选，默认为 `true`，是否包含实时行情。

### DELETE `/api/watchlist/clear` — 清空自选股

### GET `/api/watchlist/health` — 健康检查（公开，无需认证）