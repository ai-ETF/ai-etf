"""东财全市场场外净值批量接口 —— `batch` 能力。

端点：`https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx`
域名：`fund.eastmoney.com`

## 用途

一次请求拿全市场约 2.4 万行「最新已公布日 + 前一日」净值，在**本地**按调用方给的
代码筛选。源不做白名单过滤（设计文档 G5：筛选属于缓存服务的职责）。

## 实测（2026-10-18）

- 4.5 MB / 4.1s（同日另一次采样 28s+）→ `timeout` 单独设为 60s，
  不能沿用设计默认的 15s；
- `var db={datas:[21列×24252], showday:["2026-10-16","2026-10-15"]}`；
- 行内下标：`[0]`代码、`[3]/[4]` T 日单位/累计、`[5]/[6]` T-1 日单位/累计、
  `[8]` 日增长率。

## ⚠️ 坑：列名里带日期

akshare 的 DataFrame 列名是 `2026-10-13-单位净值` 这种**随日期变化**的列名。
根本原因在这里：日期来自响应里的 `showday`，不在每一行里。所以本实现**按
`showday[0]` / `showday[1]` 拼出「列名」再取值，绝不直接把下标写死成某一天**。
`showday` 的「当日」= **最新已公布日**，不是日历今天。
"""
import json
import re
from datetime import date, datetime
from typing import Any, Optional

from server.sources.http import HttpSource
from server.sources.models import (
    CAP_BATCH,
    FailureKind,
    NavPoint,
    SourceError,
    SourceMeta,
    to_decimal,
)

URL = "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"

PARAMS = {
    "t": "1",
    "lx": "1",
    "letter": "",
    "gsid": "",
    "text": "",
    "sort": "zdf,desc",
    "page": "1,50000",
    "dt": "1580914040623",
    "atfc": "",
    "onlySale": "0",
}

# 行内下标（21 列）。日期不在行内，见模块 docstring。
COL_CODE = 0
COL_T_UNIT = 3
COL_T_ACC = 4
COL_PREV_UNIT = 5
COL_PREV_ACC = 6
COL_GROWTH = 8

# 全市场正常约 2.4 万行；低于这个量级说明响应被截断，按 SCHEMA_DRIFT 处理，
# 防止「静默返回 1 行」把当日批量更新写坏。
MIN_ROWS = 1000


def _extract_js_value(text: str, key: str) -> Optional[str]:
    """从 JS 对象字面量里按 key 取出**括号配对**的值（支持嵌套数组/字符串）。

    不用正则 `\\[.*?\\]`：`datas` 里每行都是数组，非贪婪正则会提前收尾。
    """
    match = re.search(rf"\b{re.escape(key)}\s*:\s*", text)
    if match is None:
        return None
    start = match.end()
    if start >= len(text) or text[start] not in "[{":
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _loads(raw: str, source: str, what: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise SourceError(
            source, FailureKind.PARSE_ERROR, f"{what} 解析失败: {exc}"
        ) from exc


def _parse_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def parse_batch_payload(
    text: str, codes: set[str], source: str
) -> dict[str, list[NavPoint]]:
    """解析批量响应，只返回请求的代码。

    返回 `{fund_code: [T 日点, T-1 日点]}`；某代码在批量窗口里没有有效净值时不出现在
    结果里（这是「源没有覆盖」，不是失败）。整个响应为空 / 结构漂移才抛错。
    """
    datas_raw = _extract_js_value(text, "datas")
    showday_raw = _extract_js_value(text, "showday")
    if datas_raw is None or showday_raw is None:
        raise SourceError(
            source,
            FailureKind.SCHEMA_DRIFT,
            "批量响应缺少 datas 或 showday 变量，上游格式可能已变更",
        )

    rows = _loads(datas_raw, source, "datas")
    showday = _loads(showday_raw, source, "showday")
    if not isinstance(rows, list) or not isinstance(showday, list) or len(showday) < 2:
        raise SourceError(source, FailureKind.SCHEMA_DRIFT, "datas/showday 结构异常")
    if not rows:
        raise SourceError(source, FailureKind.EMPTY_PAYLOAD, "批量响应 datas 为空")
    if len(rows) < MIN_ROWS:
        raise SourceError(
            source,
            FailureKind.SCHEMA_DRIFT,
            f"批量响应只有 {len(rows)} 行，明显少于正常量级（{MIN_ROWS}+），疑似被截断",
        )

    today = _parse_date(showday[0])
    previous = _parse_date(showday[1])
    if today is None or previous is None:
        raise SourceError(
            source, FailureKind.SCHEMA_DRIFT, f"showday 日期非法: {showday!r}"
        )

    result: dict[str, list[NavPoint]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) <= COL_GROWTH:
            continue
        fund_code = str(row[COL_CODE]).strip()
        if fund_code not in codes:
            continue

        points: list[NavPoint] = []
        current = NavPoint(
            fund_code=fund_code,
            nav_date=today,
            unit_nav=to_decimal(row[COL_T_UNIT]),
            accumulated_nav=to_decimal(row[COL_T_ACC]),
            daily_growth=to_decimal(row[COL_GROWTH]),
            source=source,
        )
        if current.unit_nav is not None or current.accumulated_nav is not None:
            points.append(current)

        older = NavPoint(
            fund_code=fund_code,
            nav_date=previous,
            unit_nav=to_decimal(row[COL_PREV_UNIT]),
            accumulated_nav=to_decimal(row[COL_PREV_ACC]),
            # 行内的日增长率只属于 T 日；T-1 日不臆造。
            daily_growth=None,
            source=source,
        )
        if older.unit_nav is not None or older.accumulated_nav is not None:
            points.append(older)

        if points:
            result[fund_code] = points

    return result


class EmFundJjjzSource(HttpSource):
    meta = SourceMeta(
        name="em_fund_jjjz",
        domain="fund.eastmoney.com",
        capabilities=frozenset({CAP_BATCH}),
        priority=100,
        timeout=60.0,  # 实测 4.1s ~ 28s+，默认 15s 不够
        description="东财全市场场外净值（当日+前日），1 请求 2.4 万行，响应可达 4.5MB",
    )

    def fetch_latest_batch(self, codes: list[str]) -> dict[str, list[NavPoint]]:
        normalized = {str(code).strip() for code in codes if str(code).strip()}
        if not normalized:
            raise SourceError(
                self.meta.name, FailureKind.INVALID_REQUEST, "codes 不能为空"
            )
        text = self._get_text(URL, params=PARAMS)
        return parse_batch_payload(text, normalized, self.meta.name)
