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

---

## 模拟持仓交易 `/api/portfolio`（需 JWT 认证）

所有接口需在 Header 中携带 `Authorization: Bearer <token>`。

### POST `/api/portfolio/buy` — 买入建仓/加仓

**请求体**:
```json
{
  "fund_code": "512890",
  "quantity": 100,
  "price": null
}
```

- `price` 可选，不传则取当前市价
- 校验可用现金、最低申购金额
- 手续费自动计算并扣除
- 持仓成本价按加权平均法重算
- 写入交易流水

**响应**:
```json
{
  "success": true,
  "message": "买入成功",
  "data": {
    "fund_code": "512890",
    "fund_name": "华泰柏瑞红利低波ETF",
    "price": 1.234,
    "quantity": 100.0,
    "amount": 123.40,
    "fee": 0.19,
    "total_cost": 123.59,
    "position_qty": 500.0,
    "cost_price": 1.2000,
    "cash_remaining": 99876.41,
    "trade_time": "2026-07-28T10:00:00+00:00"
  }
}
```

### POST `/api/portfolio/sell` — 卖出减仓/清仓

**请求体**:
```json
{
  "fund_code": "512890",
  "quantity": 50,
  "price": null
}
```

- `price` 可选，不传则取当前市价
- 校验持仓数量是否充足
- 按持有天数计算赎回费
- 清仓后删除持仓记录
- 写入交易流水

**响应**:
```json
{
  "success": true,
  "message": "卖出成功",
  "data": {
    "fund_code": "512890",
    "fund_name": "华泰柏瑞红利低波ETF",
    "price": 1.250,
    "quantity": 50.0,
    "amount": 62.50,
    "fee": 0.31,
    "net_amount": 62.19,
    "trade_pnl": 3.19,
    "hold_days": 30,
    "position_qty": 450.0,
    "cash_remaining": 99938.60,
    "trade_time": "2026-07-28T10:30:00+00:00"
  }
}
```

### GET `/api/portfolio/positions?include_quote=true` — 持仓列表

- `include_quote` 可选，默认 `true`，是否按实时行情计算市值和盈亏
- 每项包含：fund_code, fund_name, quantity, cost_price, cost_value, market_price, market_value, pnl, pnl_pct

**响应**:
```json
{
  "total": 2,
  "items": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "fund_code": "512890",
      "fund_name": "华泰柏瑞红利低波ETF",
      "quantity": 500.0,
      "cost_price": 1.2000,
      "cost_value": 600.00,
      "market_price": 1.234,
      "market_value": 617.00,
      "pnl": 17.00,
      "pnl_pct": 2.8333,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "total_pnl": 17.00,
  "total_position_value": 617.00
}
```

### GET `/api/portfolio/account` — 账户概况

**响应**:
```json
{
  "cash": 99000.00,
  "position_value": 617.00,
  "total_assets": 99617.00,
  "total_pnl": -383.00,
  "total_return_rate": -0.00383,
  "position_count": 2
}
```

### GET `/api/portfolio/trade-flow?page=1&page_size=20` — 交易流水

支持可选过滤参数：
- `fund_code`: 基金代码
- `direction`: buy 或 sell
- `page`: 页码（默认 1）
- `page_size`: 每页条数（默认 20，最大 100）

**响应**:
```json
{
  "total": 5,
  "page": 1,
  "page_size": 20,
  "total_pages": 1,
  "items": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "fund_code": "512890",
      "fund_name": "华泰柏瑞红利低波ETF",
      "direction": "buy",
      "price": 1.2000,
      "quantity": 500.0,
      "amount": 600.00,
      "fee": 0.90,
      "trade_time": "2026-07-28T...}"
    }
  ]
}
```

### POST `/api/portfolio/snapshot` — 手动创建当日资产快照

幂等操作：同一天已存在快照则覆盖更新。

**响应**:
```json
{
  "success": true,
  "message": "快照已保存",
  "data": {
    "snapshot_date": "2026-07-28",
    "total_assets": 99617.00,
    "cash": 99000.00,
    "position_value": 617.00,
    "total_pnl": -383.00,
    "total_return_rate": -0.00383
  }
}
```

### GET `/api/portfolio/daily-returns?days=30` — 每日收益率

- `days` 可选，默认 30，最大 365
- 日收益率 = (今日总资产 - 昨日总资产) / 昨日总资产

**响应**:
```json
{
  "items": [
    {
      "date": "2026-07-27",
      "total_assets": 99500.00,
      "cash": 99000.00,
      "position_value": 500.00,
      "total_pnl": -500.00,
      "total_return_rate": -0.005,
      "daily_return": 0.0012
    }
  ]
}
```

### GET `/api/portfolio/health` — 健康检查（公开）