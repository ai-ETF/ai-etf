"""L3 契约测试（C1–C6）—— 把「前后端接口约定」钉死在后端仓库里。

所测功能：前端真实调用点是否逐条存在于后端路由表；鉴权分级是否被误改；
开发专用端点是否在生产环境关闭；SSE 帧格式；API 文档是否引用了不存在的接口；
「后端有、前端零入口」的端点是否被显式登记。

测试方法：C1/C2/C3/C5/C6 全部是**静态**断言（读 `app.routes` / `app.openapi()` /
`docs/api/*.md` / monkeypatch 环境变量）—— **不启动服务器、不联网、不碰数据库**。
唯一例外是 C4（需要真实响应字节），它复用既有的 `integration_net` marker，
默认不跑，且缺少环境变量时显式 skip。

为什么放在这一层：这些约定用 E2E 测不出来（UI 上看不见"路由缺失"，只能看见
一次 404），用单元测试又够不着（单元测试测的是函数，不是路由注册）。它们的
失效方式是**静默的**——前端发了后端不认识的名字，不报错，只是结果不对。

⚠️ 本文件里的断言值全部来自 `tests/contract/baseline.py`。改基线前先读那个文件
开头的维护约定。
"""
import os

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from tests.contract.baseline import (
    AUTH_BASELINE,
    FRONTEND_CALL_POINTS,
    NON_BUSINESS_ENDPOINTS,
    UNWIRED_BUSINESS_ENDPOINTS,
    X_USER_ID_ENDPOINTS,
)

# conftest.py 已用空替身预填充重依赖模块，这里可以轻量导入真实 app
from server.app import app


# ============================================================================
# 路由表读取工具
# ============================================================================

def _all_routes() -> dict[tuple[str, str], APIRoute]:
    """返回 {(METHOD, path): APIRoute}。只保留真实业务方法（去掉 HEAD/OPTIONS）。"""
    out: dict[tuple[str, str], APIRoute] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            out[(method, route.path)] = route
    return out


ROUTES: dict[tuple[str, str], APIRoute] = _all_routes()
ROUTE_KEYS: set[tuple[str, str]] = set(ROUTES)


def _dependency_callables(route: APIRoute) -> set:
    """递归收集一个路由依赖的全部可调用对象。

    为什么要递归：`Depends(get_current_user)` 可能挂在子依赖里，
    只看顶层 `route.dependant.dependencies` 会漏。
    """
    found: set = set()

    def walk(dependant) -> None:
        for sub in dependant.dependencies:
            found.add(sub.call)
            walk(sub)

    walk(route.dependant)
    return found


def _auth_kind(route: APIRoute) -> str:
    """把一个路由分到 jwt / x_user_id / public 三档。

    分档口径与 baseline.py 的注释一致。注意 `/logout` 与 `/delete-account` 不是
    走 `Depends(get_current_user)`，而是手写 `authorization: str = Header(...)`，
    所以还要额外识别「必填 authorization header」这一种写法。
    """
    names = {getattr(c, "__name__", str(c)) for c in _dependency_callables(route)}
    if "_get_test_user" in names:
        return "x_user_id"
    if "get_current_user" in names:
        return "jwt"
    if any(p.name == "authorization" for p in route.dependant.header_params):
        return "jwt"
    return "public"


def _query_param_names(route: APIRoute) -> set[str]:
    return {p.name for p in route.dependant.query_params}


def _body_field_names(route: APIRoute) -> set[str]:
    """取出请求体 Pydantic 模型的字段名集合。无请求体则返回空集。"""
    params = list(getattr(route.dependant, "body_params", []))
    if not params:
        return set()
    model = getattr(params[0].field_info, "annotation", None)
    fields = getattr(model, "model_fields", None)
    return set(fields.keys()) if fields else set()


# ============================================================================
# C1：前端 23 个调用点逐条存在
# ============================================================================

@pytest.mark.contract
@pytest.mark.parametrize("cp", FRONTEND_CALL_POINTS, ids=lambda cp: f"{cp.method} {cp.path}")
def test_c1_前端调用点存在(cp):
    """路由必须存在（方法 + 路径模板）。

    ⭐ 金丝雀：`PUT /api/secure-chat/chats/{chat_id}/title` 缺失时，
    前端「重命名会话」必然 404 —— 这个 bug 真实发生过（commit eefefd3）。
    """
    assert (cp.method, cp.path) in ROUTE_KEYS, (
        f"前端在 {cp.frontend_ref} 调用了 {cp.method} {cp.path}，"
        f"但后端没有这条路由（后端参考定义在 {cp.backend_ref}）"
    )


