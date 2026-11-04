#!/usr/bin/env python3
"""Merge a parsed relational model with an existing E-R HTML, producing new DATA.

The Markdown owns structure (tables, columns, keys, foreign keys, domains, views,
enums). The HTML keeps presentation-only facts (card positions, colors, row
counts, index definitions) unless the Markdown says otherwise.

Usage:
    python build_data.py <model.json> <existing.html> --out data.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PALETTE = ["#2563eb", "#7c3aed", "#ea580c", "#475569", "#0d9488", "#b45309", "#be123c", "#0f766e"]
# The canvases are hand-placed and irregular, so new cards go on a fresh row
# below every existing card instead of trying to guess a global grid.
GRID_X, GRID_Y = 70, 80
NEW_COLS, NEW_COL_W, NEW_ROW_H = 4, 350, 190


def extract_data(html: str) -> tuple[dict, int, int]:
    """Return (DATA, start, end) where [start:end] is the JSON object literal."""
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
    raise ValueError("没有找到完整的 const DATA={...}")


def auto_layout(nodes: list[str], taken: dict[str, list[int]]) -> dict[str, list[int]]:
    pending = [n for n in nodes if n not in taken]
    if not pending:
        return {}
    base_x = min((v[0] for v in taken.values()), default=GRID_X)
    row_y = max((v[1] for v in taken.values()), default=GRID_Y - NEW_ROW_H) + NEW_ROW_H
    return {
        node: [base_x + (i % NEW_COLS) * NEW_COL_W, row_y + (i // NEW_COLS) * NEW_ROW_H]
        for i, node in enumerate(pending)
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model")
    ap.add_argument("html")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    model = json.loads(Path(args.model).read_text(encoding="utf-8"))
    html = Path(args.html).read_text(encoding="utf-8")
    old, _, _ = extract_data(html)
    old_tables = old.get("tables", {})
    old_rels = old.get("relationships", [])
    old_domains = old.get("domains", [])
    old_views = {v["name"]: v for v in old.get("views", [])}
    old_positions = old.get("positions", {})
    old_heights = old.get("canvasHeights", {})

    domain_by_name = {d["name"]: d for d in old_domains}
    domain_id = {}
    palette_i = 0
    for d in model["domains"]:
        od = domain_by_name.get(d["name"])
        d["_id"] = od["id"] if od else f"d{len(domain_id) + 1}"
        d["_color"] = od["color"] if od else PALETTE[palette_i % len(PALETTE)]
        palette_i += 1
        domain_id[d["name"]] = d["_id"]

    table_domain = {t["name"]: domain_id.get(t.get("domain") or "") for t in model["tables"]}

    # ---- tables -----------------------------------------------------------
    tables: dict[str, dict] = {}
    for t in model["tables"]:
        name = t["name"]
        old_t = old_tables.get(name, {})
        cols = t["columns"] or old_t.get("columns", [])
        fk_cols = {c for fk in t["foreign_keys"] for c in fk["from_columns"]}
        # Only UNIQUE *constraints* get the UQ badge. Partial and index-only
        # uniqueness stays visible in the drawer but is not shown on the card.
        if old_t.get("unique_constraints"):
            uq_cols = {c for uc in old_t["unique_constraints"] for c in uc["columns"]}
        elif old_t:
            uq_cols = set()
        else:
            uq_cols = {
                c
                for ck in t["candidate_keys"]
                if not ck.get("predicate")
                for c in ck["columns"]
            }
        pk_cols = set(t["primary_key"])

        new_cols = []
        for c in cols:
            key = []
            if c["name"] in pk_cols:
                key.append("PK")
            if c["name"] in fk_cols:
                key.append("FK")
            if c["name"] in uq_cols:
                key.append("UQ")
            old_col = next((x for x in old_t.get("columns", []) if x["name"] == c["name"]), {})
            new_cols.append(
                {
                    "name": c["name"],
                    "type": c["type"],
                    "nullable": c["nullable"],
                    "default": old_col.get("default"),
                    "key": key,
                }
            )

        old_key_fields = [f for f in old_t.get("key_fields", []) if f in {c["name"] for c in new_cols}]
        if not old_key_fields:
            old_key_fields = [c["name"] for c in new_cols if c["name"] not in pk_cols][:5]

        unique_indexes = old_t.get("unique_indexes")
        unique_constraints = old_t.get("unique_constraints")
        if unique_indexes is None:
            unique_indexes = []
            if t["primary_key"]:
                unique_indexes.append(
                    {
                        "name": f"{name}_pkey",
                        "columns": t["primary_key"],
                        "predicate": None,
                        "is_primary": True,
                        "method": "btree",
                        "definition": f"CREATE UNIQUE INDEX {name}_pkey ON public.{name} USING btree ({', '.join(t['primary_key'])})",
                    }
                )
        if unique_constraints is None:
            unique_constraints = []
            for ck in t["candidate_keys"]:
                uname = ck.get("name") or f"{name}_{'_'.join(ck['columns'])}_key"
                unique_constraints.append(
                    {
                        "name": uname,
                        "columns": ck["columns"],
                        "definition": f"UNIQUE ({', '.join(ck['columns'])})",
                    }
                )
                unique_indexes.append(
                    {
                        "name": uname,
                        "columns": ck["columns"],
                        "predicate": ck.get("predicate"),
                        "is_primary": False,
                        "method": "btree",
                        "definition": f"CREATE UNIQUE INDEX {uname} ON public.{name} USING btree ({', '.join(ck['columns'])})"
                        + (f" WHERE {ck['predicate']}" if ck.get("predicate") else ""),
                    }
                )

        tables[name] = {
            "name": name,
            "domain": domain_id.get(t.get("domain") or ""),
            "cn": t["cn"] or old_t.get("cn", ""),
            "kind": old_t.get("kind") or ("external_table" if t["external"] else "table"),
            "primary_key": t["primary_key"],
            "columns": new_cols,
            "key_fields": old_key_fields,
            "unique_indexes": unique_indexes,
            "note": (old_t.get("note", "") if t["external"] else (t.get("note") or old_t.get("note", ""))),
            "schema": old_t.get("schema") or ("auth" if name.startswith("auth.") else "public"),
            "business_domain": old_t.get("business_domain") or (t.get("domain") or ""),
            "unique_constraints": unique_constraints,
        }
        if "row_count" in old_t:
            tables[name]["row_count"] = old_t["row_count"]

    # ---- relationships ----------------------------------------------------
    old_by_key = {
        (r["from"], tuple(r["from_cols"]), r["to"], tuple(r["to_cols"]), r["type"]): r for r in old_rels
    }
    relationships = []
    for r in model["relationships"]:
        key = (r["from"], tuple(r["from_columns"]), r["to"], tuple(r["to_columns"]), r["type"])
        o = old_by_key.get(key, {})
        if r["type"] == "hard":
            rid = r.get("constraint") or o.get("id") or f"{r['from']}_{'_'.join(r['from_columns'])}_fkey"
            validated, confidence = True, "declared"
            note = "真实外键约束"
        else:
            rid = o.get("id") or f"{r['from']}_{'_'.join(r['from_columns'])}_to_{r['to']}"
            validated, confidence = None, "inferred"
            note = r.get("note") or o.get("note", "")
        relationships.append(
            {
                "id": rid,
                "from": r["from"],
                "from_cols": r["from_columns"],
                "to": r["to"],
                "to_cols": r["to_columns"],
                "type": r["type"],
                "cardinality": r.get("cardinality") or "N:1",
                "on_delete": r.get("on_delete"),
                "note": note,
                "on_update": o.get("on_update", "NO ACTION" if r["type"] == "hard" else None),
                **({"validated": True} if r["type"] == "hard" else {}),
                "confidence": confidence,
                "name": rid,
                "from_entity": r["from"],
                "from_columns": r["from_columns"],
                "to_entity": r["to"],
                "to_columns": r["to_columns"],
            }
        )

    # ---- domains, layout --------------------------------------------------
    domains, positions, heights = [], {}, {}
    for d in model["domains"]:
        did = d["_id"]
        nodes = d["nodes"]
        old_d = domain_by_name.get(d["name"], {})

        rel_ids = []
        refs = []
        for r in relationships:
            inside_from, inside_to = r["from"] in nodes, r["to"] in nodes
            if inside_from and inside_to:
                rel_ids.append(r["id"])
            elif inside_from and not inside_to and r["type"] == "hard":
                # Reference nodes exist for declared cross-domain FKs only;
                # logical links stay as dashed edges inside their own domain.
                if r["to"] not in nodes and r["to"] not in refs:
                    refs.append(r["to"])
        old_refs = [r for r in old_d.get("refs", []) if r in refs]
        refs = old_refs + [r for r in refs if r not in old_refs]

        # renderER draws every edge whose *source* belongs to this domain and
        # only renders a card when the table has a position here. Cross-domain
        # targets therefore need a ghost position even though they are not
        # domain nodes.
        ghosts = []
        for r in relationships:
            if table_domain.get(r["from"]) == did and r["to"] not in nodes and r["to"] not in ghosts:
                ghosts.append(r["to"])

        old_pos = old_positions.get(did, {})
        pos = {k: v for k, v in old_pos.items() if k in tables}
        pos.update(auto_layout(nodes + ghosts, pos))
        positions[did] = pos

        max_y = max((y for _, y in pos.values()), default=GRID_Y)
        computed_h = max_y + 140 + 60
        heights[did] = max(old_heights.get(did, 0), computed_h)
        domains.append(
            {
                "id": did,
                "name": d["name"],
                "no": d["no"],
                "color": d["_color"],
                "desc": d["desc"],
                "height": heights[did],
                "nodes": nodes,
                "relationships": rel_ids,
                "refs": refs,
            }
        )

    # ---- views, summary ---------------------------------------------------
    views = []
    for v in model["views"]:
        ov = old_views.get(v["name"], {})
        views.append(
            {
                "name": v["name"],
                "schema": ov.get("schema", "public"),
                "kind": v["kind"],
                "derived_from": v["derived_from"] or ov.get("derived_from", []),
                "definition_options": v.get("definition_options") or ov.get("definition_options"),
                "columns": [
                    {"name": c["name"], "type": c["type"], "nullable": c["nullable"], "default": None, "key": []}
                    for c in v["columns"]
                ],
                "note": v.get("note") or ov.get("note", ""),
            }
        )

    s = model["stats"]
    summary = {
        "tables": s["tables"],
        "entities": s["entities"],
        "columns": s["columns"],
        "hard": s["hard"],
        "logical": s["logical"],
        "authUserFks": s["authUserFks"],
        "views": s["views"],
        "viewColumns": s["viewColumns"],
        "uniqueIndexes": sum(len(t["unique_indexes"]) for t in tables.values()),
        "uniqueConstraints": sum(len(t["unique_constraints"]) for t in tables.values()),
        "partialUniqueIndexes": sum(
            1 for t in tables.values() for i in t["unique_indexes"] if i.get("predicate")
        ),
    }

    data = {
        "domains": domains,
        "tables": tables,
        "relationships": relationships,
        "positions": positions,
        "canvasHeights": heights,
        "summary": summary,
        "views": views,
    }

    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    removed = sorted(set(old_tables) - set(tables))
    added = sorted(set(tables) - set(old_tables))
    if added:
        print(f"新增表（已自动排版）：{', '.join(added)}", file=sys.stderr)
    if removed:
        print(f"WARN 将从图中移除的表：{', '.join(removed)}；确认 md 是有意删除它们", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
