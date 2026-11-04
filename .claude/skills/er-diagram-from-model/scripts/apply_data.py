#!/usr/bin/env python3
"""Replace the `const DATA=...` payload in an E-R HTML file.

Everything outside that one object literal is left untouched, so the page's
CSS, DOM and rendering code keep working.

Usage:
    python apply_data.py <target.html> <data.json> [--no-backup] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path


def extract_data(html: str) -> tuple[dict, int, int]:
    marker = html.index("const DATA=")
    start = html.index("{", marker)
    depth, in_str, esc = 0, False, False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : i + 1]), start, i + 1
    raise ValueError("没有找到完整的 const DATA={...}，目标可能不是本 skill 支持的页面")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("html")
    ap.add_argument("data")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.html)
    html = path.read_text(encoding="utf-8")
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    old, start, end = extract_data(html)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    updated = html[:start] + payload + html[end:]

    # Never write a file that the page itself cannot parse.
    check, _, _ = extract_data(updated)
    if check != data:
        print("ERROR 写入前自检失败：替换后的 DATA 与输入不一致", file=sys.stderr)
        return 1

    s_old, s_new = old.get("summary", {}), data.get("summary", {})
    print(f"tables {s_old.get('tables')} → {s_new.get('tables')}", file=sys.stderr)
    print(f"columns {s_old.get('columns')} → {s_new.get('columns')}", file=sys.stderr)
    print(f"relationships {len(old.get('relationships', []))} → {len(data.get('relationships', []))}", file=sys.stderr)

    if args.dry_run:
        print("dry-run：未写入文件", file=sys.stderr)
        return 0

    if not args.no_backup:
        backup = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(path, backup)
        print(f"备份：{backup}", file=sys.stderr)

    path.write_text(updated, encoding="utf-8")
    print(f"已更新：{path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
