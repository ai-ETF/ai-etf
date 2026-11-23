#!/usr/bin/env python3
"""交易日历只读核验脚本（不触网、不写库）。

在部署目录执行（需要 .env 与项目依赖）：

    cd /root/ai-etf
    .venv/bin/python - < scripts/verify_calendar.py
    .venv/bin/python - --from 2027-01-01 --to 2027-03-01 < scripts/verify_calendar.py

默认抽查「下个自然月」。脚本只做机械性检查（断档、周末开市、行数/状态一致性），
并把区间内的非交易日按连续段列出；这些段是否与国务院/交易所公告一致，必须人工判定。
退出码：机械性检查失败为 1，否则为 0（即使仍需人工判定）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# 只加载，不读取、不打印内容。
load_dotenv(Path.cwd() / ".env")

from server.storage.supabase_client import get_supabase  # noqa: E402

BEIJING_TZ = timezone(timedelta(hours=8))
PAGE_SIZE = 1000


def _parse_date(value) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(str(value)[:10])


def _default_range(today: date) -> tuple[date, date]:
    first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    return first, (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _fetch_rows(client) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        batch = (
            client.table("trading_calendar")
            .select("trade_date,is_trading_day,source")
            .order("trade_date")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _group_ranges(days: list[date]) -> list[list[date]]:
    groups: list[list[date]] = []
    for d in days:
        if groups and d == groups[-1][-1] + timedelta(days=1):
            groups[-1].append(d)
        else:
            groups.append([d])
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description="交易日历只读核验")
    parser.add_argument("--from", dest="range_start", help="抽查起点 YYYY-MM-DD（默认下月 1 日）")
    parser.add_argument("--to", dest="range_end", help="抽查终点 YYYY-MM-DD，含（默认下月最后一天）")
    args = parser.parse_args()

    today = datetime.now(BEIJING_TZ).date()
    default_start, default_end = _default_range(today)
    range_start = date.fromisoformat(args.range_start) if args.range_start else default_start
    range_end = date.fromisoformat(args.range_end) if args.range_end else default_end
    if range_start > range_end:
        print(f"[FAIL] 抽查区间非法：{range_start} > {range_end}")
        return 1

    client = get_supabase()
    problems: list[str] = []
    warnings: list[str] = []

    state_rows = (
        client.table("trading_calendar_state").select("*").eq("id", True).limit(1).execute().data
        or []
    )
    state = state_rows[0] if state_rows else None

    rows = _fetch_rows(client)
    parsed = {_parse_date(r["trade_date"]): bool(r["is_trading_day"]) for r in rows}
    parsed.pop(None, None)
    sources = sorted({r.get("source") for r in rows if r.get("source")})

    print("=== 1. 状态（trading_calendar_state）===")
    if state is None:
        problems.append("trading_calendar_state 为空（尚未成功刷新过）")
        print("  [FAIL] state 表没有行")
    else:
        coverage_start = _parse_date(state.get("coverage_start"))
        coverage_end = _parse_date(state.get("coverage_end"))
        success_at = state.get("last_success_at")
        print(f"  coverage_start : {coverage_start}")
        print(f"  coverage_end   : {coverage_end}")
        print(f"  last_success_at: {success_at}")
        print(f"  last_error     : {state.get('last_error') or '无'}")
        if coverage_start is None or coverage_end is None:
            problems.append("state 缺少覆盖区间")
        elif coverage_start > coverage_end:
            problems.append(f"覆盖区间非法：{coverage_start} > {coverage_end}")

    print("=== 2. 规模与完整性（trading_calendar）===")
    if not parsed:
        problems.append("trading_calendar 没有数据")
        print("  [FAIL] 表为空")
    else:
        first, last = min(parsed), max(parsed)
        trading = sum(1 for v in parsed.values() if v)
        expected = (last - first).days + 1
        print(f"  总行数          : {len(parsed)}")
        print(f"  交易日/非交易日 : {trading} / {len(parsed) - trading}")
        print(f"  日期范围        : {first} .. {last}")
        print(f"  预期行数        : {expected}")

        if expected != len(parsed):
            problems.append(f"日期断档：应有 {expected} 行，实际 {len(parsed)} 行")
            print("  [FAIL] 存在日期断档")
        else:
            print("  [OK] 覆盖区间内每个自然日都有且仅有一行")

        if state is not None and state.get("coverage_start") and state.get("coverage_end"):
            if (_parse_date(state["coverage_start"]), _parse_date(state["coverage_end"])) != (first, last):
                problems.append("state 覆盖区间与表内 min/max 不一致")
                print("  [FAIL] state 覆盖区间与表内 min/max 不一致")
            else:
                print("  [OK] state 覆盖区间与表内 min/max 一致")

        weekend_trading = [d for d, v in parsed.items() if d.weekday() >= 5 and v]
        if weekend_trading:
            problems.append(f"{len(weekend_trading)} 个周末被标记为交易日")
            print(f"  [FAIL] 周末开市 {len(weekend_trading)} 天，例如 {weekend_trading[:5]}")
        else:
            print("  [OK] 没有任何周六/周日被标记为交易日")

        print(f"  source 取值     : {', '.join(sources) or '(空)'}")

        if last < today + timedelta(days=45):
            warnings.append(f"coverage_end={last} 距今天不足 45 天")
        if last < range_end:
            warnings.append(f"coverage_end={last} 早于抽查终点 {range_end}，区间外无法核验")
        success = _parse_date(state.get("last_success_at")) if state else None
        if success and (today - success).days > 400:
            warnings.append(f"last_success_at 距今 {(today - success).days} 天，可能漏做年度拉取")

    print(f"=== 3. 抽查区间 {range_start} .. {range_end} ===")
    in_range = {d: v for d, v in parsed.items() if range_start <= d <= range_end}
    if not in_range:
        problems.append(f"抽查区间 {range_start}..{range_end} 没有任何数据")
        print("  [FAIL] 区间内无数据")
    else:
        non_trading = sorted(d for d, v in in_range.items() if not v)
        if not non_trading:
            print("  非交易日: 无（连续交易，需确认区间内确实没有节假日）")
        for group in _group_ranges(non_trading):
            span = f"{group[0]} .. {group[-1]}" if len(group) > 1 else f"{group[0]}"
            weekdays = [d for d in group if d.weekday() < 5]
            if not weekdays:
                note = "全为周末"
            else:
                detail = ", ".join(f"{d}({d.strftime('%a')})" for d in weekdays)
                note = f"含工作日 {detail} → 需对照公告"
            print(f"  {span}（{len(group)} 天）：{note}")

        weekend_trading_in_range = [
            d for d, v in in_range.items() if d.weekday() >= 5 and v
        ]
        if weekend_trading_in_range:
            problems.append("抽查区间内存在周末开市")
            print(f"  [FAIL] 区间内周末开市：{weekend_trading_in_range}")

    print("=== 4. 提示 ===")
    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")
    else:
        print("  [OK] 覆盖区间与最近成功时间均在正常范围")

    print("=== 5. 结论 ===")
    if problems:
        print("  机械性检查: 未通过")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("  机械性检查: 通过")
    print("  人工判定  : 未完成 —— 请对照国务院节假日安排/交易所公告核对第 3 节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