@pytest.mark.contract
@pytest.mark.parametrize("cp", FRONTEND_CALL_POINTS, ids=lambda cp: f"{cp.method} {cp.path}")
def test_c1_前端发送的查询参数名后端认识(cp):
    """前端发的 query 参数名必须都在后端声明里。

    这条防的是 `ranking` 的 `limit` vs `top_n` 那类问题：名字对不上时
    FastAPI 不报错（多出来的参数被忽略），只是**永远拿默认值**，
    表现为「榜单恒 10 条」这种没人怀疑是参数名问题的现象。
    """
    if not cp.query_params:
        pytest.skip("该调用点不带查询参数")
    declared = _query_param_names(ROUTES[(cp.method, cp.path)])
    missing = set(cp.query_params) - declared
    assert not missing, (
        f"{cp.method} {cp.path} 的前端调用点 {cp.frontend_ref} 发送了 "
        f"{sorted(missing)}，但后端只声明了 {sorted(declared)}"
    )


@pytest.mark.contract
@pytest.mark.parametrize("cp", FRONTEND_CALL_POINTS, ids=lambda cp: f"{cp.method} {cp.path}")
def test_c1_前端发送的请求体字段后端认识(cp):
    """前端发的 body 字段名必须都存在于后端请求体模型上。"""
    if not cp.body_fields:
        pytest.skip("该调用点不带请求体")
    declared = _body_field_names(ROUTES[(cp.method, cp.path)])
    missing = set(cp.body_fields) - declared
    assert not missing, (
        f"{cp.method} {cp.path} 的前端调用点 {cp.frontend_ref} 发送了 "
        f"{sorted(missing)}，但后端请求体只声明了 {sorted(declared)}"
    )


# ============================================================================
# C2：鉴权分级快照
# ============================================================================

@pytest.mark.contract
def test_c2_路由集合与基线一致():
    """新增/删除路由必须同步更新 baseline.py。

    没有这条，C2 的参数化只会覆盖基线里已有的路由 —— 新加一条公开的敏感接口
    不会被发现。
    """
    added = ROUTE_KEYS - set(AUTH_BASELINE)
    removed = set(AUTH_BASELINE) - ROUTE_KEYS
    assert not added, (
        f"后端新增了 {sorted(added)}，但 baseline.AUTH_BASELINE 里没有登记。"
        f"请为它补一条分级（jwt / x_user_id / public）—— 这一步是刻意设计的，"
        f"目的是让「新接口默认是公开的」这件事必须由人显式确认。"
    )
    assert not removed, (
        f"baseline.AUTH_BASELINE 里的 {sorted(removed)} 已不存在于后端路由表，"
        f"请从基线里删掉"
    )


@pytest.mark.contract
@pytest.mark.parametrize(
    "key", sorted(AUTH_BASELINE), ids=lambda k: f"{k[0]} {k[1]}"
)
def test_c2_鉴权分级未被改动(key):
    """每个路由的鉴权类型必须与基线一致。

    防的是「有人把受保护接口误改成公开」—— 概率低，但一旦发生就是数据泄漏。
    """
    expected = AUTH_BASELINE[key]
    actual = _auth_kind(ROUTES[key])
    assert actual == expected, (
        f"{key[0]} {key[1]} 的鉴权分级从 {expected} 变成了 {actual}。"
        f"如果这是有意的，请同步修改 baseline.AUTH_BASELINE 并在 PR 里说明原因。"
    )


# ============================================================================
# C3：开发专用端点在生产环境必须关闭
# ============================================================================

@pytest.mark.contract
def test_c3_所有x_user_id端点都挂了守卫():
    """7 个 /api/portfolio/test/* 必须全部经由 `_get_test_user`。

    只测 `_get_test_user` 本身是不够的 —— 如果哪天新增一个 test/* 端点忘了挂守卫，
    它就会绕过生产环境保护。
    """
    for key in sorted(X_USER_ID_ENDPOINTS):
        names = {getattr(c, "__name__", str(c)) for c in _dependency_callables(ROUTES[key])}
        assert "_get_test_user" in names, (
            f"{key[0]} {key[1]} 没有依赖 _get_test_user，"
            f"在 ENV=production 下不会被关闭"
        )


