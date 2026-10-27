---
id: "50-测试/单元测试/07-API层"
title: "07-API 层"
status: active
owner: "sing"
updated: 2026-10-27
tags: ["测试", "单元测试"]
supersedes: []
superseded_by: null
---

# 07-API 层

**被测模块**：`server/api/*`（market / secure_chat / portfolio / watchlist / risk）、`server/models/schemas.py`
**测试文件**（`tests/unit/server/api/`）：
- `test_schemas.py`、`test_market_api.py`、`test_secure_chat_api.py`、`test_portfolio_api.py`、`test_watchlist_api.py`、`test_risk_api.py`、`test_app.py`
- `conftest.py`（替身 langchain / document_service，见下）

**测试方法**：FastAPI `TestClient` + 最小 app + `dependency_overrides` 注入固定 `user_id`（跳过 JWT）+ monkeypatch 路由内部服务；全程不联网、不连 Supabase。

## 功能

各 API 路由端点的请求/响应契约：入参校验、业务服务调用、成功/失败状态码映射、响应模型序列化。

## 业务场景 / 预期结果 / 测试结果（8 组，59 例）

### 一、schemas 校验（8 例）

| 覆盖 | 结果 |
|------|:---:|
| `PurchaseRequest`/`WatchlistAddRequest`/`SubmitRequest`/`SubmitAnswerItem`/`AutoInvestConfigRequest` 必填缺失抛错、int→float 类型转换、可选字段默认值 | 8 例 ✅ |

### 二、market 路由（7 例，search / detail 子模块）

| 端点 | 覆盖场景 | 结果 |
|------|------|:---:|
| `GET /market/search` | 命中并返回最新净值 / **场内 ETF 代码返回 `total: 0`** | 2 例 ✅ |
| `GET /market/detail/{code}` | **目录外代码 404 + 明确原因** / 历史净值暂不可用 503 / 正常返回且 `is_qdii` 透传、**不含 `realtime`** | 3 例 ✅ |
| `GET /market/detail/name/{name}` | 名称命中目录外基金 404 / 历史净值不可用 503 | 2 例 ✅ |

> 2026-10-26：`quotes` / `money_flow` 子模块及其 4 例随 30 秒行情下线删除；
> 新增的用例守住「目录外 404、数据未就绪 503」这两条错误语义。

### 三、secure_chat 路由（12 例）

| 端点 | 覆盖场景 | 结果 |
|------|------|:---:|
| `POST /secure-chat/login` | 登录成功返回 token/user_id / 未返回 session 抛 401 | 2 例 ✅ |
| `POST /secure-chat/register` | 邮箱确认模式 / 自动登录透传 refresh_token | 2 例 ✅ |
| `POST /secure-chat/refresh` | 成功返回新 token 对 / token 失效透传 401 / 缺参 422 | 3 例 ✅ |
| `POST /secure-chat/logout` | 撤销 token | 1 例 ✅ |
| `POST /secure-chat/delete-account` | 注销账号 | 1 例 ✅ |
| `GET /secure-chat/chats` | 会话列表 | 1 例 ✅ |
| `GET /secure-chat/chats/{id}/messages` | 消息历史 | 1 例 ✅ |
| `DELETE /secure-chat/chats/{id}` | 删除会话 | 1 例 ✅ |

### 四、portfolio 路由（8 例）

| 端点 | 覆盖场景 | 结果 |
|------|------|:---:|
| `POST /apply-purchase` | 成功 / 失败 400 | 2 例 ✅ |
| `POST /apply-redeem` | 成功 | 1 例 ✅ |
| `GET /positions` | 持仓列表 | 1 例 ✅ |
| `GET /account` | 账户概况 | 1 例 ✅ |
| `GET /trade-flow` | 交易流水 | 1 例 ✅ |
| `GET/POST /auto-invest/config` | 查询 / 设置余额理财 | 2 例 ✅ |

### 五、watchlist 路由（4 例）

| 端点 | 结果 |
|------|:---:|
| add / remove / list / clear | 4 例 ✅ |

### 六、risk 路由（5 例）

| 端点 | 覆盖场景 | 结果 |
|------|------|:---:|
| `GET /questionnaire` | 返回问卷 | 1 例 ✅ |
| `POST /submit` | 成功 201 / 业务失败 400 | 2 例 ✅ |
| `GET /profile` | 有画像 / 无画像 | 2 例 ✅ |

### 七、交易日历管理路由（12 例）

| 端点 | 覆盖场景 | 结果 |
|------|------|:---:|
| `POST /admin/trading-calendar/refresh` | 未配管理凭证 503 / 凭证错误 401 / 缺幂等键 400 / 刷新成功返回契约字段 / dry_run 透传不写库 / 已有刷新在跑 409 / 数据校验失败 422 / 源失败 502 / 源超时 504 / 整体超时 504 / 未预期异常 500 | 11 例 ✅ |
| `GET /admin/trading-calendar/status` | 只读返回 ready | 1 例 ✅ |

> 详见 `docs/40-运维/交易日历` 与 `trading-calendar-ops` 技能。

### 八、app 生命周期（3 例）

`test_app.py` 覆盖 `lifespan` 启停（含调度器注册/关闭无残留）。

## 运行方式

```bash
poetry run pytest tests/unit/server/api/ -v
```

> 本次 59 例全部通过（`test_app.py` 3 例覆盖 `lifespan`，`test_admin_trading_calendar.py` 12 例见下）。

## 关键说明

### 1. conftest 替身（重依赖导入优化）

本环境 `langchain_anthropic` 导入 >60s，`document_service`（→ embedder/graphs）同样极重；二者在 `import server.api`（父包 `__init__` import `secure_chat`/`upload`）时被连带加载，会拖垮所有 API 测试。`tests/unit/server/api/conftest.py` 用空替身预填充 `sys.modules`：

- **langchain**：`server.llm` 只把 langchain 类当类型提示，`astream_text` 是纯逻辑、`get_llm` 惰性，故用空类替身即可让 `server.llm` 以真实代码加载。
- **document_service**：upload 路由依赖，M 类不测 upload，直接替换为 `DocumentService` 空类。

业务服务（FinanceApiService / PortfolioService / RiskService / WatchlistService / auth_service 等）在各测试文件里另行 monkeypatch。

### 2. 观察（未改源码）

- [server/api/risk.py:84](../../../server/api/risk.py#L84) 用了 Pydantic v2 已弃用的 `a.dict()`（应改 `a.model_dump()`），有 `DeprecationWarning`，功能正常。
- `server/api/portfolio.py` 的 `get/set_auto_invest_config` 端点**在函数内重新 `import PortfolioService`**，与其余端点的模块级 import 不同——测试需同时 monkeypatch `server.api.portfolio.PortfolioService` 和 `server.services.portfolio_service.PortfolioService` 两处。
- `TestClient.delete` 不支持请求体；对 DELETE 且带 Pydantic 模型 body 的端点（如 `watchlist/remove`）需用 `client.request("DELETE", url, json=...)`。

### 3. 进度衔接

`test_app.py` 顺带覆盖了 N 类的 `app 生命周期 lifespan`（此前因 `server.app` 重导入而推迟）。至此 **N 类 6/6 全部完成**。
