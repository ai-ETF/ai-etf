#!/usr/bin/env python3
"""
E2E 测试夹具 —— 一次性账号的注册 / 取 token / 注销

E2E 的交易断言依赖**精确数值**（初始现金 100000.00、冻结资金 0、持仓 0、流水 0），
所以每条用例都要一个干净的账号；复用固定账号会让第二次运行永久变红。
本脚本负责把账号准备好并把 token 交出去，**被测端仍然走 UI 登录**（登录页因此不被排除在覆盖外）。

用法：
    poetry run python docs/e2e/scripts/e2e_fixture.py register
    poetry run python docs/e2e/scripts/e2e_fixture.py token <email> <password>
    poetry run python docs/e2e/scripts/e2e_fixture.py cleanup <token> <password>
    poetry run python docs/e2e/scripts/e2e_fixture.py backdate-order <user_id> <fund_code> [--date YYYY-MM-DD]
    poetry run python docs/e2e/scripts/e2e_fixture.py --api http://127.0.0.1:8000 register

**输出契约**：stdout 是一段纯 JSON，人看的进度/警告/报错一律走 stderr。
成功 exit 0，任何失败 exit 1。
（⚠️ 2026-10-13 订正：这里原先写「供 jest 的 helpers/fixture.js 用 execSync 解析」——
**没有那个文件**，`application/e2e/` 下也不存在 `execSync`。JS 侧是**逐条对齐本脚本的
孪生实现** `application/e2e/helpers/api.js`（见该文件开头），改一边要同步另一边。）

**两个刻意的设计决定**：
1. **不得 import `server.*`** —— 夹具必须用 HTTP 打后端。直接 import 会让夹具与被测服务
   共享进程状态（数据库连接、缓存、内存态的 token 撤销清单），断言会被污染。
2. `cleanup` 遇到 401/404 时**不报错**，而是输出 `{"success": false, "already_gone": true}`
   并 exit 0。因为它跑在 teardown 里，"账号已经不在了"不该让整条用例变红；
   但会在 stderr 上大声提示 —— 也可能是 token 过期而账号仍在，需要人工核对。

**`backdate-order`（2026-10-13 新增）**：把某只基金**最早一笔** pending 买单的
`confirm_date` 改到过去，好让 `POST /api/portfolio/confirm-pending` 确认得掉它 ——
这是**一次 E2E 会话内造出「已确认持仓」的唯一办法**：买单落库的确认日 = 受理日 +
`confirm_delay` 个交易日，本仓库所有基金的 `confirm_delay` 都 ≥ 1，当天确认不了。
造这个状态是为了覆盖赎回拦截（用例 P1-04）：它的前提是「该基金已有已确认持仓 +
有一笔 pending 买单」，两个条件缺一不可。

它打的是后端开发端点 `POST /api/portfolio/test/backdate-order`（与 `/test/*` 同一守卫，
`ENV=production` 时 404），**不是直连数据库** —— 理由就是上面第 1 条：夹具只用 HTTP，
所以它不需要也不持有任何数据库密钥。同一件事在
.claude/skills/e2e-testing/references/02-夹具与断言设计.md §4.5 里被称作「改库子命令」。

⚠️ **整组 `/api/portfolio/test/*` 默认不注册**（2026-10-13 起）：起后端必须带
`ENABLE_TEST_ENDPOINTS=1`，否则这些路径不存在，夹具会拿到 404 而不是「没权限」。
这是刻意的 —— 原先只靠「`ENV` 不等于 production」，管不住「非生产但公网可达」的机器。

**仍然不要加 `confirm-pending` 子命令。** 原先的理由是「它确认不了刚下的单」，有了
`backdate-order` 之后这个理由不再成立；但结论不变 —— 确认动作应当由**用例带着自己的
JWT**打正式端点 `POST /api/portfolio/confirm-pending` 来做，夹具不该持有用户身份，
否则「谁能确认订单」这件事就被绕过去了。

依赖：httpx（后端已有依赖）。默认打 http://localhost:8000，--api 或环境变量 E2E_API 可覆盖。
"""

