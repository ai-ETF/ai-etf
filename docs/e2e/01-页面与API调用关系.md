# E2E 规划 · 页面 → API 调用关系（校验与补全）

> 本文**不重做** `00-背景与已知问题.md` §4.3 的映射表，而是在其基础上**逐个调用点核对后补全与纠错**。
> 核对方式：前端全量 grep 调用点 → 回溯到页面/组件 → 与后端 58 个路由逐条比对。
> 核对日期：2026-09-20。前端 `application@feature/market-inquiry`（工作区有 1 处未提交改动），后端 `ai-etf@fix/secure-chat-rename-title`。

---

## 一、结论摘要（先看这 6 条）

| # | 结论 | 影响 |
|---|---|---|
| 1 | `00` 文档的 10 个页面映射**基本准确**，仅缺 **1 处**：`pages/settings` 还调 `GET /api/portfolio/account` | 补进映射表 |
| 2 | **后端 58 个端点，只有 23 个有前端活跃调用点**（`00` 说的「8 个未接线」是**族级**口径，端点级实际是 **19 个业务端点无前端入口**） | 候选路径必须按本文 §四 的白名单挑 |
| 3 | ⭐ `POST /api/secure-chat/delete-account`（注销账号）**在 ✅要测范围内，但前端根本没有入口** | 注销**不能**设计成 E2E 路径步骤，只能做接口级测试 |
| 4 | ⭐ `00` 说的「`ranking` 传 `limit` 已修」**修在了死代码里**：`/api/market/ranking` 唯一调用点是 `useMarketQuery.ts`，而该文件**没有任何页面 import** | 前端**没有任何涨幅榜入口**，`ranking` 实际等同未接线 |
| 5 | `api/modules/market.ts` 的 `getSpot()` 已导出但**无人 import** → `GET /api/market/spot/{code}` 也未接线 | 同 4，勿设计进用例 |
| 6 | `src/api/modules/{etf,user}.ts`、`src/api/request.ts` 确为 `export {}` 空文件（已确认） | 真实调用在 `stores/`、`composables/`、`pages/` |

---

## 二、对 `00-背景与已知问题.md` 的修正清单

> 建议后续在 00 文档中按此表修订（本文不改动 00）。

