# API 测试指令（docs/api）

本目录是后端 API **唯一**的测试指令源。接口清单与 curl 示例均以 `server/api/__init__.py` 实际注册的路由为准，不再维护任何废弃接口的可用示例。

> 校验：修改接口后运行 `python docs/api/scripts/gen_index.py --url <API地址>` 可自动核对文档与线上路由是否一致，防止接口变更后文档过时。

## 模块导航

| 模块 | 文件 | 覆盖接口 |
|------|------|----------|
| 基础 & 认证 | [01-基础与认证.md](01-基础与认证.md) | 健康检查、`/api/secure-chat/login` 登录 |
| 对话 & 会话 | [02-对话与会话.md](02-对话与会话.md) | LLM 流式对话、会话管理 |
| 行情 | [03-行情.md](03-行情.md) | spot / ranking / kline / intraday / detail / money-flow / search / categories |
| 自选股 | [04-自选股.md](04-自选股.md) | watchlist |
| 组合交易 | [05-组合交易.md](05-组合交易.md) | portfolio：申购 / 赎回 / 持仓 / 流水 / 快照 / 定投 / `test/*` 开发接口 |
| 风险测评 | [06-风险测评.md](06-风险测评.md) | risk：问卷 / 提交 / 画像 |
| 文档上传 | [07-文档上传.md](07-文档上传.md) | upload |

## 环境配置

所有指令统一使用以下变量。**登录接口只在 `01-基础与认证.md` 出现一次**，其余模块文档直接引用这里的 `$TOKEN` / `$AUTH`。

```bash
# 服务器地址（按需切换）
API="https://ai-etf.xyz"           # 远程（HTTPS）
# API="http://localhost:8000"      # 本地

# 测试账号（填入你的账号）
EMAIL="<你的邮箱>"
PASSWORD="<你的密码>"

# 登录并提取 access_token（等价命令见 01-基础与认证.md）
TOKEN=$(curl -s -X POST "$API/api/secure-chat/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
AUTH="Authorization: Bearer $TOKEN"
```

> 提示：token 有效期 3600 秒（1 小时），过期后重新执行登录即可。

## 接口总览

> 由 `scripts/gen_index.py` 从线上 `/openapi.json` 生成，字段含义：`🔒`=需要 JWT，`-`=公开接口。

