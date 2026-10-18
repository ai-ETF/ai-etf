#!/usr/bin/env python3
"""文档结构校验。

用法:
    python3 docs/scripts/doc_lint.py

检查项:
- 顶层目录白名单、根目录只允许 README.md
- 目录深度不超过 2 层、单目录 Markdown 不超过 15 篇
- 文件名禁用词
- frontmatter 必填字段、status 合法性、id/title 唯一性
- deprecated 文档必须位于 90-归档/
- 相对链接可解析
"""

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2]
REPO = DOCS.parent

TOP_LEVEL = {
    "00-协作规范",
    "10-需求",
    "20-设计",
    "30-接口",
    "40-运维",
    "50-测试",
    "60-参考",
    "70-方案与决策",
    "90-归档",
}
REQUIRED_FIELDS = {"id", "title", "status", "owner", "updated", "tags"}
VALID_STATUS = {"draft", "active", "deprecated"}
BANNED_WORDS = ("最终", "最新", "新版", "旧版", "副本", "final", "tmp", "待整理", "v2")
MAX_PER_DIR = 15
MAX_DIR_DEPTH = 2
SKIP_FRONTMATTER = {"README.md", "_template.md"}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\n]+)\)")
FENCE_RE = re.compile(r"```.*?```", re.S)
IGNORE_MISSING = {REPO / "local_models"}


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def rel(path: Path) -> str:
    return str(path.relative_to(DOCS))


def main() -> int:
    errors = []
    ids = {}
    titles = {}

    for path in sorted(DOCS.rglob("*")):
        if not path.is_dir() or path == DOCS:
            continue
        parts = path.relative_to(DOCS).parts
        if parts[0] not in TOP_LEVEL:
            errors.append(f"顶层目录不在白名单: {rel(path)}")
        if len(parts) > MAX_DIR_DEPTH:
            errors.append(f"目录过深（最多 {MAX_DIR_DEPTH} 层）: {rel(path)}")
        count = len(list(path.glob("*.md")))
        if count > MAX_PER_DIR:
            errors.append(f"单目录 Markdown 超过 {MAX_PER_DIR} 篇: {rel(path)} ({count})")

    for path in sorted(DOCS.glob("*.md")):
        if path.name != "README.md":
            errors.append(f"docs 根目录只允许 README.md: {path.name}")

    for path in sorted(DOCS.rglob("*.md")):
        r = path.relative_to(DOCS)
        if r.parts[0] not in TOP_LEVEL:
            continue
        if path.name != "README.md":
            for word in BANNED_WORDS:
                if word in path.name:
                    errors.append(f"文件名含禁用词「{word}」: {rel(path)}")
        if path.name in SKIP_FRONTMATTER:
            continue

        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        missing = REQUIRED_FIELDS - fm.keys()
        if missing:
            errors.append(f"frontmatter 缺少字段 {sorted(missing)}: {rel(path)}")
            continue
        if fm["status"] not in VALID_STATUS:
            errors.append(f"非法 status「{fm['status']}」: {rel(path)}")
        if fm["status"] == "deprecated" and r.parts[0] != "90-归档":
            errors.append(f"deprecated 文档不在 90-归档/: {rel(path)}")
        if fm["id"] in ids:
            errors.append(f"id 重复「{fm['id']}」: {rel(path)} 与 {ids[fm['id']]}")
        else:
            ids[fm["id"]] = rel(path)
        if fm["title"] in titles:
            errors.append(f"title 重复「{fm['title']}」: {rel(path)} 与 {titles[fm['title']]}")
        else:
            titles[fm["title"]] = rel(path)

        scan = FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        for match in LINK_RE.finditer(scan):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if not target or len(target) > 200 or " " in target:
                continue
            if target.startswith("/"):
                resolved = REPO / target.lstrip("/")
            else:
                resolved = (path.parent / target).resolve()
            if any(resolved == p or p in resolved.parents for p in IGNORE_MISSING):
                continue
            if not resolved.exists():
                line = scan[: match.start()].count("\n") + 1
                errors.append(f"链接失效 {rel(path)}:{line}: {target}")

    if errors:
        print("\n".join(f"❌ {e}" for e in errors))
        print(f"\n共 {len(errors)} 个问题")
        return 1
    print("✅ 文档结构校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
