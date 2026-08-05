# AI-ETF 后端 API 测试命令清单

> 后端地址：`http://47.113.220.182:8000`
> 更新日期：2026-08-05

---

## 一、基础测试（无需认证）

```bash
API="http://47.113.220.182:8000"
```

### 1.1 健康检查

```bash
curl -s "$API/" | python3 -m json.tool
curl -s "$API/api/upload/health" | python3 -m json.tool
curl -s "$API/api/portfolio/health" | python3 -m json.tool
curl -s "$API/api/watchlist/health" | python3 -m json.tool
```

### 1.2 测试端点

```bash
curl -s "$API/api/test/hello" | python3 -m json.tool
```

---

## 二、LLM 对话

### 2.1 简单对话（无需认证）

```bash
curl -s -X POST "$API/api/simple-chat" \
  -H "Content-Type: application/json" \
  -d '{"question": "你好，请介绍一下自己"}' | python3 -m json.tool
```

### 2.2 登录获取 JWT Token

```bash
curl -s -X POST "$API/api/secure-chat/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "lpqs@outlook.com", "password": "your_password"}' | python3 -m json.tool
```

### 2.3 流式对话（需 JWT）

```bash
curl -s -X POST "$API/api/secure-chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question": "我想买沪深300ETF，怎么选？"}'
```

### 2.4 获取会话列表（需 JWT）

```bash
curl -s "$API/api/secure-chat/chats?limit=50" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 2.5 查看会话消息（需 JWT）

```bash
curl -s "$API/api/secure-chat/chats/<CHAT_ID>/messages" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 2.6 删除会话（需 JWT）

```bash
curl -s -X DELETE "$API/api/secure-chat/chats/<CHAT_ID>" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## 三、文档上传

```bash
curl -s -X POST "$API/api/upload" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/document.pdf", "source": "test"}' | python3 -m json.tool
```

---

## 四、自选股管理（需 JWT）

### 4.1 添加自选股

```bash
curl -s -X POST "$API/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code": "512890", "fund_name": "红利低波ETF"}'

curl -s -X POST "$API/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code": "510300", "fund_name": "沪深300ETF"}'
```

### 4.2 查询自选股列表（含实时行情）

```bash
curl -s "$API/api/watchlist/list?include_quote=true" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 4.3 移除自选股

```bash
curl -s -X DELETE "$API/api/watchlist/remove" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code": "510300"}' | python3 -m json.tool
```

### 4.4 清空自选股

```bash
curl -s -X DELETE "$API/api/watchlist/clear" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## 五、场外基金模拟交易（需 JWT）

### 5.1 查看账户概况

```bash
curl -s "$API/api/portfolio/account" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 5.2 查看持仓

```bash
curl -s "$API/api/portfolio/positions?include_quote=true" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 5.3 申购（按金额，元）

```bash
# A 股联接基金（T+1 确认）
curl -s -X POST "$API/api/portfolio/apply-purchase" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code":"110020","amount":1000}' | python3 -m json.tool

# C 类基金（免申购费）
curl -s -X POST "$API/api/portfolio/apply-purchase" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code":"001595","amount":2000}' | python3 -m json.tool

# QDII 基金（T+2 确认）
curl -s -X POST "$API/api/portfolio/apply-purchase" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code":"000071","amount":500}' | python3 -m json.tool
```

### 5.4 赎回（按份额，份）

```bash
curl -s -X POST "$API/api/portfolio/apply-redeem" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code":"110020","quantity":100}' | python3 -m json.tool
```

### 5.5 交易流水

```bash
# 全部
curl -s "$API/api/portfolio/trade-flow?page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 按基金筛选
curl -s "$API/api/portfolio/trade-flow?fund_code=110020&page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 按方向筛选
curl -s "$API/api/portfolio/trade-flow?direction=buy&page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 5.6 创建每日快照

```bash
curl -s -X POST "$API/api/portfolio/snapshot" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 5.7 每日收益率

```bash
curl -s "$API/api/portfolio/daily-returns?days=30" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 5.8 手动确认 pending 订单（无需认证）

```bash
curl -s -X POST "$API/api/portfolio/confirm-pending" | python3 -m json.tool
```

### 5.9 拦截验证

```bash
# ETF 拦截
curl -s -X POST "$API/api/portfolio/apply-purchase" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code":"510300","amount":1000}' | python3 -m json.tool

# 白名单拦截
curl -s -X POST "$API/api/portfolio/apply-purchase" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code":"000001","amount":1000}' | python3 -m json.tool

# 未持仓赎回拦截
curl -s -X POST "$API/api/portfolio/apply-redeem" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"fund_code":"009067","quantity":10}' | python3 -m json.tool
```

---

## 六、一键测试脚本

使用预设脚本快速验证全流程：

```bash
API_HOST="http://47.113.220.182:8000" \
SUPABASE_TEST_PASSWORD="your_password" \
./docs/test_portfolio_jwt.sh
```

---

## 已废弃的功能

以下接口已被移除，不再可用：

| 废弃接口 | 替代方案 |
|---------|---------|
| `GET/POST /api/ask` | `/api/secure-chat` 或 `/api/simple-chat` |
| `POST /api/portfolio/buy` | `POST /api/portfolio/apply-purchase`（按金额） |
| `POST /api/portfolio/sell` | `POST /api/portfolio/apply-redeem`（按份额） |
| `POST /api/portfolio/reserve-buy` | 已删除，无需预约 |
| `POST /api/portfolio/reserve-sell` | 已删除，无需预约 |
| `GET /api/portfolio/reservations` | 已删除 |
| `POST /api/portfolio/cancel-reservation` | 已删除 |
