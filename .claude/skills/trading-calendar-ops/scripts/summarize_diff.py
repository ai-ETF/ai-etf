#!/usr/bin/env python3
"""把 refresh 接口返回的 JSON 整理成人工可核对的摘要。

用法：
    .venv/bin/python - summarize_diff.py /tmp/tc-dryrun.json

只读本地 JSON，不连数据库、不触网。重点是三块：
1. 改判 / 删除：任何一条都必须人工对照公告后才能 apply；
2. 新增的非交易日（工作日）：这些是新增法定节假日，必须对照国务院公告；
3. 新增的交易日与周末：一般用于确认覆盖区间向前滚动。
"""
from __future__ import annotations

import json
import sys
from datetime import date


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python - summarize_diff.py <refresh-response.json>")
        return 2

    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)

    print(f"dry_run          : {data.get('dry_run')}")
    print(f"coverage         : {data.get('coverage_start')} -> {data.get('coverage_end')}")
    print(f"source           : {data.get('source')}")
    print(f"stats            : {data.get('stats')}")
    print(f"diff_truncated   : {data.get('diff_truncated')}")
    print(f"elapsed_ms       : {data.get('elapsed_ms')}")

    diff = data.get("diff") or []
    changed = [i for i in diff if i.get("old") is not None and i.get("old") != i.get("new")]
    deleted = [i for i in diff if i.get("old") is not None and i.get("new") is None]
    inserted = [i for i in diff if i.get("old") is None]

    print("\n--- 改判 / 删除（必须逐条人工确认）---")
    if not changed:
        print("无")
    for item in changed:
        print(f"  {item['trade_date']}: {item['old']} -> {item['new']}")

    print("\n--- 新增的非交易日（工作日），需对照节假日公告 ---")
    holidays = [
        i["trade_date"]
        for i in inserted
        if i.get("new") is False and date.fromisoformat(i["trade_date"]).weekday() < 5
    ]
    if not holidays:
        print("无（新增的非交易日全部落在周末）")
    else:
        by_month: dict[str, list[str]] = {}
        for ds in holidays:
            by_month.setdefault(ds[:7], []).append(ds)
        for month, days in sorted(by_month.items()):
            print(f"  {month}: {', '.join(days)}")

    print("\n--- 新增交易日（用于确认覆盖区间滚动）---")
    trading = [i["trade_date"] for i in inserted if i.get("new") is True]
    if not trading:
        print("无")
    else:
        print(f"  共 {len(trading)} 天：{trading[0]} .. {trading[-1]}")

    print("\n--- 新增周末（应全部为 false）---")
    weekend = [
        i["trade_date"]
        for i in inserted
        if i.get("new") is False and date.fromisoformat(i["trade_date"]).weekday() >= 5
    ]
    print(f"  {len(weekend)} 天")

    if deleted:
        print(f"\n警告：有 {len(deleted)} 条删除，diff 中 old 有值而 new 为空。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