| 位置 | 原文 | 核对结果 | 建议改法 |
|---|---|---|---|
| §3「页面 → API」表 · `pages/settings` 行 | 只列 `POST /api/secure-chat/logout` | ❌ 不完整 | 补 `GET /api/portfolio/account`（[settings/index.vue:281](application/src/pages/settings/index.vue#L281) 的 `onShow(loadAccountSummary)`） |
| §4.2 端点统计 | 「共 57 个端点（56 个唯一路径）」「JWT 必需 23」 | ❌ 少了 1 | 应为 **58 个端点 / 57 个唯一路径**；**JWT 必需 24**。差量正是 `PUT /api/secure-chat/chats/{chat_id}/title`（该端点是在统计之后新增的）。公开 27、`X-User-Id` 7 两项**核对无误** |
| §5「已修复」· ranking 行 | 「前端改传 `top_n`」✅ | ⚠️ 事实成立但**无意义** | 该改动落在 [useMarketQuery.ts:78](application/src/composables/useMarketQuery.ts#L78)，属未被 import 的死代码。建议标注「修在死代码中，前端仍无榜单入口」 |
| §5「8 个后端接口前端未接线」 | 列 8 项 | ⚠️ 端点级为 19 项 | 见本文 §四；**另需补** `delete-account`、`spot/{code}`、`spot/name/{name}`、`detail/name/{name}`、`kline/name/{name}`、`category/{category}` |
| §5「README 接口总览表已过时」 | 「缺 register/logout/delete-account…需重跑 gen_index.py」 | ✅ **已解决** | commit `3f2573c`「补齐接口文档」已修，`docs/api/README.md` 现列 **58 行**、含 `PUT .../title`。该项可从已知问题中移除 |
| §3 注「`useMarketQuery.ts` 的 `askQuestion` 未被任何页面 import」 | — | ✅ 复核正确 | 保持 |

---

## 三、完整映射表（11 个入口 × 活跃调用点）

> 「真实」= 从页面可触达的调用；「死代码」= 有代码但无 import 链。
> 后端路径统一省略 `/api` 前缀之外的模块前缀。

### 3.1 页面级（`src/pages/` 共 10 个，与 `src/pages.json` 一致）

| 页面 | 后端接口 | 调用点 | 真实 |
|---|---|---|:---:|
| `pages/login` | `POST /secure-chat/login` | [useAuth.ts:109-115](application/src/composables/useAuth.ts#L109-L115)（`uni.request` 直调，**绕过** `utils/request.ts`） | ✅ |
| `pages/register` | `POST /secure-chat/register` | [useAuth.ts:146-152](application/src/composables/useAuth.ts#L146-L152)（同上，直调） | ✅ |
| `pages/index`（首页/聊天） | `POST /secure-chat`（SSE） | [index.vue:208-219](application/src/pages/index/index.vue#L208-L219) MP 分支 `uni.request + enableChunked`；[index.vue:303](application/src/pages/index/index.vue#L303) H5 分支 `fetch` | ✅ |
| | `GET /secure-chat/chats?limit=50` | [chat.ts:91-94](application/src/stores/chat.ts#L91-L94) | ✅ |
| | `GET /secure-chat/chats/{id}/messages?limit=100` | [chat.ts:111-114](application/src/stores/chat.ts#L111-L114) | ✅ |
| | `DELETE /secure-chat/chats/{id}` | [chat.ts:163-166](application/src/stores/chat.ts#L163-L166) | ✅ |
| | `PUT /secure-chat/chats/{id}/title` | [chat.ts:188-193](application/src/stores/chat.ts#L188-L193) | ✅ |
| `pages/etf-detail` | `GET /market/detail/{code}` | [etf-detail/index.vue:171](application/src/pages/etf-detail/index.vue#L171) | ✅ |
| | `GET /market/kline/{code}?period=daily&limit=60` | [etf-detail/index.vue:98](application/src/pages/etf-detail/index.vue#L98) | ✅ |
| | `POST /watchlist/add` / `DELETE /watchlist/remove` | [etf-detail/index.vue:149-150](application/src/pages/etf-detail/index.vue#L149-L150) → [watchlist.ts:256](application/src/stores/watchlist.ts#L256) | ✅ |
| | `GET /watchlist/list` | [etf-detail/index.vue:74](application/src/pages/etf-detail/index.vue#L74)（为判断 `followed`） | ✅ |
| `pages/watchlist` | `GET /watchlist/list?include_quote=true` | [watchlist.ts:126](application/src/stores/watchlist.ts#L126) | ✅ |
| | `POST /watchlist/add`（带 `fund_name`） | [watchlist/index.vue:226](application/src/pages/watchlist/index.vue#L226) | ✅ |
| | `DELETE /watchlist/remove`（**带 body**） | [watchlist/index.vue:266](application/src/pages/watchlist/index.vue#L266) | ✅ |
| | `DELETE /watchlist/clear` | [watchlist/index.vue:285](application/src/pages/watchlist/index.vue#L285) | ✅ |
| | `GET /market/search?keyword=&top_n=15` | [watchlist.ts:156](application/src/stores/watchlist.ts#L156)（防抖 400ms，[watchlist/index.vue:378](application/src/pages/watchlist/index.vue#L378)） | ✅ |
| | `GET /market/detail/{code}`（搜索无结果时的六位代码回退） | [watchlist.ts:168](application/src/stores/watchlist.ts#L168)、[:204](application/src/stores/watchlist.ts#L204) | ✅ |
| | `GET /portfolio/account`、`GET /portfolio/positions?include_quote=true` | [watchlist/index.vue:317+](application/src/pages/watchlist/index.vue#L317)（仅「持仓」Tab） | ✅ |
| `pages/purchase` | `GET /market/detail/{code}` | [purchase/index.vue:66](application/src/pages/purchase/index.vue#L66) | ✅ |
| | `POST /portfolio/apply-purchase`（`fund_code`+`amount`） | [purchase/index.vue:84](application/src/pages/purchase/index.vue#L84) → [portfolio.ts:98](application/src/api/modules/portfolio.ts#L98) | ✅ |
| | `GET /portfolio/account` | [purchase/index.vue:60](application/src/pages/purchase/index.vue#L60)（`onShow` 每次进入都调） | ✅ |
| `pages/redeem` | `POST /portfolio/apply-redeem`（`fund_code`+`quantity`） | [redeem/index.vue:72](application/src/pages/redeem/index.vue#L72) | ✅ |
| | `GET /portfolio/positions` | [redeem/index.vue:40](application/src/pages/redeem/index.vue#L40) | ✅ |
| `pages/trades` | `GET /portfolio/trade-flow?page=1&page_size=20` | [trades/index.vue:25](application/src/pages/trades/index.vue#L25) | ✅ |
| `pages/risk-assessment` | `GET /risk/questionnaire` | [risk.ts:25](application/src/api/modules/risk.ts#L25) ← [risk-assessment/index.vue:292](application/src/pages/risk-assessment/index.vue#L292) | ✅ |
| | `POST /risk/submit`（`questionnaire_id`+`answers[]`） | [risk-assessment/index.vue:404-407](application/src/pages/risk-assessment/index.vue#L404-L407) | ✅ |
| | `GET /risk/profile` | [risk-assessment/index.vue:315](application/src/pages/risk-assessment/index.vue#L315) | ✅ |
| `pages/settings` | `POST /secure-chat/logout` | [useAuth.ts:181-186](application/src/composables/useAuth.ts#L181-L186)（`uni.request` 直调） | ✅ |
| | ⭐ `GET /portfolio/account` | [settings/index.vue:237](application/src/pages/settings/index.vue#L237)（`onShow`） | ✅ **00 文档遗漏** |

### 3.2 非页面入口（容易被漏掉的两类）

| 入口 | 说明 |
|---|---|
| **`utils/request.ts` 是唯一的鉴权汇聚点** | 除 `login`/`register`/`logout` 三个直调外，**其余 20 个接口全部经过** [utils/request.ts:34](application/src/utils/request.ts#L34)。401 拦截、token 注入、`/api/market/` 放行未登录都在这里 → E2E 的 P4 只需打这一个点 |
| **`components/common/TabBar.vue` 不是真的 tabBar** | `pages.json` **没有 `tabBar` 段**，四个 Tab 是自定义组件，用 `uni.redirectTo` 跳转（[TabBar.vue:116-133](application/src/components/common/TabBar.vue#L116-L133)）。这带来 2 个后果：① Tab 切换会**销毁当前页栈**；② ⚠️ [settings/index.vue:309](application/src/pages/settings/index.vue#L309) 的「持仓卡片」用的是 **`uni.switchTab`**，而 `pages.json` 无 tabBar → **该入口在微信端会失败**（详见 §六 需确认 #2） |

---

## 四、后端 58 端点 × 前端接线情况（E2E 白名单）

> 口径：**有前端活跃调用点 = 可进 E2E 路径**；「无入口」= 前端无任何可达调用，**禁止**设计成 E2E 用例步骤。

### 4.1 ✅ 有前端活跃调用点（23 个）— E2E 只能从这 23 个里挑

| # | 后端接口 | 前端入口 |
|---|---|---|
| 1 | `POST /api/secure-chat/login` | 登录页 |
| 2 | `POST /api/secure-chat/register` | 注册页 |
| 3 | `POST /api/secure-chat/logout` | 设置页 |
| 4 | `POST /api/secure-chat`（SSE） | 首页 |
| 5 | `GET /api/secure-chat/chats` | 首页 |
| 6 | `GET /api/secure-chat/chats/{id}/messages` | 首页 |
| 7 | `DELETE /api/secure-chat/chats/{id}` | 首页 |
| 8 | `PUT /api/secure-chat/chats/{id}/title` | 首页 |
| 9 | `GET /api/market/search` | 自选页 |
| 10 | `GET /api/market/detail/{code}` | 详情页 / 申购页 / 自选页 |
| 11 | `GET /api/market/kline/{code}` | 详情页 |
| 12 | `POST /api/watchlist/add` | 自选页 / 详情页 |
| 13 | `DELETE /api/watchlist/remove` | 自选页 / 详情页 |
| 14 | `GET /api/watchlist/list` | 自选页 / 详情页 |
| 15 | `DELETE /api/watchlist/clear` | 自选页 |
| 16 | `GET /api/portfolio/account` | 自选页 / 申购页 / 设置页 |
| 17 | `GET /api/portfolio/positions` | 自选页 / 赎回页 |
| 18 | `POST /api/portfolio/apply-purchase` | 申购页 |
| 19 | `POST /api/portfolio/apply-redeem` | 赎回页 |
| 20 | `GET /api/portfolio/trade-flow` | 交易记录页 |
| 21 | `GET /api/risk/questionnaire` | 风险测评页 |
| 22 | `POST /api/risk/submit` | 风险测评页 |
| 23 | `GET /api/risk/profile` | 风险测评页 |

### 4.2 ❌ 无前端入口的业务端点（19 个）— 不要设计进 E2E

| 接口 | 备注 |
|---|---|
| `POST /api/secure-chat/delete-account` | ⭐ **在 ✅要测范围内，但无前端入口** → 只能接口级测试 |
| `GET /api/market/spot/{code}` | `getSpot()` 已导出、无人 import |
| `GET /api/market/spot/name/{name}` | 仅存在于死代码 `useMarketQuery.ts` |
| `GET /api/market/ranking` | 同上（`limit→top_n` 的修复也在此） |
| `GET /api/market/detail/name/{name}` | 同上 |
| `GET /api/market/kline/name/{name}` | 无引用 |
| `GET /api/market/intraday/{code}`、`/name/{name}` | `00` 已列 |
| `GET /api/market/money-flow/{code}`、`/name/{name}`、`/ranking` | `00` 已列 |
| `POST /api/market/filter` | `00` 已列（注：前端 `src` 里的 `filter` 命中全是 `Array.filter`，非接口调用） |
| `GET /api/market/categories` | `00` 已列 |
| `GET /api/market/category/{category}` | **`00` 未列**，补 |
| `POST /api/portfolio/snapshot` | `00` 已列 |
| `POST /api/portfolio/confirm-pending` | `00` 已列。⚠️ 初版曾说它是「P1 的关键测试夹具」—— **这个说法已作废**（它确认不了刚下的单，见 §5.3）。不用它 |
| `GET /api/portfolio/daily-returns` | `00` 已列 |
| `GET`+`POST /api/portfolio/auto-invest/config` | `00` 已列（同路径两方法） |

### 4.3 其余 16 个（非业务，探针用）

| 类别 | 端点 |
|---|---|
| 健康检查（6） | `GET /`、`GET /api/test/hello`、`GET /api/market/health`、`GET /api/watchlist/health`、`GET /api/portfolio/health`、`GET /api/risk/health` |
| 开发专用（7） | `POST /api/portfolio/test/apply-purchase`、`/apply-redeem`、`GET /test/positions`、`/test/account`、`/test/trade-flow`、`POST /test/snapshot`、`GET /test/daily-returns`（`X-User-Id`，**仅非生产可用**，见 §五） |
| 范围外（3） | `/api/upload`、`/api/upload/process-file-from-edge`、`/api/upload/health`（软工作业遗迹，不测） |

---

## 五、对 E2E 有直接影响的实现细节（读代码得到，`00` 未写）

### 5.1 鉴权与 401 的三个分支

| 分支 | 触发条件 | 前端行为 | 代码 |
|---|---|---|---|
| 本地已过期 | `expireTime <= now` 或 JWT `exp` 已过 | **不发请求**，直接 `expireAuthAndRedirect()` → toast + `reLaunch('/pages/login/index')`，并 reject `'登录状态已过期，请重新登录'` | [request.ts:39-42](application/src/utils/request.ts#L39-L42) |
| 服务端 401 | HTTP 401 | `handleUnauthorized()` → `expireAuthAndRedirect()` → 同样 toast + reLaunch | [request.ts:61-65](application/src/utils/request.ts#L61-L65) |
| 行情例外 | URL 匹配 `/(?:^|\/)api\/market\//` | **放行**，不带 token 也发请求 | [request.ts:38](application/src/utils/request.ts#L38) |

补充事实（用于断言设计）：

- `expireAuthAndRedirect` 有 **`redirecting` 互斥锁**（[auth.ts:181-197](application/src/utils/auth.ts#L181-L197)），首跳后 `setTimeout 250ms` 再 `reLaunch`，`complete` 后 300ms 解锁。→ **E2E 断言必须给 ≥600ms 的等待窗口**，否则会读到"还没跳"的假失败。
- ⚠️ 后端 `get_current_user` 的签名是 `Header(...)`（必填，[deps.py:41](ai-etf/server/auth/deps.py#L41)）→ **完全不传 `Authorization` 头会得到 422，不是 401**。前端不会触发这一分支（本地没过期就一定带 token），但接口级用例要注意。
- token 有效期：`AUTH_SESSION_TTL_MS = 1h`，且 `expireTime = min(now+1h, now+serverTTL, jwt.exp)`（[auth.ts:93-107](application/src/utils/auth.ts#L93-L107)）。后端登录返回 `expires_in: 3600`。
- 登出后原 token **服务端即时失效**（内存黑名单，`401 令牌已注销`），但**进程重启会失效**（`docs/api/01` §5）。

### 5.2 SSE 的真实 wire format（断言要按这个写）

后端 [utils/sse.py:19](ai-etf/server/utils/sse.py#L19)：

```
data: {"type":"token","content":"<文本>"}\n\n
data: {"type":"done","chat_id":"<uuid>"}\n\n     ← 仅此帧带 chat_id
data: {"type":"error","message":"<文本>"}\n\n    ← 异常时
```

- `ensure_ascii=False` → **中文是原始 UTF-8，不是 `\uXXXX`**，所以 MP 端必须做**跨分块 UTF-8 解码**（前端为此写了手写降级解码器 [index.vue:439-523](application/src/pages/index/index.vue#L439-L523)，因为真机可能没有 `TextDecoder`）。这是 E2E 最容易出错的点。
- **没有 `event:` 字段**，只有 `data:`；前端 `parseSSELine` 用 `line.startsWith('data:')` 解析（[index.vue:389-433](application/src/pages/index/index.vue#L389-L433)）。后端**从不发 `[DONE]` 哨兵**（前端解析器容错支持，但永远不会命中）。
- 响应头带 **`X-Session-ID: <chat_id>`**（[sse.py:33-41](ai-etf/server/utils/sse.py#L33-L41)；建会话失败时为 `X-Session-ID: error`）→ **这是比解析 body 更省事的 `chat_id` 断言锚点**，接口级用例优先用它。
- 路由是 `@router.post("")`，即 **`/api/secure-chat` 无尾斜杠**（前端也是这么发的）。
- 401 是**普通 HTTP 401 JSON**（`Depends` 在生成器启动前就抛了），**不会**变成 SSE `error` 帧。
- 会话标题由后端自动生成：`question[:20] + "..."`（[secure_chat.py:271-274](ai-etf/server/api/secure_chat.py#L271-L274)）→ **可用于断言**。
- 前端超时：首 token 65s、总请求 120s（[index.vue:63-66](application/src/pages/index/index.vue#L63-L66)）→ **单步等待必须 > 130s**。
- 失败时前端会把错误**写进气泡**：`抱歉，${message}。`（[index.vue:557](application/src/pages/index/index.vue#L557)）→ ⚠️ **断言"有回复"会把失败当成功**，必须排除以「抱歉，」开头的文本。

### 5.3 交易链路的硬约束（**这条会决定 P1 能不能跑通**）

读 [portfolio_service.py:520-643](ai-etf/server/services/portfolio_service.py#L520-L643)：

| 事实 | 代码 | 后果 |
|---|---|---|
| **申购一律 pending，不立即建仓** | [:596-611](ai-etf/server/services/portfolio_service.py#L596-L611)「场外基金统一走 pending 流程」 | 申购成功后**持仓仍为 0**，流水也**没有**该笔记录；`cash` 减少、`frozen_cash` 增加 |
| 15:00 只决定 `confirm_date` 是"当日"还是"下一交易日"**（注意：这不是最终落库的确认日）** | [:543-548](ai-etf/server/services/portfolio_service.py#L543-L548)、`_is_before_cutoff = dt.hour < 15` | 与 `docs/api/05` 开头「15:00 前提交立即按当日净值确认」的表述**不一致**（该表述易误读为"立即确认"） |
| ⚠️ **落库的确认日 = `confirm_date` 再往后推 `confirm_delay` 个交易日** | [:550-552](ai-etf/server/services/portfolio_service.py#L550-L552)：`actual_confirm` 循环 `_next_trading_day()`；[:610](ai-etf/server/services/portfolio_service.py#L610) 落库的是 `actual_confirm` | `110020` 的 `confirm_delay = 1`（[seed.sql:5](ai-etf/supabase/seed.sql#L5)）→ **确认日必然 ≥ 次日**。当日 15:37 的调度器也确认不了它 |
| 确认只发生在两处 | ① 调度器 `CronTrigger(hour=15, minute=37, day_of_week="mon-fri")`（[spot_cache_scheduler.py:103-106](ai-etf/server/services/spot_cache_scheduler.py#L103-L106)）② `POST /api/portfolio/confirm-pending`（`skip_trading_day_check=True`，只确认 `confirm_date <= today`） | ⚠️ **买卖单不对称，必须分开说**：**买单**落库的是推进过的 `actual_confirm` → **任何时间都无法在"下单当天"确认**（不只是非交易日/15:00 后）；**赎单**落库的是**未推进**的 `confirm_date` → 交易日 15:00 前下单，**当天就能确认**。**推论：E2E 会话内走不到"申购建仓"；但"赎回确认"在窗口内是可达的**——见 [03 §二.1](03-E2E用例清单.md)、[03 §二.2](03-E2E用例清单.md) |
| 存在 pending 申购时，同基金**不可赎回** | [:725-740](ai-etf/server/services/portfolio_service.py#L725-L740) | 可作**确定性断言**（任何时间都成立） |
| 赎回同样走 pending，不立即扣减份额 | [:770-782](ai-etf/server/services/portfolio_service.py#L770-L782) | 赎回后 `positions.quantity` 不变，仅"可用份额"变少 |
| 流水只含**已确认**订单 | `docs/api/05` §5 | pending 期间交易记录页为空 |
| `INITIAL_CASH = 100000.00` | [:27](ai-etf/server/services/portfolio_service.py#L27) | 新用户初始现金恒定，**可精确断言** |
| `auto_invest_enabled` 默认 **false** | [migrations/…:275](ai-etf/supabase/migrations/20260819113859_remote_schema.sql#L275) | 「新用户自动申购货基」**默认不发生** → 新用户 `position_count = 0`，状态干净（对 E2E 是好事） |
| 风险测评**不是**交易的硬前置 | `_get_risk_warning` 注释「建议性，任何异常都不影响交易」[:579-580](ai-etf/server/services/portfolio_service.py#L579-L580) | 路径可以**拆开**，不必把风险测评塞进 P1 |
| 最低申购 10 元、白名单 20 只、场内 ETF 拦截 | [docs/api/05](ai-etf/docs/api/05-组合交易.md#L237-L272) | 现成的**负例断言** |

### 5.4 测试夹具的可用性

- `/api/portfolio/test/*`（7 个，`X-User-Id`）**仅非生产可用**：`os.getenv("ENV").lower() == "production"` → 404（[portfolio.py:50-56](ai-etf/server/api/portfolio.py#L50-L56)）。
- 本地 `.env` **不含 `ENV`**（只有 `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_JWT_SECRET`）→ `os.getenv("ENV","")` 为空 → **本地必然非生产 → test/\* 可用**。
- ⚠️ `test/*` 与正式端点走**同一个** `PortfolioService`，因此 `test/apply-purchase` **同样是 pending** → 它**不能**用来"造出已确认持仓"。
- ⚠️ **"已确认持仓"并非完全造不出来——有两条路，都有代价**：
  1. **货基自动申购（合法接口，立即确认）**：`_auto_invest_money_fund` 在 `apply_purchase` 之后**直接**调 `_confirm_money_fund_order`（[portfolio_service.py:129-160](ai-etf/server/services/portfolio_service.py#L129-L160)），绕过确认日门控 → 会话内即可得到 `000198` 的**已确认**持仓。开关由 `POST /portfolio/auto-invest/config` 打开（**前端零调用 → 只能作夹具**，且 UI 无入口），随后任意一次 `GET /account` 触发（[portfolio_service.py:919-925](ai-etf/server/services/portfolio_service.py#L919-L925)）。
     ⚠️ **两个坑**：① `000198` **不在前端白名单**，用它做标的无法走 UI 买入；② `_auto_invest_money_fund` 只在「已有货基持仓」时跳过（[:138-140](ai-etf/server/services/portfolio_service.py#L138-L140)），而 `account_summary` **先**跑自动申购**再**读 `cash` → **全额赎回后钱会被立刻重新申购成货基，「可用现金变多」在 UI 上根本看不到**。
  2. **改库回填 `confirm_date`**：直接改库，最直白，但纯造状态。
  **为什么"申购→确认后建仓"仍然不做 E2E**：不是"造不出来"，而是**收益低于已有集成测试**（见 [03 §二.1](03-E2E用例清单.md)）——那句话是取舍，不是不可能。

---

## 六、需确认（不要当成事实用）

| # | 事项 | 为什么重要 | 问谁 |
|---|---|---|---|
| 1 | **前端在微信开发者工具里打开的到底是哪个目录**（仓库根 `project.config.json` 有 `appid`，但 `dist/` 从未构建、也未见 `miniprogramRoot`） | 决定 automator 的 `projectPath` 与 `cliPath` | 前端同学 |
| 2 | [settings/index.vue:309](application/src/pages/settings/index.vue#L309) 用 `uni.switchTab` 跳自选页，但 `pages.json` 无 `tabBar` 段 → 静态判断**会失败** | 若成立，「设置 → 持仓卡片」是**坏入口**，E2E 需绕开（改走 TabBar） | 前端同学 / 真机一试即知 |
| 3 | `.env.development` / `.env.production` 均为 **0 字节**，`API_BASE` 硬编码 `https://ai-etf.xyz` | 决定了「本地环境」选项需要前端改 1 处代码，见 `05-执行计划.md` 阶段 0 | 前端同学 |
| 4 | 生产环境 `.env` 是否设了 `ENV=production` | 决定线上能否用 `test/*` 夹具（我**不能读** `.env`，也无法看到线上环境变量） | 后端作者（自己） |
| 5 | `uni.showModal({editable:true})`（重命名）在 automator 下能否驱动 | P2 的重命名步骤能否自动化，见 `03` §SSE/弹窗 | 需实机验证 |
| 6 | 后端是否提供 LLM mock/短路开关 | 决定 P2 能否进 CI（否则每次跑都真实调 LLM） | 后端作者（自己）——**当前未发现此类开关** |

---

## 七、复核方法（可重跑）

```bash
# 前端：列全部调用点
cd application && grep -rn "/api/" src --include="*.ts" --include="*.vue"

# 前端：查某接口是否有活跃入口（以 ranking 为例，命中即说明只在死代码里）
grep -rn "market/ranking" src

# 后端：列全部路由
cd ai-etf && grep -rn "@router\.\(get\|post\|put\|delete\|patch\)" server/api/

# 文档一致性
python docs/api/scripts/gen_index.py --url https://ai-etf.xyz
```
