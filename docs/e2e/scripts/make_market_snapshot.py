#!/usr/bin/env python3
"""
生成 E2E 行情夹具的快照文件（`docs/e2e/fixtures/market_snapshot.json`）。

配套模块：`server/services/market_fixture.py`（读这个文件，替换 akshare 的行情调用）。
格式说明见那个模块的 docstring，这里只说「怎么生成」。

## 两种模式

    # ① 合成数据（默认，**不需要网络**，可重复）
    poetry run python docs/e2e/scripts/make_market_snapshot.py

    # ② 抓真实行情（需要能连上东财；抓不到的段自动退回合成值并告警）
    poetry run python docs/e2e/scripts/make_market_snapshot.py --capture

**默认为什么是合成数据**：夹具的全部意义是「用例可重复」。真实行情每分钟在变，
拿它当基线的话，断言只能写成「price > 0」这种没信息量的条件，还会随机变红。
合成数据的数值是**手挑的、写死的**，可以让断言精确到小数位
（例如「510300 现价必须是 3.876」）。

`--capture` 的用途不是「平时都用它」，而是：**换一批基金代码**或**想知道真实字段长什么样**时，
抓一份回来对着改合成值。抓到的文件里 `_meta.source` 会标成 `akshare`，提醒你它不是可重复的基线。

## 改数据时的注意事项

- `spot` 里的 `code/name` 决定 `/api/market/search` 能搜到什么 ——
  搜索是**大小写不敏感的子串匹配**（`finance_api_service.py:629-631`）。
  现在的合成数据里，搜 "300" 只会命中 `510300`（名字含「300」），这是刻意的，
  好让「搜索结果条数」可以写成精确断言。
- `kline` 至少要给 `daily`，否则 ETF 详情页的 K 线图不渲染
  （`src/pages/etf-detail/index.vue:69` 的 canvas 在 `v-else` 分支里）。
  **`kline` 有文件缓存**（`/tmp/etf_kline_cache/`，TTL 一天），改完要
  `rm -rf /tmp/etf_kline_cache` 才生效。
- `trade_dates` 是「A 股交易日」清单，`portfolio_service.py:458`（`_is_trading_day`，
  PR #18 后委托给 `trading_calendar.py`）拿它判断今天能不能交易。
  **它必须包含「跑用例的那一天」**，否则所有申购都会被算成「下一交易日确认」。
  下面 `_synthetic_trade_dates()` 默认覆盖到 2026 年底，之后要重新生成。
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# 快照写到哪（相对本文件：docs/e2e/scripts/ → docs/e2e/fixtures/）
REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_PATH = REPO_ROOT / "docs" / "e2e" / "fixtures" / "market_snapshot.json"

# 合成数据里出现的基金。前两个是 ETF（走 fund_etf_spot_em），
# 后两个是场外基金（走 fund_open_fund_info_em / overview），
# 都取自前端白名单 `application/src/config/portfolio.ts:2-6`。
SPOT_CODES = ["510300", "510500", "159915"]
OVERVIEW_CODES = ["510300", "110020"]
OPEN_FUND_NAV_CODES = ["110020"]


def _warn(msg: str) -> None:
    print(f"[make_snapshot] {msg}", file=sys.stderr)


# ==================================================================
# ① 合成数据
# ==================================================================

_SPOT = [
    {
        "code": "510300",
        "name": "沪深300ETF",
        "price": 3.876,
        "change": 0.047,
        "change_pct": 1.23,
        "prev_close": 3.829,
        "open": 3.835,
        "high": 3.891,
        "low": 3.828,
        "volume": 125000000.0,
        "amount": 483150000.0,
        "turnover_rate": 2.15,
        "amplitude": 1.64,
        "volume_ratio": 1.08,
        "bid_price": 3.875,
        "ask_price": 3.877,
        "outer_vol": 68000000.0,
        "inner_vol": 57000000.0,
        "order_ratio": 12.5,
        "main_inflow": 38500000.0,
        "main_inflow_pct": 7.97,
        "latest_shares": 5820000000.0,
        "float_mv": 22550000000.0,
        "total_mv": 22560000000.0,
        "data_date": "2026-09-30",
        "update_time": "15:00:00",
    },
    {
        "code": "510500",
        "name": "中证500ETF",
        "price": 5.612,
        "change": -0.031,
        "change_pct": -0.55,
        "prev_close": 5.643,
        "open": 5.650,
        "high": 5.662,
        "low": 5.601,
        "volume": 43200000.0,
        "amount": 242800000.0,
        "turnover_rate": 1.32,
        "amplitude": 1.08,
        "volume_ratio": 0.94,
        "bid_price": 5.611,
        "ask_price": 5.613,
        "outer_vol": 20100000.0,
        "inner_vol": 23100000.0,
        "order_ratio": -8.2,
        "main_inflow": -15600000.0,
        "main_inflow_pct": -6.43,
        "latest_shares": 3240000000.0,
        "float_mv": 18170000000.0,
        "total_mv": 18180000000.0,
        "data_date": "2026-09-30",
        "update_time": "15:00:00",
    },
    {
        "code": "159915",
        "name": "创业板ETF",
        "price": 2.104,
        "change": 0.026,
        "change_pct": 1.25,
        "prev_close": 2.078,
        "open": 2.082,
        "high": 2.112,
        "low": 2.079,
        "volume": 88000000.0,
        "amount": 184900000.0,
        "turnover_rate": 3.41,
        "amplitude": 1.59,
        "volume_ratio": 1.21,
        "bid_price": 2.103,
        "ask_price": 2.105,
        "outer_vol": 47500000.0,
        "inner_vol": 40500000.0,
        "order_ratio": 6.8,
        "main_inflow": 21300000.0,
        "main_inflow_pct": 11.52,
        "latest_shares": 2210000000.0,
        "float_mv": 4650000000.0,
        "total_mv": 4652000000.0,
        "data_date": "2026-09-30",
        "update_time": "15:00:00",
    },
]

# 510300 的日 K：6 根，收盘价刻意单调上升，方便断言「最后一根收盘 = 3.876 = spot 里的现价」
_KLINE_510300_DAILY = [
    ("2026-09-23", 3.802, 3.811, 3.820, 3.795, 58200000.0),
    ("2026-09-24", 3.813, 3.805, 3.826, 3.799, 61300000.0),
    ("2026-09-25", 3.806, 3.822, 3.831, 3.803, 55100000.0),
    ("2026-09-28", 3.824, 3.841, 3.850, 3.819, 72400000.0),
    ("2026-09-29", 3.843, 3.829, 3.848, 3.824, 66800000.0),
    ("2026-09-30", 3.829, 3.876, 3.891, 3.828, 125000000.0),
]

_OVERVIEW = {
    "510300": {
        "code": "510300",
        "full_name": "华泰柏瑞沪深300交易型开放式指数证券投资基金",
        "short_name": "沪深300ETF",
        "fund_type": "指数型-股票",
        "issue_date": "2012-04-05",
        "establish_date": "2012-05-04",
        "net_asset_scale": "2255.60亿元",
        "share_scale": "582.00亿份",
        "manager_company": "华泰柏瑞基金管理有限公司",
        "custodian": "中国银行股份有限公司",
        "fund_manager": "柳军",
        "dividend_history": "每份累计0.42元",
        "management_fee": "0.50%",
        "custody_fee": "0.10%",
        "subscription_fee": "---",
        "purchase_fee": "---",
        "redemption_fee": "---",
        "benchmark": "沪深300指数收益率",
        "tracking_target": "沪深300指数",
    },
    "110020": {
        "code": "110020",
        "full_name": "易方达沪深300交易型开放式指数发起式证券投资基金联接基金A类",
        "short_name": "易方达沪深300ETF联接A",
        "fund_type": "指数型-股票",
        "issue_date": "2009-07-16",
        "establish_date": "2009-08-26",
        "net_asset_scale": "128.40亿元",
        "share_scale": "78.20亿份",
        "manager_company": "易方达基金管理有限公司",
        "custodian": "中国建设银行股份有限公司",
        "fund_manager": "余海燕",
        "dividend_history": "每份累计0.35元",
        "management_fee": "0.15%",
        "custody_fee": "0.05%",
        "subscription_fee": "0.12%",
        "purchase_fee": "0.12%",
        "redemption_fee": "0.50%",
        "benchmark": "沪深300指数收益率×95%+活期存款利率(税后)×5%",
        "tracking_target": "沪深300指数",
    },
}

# `fund_etf_fund_info_em()` 是全市场净值表（不接 symbol，见 market_fixture.py 的说明）。
# 下游 `.tail(limit)` 永远取最后几条，所以这里就放 5 条、顺序即「日期递增」。
_FUND_INFO = [
    {"date": "2026-09-24", "nav": 1.7231, "accumulated_nav": 2.4180, "daily_growth": -0.42},
    {"date": "2026-09-25", "nav": 1.7302, "accumulated_nav": 2.4251, "daily_growth": 0.41},
    {"date": "2026-09-28", "nav": 1.7421, "accumulated_nav": 2.4370, "daily_growth": 0.69},
    {"date": "2026-09-29", "nav": 1.7374, "accumulated_nav": 2.4323, "daily_growth": -0.27},
    {"date": "2026-09-30", "nav": 1.7588, "accumulated_nav": 2.4537, "daily_growth": 1.23},
]

# `fund_open_fund_info_em(symbol, "单位净值走势")`：给申购用，下游只取 `iloc[-1]`
_OPEN_FUND_NAV = {
    "110020": [
        {"date": "2026-09-28", "nav": 1.7582, "daily_growth": 0.69},
        {"date": "2026-09-29", "nav": 1.7535, "daily_growth": -0.27},
        {"date": "2026-09-30", "nav": 1.7749, "daily_growth": 1.22},
    ]
}


def _synthetic_trade_dates(start: date, end: date) -> list[str]:
    """工作日清单（不含法定节假日）。够用了：夹具是给「是不是交易日」这个判断用的，
    精确到真日历反而要在没有网络的机器上维护一份节假日表。

    ⚠️ 清单**必须覆盖跑用例的那一天**，否则申购用例会被算成「下一交易日确认」。
    """
    out = []
    d = start
    while d <= end:
        # 2026 国庆假期（10-01 ~ 10-08），照实排除，别让夹具假装国庆能交易
        if d.weekday() < 5 and not (date(2026, 10, 1) <= d <= date(2026, 10, 8)):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def build_synthetic() -> dict:
    daily = [
        {
            "date": d,
            "open": o,
            "close": c,
            "high": h,
            "low": lo,
            "volume": v,
            "amount": round(v * (h + lo) / 2, 2),
            "amplitude": round((h - lo) / lo * 100, 2),
            "change_pct": 0.0,
            "change": 0.0,
            "turnover_rate": 0.0,
        }
        for (d, o, c, h, lo, v) in _KLINE_510300_DAILY
    ]
    # 涨跌额/涨跌幅按前一根收盘算，别写死 —— 看图的人会核对
    for i, bar in enumerate(daily):
        prev = daily[i - 1]["close"] if i > 0 else bar["open"]
        bar["change"] = round(bar["close"] - prev, 3)
        bar["change_pct"] = round((bar["close"] - prev) / prev * 100, 2)

    return {
        "_meta": {
            "source": "synthetic",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "note": "合成数据，数值写死以保证用例可重复。用法见 docs/e2e/09-P3阻塞与数据夹具建议.md。",
        },
        "spot": _SPOT,
        "kline": {
            "510300": {
                "daily": daily,
                # weekly/monthly 先给空：页面默认取 daily，用到再按需补
                "weekly": [],
                "monthly": [],
                "min": [],
            }
        },
        "overview": _OVERVIEW,
        "fund_info": _FUND_INFO,
        "open_fund_nav": _OPEN_FUND_NAV,
        "trade_dates": _synthetic_trade_dates(date(2026, 1, 1), date(2026, 12, 31)),
    }


# ==================================================================
# ② 抓真实行情（可选）
# ==================================================================


def build_captured() -> dict:
    """尽量从 akshare 抓；每一段单独 try，抓不到就退回合成值并告警。

    刻意**不做成「抓失败就整体报错」**：这台机器本来就常常连不上东财，
    因为一个次要的段（比如交易日历）抓不到就整份不生成，没有意义。
    但 `_meta` 会逐段记录哪些是真的、哪些是合成的，不会让人误以为全是真数据。
    """
    import akshare as ak

    snapshot = build_synthetic()
    snapshot["_meta"]["source"] = "akshare"
    snapshot["_meta"]["captured"] = {}
    snapshot["_meta"]["fallback"] = []

    # --- 实时行情 ---
    try:
        df = ak.fund_etf_spot_em()
        have = df[df["代码"].astype(str).isin(SPOT_CODES)]
        if have.empty:
            raise ValueError(f"返回 {len(df)} 行，但没有 {SPOT_CODES}")
        rows = []
        for _, r in have.iterrows():
            rows.append(
                {
                    "code": str(r["代码"]),
                    "name": str(r["名称"]),
                    "price": float(r["最新价"]),
                    "change": float(r["涨跌额"]),
                    "change_pct": float(r["涨跌幅"]),
                    "prev_close": float(r["昨收"]),
                    "open": float(r["开盘价"]),
                    "high": float(r["最高价"]),
                    "low": float(r["最低价"]),
                    "volume": float(r["成交量"]),
                    "amount": float(r["成交额"]),
                    "turnover_rate": float(r["换手率"]),
                    "amplitude": float(r["振幅"]),
                    "volume_ratio": float(r["量比"]),
                    "data_date": datetime.now().strftime("%Y-%m-%d"),
                    "update_time": datetime.now().strftime("%H:%M:%S"),
                }
            )
        snapshot["spot"] = rows
        snapshot["_meta"]["captured"]["spot"] = [r["code"] for r in rows]
    except Exception as e:  # noqa: BLE001 - 抓数据失败的原因五花八门，一律退回合成值
        _warn(f"spot 抓取失败，退回合成值：{e}")
        snapshot["_meta"]["fallback"].append("spot")

    # --- 日 K ---
    try:
        df = ak.fund_etf_hist_em(symbol="510300", period="daily", adjust="")
        bars = []
        for _, r in df.tail(30).iterrows():
            bars.append(
                {
                    "date": str(r["日期"]),
                    "open": float(r["开盘"]),
                    "close": float(r["收盘"]),
                    "high": float(r["最高"]),
                    "low": float(r["最低"]),
                    "volume": float(r["成交量"]),
                    "amount": float(r["成交额"]),
                    "amplitude": float(r["振幅"]),
                    "change_pct": float(r["涨跌幅"]),
                    "change": float(r["涨跌额"]),
                    "turnover_rate": float(r["换手率"]),
                }
            )
        snapshot["kline"]["510300"]["daily"] = bars
        snapshot["_meta"]["captured"]["kline_510300_daily"] = len(bars)
    except Exception as e:  # noqa: BLE001
        _warn(f"kline 抓取失败，退回合成值：{e}")
        snapshot["_meta"]["fallback"].append("kline")

    # --- 概览 ---
    for code in OVERVIEW_CODES:
        try:
            df = ak.fund_overview_em(symbol=code)
            snapshot["overview"][code] = {
                "code": code,
                "full_name": str(df.iloc[0].get("基金全称", "")),
                "short_name": str(df.iloc[0].get("基金简称", "")),
                "fund_type": str(df.iloc[0].get("基金类型", "")),
                "establish_date": str(df.iloc[0].get("成立日期/规模", "")),
                # 列名是 `净资产规模`，不是 `资产规模` —— 下游 finance_api_service.py:547 就是这么取的
                "net_asset_scale": str(df.iloc[0].get("净资产规模", "")),
                "share_scale": str(df.iloc[0].get("份额规模", "")),
                "manager_company": str(df.iloc[0].get("基金管理人", "")),
                "custodian": str(df.iloc[0].get("基金托管人", "")),
                "fund_manager": str(df.iloc[0].get("基金经理人", "")),
                "management_fee": str(df.iloc[0].get("管理费率", "")),
                "custody_fee": str(df.iloc[0].get("托管费率", "")),
                "benchmark": str(df.iloc[0].get("业绩比较基准", "")),
                "tracking_target": str(df.iloc[0].get("跟踪标的", "")),
            }
            snapshot["_meta"]["captured"].setdefault("overview", []).append(code)
        except Exception as e:  # noqa: BLE001
            _warn(f"overview[{code}] 抓取失败，保留合成值：{e}")
            snapshot["_meta"]["fallback"].append(f"overview.{code}")

    # --- 交易日历 ---
    try:
        df = ak.tool_trade_date_hist_sina()
        dates = [str(d) for d in df["trade_date"].tolist()]
        snapshot["trade_dates"] = dates
        snapshot["_meta"]["captured"]["trade_dates"] = len(dates)
    except Exception as e:  # noqa: BLE001
        _warn(f"trade_dates 抓取失败，退回合成值：{e}")
        snapshot["_meta"]["fallback"].append("trade_dates")

    return snapshot


# ==================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture",
        action="store_true",
        help="尝试从 akshare 抓真实数据（需联网），抓不到的段退回合成值",
    )
    parser.add_argument("--out", default=str(OUT_PATH), help=f"输出路径（默认 {OUT_PATH}）")
    args = parser.parse_args()

    snapshot = build_captured() if args.capture else build_synthetic()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    meta = snapshot["_meta"]
    print(f"✅ 已写出 {out}", file=sys.stderr)
    print(
        f"   source={meta['source']}  spot={len(snapshot['spot'])} 只  "
        f"kline={len(snapshot['kline'])} 个代码  "
        f"trade_dates={len(snapshot['trade_dates'])} 天（{snapshot['trade_dates'][0]} ~ "
        f"{snapshot['trade_dates'][-1]}）",
        file=sys.stderr,
    )
    if meta.get("fallback"):
        _warn(f"以下段落抓取失败、用的是合成值：{meta['fallback']}")

    # 提醒：K 线有文件缓存，换了快照但不删缓存 = 改了不生效（这个坑很费时间，说大声点）
    print(
        "   提醒：K 线走文件缓存 /tmp/etf_kline_cache/（TTL 一天）。"
        "改了快照里的 kline 想立刻生效，先 rm -rf /tmp/etf_kline_cache",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