@pytest.mark.contract
def test_c3_生产环境下守卫返回404(monkeypatch):
    """`ENV=production` 时 `_get_test_user` 必须抛 404（而不是 401/403）。

    依据 server/api/portfolio.py:50-56。选 404 而不是 403 是有意的：
    对外不暴露「这里有端点但你没权限」。
    """
    from server.api.portfolio import _get_test_user

    monkeypatch.setenv("ENV", "production")
    with pytest.raises(HTTPException) as excinfo:
        _get_test_user("any-user-id")
    assert excinfo.value.status_code == 404


@pytest.mark.contract
def test_c3_非生产环境下缺header报400(monkeypatch):
    """非生产且没传 X-User-Id 时报 400，提示补 header。"""
    from server.api.portfolio import _get_test_user

    monkeypatch.setenv("ENV", "")
    with pytest.raises(HTTPException) as excinfo:
        _get_test_user(None)
    assert excinfo.value.status_code == 400


@pytest.mark.contract
def test_c3_非生产环境下正常返回user_id(monkeypatch):
    """非生产且传了 X-User-Id 时原样返回。"""
    from server.api.portfolio import _get_test_user

    monkeypatch.setenv("ENV", "development")
    assert _get_test_user("user-123") == "user-123"


# ============================================================================
# C5：docs/api/*.md 不得引用不存在的接口
# ============================================================================

