"""L3 契约测试的基线快照（**本文件是数据，不是测试**）。

为什么单独放一个文件：C1/C2/C6 断言的都是「当前事实」，事实会变（前端接了新接口、
后端加了新路由）。把事实集中在一处，改动时 diff 一眼可见；散在测试函数里则会被
当成"测试挂了"而不是"事实变了"。

⚠️ 维护约定：**改了这里就等于改了断言**。任何一次修改都应在 PR 描述里说明
"为什么事实变了"，而不是为了让测试变绿而改。

三份数据的来源：
- FRONTEND_CALL_POINTS  ← docs/e2e/01-页面与API调用关系.md §3.1（前端真实调用点）
- AUTH_BASELINE        ← 由 `server.app` 路由表实测导出（2026-09-24）
- UNWIRED_*            ← docs/e2e/01-页面与API调用关系.md §4.2 / §4.3
"""
from typing import NamedTuple


class CallPoint(NamedTuple):
    """一个前端活跃调用点。

    query_params / body_fields 只登记**前端实际发送的**字段名 —— 后端多收几个
    可选参数不算契约破坏，但前端发了后端不认识的名字就会静默失效
    （`ranking` 的 `limit` vs `top_n` 就是这么炸的）。
    """
    method: str
    path: str
    query_params: tuple[str, ...]
    body_fields: tuple[str, ...]
    frontend_ref: str   # 前端调用点 file:line
    backend_ref: str    # 后端路由定义 file:line


# ============================================================================
# C1：前端 23 个活跃调用点
# 依据 docs/e2e/01-页面与API调用关系.md §4.1（原表列的是"后端接口 + 前端入口"，
# 此处补上方法、路径模板、查询参数名与 body 字段名）
# ============================================================================
FRONTEND_CALL_POINTS: tuple[CallPoint, ...] = (
    # --- pages/login、pages/register、pages/settings：三个 uni.request 直调（绕过 utils/request.ts） ---
    CallPoint("POST", "/api/secure-chat/login", (), ("email", "password"),
              "application/src/composables/useAuth.ts:109-115",
              "server/api/secure_chat.py:100"),
    CallPoint("POST", "/api/secure-chat/register", (), ("email", "password"),
              "application/src/composables/useAuth.ts:146-152",
              "server/api/secure_chat.py:135"),
    CallPoint("POST", "/api/secure-chat/logout", (), (),
              "application/src/composables/useAuth.ts:181-186",
              "server/api/secure_chat.py:170"),

    # --- pages/index（首页 / 聊天）---
    CallPoint("POST", "/api/secure-chat", (), ("question", "chat_id"),
              "application/src/pages/index/index.vue:208-219",
              "server/api/secure_chat.py:251"),
    CallPoint("GET", "/api/secure-chat/chats", ("limit",), (),
              "application/src/stores/chat.ts:91-94",
              "server/api/secure_chat.py:312"),
    CallPoint("GET", "/api/secure-chat/chats/{chat_id}/messages", ("limit",), (),
              "application/src/stores/chat.ts:111-114",
              "server/api/secure_chat.py:340"),
    CallPoint("DELETE", "/api/secure-chat/chats/{chat_id}", (), (),
              "application/src/stores/chat.ts:163-166",
              "server/api/secure_chat.py:381"),
    # ⭐ 金丝雀：这条路由一度只存在于 fix/secure-chat-rename-title 分支上，
    #    从 dev 拉分支会让 C1 必红。它缺失时前端「重命名会话」必然 404。
    CallPoint("PUT", "/api/secure-chat/chats/{chat_id}/title", (), ("title",),
              "application/src/stores/chat.ts:188-193",
              "server/api/secure_chat.py:409"),

    # --- pages/watchlist、pages/etf-detail ---
    CallPoint("GET", "/api/market/search", ("keyword", "top_n"), (),
              "application/src/stores/watchlist.ts:156",
              "server/api/market/search.py:26"),
    CallPoint("GET", "/api/market/detail/{fund_code}", (), (),
              "application/src/pages/etf-detail/index.vue:171",
              "server/api/market/detail.py:22"),
    CallPoint("GET", "/api/market/kline/{fund_code}", ("period", "limit"), (),
              "application/src/pages/etf-detail/index.vue:98",
              "server/api/market/historical.py:28"),
    CallPoint("POST", "/api/watchlist/add", (), ("fund_code", "fund_name"),
              "application/src/pages/etf-detail/index.vue:149-150"
              " → application/src/stores/watchlist.ts:256",
              "server/api/watchlist.py:25"),
    CallPoint("DELETE", "/api/watchlist/remove", (), ("fund_code",),
              "application/src/pages/watchlist/index.vue:266",
              "server/api/watchlist.py:51"),
    CallPoint("GET", "/api/watchlist/list", ("include_quote",), (),
              "application/src/stores/watchlist.ts:126",
              "server/api/watchlist.py:73"),
    CallPoint("DELETE", "/api/watchlist/clear", (), (),
              "application/src/pages/watchlist/index.vue:285",
              "server/api/watchlist.py:93"),

    # --- pages/watchlist、pages/purchase、pages/redeem、pages/trades、pages/settings ---
    CallPoint("GET", "/api/portfolio/account", (), (),
              "application/src/pages/purchase/index.vue:60"
              " / application/src/pages/settings/index.vue:237"
              " / application/src/pages/watchlist/index.vue:317",
              "server/api/portfolio.py:139"),
    CallPoint("GET", "/api/portfolio/positions", ("include_quote",), (),
              "application/src/pages/watchlist/index.vue:317"
              " / application/src/pages/redeem/index.vue:40",
              "server/api/portfolio.py:122"),
    CallPoint("POST", "/api/portfolio/apply-purchase", (), ("fund_code", "amount"),
              "application/src/pages/purchase/index.vue:84"
              " → application/src/api/modules/portfolio.ts:98",
              "server/api/portfolio.py:62"),
    CallPoint("POST", "/api/portfolio/apply-redeem", (), ("fund_code", "quantity"),
              "application/src/pages/redeem/index.vue:72",
              "server/api/portfolio.py:93"),
    CallPoint("GET", "/api/portfolio/trade-flow", ("page", "page_size"), (),
              "application/src/pages/trades/index.vue:25",
              "server/api/portfolio.py:148"),

    # --- pages/risk-assessment ---
    CallPoint("GET", "/api/risk/questionnaire", (), (),
              "application/src/api/modules/risk.ts:25",
              "server/api/risk.py:28"),
    CallPoint("POST", "/api/risk/submit", (), ("questionnaire_id", "answers"),
              "application/src/pages/risk-assessment/index.vue:404-407",
              "server/api/risk.py:69"),
    CallPoint("GET", "/api/risk/profile", (), (),
              "application/src/pages/risk-assessment/index.vue:315",
              "server/api/risk.py:102"),
)


