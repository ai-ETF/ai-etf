#!/usr/bin/env python3
"""Validate a parsed relational model. Exit code 1 means: do not touch the HTML.

Usage:
    python validate_model.py <model.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model")
    args = ap.parse_args()

    m = json.loads(Path(args.model).read_text(encoding="utf-8"))
    tables = {t["name"]: t for t in m["tables"]}
    domains = m["domains"]
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Header statistics must match what was actually parsed.
    meta, stats = m.get("meta", {}), m.get("stats", {})
    for key in ("tables", "columns", "hard", "logical", "views", "enums"):
        if key in meta and meta[key] != stats.get(key):
            errors.append(
                f"文件头部统计 {key}={meta[key]}，实际解析为 {stats.get(key)}；先改文件头或修正正文"
            )

    # 2. Every table has a primary key and unique column names.
    for name, t in tables.items():
        if not t["primary_key"]:
            errors.append(f"{name}: 没有主键（关系模型要求每个关系至少有一个候选键）")
        col_names = [c["name"] for c in t["columns"]]
        dup = {c for c in col_names if col_names.count(c) > 1}
        if dup:
            errors.append(f"{name}: 字段重复 {sorted(dup)}")
        for pk in t["primary_key"]:
            if pk not in col_names:
                errors.append(f"{name}: 主键 `{pk}` 不在字段表里")

    # 3. Foreign keys and logical references point at real tables/columns.
    for r in m["relationships"]:
        target = tables.get(r["to"])
        source = tables.get(r["from"])
        if source is None:
            errors.append(f"关系 `{r['from']} → {r['to']}`：从表 {r['from']} 不存在")
            continue
        if target is None:
            errors.append(f"关系 `{r['from']} → {r['to']}`：目标表 {r['to']} 不存在")
            continue
        src_cols = {c["name"] for c in source["columns"]}
        dst_cols = {c["name"] for c in target["columns"]}
        for c in r["from_columns"]:
            if c not in src_cols:
                errors.append(f"关系 `{r['from']} → {r['to']}`：从字段 {r['from']}.{c} 不存在")
        for c in r["to_columns"]:
            if c not in dst_cols:
                errors.append(f"关系 `{r['from']} → {r['to']}`：目标字段 {r['to']}.{c} 不存在")

    # 4. Domain coverage: every table exactly once, every node a real table.
    node_owner: dict[str, str] = {}
    for d in domains:
        for node in d["nodes"]:
            if node not in tables:
                errors.append(f"业务域 {d['no']} `{d['name']}` 包含不存在的表 {node}")
            if node in node_owner:
                errors.append(f"表 {node} 同时出现在域 {node_owner[node]} 和 {d['no']}")
            node_owner[node] = d["no"]
        for t in m["tables"]:
            if t["domain"] == d["name"] and t["name"] not in d["nodes"]:
                errors.append(f"表 {t['name']} 标注属于域 `{d['name']}`，但没写进该域的节点清单")
    for name, t in tables.items():
        if name not in node_owner:
            errors.append(f"表 {name} 没有归入任何业务域")
        if not t.get("domain"):
            errors.append(f"表 {name} 没有业务域标注")

    # 5. Candidate keys must exist as columns.
    for name, t in tables.items():
        cols = {c["name"] for c in t["columns"]}
        for ck in t.get("candidate_keys", []):
            for c in ck["columns"]:
                if c not in cols:
                    errors.append(f"{name}: 候选键字段 `{c}` 不在字段表里")

    # Warnings: things that are legal but usually accidental.
    for name, t in tables.items():
        if name != "auth.users" and not t.get("note"):
            warnings.append(f"{name}: 没有「说明」，E-R 图卡片会缺少中文描述")

    for w in warnings:
        print(f"WARN  {w}", file=sys.stderr)
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)

    if errors:
        print(f"\n校验失败：{len(errors)} 个错误，{len(warnings)} 个警告", file=sys.stderr)
        return 1
    print(f"校验通过：{len(tables)} 个关系，{len(m['relationships'])} 条关系，{len(domains)} 个业务域")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
