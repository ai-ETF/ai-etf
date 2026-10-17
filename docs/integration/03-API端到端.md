# 03-API端到端

**被测模块**：`server/api/portfolio.py`、`server/api/off_exchange_funds.py`、`server/api/watchlist.py`、`server/api/risk.py`、`server/api/secure_chat.py`
**测试文件**：`tests/integration/server/api/test_portfolio_e2e.py`、`test_off_exchange_funds_e2e.py`、`test_watchlist_e2e.py`、`test_risk_e2e.py`、`test_secure_chat_e2e.py`
**测试方法**：FastAPI `TestClient` + 真实 `app` + 本地 Supabase 栈；鉴权用**自签 HS256 JWT**（`aud=authenticated`）或真实注册登录；调度器在 fixture 里替换成空函数，避免启动时抓行情

## 功能

从 HTTP 路由一路打到真实数据库的「纵向切片」：路由参数解析 → 鉴权 → 服务层 → Postgres → 响应体。这里测的是**接口契约与真实数据的结合**，不是单独的业务逻辑（后者在 02 文档）。

> `api_client` fixture（`tests/integration/conftest.py:303-335`）做三件事：给 `get_supabase()` 换一个独立的本地 client（避免 `sign_up` 把 service_role 切成 authenticated 触发 RLS）、把调度器换成空函数、把 `SUPABASE_JWT_SECRET` 指向本地 secret 使自签 token 能通过校验。

## 业务场景 / 预期结果 / 测试结果

### 一、场外基金交易 API（3 例）

| 场景 | 预期 |
|------|------|
| 工作日盘中申购 1000 元 | 200、`success=true`、`status=pending`；库里 `cash=99000`、`frozen_cash=1000`、1 条 pending 订单 |
| 申购后查账户概况 | 200，`cash=99000`、`frozen_cash=1000`（响应与库一致） |
| 申购不支持的基金 999999 | 400，`detail` 含「不支持」 |

**测试结果**：3 例全部通过。

### 二、场外基金目录 API（14 例）

**业务场景**：小程序「买基金」页的列表、搜索、分页、详情都走这里。重点是列表与详情返回的**口径一致**、详情能查到就一定能下单。

#### 2.1 鉴权（2 例）

| 场景 | 预期 |
|------|------|
| 无 token 查列表 | 422 |
| 无 token 查详情 | 422 |

**依据**：鉴权依赖声明为 `authorization: str = Header(...)`（`server/auth/deps.py:41`），缺头是**请求参数校验失败**，FastAPI 固定返回 422。同仓 `test_watchlist_e2e.py:23-27` 就是按 422 写的。⇒ 原用例期望 401/403 是写错了，2026-10-17 已改为 422。

**测试结果**：2 例全部通过。

#### 2.2 列表、搜索、分页（8 例）

| 场景 | 预期 |
|------|------|
| 查列表 | `total >= 20`；默认第 1 页 / 每页 20 条；110020 的基金名、类型、份额类别、T+1/T+3、风险标签全部正确 |
| 列表项 | **不含** `purchase_fee_tiers`（分档体积大，只在详情返回） |
| 按代码搜 110020 | `total=1`，代码正确 |
| 按名称搜「银行」 | `total=2`，代码集合 `{001594, 001595}`，名称都含「银行」 |
| 搜索无结果 | 200，`total=0`，`items=[]` |
| 搜索词含特殊字符 `110020,name.ilike.x` | 200，`total=0` |
| 分页 page=1/2，每页 5 | 各 5 条；两页不重叠；`total` 一致 |
| `page_size=500` | 422（超过上限） |

> 特殊字符那条的意图：PostgREST 的 `or_` 过滤器用逗号/括号分隔表达式，关键词里的这些字符必须被剔除。实现（`server/services/fund_fee_service.py:199`）清洗后变成 `110020nameilikex`，匹配 0 条。**2026-10-17 决定按「清洗后 0 条」改期望**：这条用例钉的是「特殊字符不会把查询搞坏（不 500、不注入）」，清洗规则本身由实现决定，不在测试里锁死。