# ============================================================================
# C6：19 个「后端有、前端零入口」的业务端点
# 依据 docs/e2e/01-页面与API调用关系.md §4.2。它们禁止被设计成 E2E 用例步骤
# （前端无入口，跑不通）；但**必须被显式登记** —— 哪天有人接线了，C6 会红，
# 提醒同步更新 E2E 白名单与 C1。
# ============================================================================
UNWIRED_BUSINESS_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({
    # ⭐ 唯一一条「在要测范围内、但没有前端入口」的 → 只能做接口级测试
    ("POST", "/api/secure-chat/delete-account"),
    ("GET", "/api/market/spot/{fund_code}"),
    ("GET", "/api/market/spot/name/{fund_name}"),
    ("GET", "/api/market/ranking"),              # `limit` → `top_n` 的修复就在这条上
    ("GET", "/api/market/detail/name/{fund_name}"),
    ("GET", "/api/market/kline/name/{fund_name}"),
    ("GET", "/api/market/intraday/{fund_code}"),
    ("GET", "/api/market/intraday/name/{fund_name}"),
    ("GET", "/api/market/money-flow/{fund_code}"),
    ("GET", "/api/market/money-flow/name/{fund_name}"),
    ("GET", "/api/market/money-flow/ranking"),
    ("POST", "/api/market/filter"),
    ("GET", "/api/market/categories"),
    ("GET", "/api/market/category/{category}"),
    ("POST", "/api/portfolio/snapshot"),
    ("POST", "/api/portfolio/confirm-pending"),  # 确认不了刚下的买单，见 01 §5.3
    ("GET", "/api/portfolio/daily-returns"),
    ("GET", "/api/portfolio/auto-invest/config"),
    ("POST", "/api/portfolio/auto-invest/config"),
})


# ============================================================================
# 16 个非业务端点（健康检查 6 + 开发专用 7 + 范围外 3）
# 依据 docs/e2e/01-页面与API调用关系.md §4.3。它们既不算"已接线"也不算"未接线"，
# 单独一档，免得 23+19 对不上 58 时看不出差在哪。
# ============================================================================
NON_BUSINESS_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({
    # 健康检查（6）
    ("GET", "/"),
    ("GET", "/api/test/hello"),
    ("GET", "/api/market/health"),
    ("GET", "/api/watchlist/health"),
    ("GET", "/api/portfolio/health"),
    ("GET", "/api/risk/health"),
    # 开发专用（7，X-User-Id，仅非生产可用）
    ("POST", "/api/portfolio/test/apply-purchase"),
    ("POST", "/api/portfolio/test/apply-redeem"),
    ("GET", "/api/portfolio/test/positions"),
    ("GET", "/api/portfolio/test/account"),
    ("GET", "/api/portfolio/test/trade-flow"),
    ("POST", "/api/portfolio/test/snapshot"),
    ("GET", "/api/portfolio/test/daily-returns"),
    # 范围外（3，软工作业遗迹，组长已确认不测）
    ("POST", "/api/upload"),
    ("POST", "/api/upload/process-file-from-edge"),
    ("GET", "/api/upload/health"),
})


