#!/usr/bin/env python3
"""Parse a relational-model Markdown file into a normalized JSON model.

Usage:
    python parse_model.py <model.md> [--out model.json]

The input format is documented in references/input-contract.md.
Output goes to stdout when --out is omitted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def section_map(text: str) -> dict[str, str]:
    """Split the document on `## <n>.` headings; keys are the section numbers."""
    sections: dict[str, str] = {}
    for part in re.split(r"(?m)^##\s+", text)[1:]:
        head, _, body = part.partition("\n")
        num = head.split(".", 1)[0].strip()
        if num.isdigit():
            sections[num] = body
    return sections


def split_segments(value: str) -> list[str]:
    """Split on `；` only when the next segment starts with a code span."""
    return [s.strip() for s in re.split(r"；(?=\s*`)", value) if s.strip()]


def parse_columns(content: str) -> list[dict]:
    """Read the `| 列名 | 类型 | 约束 |` table inside a table section."""
    cols: list[dict] = []
    in_table = False
    for line in content.splitlines():
        if re.match(r"^\|\s*列名\s*\|", line):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.strip().startswith("|"):
            break
        if re.match(r"^\|[\s:|-]+\|$", line.strip()):
            continue
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*$", line)
        if not m:
            continue
        name, typ, cons_cell = m.group(1), m.group(2), m.group(3)
        nullable = True
        keys = []
        for item in ([] if cons_cell in ("", "—") else cons_cell.split(",")):
            item = item.strip()
            if item == "PK":
                keys.append("PK")
            elif item == "FK" or item.startswith("FK→"):
                keys.append("FK")
            elif item == "UNIQUE":
                keys.append("UQ")
            elif item == "NOT NULL":
                nullable = False
            elif item == "NULL":
                nullable = True
        cols.append({"name": name, "type": typ, "nullable": nullable, "keys": keys})
    return cols


def parse_candidate_keys(value: str) -> list[dict]:
    out = []
    for seg in split_segments(value):
        cols = re.findall(r"`([^`]+)`", seg)
        if not cols:
            continue
        predicate = None
        m = re.search(r"部分唯一：(.+?)）\s*$", seg)
        if m:
            predicate = m.group(1).strip()
        out.append({"columns": cols, "predicate": predicate, "name": None})
    return out


def parse_fk_line(value: str) -> list[dict]:
    out = []
    for seg in split_segments(value):
        m = re.match(
            r"`([^`]+)`\s*→\s*`([^`(]+)\(([^)]+)\)`(?:\s+ON DELETE\s+(.+?))?\s*$", seg
        )
        if not m:
            continue
        out.append(
            {
                "from_columns": [c.strip() for c in m.group(1).replace("`", "").split(",")],
                "to_table": m.group(2).strip(),
                "to_columns": [c.strip() for c in m.group(3).split(",")],
                "on_delete": (m.group(4) or "").strip() or None,
            }
        )
    return out


def parse_logical_line(value: str) -> list[dict]:
    out = []
    for seg in split_segments(value):
        m = re.match(
            r"`([^`]+)`\s*⇢\s*`([^`(]+)\(([^)]+)\)`（(.*)）\s*$", seg
        )
        if not m:
            continue
        out.append(
            {
                "from_columns": [c.strip() for c in m.group(1).replace("`", "").split(",")],
                "to_table": m.group(2).strip(),
                "to_columns": [c.strip() for c in m.group(3).split(",")],
                "note": m.group(4).strip(),
            }
        )
    return out


def parse_domains(section: str) -> list[dict]:
    domains = []
    for line in section.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*(.+?)\s*\|\s*$", line)
        if not m:
            continue
        no, name, desc, nodes_cell = m.groups()
        nodes = re.findall(r"`([^`]+)`", nodes_cell)
        domains.append({"no": no, "name": name.strip(), "desc": desc.strip(), "nodes": nodes})
    return domains


def parse_tables(section: str) -> list[dict]:
    tables = []
    current_domain = None
    chunks = re.split(r"(?m)^(###\s+域\s+.+|####\s+.+)$", section)
    # chunks: [preamble, heading, content, heading, content, ...]
    for i in range(1, len(chunks), 2):
        heading, content = chunks[i].strip(), chunks[i + 1]
        dm = re.match(r"^###\s+域\s*(\d+)\s*·\s*(.+)$", heading)
        if dm:
            current_domain = dm.group(1)
            continue
        tm = re.match(r"^####\s*`([^`]+)`(?:\s*（(.+)）)?\s*$", heading)
        if not tm:
            continue
        name, cn = tm.group(1).strip(), (tm.group(2) or "").strip()
        external = "外部" in cn
        if external:
            cn = ""  # keep the presentation name from the existing HTML

        def bullet(label: str) -> str | None:
            m = re.search(rf"(?m)^-\s*{label}：(.*)$", content)
            return m.group(1).strip() if m else None

        pk_value = bullet("主键")
        primary_key = re.findall(r"`([^`]+)`", pk_value) if pk_value else []
        ck_value = bullet(r"候选键（主键之外）")
        fk_value = bullet("外键")
        logical_value = bullet("逻辑引用")
        note = bullet("说明")

        columns = parse_columns(content)
        if external and not columns:
            # External entities only list the referenced key, e.g. `id uuid`.
            for spec in re.findall(r"`([^`]+)`", bullet("属性") or ""):
                parts = spec.strip().split()
                if len(parts) >= 2:
                    columns.append(
                        {
                            "name": parts[0],
                            "type": " ".join(parts[1:]),
                            "nullable": False,
                            "keys": ["PK"] if parts[0] in primary_key else [],
                        }
                    )

        tables.append(
            {
                "name": name,
                "cn": cn,
                "note": note,
                "domain_no": current_domain,
                "external": external,
                "primary_key": primary_key,
                "candidate_keys": parse_candidate_keys(ck_value) if ck_value and ck_value != "—" else [],
                "foreign_keys": parse_fk_line(fk_value) if fk_value and fk_value != "—" else [],
                "logical_refs": parse_logical_line(logical_value)
                if logical_value and logical_value != "—"
                else [],
                "columns": columns,
            }
        )
    return tables


def parse_views(section: str) -> list[dict]:
    views = []
    chunks = re.split(r"(?m)^(###\s+.+)$", section)
    for i in range(1, len(chunks), 2):
        heading, content = chunks[i].strip(), chunks[i + 1]
        m = re.match(r"^###\s*`([^`]+)`\s*$", heading)
        if not m:
            continue
        name = m.group(1)

        def bullet(label: str) -> str | None:
            mm = re.search(rf"(?m)^-\s*{label}：(.*)$", content)
            return mm.group(1).strip() if mm else None

        kind_val = bullet("类型") or "`view`"
        kind = (re.search(r"`([^`]+)`", kind_val) or [None, "view"])[1]
        options = None
        om = re.search(r"（(.+?)）", kind_val)
        if om:
            options = om.group(1).strip()
        derived_val = bullet("派生自") or ""
        views.append(
            {
                "name": name,
                "kind": kind,
                "definition_options": options,
                "derived_from": re.findall(r"`([^`]+)`", derived_val),
                "note": bullet("说明"),
                "columns": parse_columns(content),
            }
        )
    return views


def parse_enums(section: str) -> list[dict]:
    enums = []
    for line in section.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$", line)
        if not m or m.group(1) in ("枚举名",):
            continue
        values = [v.strip() for v in re.split(r"[、,]", m.group(2)) if v.strip()]
        enums.append({"name": m.group(1), "values": values})
    return enums


def parse_relationships(section: str) -> list[dict]:
    rels = []
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        _, kind_label, from_cell, to_cell, cardinality, on_delete, label = cells[:7]
        from_cell = from_cell.strip("`")
        to_cell = to_cell.strip("`")
        if "." not in from_cell or "." not in to_cell:
            continue
        # Table names may contain dots (auth.users), so split at the last one.
        from_table, from_cols = from_cell.rsplit(".", 1)
        to_table, to_cols = to_cell.rsplit(".", 1)
        rel_type = "hard" if kind_label == "真实外键" else "logical"
        on_delete_value = None if on_delete in ("—", "") else on_delete
        rels.append(
            {
                "from": from_table.strip(),
                "from_columns": [c.strip() for c in from_cols.split(",")],
                "to": to_table.strip(),
                "to_columns": [c.strip() for c in to_cols.split(",")],
                "type": rel_type,
                "cardinality": cardinality or "N:1",
                "on_delete": on_delete_value,
                "constraint": label if rel_type == "hard" else None,
                "note": "真实外键约束" if rel_type == "hard" else label,
            }
        )
    return rels


def parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    sections = section_map(text)

    stat = re.search(
        r"(\d+)\s*表\s*/\s*(\d+)\s*列\s*/\s*(\d+)\s*外键\s*/\s*(\d+)\s*逻辑引用\s*/\s*(\d+)\s*视图\s*/\s*(\d+)\s*枚举",
        text,
    )
    meta = (
        dict(zip(("tables", "columns", "hard", "logical", "views", "enums"), map(int, stat.groups())))
        if stat
        else {}
    )

    domains = parse_domains(sections.get("1", ""))
    tables = parse_tables(sections.get("2", ""))
    views = parse_views(sections.get("3", ""))
    enums = parse_enums(sections.get("4", ""))
    relationships = parse_relationships(sections.get("5", ""))

    domain_by_no = {d["no"]: d for d in domains}
    for t in tables:
        d = domain_by_no.get(t["domain_no"] or "")
        t["domain"] = d["name"] if d else None

    return {
        "meta": meta,
        "domains": domains,
        "tables": tables,
        "views": views,
        "enums": enums,
        "relationships": relationships,
        "stats": {
            "tables": sum(1 for t in tables if not t["external"]),
            "entities": len(tables),
            "columns": sum(len(t["columns"]) for t in tables if not t["external"]),
            "hard": sum(1 for r in relationships if r["type"] == "hard"),
            "logical": sum(1 for r in relationships if r["type"] == "logical"),
            "authUserFks": sum(
                1 for r in relationships if r["type"] == "hard" and r["to"] == "auth.users"
            ),
            "views": len(views),
            "viewColumns": sum(len(v["columns"]) for v in views),
            "enums": len(enums),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model")
    ap.add_argument("--out")
    args = ap.parse_args()

    model = parse(Path(args.model))
    payload = json.dumps(model, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