| 方法 | 路径 | 认证 | 文档 |
|------|------|:---:|------|
| GET | `/` | - | [01](01-基础与认证.md) |
| GET | `/api/test/hello` | - | [01](01-基础与认证.md) |
| POST | `/api/secure-chat/login` | - | [01](01-基础与认证.md) |
| POST | `/api/secure-chat` | 🔒 | [02](02-对话与会话.md) |
| GET | `/api/secure-chat/chats` | 🔒 | [02](02-对话与会话.md) |
| GET | `/api/secure-chat/chats/{chat_id}/messages` | 🔒 | [02](02-对话与会话.md) |
| DELETE | `/api/secure-chat/chats/{chat_id}` | 🔒 | [02](02-对话与会话.md) |
| POST | `/api/watchlist/add` | 🔒 | [04](04-自选股.md) |
| DELETE | `/api/watchlist/remove` | 🔒 | [04](04-自选股.md) |
| GET | `/api/watchlist/list` | 🔒 | [04](04-自选股.md) |
| DELETE | `/api/watchlist/clear` | 🔒 | [04](04-自选股.md) |
| GET | `/api/watchlist/health` | - | [04](04-自选股.md) |
| GET | `/api/market/health` | - | [03](03-行情.md) |
| GET | `/api/market/spot/{fund_code}` | - | [03](03-行情.md) |
| GET | `/api/market/spot/name/{fund_name}` | - | [03](03-行情.md) |
| GET | `/api/market/ranking` | - | [03](03-行情.md) |
| GET | `/api/market/kline/{fund_code}` | - | [03](03-行情.md) |
| GET | `/api/market/kline/name/{fund_name}` | - | [03](03-行情.md) |
| GET | `/api/market/intraday/{fund_code}` | - | [03](03-行情.md) |
| GET | `/api/market/intraday/name/{fund_name}` | - | [03](03-行情.md) |
| GET | `/api/market/detail/{fund_code}` | - | [03](03-行情.md) |
| GET | `/api/market/detail/name/{fund_name}` | - | [03](03-行情.md) |
| GET | `/api/market/money-flow/{fund_code}` | - | [03](03-行情.md) |
| GET | `/api/market/money-flow/name/{fund_name}` | - | [03](03-行情.md) |
| GET | `/api/market/money-flow/ranking` | - | [03](03-行情.md) |
| GET | `/api/market/search` | - | [03](03-行情.md) |
| POST | `/api/market/filter` | - | [03](03-行情.md) |
| GET | `/api/market/categories` | - | [03](03-行情.md) |
| GET | `/api/market/category/{category}` | - | [03](03-行情.md) |
| POST | `/api/portfolio/apply-purchase` | 🔒 | [05](05-组合交易.md) |
| POST | `/api/portfolio/apply-redeem` | 🔒 | [05](05-组合交易.md) |
| GET | `/api/portfolio/positions` | 🔒 | [05](05-组合交易.md) |
| GET | `/api/portfolio/account` | 🔒 | [05](05-组合交易.md) |
| GET | `/api/portfolio/trade-flow` | 🔒 | [05](05-组合交易.md) |
| POST | `/api/portfolio/snapshot` | 🔒 | [05](05-组合交易.md) |
| POST | `/api/portfolio/confirm-pending` | 🔒 | [05](05-组合交易.md) |
| GET | `/api/portfolio/daily-returns` | 🔒 | [05](05-组合交易.md) |
| GET | `/api/portfolio/auto-invest/config` | 🔒 | [05](05-组合交易.md) |
| POST | `/api/portfolio/auto-invest/config` | 🔒 | [05](05-组合交易.md) |
| GET | `/api/portfolio/health` | - | [05](05-组合交易.md) |
| POST | `/api/portfolio/test/apply-purchase` | `X-User-Id` | [05](05-组合交易.md) |
| POST | `/api/portfolio/test/apply-redeem` | `X-User-Id` | [05](05-组合交易.md) |
| GET | `/api/portfolio/test/positions` | `X-User-Id` | [05](05-组合交易.md) |
| GET | `/api/portfolio/test/account` | `X-User-Id` | [05](05-组合交易.md) |
| GET | `/api/portfolio/test/trade-flow` | `X-User-Id` | [05](05-组合交易.md) |
| POST | `/api/portfolio/test/snapshot` | `X-User-Id` | [05](05-组合交易.md) |
| GET | `/api/portfolio/test/daily-returns` | `X-User-Id` | [05](05-组合交易.md) |
| GET | `/api/risk/health` | - | [06](06-风险测评.md) |
| GET | `/api/risk/questionnaire` | 🔒 | [06](06-风险测评.md) |
| POST | `/api/risk/submit` | 🔒 | [06](06-风险测评.md) |
| GET | `/api/risk/profile` | 🔒 | [06](06-风险测评.md) |
| POST | `/api/upload` | - | [07](07-文档上传.md) |
| POST | `/api/upload/process-file-from-edge` | - | [07](07-文档上传.md) |
| GET | `/api/upload/health` | - | [07](07-文档上传.md) |

## 新增接口规范

1. 复制 [`_template.md`](_template.md) 为 `NN-模块名.md`（`NN` 为顺序号，保持列表稳定）。
2. 按模板填写：接口说明、curl 示例（统一用 `$API` / `$TOKEN` 变量）、参数表、响应要点。
3. 在 README「接口总览」表加一行。
4. 运行校验：
   ```bash
   python docs/api/scripts/gen_index.py --url "$API"
   ```
   确认输出没有「缺文档」/「文档引用了不存在的接口」告警。

## 冒烟测试

```bash
bash docs/api/scripts/smoke_test.sh          # 默认远程
bash docs/api/scripts/smoke_test.sh --url http://localhost:8000
```

仅测试无需 JWT 的公开接口，快速确认服务是否健康。
