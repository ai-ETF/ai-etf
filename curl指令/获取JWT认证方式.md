```bash
# 登录获取 JWT token
curl -X POST "http://47.113.220.182:8000/api/secure-chat/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "lpqst@outlook.com", "password": "ai-ETF"}'
```