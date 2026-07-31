# AI-ETF 后端 API 测试命令清单

> 后端地址：`http://47.113.220.182:8000`
> 测试时间：2026-07-27

---

## 一、基础测试

```bash
# 健康检查
curl -X GET "http://47.113.220.182:8000/"
```

```bash
# 上传模块健康检查
curl -X GET "http://47.113.220.182:8000/api/upload/health"
```

```bash
# 测试端点
curl -X GET "http://47.113.220.182:8000/api/test/hello"
```

---

## 二、已弃用的问答接口

> ⚠️ 以下 `/api/ask` 接口已弃用，建议迁移至 `/api/secure-chat` 或 `/api/simple-chat`。

### 2.1 问费率

```bash
curl -X POST "http://47.113.220.182:8000/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "华泰柏瑞红利低波ETF的管理费是多少"}'
```

### 2.2 问行情

```bash
curl -X POST "http://47.113.220.182:8000/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "华泰柏瑞红利低波ETF现在涨多少"}'
```

### 2.3 问榜单

```bash
curl -X POST "http://47.113.220.182:8000/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "ETF涨幅榜"}'
```

---

## 三、LLM 对话

### 3.1 简单对话（无认证、无历史记录）

```bash
curl -X POST "http://47.113.220.182:8000/api/simple-chat" \
  -H "Content-Type: application/json" \
  -d '{"question": "你好，请介绍一下自己"}'
```

### 3.2 登录获取 JWT Token

```bash
curl -X POST "http://47.113.220.182:8000/api/secure-chat/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "your_email@example.com", "password": "your_password"}'
```

### 3.3 流式对话（需 JWT 认证）

将 `<TOKEN>` 替换为登录获取的 access_token。

```bash
curl -X POST "http://47.113.220.182:8000/api/secure-chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"question": "我想买沪深300ETF，怎么选？"}'
```

### 3.4 获取会话列表（需 JWT）

```bash
curl -X GET "http://47.113.220.182:8000/api/secure-chat/chats?limit=50" \
  -H "Authorization: Bearer <TOKEN>"
```

### 3.5 查看会话消息（需 JWT）

```bash
curl -X GET "http://47.113.220.182:8000/api/secure-chat/chats/<CHAT_ID>/messages" \
  -H "Authorization: Bearer <TOKEN>"
```

### 3.6 删除会话（需 JWT）

```bash
curl -X DELETE "http://47.113.220.182:8000/api/secure-chat/chats/<CHAT_ID>" \
  -H "Authorization: Bearer <TOKEN>"
```

---

## 四、文档上传

### 4.1 上传文档

```bash
curl -X POST "http://47.113.220.182:8000/api/upload" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/document.pdf", "source": "test"}'
```

---

## 五、自选股管理（需 JWT 认证）

所有自选股接口需要在 Header 中携带 `Authorization: Bearer <TOKEN>`。
user_id 从 JWT 中自动读取，**不要**在请求体中传 `user_id`。

### 5.1 添加自选股

```bash
curl -X POST "http://47.113.220.182:8000/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"fund_code": "512890", "fund_name": "红利低波ETF华泰柏瑞"}'
```

```bash
curl -X POST "http://47.113.220.182:8000/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"fund_code": "510300", "fund_name": "沪深300ETF华泰柏瑞"}'
```

```bash
curl -X POST "http://47.113.220.182:8000/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"fund_code": "159611", "fund_name": "电力ETF广发"}'
```

### 5.2 查询自选股列表（含实时行情）

```bash
curl -X GET "http://47.113.220.182:8000/api/watchlist/list?include_quote=true" \
  -H "Authorization: Bearer <TOKEN>"
```

### 5.3 移除自选股

```bash
curl -X DELETE "http://47.113.220.182:8000/api/watchlist/remove" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"fund_code": "510300"}'
```

### 5.4 清空自选股

```bash
curl -X DELETE "http://47.113.220.182:8000/api/watchlist/clear" \
  -H "Authorization: Bearer <TOKEN>"
```

### 5.5 健康检查（公开，无需认证）

```bash
curl -X GET "http://47.113.220.182:8000/api/watchlist/health"
```

---

## 快速验证脚本

一键测试核心公开接口（不含需 JWT 的接口）：

```bash
#!/bin/bash
API="http://47.113.220.182:8000"

echo "=== 1. 健康检查 ==="
curl -s $API/

echo -e "\n=== 2. 测试端点 ==="
curl -s $API/api/test/hello | python3 -m json.tool 2>/dev/null

echo -e "\n=== 3. 上传健康检查 ==="
curl -s $API/api/upload/health | python3 -m json.tool 2>/dev/null

echo -e "\n=== 4. 自选股健康检查 ==="
curl -s $API/api/watchlist/health | python3 -m json.tool 2>/dev/null

echo -e "\n=== 5. 简单对话 ==="
curl -s -X POST $API/api/simple-chat \
  -H "Content-Type: application/json" \
  -d '{"question": "你好"}' | head -c 200
echo

echo -e "\n=== 6. 问答（已弃用）==="
curl -s -X POST $API/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "华泰柏瑞红利低波ETF的管理费是多少"}' | python3 -m json.tool 2>/dev/null | head -20

echo -e "\n✅ 测试完成"
```