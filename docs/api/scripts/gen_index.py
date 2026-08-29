#!/usr/bin/env python3
"""
接口清单校验 + 生成工具

从线上 FastAPI 的 /openapi.json 拉取实际注册的路由，与 docs/api/*.md 文档核对：

1. 校验「缺文档」：线上存在但文档里搜不到路径的接口
2. 校验「文档引用了不存在的接口」：文档里写了但线上没有的路径（即废弃接口没删干净）
3. --gen-table：打印一份可直接粘贴进 README.md「接口总览」的 Markdown 表格

用法：
    python docs/api/scripts/gen_index.py --url https://ai-etf.xyz
    python docs/api/scripts/gen_index.py --url "$API" --gen-table

依赖：仅标准库，无需安装任何包。
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parents[1]  # docs/api/
SKIP_FILES = {"README.md", "_template.md"}

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}

# 生成 README 总览表时，把路径归到模块文档（按前缀匹配，前面的优先）
# 根路径 / 单独在 module_for 中处理，不放进前缀，避免 "/" 匹配所有路径。
MODULE_BY_PREFIX = [
    (("/api/secure-chat/login", "/api/test"), "01-基础与认证.md"),
    (("/api/secure-chat",), "02-对话与会话.md"),
    (("/api/market",), "03-行情.md"),
    (("/api/watchlist",), "04-自选股.md"),
    (("/api/portfolio",), "05-组合交易.md"),
    (("/api/risk",), "06-风险测评.md"),
    (("/api/upload",), "07-文档上传.md"),
]

def normalize(path: str) -> str:
    """把 {chat_id} / <CHAT_ID> 统一成占位符 {P}，便于比对。根路径 / 保持不变。"""
    return re.sub(r"\{[^}]*\}|<[^>]*>", "{P}", path)


def segment_match(a: str, b: str) -> bool:
    """两个路径段是否等价：完全相同，或任一是占位符 {P}。"""
    return a == b or a == "{P}" or b == "{P}"


def path_match(t: str, p: str) -> bool:
    """文档 token t 是否与线上路径 p 匹配（允许具体值 ↔ {P}）。"""
    ta, pa = t.split("/"), p.split("/")
    if len(ta) != len(pa):
        return False
    return all(segment_match(x, y) for x, y in zip(ta, pa))


def fetch_openapi(url: str) -> dict:
    base = url.rstrip("/")
    with urllib.request.urlopen(f"{base}/openapi.json", timeout=15) as resp:
        return json.load(resp)


def openapi_endpoints(spec: dict):
    """返回归一化后的 {(method, path)} 集合。"""
    out = set()
    for path, item in (spec.get("paths") or {}).items():
        for method in item:
            if method.lower() in HTTP_METHODS:
                out.add((method.upper(), normalize(path)))
    return out


def doc_path_tokens(docs: str) -> set:
    """从文档文本中提取所有 /api/... 路径 token 并归一化。\w 覆盖中文路径段。"""
    tokens = re.findall(r"/api/[\w\-.{}<>%/]+", docs)
    return {normalize(t).rstrip(".") for t in tokens}


def collect_docs() -> str:
    """拼接所有模块文档（跳过 README 和模板）。"""
    parts = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        if f.name in SKIP_FILES:
            continue
        parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


def module_for(path: str) -> str:
    if path == "/":
        return "01-基础与认证.md"
    for prefixes, doc in MODULE_BY_PREFIX:
        if any(path.startswith(p) for p in prefixes):
            return doc
    return "-"


def needs_auth(method: str, path: str) -> str:
    """认证列：openapi 不会暴露 Depends(get_current_user)，用路径规则近似。"""
    if path == "/" or path == "/api/secure-chat/login":
        return "-"
    if path.startswith(("/api/market", "/api/upload", "/api/test")):
        return "-"
    if path.endswith("/health"):
        return "-"
    if path.startswith("/api/portfolio/test/"):
        return "`X-User-Id`"
    return "🔒"


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 API 文档与线上路由是否一致")
    parser.add_argument("--url", default="http://localhost:8000", help="后端地址，默认 http://localhost:8000")
    parser.add_argument("--gen-table", action="store_true", help="同时打印 README 接口总览表")
    args = parser.parse_args()

    try:
        spec = fetch_openapi(args.url)
    except Exception as e:
        print(f"❌ 拉取 {args.url}/openapi.json 失败: {e}", file=sys.stderr)
        return 2

    live = openapi_endpoints(spec)
    live_paths = {p for _, p in live}
    docs = collect_docs()
    doc_tokens = doc_path_tokens(docs)

    # 1. 缺文档：线上有、文档里没有可匹配的路径
    missing = sorted(
        (m, p) for m, p in live
        if p != "/" and not any(path_match(t, p) for t in doc_tokens)
    )

    # 2. 文档引用了不存在的接口（废弃没删干净）。
    #    文档标题里会出现模块前缀（如「03 行情（/api/market）」），它本身不是路由，
    #    但如果它是某条线上路径的前缀，则视为模块导航引用而非废弃接口，不告警。
    stale = sorted(
        t for t in doc_tokens
        if not any(path_match(t, p) for p in live_paths)
        and not any(p.startswith(t) for p in live_paths)
    )

    print(f"✅ 线上接口数: {len(live)}（来源 {args.url}/openapi.json）")
    print(f"   文档扫描: docs/api/*.md（跳过 README.md / _template.md）\n")

    if missing:
        print("⚠️  线上存在但文档里缺失的接口：")
        for m, p in missing:
            print(f"   - {m:6} {p}")
    else:
        print("✅ 无缺失文档的接口。")

    if stale:
        print("\n⚠️  文档引用了不存在的接口（疑似废弃未删干净）：")
        for p in stale:
            print(f"   - {p}")
    else:
        print("✅ 文档没有引用不存在的接口。")

    if args.gen_table:
        print("\n--- README 接口总览表（可直接粘贴）---\n")
        print("| 方法 | 路径 | 认证 | 文档 |")
        print("|------|------|:---:|------|")
        for method, path in sorted(live, key=lambda x: (x[1], x[0])):
            auth = needs_auth(method, path)
            doc = module_for(path)
            print(f"| {method:6} | `{path}` | {auth} | [{doc}]({doc}) |")

    ok = not missing and not stale
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