import argparse
import json
import os
import sys
import time

import httpx

DEFAULT_API = "http://localhost:8000"
API_PREFIX = "/api/secure-chat"

# 并行 worker 撞同一毫秒时 register 会拿到 409（重复邮箱），重试即可换一个新时间戳
REGISTER_ATTEMPTS = 3


class FixtureError(Exception):
    """夹具自身的失败。hint 是给人看的下一步动作。"""

    def __init__(self, message: str, hint: str = "", status: int | None = None):
        super().__init__(message)
        self.hint = hint
        self.status = status


def _warn(msg: str) -> None:
    print(f"[fixture] {msg}", file=sys.stderr)


def _detail(resp: httpx.Response) -> str:
    """取 FastAPI 的错误文案。校验失败时 detail 是 list，直接 str 出来即可。"""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return str(body)[:200]


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    headers: dict | None = None,
) -> dict:
    """发一次请求并返回 JSON。HTTP 错误统一转成带状态码的 FixtureError。

    headers 用于开发端点（免 JWT，改传 X-User-Id），与 token 二选一。
    """
    req_headers = dict(headers or {})
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    try:
        resp = client.request(method, path, json=payload, headers=req_headers)
    except httpx.HTTPError as e:
        raise FixtureError(
            f"连不上后端 {client.base_url}{path}：{e}",
            hint=(
                "确认后端已启动（poetry run uvicorn server.app:app --port 8000），"
                "或用 --api 指向正确地址。"
                "若只有 /api/portfolio/test/* 报 404，是启动时漏了 ENABLE_TEST_ENDPOINTS=1。"
            ),
        ) from e

    if resp.status_code >= 400:
        raise FixtureError(
            f"{method} {path} → HTTP {resp.status_code}：{_detail(resp)}",
            status=resp.status_code,
        )
    try:
        return resp.json()
    except ValueError as e:
        raise FixtureError(f"{method} {path} 的响应不是 JSON：{resp.text[:200]}") from e


def cmd_register(client: httpx.Client) -> dict:
    """注册一次性账号，返回 {email, password, token, user_id}。"""
    for attempt in range(1, REGISTER_ATTEMPTS + 1):
        ts = int(time.time() * 1000)
        email = f"e2e{ts}@ai-etf.xyz"
        password = f"E2e_{ts}_aZ"  # 满足前端「≥8 位」校验；**不能含 ! 等 shell 元字符**
        try:
            data = _request(
                client, "POST", f"{API_PREFIX}/register",
                payload={"email": email, "password": password},
            )
        except FixtureError as e:
            if e.status == 409 and attempt < REGISTER_ATTEMPTS:
                _warn(f"{email} 已存在（并行 worker 撞车），换时间戳重试 {attempt + 1}/{REGISTER_ATTEMPTS}")
                continue
            raise

        if data.get("needs_email_confirmation"):
            raise FixtureError(
                f"注册 {email} 成功，但 Supabase 要求邮箱确认，拿不到 token。",
                hint="E2E 依赖「注册即可用」。请到 Supabase 控制台关闭 Confirm email（见 docs/e2e/05-执行计划.md §八）。",
            )

        token = data.get("access_token")
        if not token:
            # 兜底：注册没回 token 就用同一组凭据登录一次
            _warn(f"注册响应未含 access_token，改用登录取 token：{email}")
            token = cmd_token(client, email, password)["token"]

        _warn(f"已注册一次性账号 {email}")
        return {"email": email, "password": password, "token": token, "user_id": data.get("user_id")}

    raise FixtureError(f"连续 {REGISTER_ATTEMPTS} 次注册都撞上已存在的邮箱")  # 理论不可达


