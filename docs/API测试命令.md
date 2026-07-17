# AI-ETF 后端 API 测试命令清单

> 后端地址：`http://47.113.220.182:8000`
> 用户ID：`test-user-001`（自动转为UUID）
> 测试时间：2026-07-17

---

## 一、基础测试

```bash
# 健康检查
curl -X GET "http://47.113.220.182:8000/"
```

```bash
# 市场模块健康检查
curl -X GET "http://47.113.220.182:8000/api/market/health"
```

---

## 二、实时行情查询

### 2.1 按代码查询实时行情

```bash
curl -X GET "http://47.113.220.182:8000/api/market/spot/512890"
```

### 2.2 按名称查询实时行情

```bash
curl -X GET "http://47.113.220.182:8000/api/market/spot/name/华泰柏瑞红利低波ETF"
```

### 2.3 涨幅榜

```bash
curl -X GET "http://47.113.220.182:8000/api/market/ranking?top_n=10&order=desc"
```

### 2.4 跌幅榜

```bash
curl -X GET "http://47.113.220.182:8000/api/market/ranking?top_n=10&order=asc"
```

---

## 三、K线数据查询

### 3.1 日K线（最近30天）

```bash
curl -X GET "http://47.113.220.182:8000/api/market/kline/512890?period=daily&limit=30"
```

### 3.2 周K线（最近10周）

```bash
curl -X GET "http://47.113.220.182:8000/api/market/kline/512890?period=weekly&limit=10"
```

### 3.3 月K线（全部）

```bash
curl -X GET "http://47.113.220.182:8000/api/market/kline/512890?period=monthly"
```

### 3.4 按名称查询K线

```bash
curl -X GET "http://47.113.220.182:8000/api/market/kline/name/华泰柏瑞红利低波ETF?period=daily&limit=10"
```

---

## 四、分时图数据

### 4.1 按代码查询分时图

```bash
curl -X GET "http://47.113.220.182:8000/api/market/intraday/512890"
```

### 4.2 按名称查询分时图

```bash
curl -X GET "http://47.113.220.182:8000/api/market/intraday/name/华泰柏瑞红利低波ETF"
```

---

## 五、ETF详细信息

### 5.1 按代码查询详情

```bash
curl -X GET "http://47.113.220.182:8000/api/market/detail/512890"
```

### 5.2 按名称查询详情

```bash
curl -X GET "http://47.113.220.182:8000/api/market/detail/name/华泰柏瑞红利低波ETF"
```

---

## 六、资金流向

### 6.1 单只ETF资金流向

```bash
curl -X GET "http://47.113.220.182:8000/api/market/money-flow/512890"
```

### 6.2 按名称查询资金流向

```bash
curl -X GET "http://47.113.220.182:8000/api/market/money-flow/name/华泰柏瑞红利低波ETF"
```

### 6.3 资金流向排行榜（净流入榜）

```bash
curl -X GET "http://47.113.220.182:8000/api/market/money-flow/ranking?top_n=20&order=desc"
```

### 6.4 资金流出排行榜

```bash
curl -X GET "http://47.113.220.182:8000/api/market/money-flow/ranking?top_n=20&order=asc"
```

---

## 七、ETF搜索与筛选

### 7.1 搜索ETF（按关键词）

```bash
curl -X GET "http://47.113.220.182:8000/api/market/search?keyword=红利&top_n=10"
```

```bash
curl -X GET "http://47.113.220.182:8000/api/market/search?keyword=512890"
```

### 7.2 筛选ETF

```bash
curl -X POST "http://47.113.220.182:8000/api/market/filter" \
  -H "Content-Type: application/json" \
  -d '{"keyword": "红利", "min_return": 0.5, "top_n": 10, "sort_by": "涨跌幅", "sort_order": "desc"}'
```

### 7.3 获取分类列表

```bash
curl -X GET "http://47.113.220.182:8000/api/market/categories"
```

### 7.4 获取分类下基金

```bash
curl -X GET "http://47.113.220.182:8000/api/market/category/红利ETF?top_n=10"
```

```bash
curl -X GET "http://47.113.220.182:8000/api/market/category/科技ETF?top_n=10"
```

```bash
curl -X GET "http://47.113.220.182:8000/api/market/category/宽基ETF?top_n=10"
```

---

## 八、自选股管理

### 8.1 添加自选股

```bash
curl -X POST "http://47.113.220.182:8000/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user-001", "fund_code": "512890", "fund_name": "红利低波ETF华泰柏瑞"}'
```

```bash
curl -X POST "http://47.113.220.182:8000/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user-001", "fund_code": "510300", "fund_name": "沪深300ETF华泰柏瑞"}'
```

```bash
curl -X POST "http://47.113.220.182:8000/api/watchlist/add" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user-001", "fund_code": "159611", "fund_name": "电力ETF广发"}'
```

### 8.2 查询自选股列表（含实时行情）

```bash
curl -X GET "http://47.113.220.182:8000/api/watchlist/list/test-user-001?include_quote=true"
```

### 8.3 移除自选股

```bash
curl -X DELETE "http://47.113.220.182:8000/api/watchlist/remove" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user-001", "fund_code": "510300"}'
```

### 8.4 清空自选股

```bash
curl -X DELETE "http://47.113.220.182:8000/api/watchlist/clear/test-user-001"
```

---

## 九、问答系统（原有功能）

### 9.1 问费率

```bash
curl -X POST "http://47.113.220.182:8000/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "华泰柏瑞红利低波ETF的管理费是多少"}'
```

### 9.2 问行情

```bash
curl -X POST "http://47.113.220.182:8000/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "华泰柏瑞红利低波ETF现在涨多少"}'
```

### 9.3 问榜单

```bash
curl -X POST "http://47.113.220.182:8000/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "ETF涨幅榜"}'
```

---

## 快速验证脚本

一键测试核心功能：

```bash
#!/bin/bash
API="http://47.113.220.182:8000"

echo "=== 1. 健康检查 ==="
curl -s $API/

echo -e "\n=== 2. 实时行情 ==="
curl -s $API/api/market/spot/512890 | python3 -m json.tool 2>/dev/null | head -20

echo -e "\n=== 3. K线数据 ==="
curl -s "$API/api/market/kline/512890?limit=3" | python3 -m json.tool 2>/dev/null | head -20

echo -e "\n=== 4. 涨幅榜 ==="
curl -s "$API/api/market/ranking?top_n=3" | python3 -m json.tool 2>/dev/null | head -15

echo -e "\n=== 5. ETF详情 ==="
curl -s $API/api/market/detail/512890 | python3 -m json.tool 2>/dev/null | head -20

echo -e "\n=== 6. 资金流向 ==="
curl -s $API/api/market/money-flow/512890 | python3 -m json.tool 2>/dev/null | head -15

echo -e "\n=== 7. 搜索 ==="
curl -s "$API/api/market/search?keyword=红利&top_n=3" | python3 -m json.tool 2>/dev/null | head -15

echo -e "\n=== 8. 分类 ==="
curl -s $API/api/market/categories | python3 -m json.tool 2>/dev/null | head -15

echo -e "\n=== 9. 自选股 ==="
curl -s -X POST $API/api/watchlist/add \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user-001", "fund_code": "512890"}' | python3 -m json.tool 2>/dev/null
curl -s $API/api/watchlist/list/test-user-001 | python3 -m json.tool 2>/dev/null | head -15

echo -e "\n✅ 测试完成"
```