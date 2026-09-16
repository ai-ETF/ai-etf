# 07-API 层

**被测模块**：`server/api/*`（market / secure_chat / portfolio / watchlist / risk）、`server/models/schemas.py`
**测试文件**（`tests/unit/server/api/`）：
- `test_schemas.py`、`test_market_api.py`、`test_secure_chat_api.py`、`test_portfolio_api.py`、`test_watchlist_api.py`、`test_risk_api.py`、`test_app.py`
- `conftest.py`（替身 langchain / document_service，见下）

**测试方法**：FastAPI `TestClient` + 最小 app + `dependency_overrides` 注入固定 `user_id`（跳过 JWT）+ monkeypatch 路由内部服务；全程不联网、不连 Supabase。

## 功能

各 API 路由端点的请求/响应契约：入参校验、业务服务调用、成功/失败状态码映射、响应模型序列化。

## 业务场景 / 预期结果 / 测试结果（6 组，36 例）

### 一、schemas 校验（8 例）

| 覆盖 | 结果 |
|------|:---:|
| `PurchaseRequest`/`WatchlistAddRequest`/`SubmitRequest`/`SubmitAnswerItem`/`AutoInvestConfigRequest` 必填缺失抛错、int→float 类型转换、可选字段默认值 | 8 例 ✅ |

### 二、market 路由（4 例，quotes 子模块）

| 端点 | 覆盖场景 | 结果 |
|------|------|:---:|
| `GET /market/spot/{code}` | 查到行情 / 未找到返回 error | 2 例 ✅ |
| `GET /market/spot/name/{name}` | 按名称查行情 | 1 例 ✅ |
| `GET /market/ranking` | 榜单返回 items | 1 例 ✅ |

### 三、secure_chat 路由（7 例）

| 端点 | 覆盖场景 | 结果 |
|------|------|:---:|
| `POST /secure-chat/login` | 登录成功返回 token/user_id | 1 例 ✅ |
| `POST /secure-chat/register` | 邮箱确认模式 | 1 例 ✅ |
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

## 运行方式

```bash
poetry run pytest tests/unit/server/api/ -v
```

> 本次 36 例全部通过（另 `test_app.py` 覆盖 N 类 `lifespan`，2 例）。

## 关键说明

### 1. conftest 替身（重依赖导入优化）

本环境 `langchain_anthropic` 导入 >60s，`document_service`（→ embedder/graphs）同样极重；二者在 `import server.api`（父包 `__init__` import `secure_chat`/`upload`）时被连带加载，会拖垮所有 API 测试。`tests/unit/server/api/conftest.py` 用空替身预填充 `sys.modules`：

- **langchain**：`server.llm` 只把 langchain 类当类型提示，`astream_text` 是纯逻辑、`get_llm` 惰性，故用空类替身即可让 `server.llm` 以真实代码加载。
- **document_service**：upload 路由依赖，M 类不测 upload，直接替换为 `DocumentService` 空类。

业务服务（FinanceApiService / PortfolioService / RiskService / WatchlistService / auth_service 等）在各测试文件里另行 monkeypatch。

### 2. 观察（未改源码）

- [server/api/risk.py:84](server/api/risk.py#L84) 用了 Pydantic v2 已弃用的 `a.dict()`（应改 `a.model_dump()`），有 `DeprecationWarning`，功能正常。
- `server/api/portfolio.py` 的 `get/set_auto_invest_config` 端点**在函数内重新 `import PortfolioService`**，与其余端点的模块级 import 不同——测试需同时 monkeypatch `server.api.portfolio.PortfolioService` 和 `server.services.portfolio_service.PortfolioService` 两处。
- `TestClient.delete` 不支持请求体；对 DELETE 且带 Pydantic 模型 body 的端点（如 `watchlist/remove`）需用 `client.request("DELETE", url, json=...)`。

### 3. 进度衔接

`test_app.py` 顺带覆盖了 N 类的 `app 生命周期 lifespan`（此前因 `server.app` 重导入而推迟）。至此 **N 类 6/6 全部完成**。