def cmd_token(client: httpx.Client, email: str, password: str) -> dict:
    """用已有账号换 token，供交叉断言直连后端读真值。"""
    data = _request(client, "POST", f"{API_PREFIX}/login", payload={"email": email, "password": password})
    token = data.get("access_token")
    if not token:
        raise FixtureError(f"登录 {email} 返回成功，但响应里没有 access_token")
    return {
        "email": email,
        "token": token,
        "user_id": data.get("user_id"),
        "expires_in": data.get("expires_in"),
    }


def cmd_cleanup(client: httpx.Client, token: str, password: str) -> dict:
    """调 delete-account 注销账号。401/404 视为「已不存在」，不报错（理由见模块 docstring）。"""
    try:
        data = _request(
            client, "POST", f"{API_PREFIX}/delete-account",
            token=token, payload={"password": password},
        )
    except FixtureError as e:
        if e.status in (401, 404):
            _warn(f"注销返回 HTTP {e.status}，按「账号已不存在」处理。⚠️ 也可能是 token 过期而账号仍残留，请人工核对。")
            return {"success": False, "already_gone": True, "detail": str(e)}
        raise
    return {"success": True, "message": data.get("message", "账号已注销")}


def cmd_backdate_order(
    client: httpx.Client,
    user_id: str,
    fund_code: str,
    target_date: str | None = None,
) -> dict:
    """把某基金最早一笔 pending 买单的确认日改到过去（理由见模块 docstring）。

    走开发端点，所以用 X-User-Id 而不是 token。改完还要自己调
    POST /api/portfolio/confirm-pending（带该用户 JWT）才会真的建仓。
    """
    payload: dict = {"fund_code": fund_code}
    if target_date:
        payload["target_date"] = target_date
    return _request(
        client,
        "POST",
        "/api/portfolio/test/backdate-order",
        payload=payload,
        headers={"X-User-Id": user_id},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="E2E 一次性账号夹具（直连后端 HTTP，不 import server.*）",
    )
    parser.add_argument(
        "--api",
        default=os.environ.get("E2E_API") or DEFAULT_API,
        help=f"后端地址，默认 {DEFAULT_API}（也可用环境变量 E2E_API）",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="单次请求超时秒数，默认 30")

    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("register", help="注册一次性账号，输出 {email, password, token, user_id}")
    p_token = sub.add_parser("token", help="用已有账号取 token（供交叉断言）")
    p_token.add_argument("email")
    p_token.add_argument("password")
    p_cleanup = sub.add_parser("cleanup", help="调 delete-account 注销账号")
    p_cleanup.add_argument("token")
    p_cleanup.add_argument("password")
    p_backdate = sub.add_parser(
        "backdate-order",
        help="把某基金最早一笔 pending 买单的确认日改到过去（供「确认后」用例造状态）",
    )
    p_backdate.add_argument("user_id")
    p_backdate.add_argument("fund_code")
    p_backdate.add_argument(
        "--date",
        help="目标确认日 YYYY-MM-DD；不传则后端按北京时间当天算",
    )

    args = parser.parse_args(argv)

    try:
        with httpx.Client(base_url=args.api.rstrip("/"), timeout=args.timeout) as client:
            if args.cmd == "register":
                result = cmd_register(client)
            elif args.cmd == "token":
                result = cmd_token(client, args.email, args.password)
            elif args.cmd == "cleanup":
                result = cmd_cleanup(client, args.token, args.password)
            elif args.cmd == "backdate-order":
                result = cmd_backdate_order(client, args.user_id, args.fund_code, args.date)
            else:
                # 兜底：这里原先是裸 `else: cleanup`，新增子命令会被它悄悄当成 cleanup。
                # 现在新增子命令忘了接线会立刻炸，而不是发一个风马牛不相及的请求。
                raise FixtureError(f"未知子命令 {args.cmd}（分派分支漏了？）")
    except FixtureError as e:
        print(f"[fixture] 失败：{e}", file=sys.stderr)
        if e.hint:
            print(f"[fixture] 怎么办：{e.hint}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