def _load_gen_index():
    """加载现成的 docs/api/scripts/gen_index.py（它只依赖标准库）。

    复用它而不是重写：路径归一化（`{chat_id}` → `{P}`）、段级匹配、
    文档 token 提取这些约定已经在那边定好了，抄一份会漂移。
    唯一不用的是它的 `fetch_openapi()` —— 那条要联网，这里改用本地 `app.openapi()`。
    """
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs" / "api" / "scripts" / "gen_index.py"
    spec = importlib.util.spec_from_file_location("_gen_index_for_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.contract
def test_c5_文档没有引用不存在的接口():
    """`docs/api/*.md` 里出现的每个 /api/... 路径，都必须能匹配到一条真实路由。

    防的是「接口删了、文档没删」—— 上一轮规划就是靠人工比对才发现文档过时，
    这条把它变成自动的。**不需要联网**（对比的是本地 app.openapi()，不是线上）。
    """
    gen = _load_gen_index()

    live = gen.openapi_endpoints(app.openapi())
    live_paths = {p for _, p in live}
    doc_tokens = gen.doc_path_tokens(gen.collect_docs())

    stale = sorted(
        t for t in doc_tokens
        if not any(gen.path_match(t, p) for p in live_paths)
        # 文档标题里的模块前缀（如「03 行情（/api/market）」）本身不是路由，
        # 但若它是某条真实路径的前缀，就算导航引用而非废弃接口 —— 与 gen_index 同口径
        and not any(p.startswith(t) for p in live_paths)
    )
    assert not stale, (
        f"docs/api/*.md 引用了 {len(stale)} 条不存在的接口：{stale}\n"
        f"（跑 `poetry run python docs/api/scripts/gen_index.py` 可复现同一份清单）"
    )


# ============================================================================
# C6：三档口径必须覆盖全部路由
# ============================================================================

@pytest.mark.contract
def test_c6_全部路由都被显式分类():
    """每条路由必须恰好落在三档之一：已接线 / 未接线 / 非业务。

    这条是 C6 的核心：那 19 个「后端有、前端零入口」的端点**必须被登记**。
    哪天有人把前端接上去了，这条会红 —— 提醒同步更新 E2E 白名单与 C1，
    避免「以为没接线其实接了」或反之。
    """
    wired = {(cp.method, cp.path) for cp in FRONTEND_CALL_POINTS}
    classified = wired | set(UNWIRED_BUSINESS_ENDPOINTS) | set(NON_BUSINESS_ENDPOINTS)

    unclassified = sorted(ROUTE_KEYS - classified)
    assert not unclassified, (
        f"这 {len(unclassified)} 条路由没有被分类：{unclassified}\n"
        f"请判断它是「前端已接线」（补进 FRONTEND_CALL_POINTS）、"
        f"「前端零入口」（补进 UNWIRED_BUSINESS_ENDPOINTS）"
        f"还是「非业务端点」（补进 NON_BUSINESS_ENDPOINTS）"
    )

    phantom = sorted(classified - ROUTE_KEYS)
    assert not phantom, f"baseline 里登记了 {phantom}，但后端路由表里没有"


@pytest.mark.contract
def test_c6_三档口径不重叠():
    """同一个路由不能同时被登记成两档（重叠会让计数对不上）。"""
    wired = {(cp.method, cp.path) for cp in FRONTEND_CALL_POINTS}
    overlap = (
        (wired & set(UNWIRED_BUSINESS_ENDPOINTS))
        | (wired & set(NON_BUSINESS_ENDPOINTS))
        | (set(UNWIRED_BUSINESS_ENDPOINTS) & set(NON_BUSINESS_ENDPOINTS))
    )
    assert not overlap, f"这些路由被登记到了多个分档：{sorted(overlap)}"


@pytest.mark.contract
def test_c6_未接线端点数量与规划文档一致():
    """19 这个数字写在 docs/e2e/01 §4.2 里，改动时两边要一起动。"""
    assert len(UNWIRED_BUSINESS_ENDPOINTS) == 19, (
        f"未接线端点从 19 变成了 {len(UNWIRED_BUSINESS_ENDPOINTS)}。"
        f"如果确实有人接了线，请同步更新 docs/e2e/01-页面与API调用关系.md §4.2 "
        f"和 §4.1，以及 docs/e2e/03 的 E2E 白名单"
    )


# ============================================================================
# C4：SSE 帧契约（需要真实响应字节 → 复用既有 integration_net marker）
# ============================================================================

@pytest.mark.integration_net
def test_c4_sse帧契约():
    """`POST /api/secure-chat` 的逐帧格式。

    断言的是 wire format 本身（依据 server/utils/sse.py:19 与 docs/e2e/01 §5.2）：
    - Content-Type 是 text/event-stream
    - 响应头带 X-Session-ID
    - 至少 1 个 `{"type":"token","content":<str>}` 帧
    - **恰好 1 个** `{"type":"done","chat_id":<str>}` 收尾帧，且只有它带 chat_id
    - 没有 `event:` 字段（后端从不发），也没有 `[DONE]` 哨兵

    为什么单独放这一层：E2E 拿不到原始字节，只能在 UI 上看"有没有回复"；
    而"有没有回复"分不清「正常回答」和「走 error 帧的失败回答」。
    把协议钉死在这里，E2E 就不必去猜。

    ⚠️ 这条要真实后端 + 真实 LLM + 一次性账号，所以默认不跑。
    跑法：设好 E2E_API / E2E_TOKEN 后
        poetry run pytest -m integration_net tests/contract -v
    """
    base = os.getenv("E2E_API")
    token = os.getenv("E2E_TOKEN")
    if not base or not token:
        pytest.skip("需要 E2E_API 与 E2E_TOKEN（真实后端 + 一次性账号），默认不跑")

    import json
    import httpx

    frames: list[dict] = []
    with httpx.stream(
        "POST",
        f"{base.rstrip('/')}/api/secure-chat",
        json={"question": "用一句话介绍沪深300ETF"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=130.0,
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "x-session-id" in resp.headers
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload:
                frames.append(json.loads(payload))

    assert frames, "一帧都没收到"

    tokens = [f for f in frames if f.get("type") == "token"]
    dones = [f for f in frames if f.get("type") == "done"]

    assert tokens, "没有任何 token 帧"
    assert all(isinstance(f.get("content"), str) for f in tokens), "token 帧的 content 不是字符串"
    assert len(dones) == 1, f"收尾 done 帧应恰好 1 个，实际 {len(dones)} 个"
    assert isinstance(dones[0].get("chat_id"), str), "done 帧缺 chat_id"

    # 只有 done 帧带 chat_id —— 这是前端的会话锚点，多了少了都会让前端拿到错的 id
    with_id = [f for f in frames if "chat_id" in f]
    assert with_id == dones, f"除 done 帧外还有帧带了 chat_id：{with_id}"
