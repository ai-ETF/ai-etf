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

## 六、模拟持仓交易（需 JWT 认证）

所有持仓接口需要在 Header 中携带 `Authorization: Bearer <TOKEN>`。
user_id 从 JWT 中自动读取，**不要**在请求体中传 `user_id`。

> **先登录获取 Token**（见 3.2），然后将 `<TOKEN>` 替换为 `access_token`。

### 6.1 查询账户概况

```bash
curl -s "http://47.113.220.182:8000/api/portfolio/account" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

返回：现金、持仓市值、总资产、总盈亏、总收益率、持仓数量。
初始资金 10 万，首次买入时自动创建账户。

### 6.2 买入基金

不传 price 则自动获取当前市价。

```bash
# 买入 100 份 512890（红利低波ETF）
curl -s -X POST "http://47.113.220.182:8000/api/portfolio/buy" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"fund_code":"512890","quantity":100}' | python3 -m json.tool
```

```bash
# 买入 200 份 510300（沪深300ETF）
curl -s -X POST "http://47.113.220.182:8000/api/portfolio/buy" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"fund_code":"510300","quantity":200}' | python3 -m json.tool
```

校验规则：
- 可用现金必须 ≥ 成交金额 + 申购费
- 申购金额不低于最低申购金额
- 成本价按加权平均重算（含手续费）

### 6.3 卖出基金

```bash
# 卖出 50 份 512890
curl -s -X POST "http://47.113.220.182:8000/api/portfolio/sell" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"fund_code":"512890","quantity":50}' | python3 -m json.tool
```

```bash
# 全部清仓
curl -s -X POST "http://47.113.220.182:8000/api/portfolio/sell" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"fund_code":"512890","quantity":50}' | python3 -m json.tool
```

校验规则：
- 卖出份额不超过持仓量
- 按持有天数计算赎回费
- 全部卖出后持仓自动清空

### 6.4 持仓列表

```bash
# 含实时行情和盈亏
curl -s "http://47.113.220.182:8000/api/portfolio/positions?include_quote=true" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

```bash
# 仅持仓数量，不计算行情
curl -s "http://47.113.220.182:8000/api/portfolio/positions?include_quote=false" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

返回：每只持仓的成本价、市价、市值、盈亏金额、盈亏百分比。

### 6.5 交易流水（分页）

```bash
# 全部流水，第 1 页
curl -s "http://47.113.220.182:8000/api/portfolio/trade-flow?page=1&page_size=10" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

```bash
# 按基金代码过滤
curl -s "http://47.113.220.182:8000/api/portfolio/trade-flow?fund_code=512890&page=1&page_size=10" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

```bash
# 只看买入
curl -s "http://47.113.220.182:8000/api/portfolio/trade-flow?direction=buy&page=1&page_size=10" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

返回：每笔成交的时间、代码、方向、价格、数量、成交金额、手续费，按时间倒序。

### 6.6 创建每日快照

```bash
curl -s -X POST "http://47.113.220.182:8000/api/portfolio/snapshot" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

同一天重复调用会覆盖更新。日终定时任务调用此接口。

### 6.7 每日收益率

```bash
# 最近 30 天
curl -s "http://47.113.220.182:8000/api/portfolio/daily-returns?days=30" \
  -H "Authorization: Bearer <TOKEN>" | python3 -m json.tool
```

日收益率 = (今日总资产 − 昨日总资产) / 昨日总资产。

### 6.8 健康检查（公开）

```bash
curl -s "http://47.113.220.182:8000/api/portfolio/health"
```

---

## 七、持仓交易快速验证脚本

一键测试持仓全流程（需要先登录获取 TOKEN）：

```bash
#!/bin/bash
API="http://47.113.220.182:8000"

# 替换为你的 JWT token（通过 /api/secure-chat/login 获取）
TOKEN="<YOUR_JWT_TOKEN>"

echo "=== 1. 账户概况 ==="
curl -s "$API/api/portfolio/account" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n=== 2. 买入 100 份 512890 ==="
curl -s -X POST "$API/api/portfolio/buy" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fund_code":"512890","quantity":100}' | python3 -m json.tool

echo -e "\n=== 3. 持仓查询 ==="
curl -s "$API/api/portfolio/positions?include_quote=true" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n=== 4. 卖出 50 份 ==="
curl -s -X POST "$API/api/portfolio/sell" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fund_code":"512890","quantity":50}' | python3 -m json.tool

echo -e "\n=== 5. 交易流水 ==="
curl -s "$API/api/portfolio/trade-flow?page=1&page_size=10" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n=== 6. 交易后账户概况 ==="
curl -s "$API/api/portfolio/account" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n=== 7. 创建快照 ==="
curl -s -X POST "$API/api/portfolio/snapshot" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n=== 8. 每日收益率 ==="
curl -s "$API/api/portfolio/daily-returns" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo -e "\n✅ 持仓交易测试完成"
```

---

## 快速验证脚本（公开接口）

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