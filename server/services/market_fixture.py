"""
E2E 行情数据夹具 —— 用**固定快照**替换 akshare 的行情调用。

## 为什么需要它

E2E 要验证的是「页面 → store → request → API → 渲染」这一串**我们自己的**逻辑，
不是东财的行情接口今天通不通。但代码里所有行情数据都来自 akshare，于是：

1. **本机连不上东财**（2026-10-01 实测：根路径 404、API 路径连接被重置，非本项目 bug）
   → 行情缓存 `_spot_dict` 恒为空 → `/api/market/search` 返回 0 条、`realtime` 为 null
   → P3（行情 + 自选）五条用例一条都写不出来。
2. 就算网络通，行情**每分钟都在变**，断言只能写「大于 0」这种模糊条件，
   用例还会因为行情抖动而随机变红 —— 不可重复的用例等于没有用例。

夹具把最上游的数据来源换掉，**页面、store、request.ts、schemas、缓存逻辑全部保持真实**。

## 开关

    E2E_MARKET_FIXTURE=/绝对路径/market_snapshot.json

- **不设这个环境变量 = 完全现有行为，对生产零影响**（`install_if_configured()` 立刻 return，
  连 `import akshare` 都不会执行）。
- 设了但文件不存在/内容非法 = **启动时直接抛错**。这是刻意的：夹具配置错了必须当场炸，
  否则症状是「行情又空了」，和被夹的原始问题长得一模一样，排查要花掉一小时。

## 实现方式：替换 akshare 模块上的函数属性

代码里每一处调用都是函数内 `import akshare as ak` 然后 `ak.xxx(...)`，
而 Python 的 `import` 返回的是 `sys.modules` 里那个**同一个模块对象**。
所以把 `akshare.fund_etf_spot_em` 换成我们的实现，全项目所有调用点一起生效，
**不需要改任何一处业务代码**（这也是为什么不在 `finance_api_service.py` 里逐个函数加 if：
那里有 9 处调用、`portfolio_service.py` 还有 2 处，逐个改既易漏又难回滚）。

被替换的 8 个函数（全是行情/基金数据来源）：

| akshare 函数 | 调用点 | 用途 |
|---|---|---|
| `fund_etf_spot_em()` | `finance_api_service.py:1104` | 全量实时行情 → `_spot_dict`（search/spot/realtime 全靠它） |
| `fund_etf_hist_em(symbol, period, adjust)` | `:423` | 日/周/月 K 线 |
| `fund_etf_hist_min_em(symbol, period, adjust)` | `:915` | 分时 K 线 |
| `fund_overview_em(symbol)` | `:187`、`:221`、`:528` | 基金详情概览 |
| `fund_etf_fund_info_em()` | `:578` | 历史净值 |
| `fund_open_fund_info_em(symbol, indicator)` | `:205`、`portfolio_service.py:257` | 申购用的单位净值 |
| `fund_name_em()` | `:63` | 基金名称 → 代码映射 |
| `tool_trade_date_hist_sina()` | `trading_calendar.py:56` | 交易日历 —— PR #18 后是全项目唯一来源；`portfolio_service.py:466` 只是委托给它 |

## 快照的格式

快照用**英文键**（人写起来清楚），本模块负责翻译成 akshare 的**中文列名 DataFrame** ——
因为下游 `finance_api_service.py` 是按中文列名取值的（`row.get('最新价')` 等）。
把「列名映射」这件事集中在这一个文件里，快照本体就永远不用跟着 akshare 改。

生成/重建快照：`poetry run python docs/e2e/scripts/make_market_snapshot.py`

## ⚠️ 三个已知的坑（都是真实行为，不是夹具引入的）

1. **K 线有文件缓存**（`/tmp/etf_kline_cache/`，TTL 一天，见 `finance_api_service.py:16-17`）。
   夹具开着的时候改了快照，**K 线的改动当天不会生效** —— 缓存挡在前面。
   改完快照想让 K 线生效，先 `rm -rf /tmp/etf_kline_cache`。
   （不主动绕过这个缓存，是因为「缓存命中」本身也是被测逻辑的一部分。）
2. **K 线的浮点数在「缓存命中」时会变** —— `pd.read_json()` 会引进 1 ULP 误差。
   实测：清缓存后第一次请求 `high=3.82`，第二次（命中缓存）`high=3.8200000000000003`。
   所以**断言 K 线数值要用 `toBeCloseTo(x, 3)`，不要用 `toBe(x)`**。
   spot / search 走内存缓存，不受影响。
3. `_query_nav_history()` 调的是 `ak.fund_etf_fund_info_em()` —— 这个函数**不接 symbol**，
   一次返回全市场，然后 `.tail(limit)`。所以 `/api/market/detail/<任意代码>` 的
   `nav_history` 拿到的都是快照里**同一批**记录，跟请求的 fund_code 无关。
   这是既有缺陷（已登记在 docs/e2e/09），**夹具如实复现它，不掩盖**。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 环境变量名。/ E2E 侧约定：只有它被设成非空路径时才启用夹具。
ENV_VAR = "E2E_MARKET_FIXTURE"

# 记录「原始函数」，供 restore() 还原（单元测试要用到）。
# 只在这里维护一份清单 —— 被替换的函数名以 install_if_configured() 里的 `replacements` 为准，
# 不另开一个常量，免得两处漂移。
_ORIGINALS: dict[str, object] = {}
_INSTALLED = False


class MarketFixtureConfigError(RuntimeError):
    """快照文件缺失/非法。刻意抛出来，避免退化成「行情又空了」这种难查的症状。"""


# ==================================================================
# 快照读取
# ==================================================================

_SNAPSHOT: Optional[dict] = None


def load_snapshot(path: str) -> dict:
    """读快照 JSON，并做最小结构校验。结构不合法直接抛，不静默降级。"""
    p = Path(path)
    if not p.is_file():
        raise MarketFixtureConfigError(
            f"{ENV_VAR} 指向的快照文件不存在：{path}\n"
            f"→ 生成一份：poetry run python docs/e2e/scripts/make_market_snapshot.py"
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MarketFixtureConfigError(f"快照不是合法 JSON：{path}\n{path} → {e}") from e

    missing = [k for k in ("spot", "kline", "overview", "fund_info") if k not in data]
    if missing:
        raise MarketFixtureConfigError(
            f"快照缺少必需的段：{missing}（文件：{path}）。"
            f"用 docs/e2e/scripts/make_market_snapshot.py 重新生成。"
        )
    return data


def get_snapshot() -> dict:
    """取当前快照（install 时读入并缓存）。夹具没装时抛错。"""
    if _SNAPSHOT is None:
        raise MarketFixtureConfigError(
            "夹具没有安装（快照未加载）。请确认已调用 install_if_configured() 且设置了 "
            f"{ENV_VAR}。"
        )
    return _SNAPSHOT


# ==================================================================
# 快照 → akshare 形状的 DataFrame
# ==================================================================
#
# 这里的列名必须和 finance_api_service.py / portfolio_service.py 里 row.get('中文列名')
# 一一对应。列缺失不会报错（下游用 safe_float/safe_str 兜底成 0/''），但会静默变成空值，
# 所以宁可多给几列。

_SPOT_COLUMNS = [
    "代码", "名称", "最新价", "涨跌额", "涨跌幅", "昨收", "开盘价", "最高价", "最低价",
    "成交量", "成交额", "换手率", "振幅", "量比", "买一", "卖一", "外盘", "内盘", "委比",
    "主力净流入-净额", "主力净流入-净占比", "最新份额", "流通市值", "总市值",
    "数据日期", "更新时间",
]

_KLINE_COLUMNS = [
    "日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额",
    "振幅", "涨跌幅", "涨跌额", "换手率",
]


def _spot_frame(snapshot: dict) -> pd.DataFrame:
    rows = []
    for item in snapshot["spot"]:
        row = {c: None for c in _SPOT_COLUMNS}
        row.update(
            {
                "代码": item["code"],
                "名称": item["name"],
                "最新价": item["price"],
                "涨跌额": item.get("change"),
                "涨跌幅": item.get("change_pct"),
                "昨收": item.get("prev_close"),
                "开盘价": item.get("open"),
                "最高价": item.get("high"),
                "最低价": item.get("low"),
                "成交量": item.get("volume"),
                "成交额": item.get("amount"),
                "换手率": item.get("turnover_rate"),
                "振幅": item.get("amplitude"),
                # 下面这些字段快照里没有的话就是 None → 下游 safe_float 兜成 0。
                # 别嫌多：`_format_spot_data()` 会把它们全放进 spot dict，
                # 少映射一个，API 就会返回 0 —— 而 0 和"真实为 0"看起来一模一样。
                "量比": item.get("volume_ratio"),
                "买一": item.get("bid_price"),
                "卖一": item.get("ask_price"),
                "外盘": item.get("outer_vol"),
                "内盘": item.get("inner_vol"),
                "委比": item.get("order_ratio"),
                "主力净流入-净额": item.get("main_inflow"),
                "主力净流入-净占比": item.get("main_inflow_pct"),
                "最新份额": item.get("latest_shares"),
                "流通市值": item.get("float_mv"),
                "总市值": item.get("total_mv"),
                "数据日期": item.get("data_date", ""),
                "更新时间": item.get("update_time", ""),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=_SPOT_COLUMNS)


def _kline_frame(snapshot: dict, symbol: str, period: str) -> pd.DataFrame:
    """取某代码某周期的 K 线。快照里没有 → 返回空 DataFrame（与 akshare「查不到」一致）。"""
    series = snapshot.get("kline", {}).get(str(symbol), {})
    rows = series.get(period)
    if not rows:
        logger.warning(f"[market_fixture] 快照里没有 K 线：{symbol} {period}（返回空）")
        return pd.DataFrame(columns=_KLINE_COLUMNS)
    out = []
    for r in rows:
        out.append(
            {
                "日期": r["date"],
                "开盘": r["open"],
                "收盘": r["close"],
                "最高": r["high"],
                "最低": r["low"],
                "成交量": r["volume"],
                "成交额": r["amount"],
                "振幅": r.get("amplitude"),
                "涨跌幅": r.get("change_pct"),
                "涨跌额": r.get("change"),
                "换手率": r.get("turnover_rate"),
            }
        )
    return pd.DataFrame(out, columns=_KLINE_COLUMNS)


# ⚠️ 列名是照着 `finance_api_service.py` 里 `row.get(...)` 抄的，不是照 akshare 文档抄的：
# 规模那一列叫 **`净资产规模`**（`:230`、`:547`），叫成 `资产规模` 不会报错，
# 只会静默变成空串 —— 所以这里逐个核对过。
_OVERVIEW_COLUMNS = [
    "基金全称", "基金简称", "基金代码", "基金类型", "发行日期", "成立日期/规模",
    "净资产规模", "份额规模", "基金管理人", "基金托管人", "基金经理人",
    "成立来分红", "管理费率", "托管费率", "最高认购费率", "最高申购费率",
    "最高赎回费率", "业绩比较基准", "跟踪标的",
]


def _overview_frame(snapshot: dict, symbol: str) -> pd.DataFrame:
    item = snapshot.get("overview", {}).get(str(symbol))
    if not item:
        logger.warning(f"[market_fixture] 快照里没有概览：{symbol}（返回空）")
        return pd.DataFrame(columns=_OVERVIEW_COLUMNS)
    row = {c: None for c in _OVERVIEW_COLUMNS}
    row.update(
        {
            "基金全称": item.get("full_name", ""),
            "基金简称": item.get("short_name", ""),
            "基金代码": item.get("code", symbol),
            "基金类型": item.get("fund_type", ""),
            "发行日期": item.get("issue_date", ""),
            "成立日期/规模": item.get("establish_date", ""),
            "净资产规模": item.get("net_asset_scale", ""),
            "份额规模": item.get("share_scale", ""),
            "基金管理人": item.get("manager_company", ""),
            "基金托管人": item.get("custodian", ""),
            "基金经理人": item.get("fund_manager", ""),
            "成立来分红": item.get("dividend_history", ""),
            "管理费率": item.get("management_fee", ""),
            "托管费率": item.get("custody_fee", ""),
            "最高认购费率": item.get("subscription_fee", ""),
            "最高申购费率": item.get("purchase_fee", ""),
            "最高赎回费率": item.get("redemption_fee", ""),
            "业绩比较基准": item.get("benchmark", ""),
            "跟踪标的": item.get("tracking_target", ""),
        }
    )
    return pd.DataFrame([row], columns=_OVERVIEW_COLUMNS)


def _fund_info_frame(snapshot: dict) -> pd.DataFrame:
    """`fund_etf_fund_info_em()` 的形状：全市场净值表，不接 symbol。

    ⚠️ 如实复现既有缺陷：下游 `_query_nav_history()` 是 `.tail(limit)`，
    拿到的永远是快照里最后几条，与请求的 fund_code 无关。见模块 docstring。
    """
    rows = [
        {
            "净值日期": r["date"],
            "单位净值": r["nav"],
            "累计净值": r.get("accumulated_nav"),
            "日增长率": r.get("daily_growth"),
        }
        for r in snapshot.get("fund_info", [])
    ]
    return pd.DataFrame(rows, columns=["净值日期", "单位净值", "累计净值", "日增长率"])


def _open_fund_nav_frame(snapshot: dict, symbol: str) -> pd.DataFrame:
    """`fund_open_fund_info_em(symbol, indicator="单位净值走势")` 的形状。

    下游只取 `df.iloc[-1].get("单位净值")`，所以给到的顺序就是「最后一条 = 最新净值」。
    """
    rows = snapshot.get("open_fund_nav", {}).get(str(symbol))
    if not rows:
        logger.warning(f"[market_fixture] 快照里没有单位净值走势：{symbol}（返回空）")
        return pd.DataFrame(columns=["净值日期", "单位净值", "日增长率"])
    return pd.DataFrame(
        [
            {
                "净值日期": r["date"],
                "单位净值": r["nav"],
                "日增长率": r.get("daily_growth"),
            }
            for r in rows
        ],
        columns=["净值日期", "单位净值", "日增长率"],
    )


def _fund_name_frame(snapshot: dict) -> pd.DataFrame:
    """`fund_name_em()` 的形状：全量基金名录，由 spot + overview 拼出来。

    列**必须按 akshare 的顺序给全 5 列** —— 下游 `_collect_fund_candidates()`
    (`finance_api_service.py:94-99`) 是按**位置**取的：`row[0]`=代码、`row[2]`=简称、
    `row[3]`=基金类型，且会跳过「简称或类型里带『联接』」的条目。
    少给列不会报错，只会让名称→代码的解析静默失灵。
    """
    rows = []
    seen = set()
    for item in snapshot.get("spot", []):
        rows.append(
            {
                "基金代码": item["code"],
                "拼音缩写": item.get("pinyin", ""),
                "基金简称": item["name"],
                "基金类型": item.get("fund_type", "指数型-股票"),
                "拼音全称": "",
            }
        )
        seen.add(item["code"])
    for code, item in snapshot.get("overview", {}).items():
        if code in seen:
            continue
        rows.append(
            {
                "基金代码": code,
                "拼音缩写": item.get("pinyin", ""),
                "基金简称": item.get("short_name", ""),
                "基金类型": item.get("fund_type", ""),
                "拼音全称": "",
            }
        )
    return pd.DataFrame(rows, columns=["基金代码", "拼音缩写", "基金简称", "基金类型", "拼音全称"])


def _trade_date_frame(snapshot: dict) -> pd.DataFrame:
    """`tool_trade_date_hist_sina()` 的形状：trade_date 列。

    与 akshare 一致，返回**全部**交易日（下游 `_is_trading_day` 是逐行比对）。
    """
    dates = snapshot.get("trade_dates") or []
    return pd.DataFrame({"trade_date": dates}, columns=["trade_date"])


# ==================================================================
# 安装 / 还原
# ==================================================================


def install_if_configured() -> bool:
    """若设置了 `E2E_MARKET_FIXTURE`，把 akshare 的行情函数换掉。

    - 没设 → **立刻返回 False**，不 import akshare、不做任何事（生产路径零开销）。
    - 设了 → 读快照并替换；任何问题**抛异常**（故意失败关闭，见模块 docstring）。
    - 重复调用是幂等的（不会把「已经替换过的我们自己」当成原始函数存起来）。
    """
    global _SNAPSHOT, _INSTALLED

    path = os.getenv(ENV_VAR, "").strip()
    if not path:
        return False

    if _INSTALLED:
        logger.info(f"[market_fixture] 已安装，跳过重复安装（{ENV_VAR}={path}）")
        return True

    _SNAPSHOT = load_snapshot(path)

    import akshare as ak  # 只有确认要启用夹具时才 import（它很重，几秒）

    # ---------- 定义替换实现 ----------
    def fund_etf_spot_em(**kwargs):  # noqa: ANN003 - 与 akshare 签名兼容
        return _spot_frame(get_snapshot())

    def fund_etf_hist_em(symbol=None, period="daily", adjust="", **kwargs):  # noqa: ANN001
        # akshare 的 period 取值是 daily/weekly/monthly，与快照里的键一致
        return _kline_frame(get_snapshot(), symbol, period or "daily")

    def fund_etf_hist_min_em(symbol=None, period="1", adjust="", **kwargs):  # noqa: ANN001
        # 快照按 "min" 段放分时数据；没有就返回空（下游会走「数据为空」分支）
        return _kline_frame(get_snapshot(), symbol, "min")

    def fund_overview_em(symbol=None, **kwargs):  # noqa: ANN001
        return _overview_frame(get_snapshot(), symbol)

    def fund_etf_fund_info_em(**kwargs):
        return _fund_info_frame(get_snapshot())

    def fund_open_fund_info_em(symbol=None, indicator=None, **kwargs):  # noqa: ANN001
        return _open_fund_nav_frame(get_snapshot(), symbol)

    def fund_name_em(**kwargs):
        return _fund_name_frame(get_snapshot())

    def tool_trade_date_hist_sina(**kwargs):
        return _trade_date_frame(get_snapshot())

    replacements = {
        "fund_etf_spot_em": fund_etf_spot_em,
        "fund_etf_hist_em": fund_etf_hist_em,
        "fund_etf_hist_min_em": fund_etf_hist_min_em,
        "fund_overview_em": fund_overview_em,
        "fund_etf_fund_info_em": fund_etf_fund_info_em,
        "fund_open_fund_info_em": fund_open_fund_info_em,
        "fund_name_em": fund_name_em,
        "tool_trade_date_hist_sina": tool_trade_date_hist_sina,
    }

    # ---------- 替换 ----------
    for name, fn in replacements.items():
        if not hasattr(ak, name):
            # akshare 升级删了某个函数 —— 说出来，别静默少替换一个
            raise MarketFixtureConfigError(
                f"当前 akshare 版本没有 `{name}`（akshare.__version__={getattr(ak, '__version__', '?')}）。"
                f"夹具需要按新版本调整；在此之前不要开夹具，否则该链路会真的去打网络。"
            )
        _ORIGINALS[name] = getattr(ak, name)
        setattr(ak, name, fn)

    _INSTALLED = True
    logger.warning(
        "[market_fixture] ⚠️ 行情夹具已启用：akshare 的 %d 个行情函数已被固定快照替换"
        "（快照：%s）。这是测试模式，不要用于生产。",
        len(replacements),
        path,
    )
    return True


def restore() -> None:
    """还原原始 akshare 函数。主要给单元测试用；服务进程里不需要调。"""
    global _INSTALLED, _SNAPSHOT
    if not _INSTALLED:
        return
    import akshare as ak

    for name, fn in _ORIGINALS.items():
        setattr(ak, name, fn)
    _ORIGINALS.clear()
    _INSTALLED = False
    _SNAPSHOT = None


def is_installed() -> bool:
    return _INSTALLED
