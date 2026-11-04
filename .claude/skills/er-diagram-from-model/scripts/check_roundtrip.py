#!/usr/bin/env python3
"""Compare an updated E-R HTML against the model it was built from.

This is the regression gate: run it after apply_data.py. It checks counts and
relationship identity, not presentation details.

Usage:
    python check_roundtrip.py <model.json> <updated.html>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def extract_data(html: str) -> dict:
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
                return json.loads(html[start : i + 1])
    raise ValueError("没有找到 const DATA={...}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model")
    ap.add_argument("html")
    args = ap.parse_args()

    m = json.loads(Path(args.model).read_text(encoding="utf-8"))
    data = extract_data(Path(args.html).read_text(encoding="utf-8"))
    problems: list[str] = []

    stats, summary = m["stats"], data.get("summary", {})
    for key in ("tables", "entities", "columns", "hard", "logical", "authUserFks", "views", "viewColumns"):
        if stats.get(key) != summary.get(key):
            problems.append(f"summary.{key}: md={stats.get(key)} html={summary.get(key)}")

    tables = data.get("tables", {})
    model_tables = {t["name"] for t in m["tables"]}
    if set(tables) != model_tables:
        problems.append(f"表集合不一致：只缺 {sorted(model_tables - set(tables))}，只多 {sorted(set(tables) - model_tables)}")
    for t in m["tables"]:
        got = tables.get(t["name"])
        if not got:
            continue
        if got.get("primary_key") != t["primary_key"]:
            problems.append(f"{t['name']}: 主键 {got.get('primary_key')} != {t['primary_key']}")
        got_cols = {c["name"] for c in got.get("columns", [])}
        want_cols = {c["name"] for c in t["columns"]}
        if got_cols != want_cols:
            problems.append(f"{t['name']}: 字段集合不一致 {sorted(want_cols - got_cols)} / {sorted(got_cols - want_cols)}")

    want_rels = {
        (r["from"], tuple(r["from_columns"]), r["to"], tuple(r["to_columns"]), r["type"])
        for r in m["relationships"]
    }
    got_rels = {
        (r["from"], tuple(r["from_cols"]), r["to"], tuple(r["to_cols"]), r["type"])
        for r in data.get("relationships", [])
    }
    if want_rels != got_rels:
        problems.append(f"关系集合不一致：只缺 {sorted(want_rels - got_rels)}，只多 {sorted(got_rels - want_rels)}")

    for d in data.get("domains", []):
        for node in d.get("nodes", []):
            if node not in tables:
                problems.append(f"域 {d['name']} 的节点 {node} 不是已定义的表")

    for p in problems:
        print(f"ERROR {p}", file=sys.stderr)
    if problems:
        print(f"\n回归检查失败：{len(problems)} 项", file=sys.stderr)
        return 1
    print(
        f"回归检查通过：{summary['tables']} 表 / {summary['columns']} 列 / "
        f"{summary['hard']} 真实外键 / {summary['logical']} 逻辑引用"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