**测试结果**：8 例全部通过。

#### 2.3 详情（4 例 → 3 失败、1 通过）

| 场景 | 预期 | 实际 |
|------|------|------|
| 110020 详情 | 费率分档 4 档、赎回分档 4 档、风险 `moderate`、`breadth_score=1` | **500**（失败） |
| 000071（QDII） | `confirm_delay=2`、`redeem_settle_delay=7`、`market_score=3` | **500**（失败） |
| 999999 | 404，`detail` 含「不支持」 | 通过 |
| 110020 能查详情 ⇔ 能下单；999999 查不到 ⇔ 下单 400 | 口径一致 | **500**（失败） |

**根因（真 bug）**：`server/api/off_exchange_funds.py:95-99`

```python
detail = svc.get_fund_detail(fund_code)
...
return OffExchangeFundDetailResponse(
    **detail,
    purchase_fee_tiers=_normalize_tiers(detail.get("purchase_fee_tiers")),
    redemption_fee_tiers=_normalize_tiers(detail.get("redemption_fee_tiers")),
)
```

`get_fund_detail()` 返回的 `detail` **本来就含** `purchase_fee_tiers` / `redemption_fee_tiers` 两个键，再作为显式关键字参数传一次 → `TypeError: got multiple values for keyword argument` → 路由 500。**这三条失败是产品缺陷，不是测试问题**；修复方向是二选一：从 `detail` 里 pop 掉这两个键再展开，或者不再显式传参、改为在展开前替换值。按规矩这里只登记，不顺手改（属别人的模块）。

**测试结果**：14 例中 **11 通过、3 失败**（只剩 3 条详情 500）；2 条鉴权与 1 条特殊字符已于 2026-10-17 改用例改对。

### 三、自选股 API（4 例）

| 场景 | 预期 |
|------|------|
| 无 Authorization 头 | 422 |
| 无效 token | 401 |
| 添加 → 列表 → 查库 → 删除 | 每步成功；库中各 1 条 / 0 条；列表 `total=1` |
| 添加两只后清空 | `removed_count=2`，库中 0 行 |

**测试结果**：4 例全部通过。

### 四、风险测评 API（4 例）

| 场景 | 预期 |
|------|------|
| 获取问卷 | 版本 `v1.0`，5 题；题目不含 `risk_score` 等内部字段 |
| 提交全选 A | 201，`profile.risk_level=conservative`；随后查询 `has_profile=true` |
| 未提交就查画像 | 200，`has_profile=false` |
| 只提交 1 题 | 400 |

**测试结果**：4 例全部通过。

### 五、认证与对话 API（4 例）

**业务场景**：走真实 Supabase Auth（gotrue），不是替身。注册使用 `auto-confirm`，测试结束用 SQL 直删用户（`sign_up` 创建的用户用 `admin.delete_user` 会报「User not allowed」，见 `conftest.py:272-300`）。

| 场景 | 预期 |
|------|------|
| 注册 | 200，返回 `access_token` 与 `user_id` |
| 用刚注册的账号登录 | 200，`access_token` 非空，`user_id` 与注册时一致 |
| 重复注册同一邮箱 | 409 |
| 密码错误登录 | 401 |

**测试结果**：4 例全部通过。

## 已知失败汇总（2026-10-17 改用例后实测）

> 全量结果：选中 90 条，**87 通过 / 3 失败 / 0 跳过，315.23 秒**。原来 7 条里「用例写错」的 4 条已改对，只剩 3 条详情 500。

| 用例 | 归类 | 处置 |
|------|------|------|
| `test_基金详情_含费率分档与风险` / `_QDII基金T加2七日` / `_与交易白名单口径一致`（3 条） | **真 bug（500）** | 登记在案；修复需改 `server/api/off_exchange_funds.py`，动别人代码前先问作者。据说组长可能已修，待确认 |

合计 **3 条固定失败**，全部来自 PR #18（`60ed1b3`），与本地环境无关。**这也是给集成测试挂 `pull_request` 之前必须先处理的事**——否则每个 PR 都会红。