# X-User-Id 端点清单（C3 用）：必须全部经由 `_get_test_user` 守卫，
# 且该守卫在 ENV=production 下返回 404。依据 server/api/portfolio.py:50-56。
X_USER_ID_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    ep for ep in NON_BUSINESS_ENDPOINTS if ep[1].startswith("/api/portfolio/test/")
)


# ============================================================================
# C2：每个路由的鉴权分级基线（2026-09-24 由 server.app 实测导出，共 58 条）
#
# 分级口径：
#   jwt        — 依赖 `get_current_user`，或显式声明了必填 `authorization` header
#   x_user_id  — 依赖 `_get_test_user`（开发专用，仅非生产可用）
#   public     — 其余（含所有 /api/market/*：行情对未登录放行，见 01 §5.1 行情例外）
#
# 防的是：有人把受保护接口误改成公开（低概率、后果极重）。
# ============================================================================
AUTH_BASELINE: dict[tuple[str, str], str] = {
    ("GET", "/"): "public",
    ("POST", "/api/secure-chat/login"): "public",
    ("POST", "/api/secure-chat/register"): "public",
    ("POST", "/api/secure-chat/logout"): "jwt",
    ("POST", "/api/secure-chat/delete-account"): "jwt",
    ("POST", "/api/secure-chat"): "jwt",
    ("GET", "/api/secure-chat/chats"): "jwt",
    ("GET", "/api/secure-chat/chats/{chat_id}/messages"): "jwt",
    ("DELETE", "/api/secure-chat/chats/{chat_id}"): "jwt",
    ("PUT", "/api/secure-chat/chats/{chat_id}/title"): "jwt",

    ("GET", "/api/market/health"): "public",
    ("GET", "/api/market/detail/{fund_code}"): "public",
    ("GET", "/api/market/detail/name/{fund_name}"): "public",
    ("GET", "/api/market/spot/{fund_code}"): "public",
    ("GET", "/api/market/spot/name/{fund_name}"): "public",
    ("GET", "/api/market/ranking"): "public",
    ("GET", "/api/market/kline/{fund_code}"): "public",
    ("GET", "/api/market/kline/name/{fund_name}"): "public",
    ("GET", "/api/market/intraday/{fund_code}"): "public",
    ("GET", "/api/market/intraday/name/{fund_name}"): "public",
    ("GET", "/api/market/money-flow/{fund_code}"): "public",
    ("GET", "/api/market/money-flow/name/{fund_name}"): "public",
    ("GET", "/api/market/money-flow/ranking"): "public",
    ("GET", "/api/market/search"): "public",
    ("POST", "/api/market/filter"): "public",
    ("GET", "/api/market/categories"): "public",
    ("GET", "/api/market/category/{category}"): "public",

    ("POST", "/api/watchlist/add"): "jwt",
    ("DELETE", "/api/watchlist/remove"): "jwt",
    ("GET", "/api/watchlist/list"): "jwt",
    ("DELETE", "/api/watchlist/clear"): "jwt",
    ("GET", "/api/watchlist/health"): "public",

    ("POST", "/api/portfolio/apply-purchase"): "jwt",
    ("POST", "/api/portfolio/apply-redeem"): "jwt",
    ("GET", "/api/portfolio/positions"): "jwt",
    ("GET", "/api/portfolio/account"): "jwt",
    ("GET", "/api/portfolio/trade-flow"): "jwt",
    ("POST", "/api/portfolio/snapshot"): "jwt",
    ("POST", "/api/portfolio/confirm-pending"): "jwt",
    ("GET", "/api/portfolio/daily-returns"): "jwt",
    ("GET", "/api/portfolio/health"): "public",
    ("GET", "/api/portfolio/auto-invest/config"): "jwt",
    ("POST", "/api/portfolio/auto-invest/config"): "jwt",
    ("POST", "/api/portfolio/test/apply-purchase"): "x_user_id",
    ("POST", "/api/portfolio/test/apply-redeem"): "x_user_id",
    ("GET", "/api/portfolio/test/positions"): "x_user_id",
    ("GET", "/api/portfolio/test/account"): "x_user_id",
    ("GET", "/api/portfolio/test/trade-flow"): "x_user_id",
    ("POST", "/api/portfolio/test/snapshot"): "x_user_id",
    ("GET", "/api/portfolio/test/daily-returns"): "x_user_id",

    ("GET", "/api/risk/questionnaire"): "jwt",
    ("POST", "/api/risk/submit"): "jwt",
    ("GET", "/api/risk/profile"): "jwt",
    ("GET", "/api/risk/health"): "public",

    ("GET", "/api/test/hello"): "public",
    ("POST", "/api/upload"): "public",
    ("POST", "/api/upload/process-file-from-edge"): "public",
    ("GET", "/api/upload/health"): "public",
}
