import json
import logging
import os
import re
import time
from typing import Optional, Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

# K线文件缓存目录
KLINE_CACHE_DIR = "/tmp/etf_kline_cache"
KLINE_CACHE_TTL = 86400  # 一天过期
KLINE_SOURCE = "sina"  # 当前行情数据源标识（用于缓存文件名隔离，换源时同步修改）

# 判断是否交易时段（交易日历的唯一来源；A 股交易日 + 9:30-15:00，识别法定节假日）
from server.services.trading_calendar import beijing_now, is_trading_time


class FinanceApiService:
    """场外基金事实数据查询（净值 / 费率 / 规模 / 详情）。

    产品只做场外基金：场内 ETF 的实时行情（30 秒轮询 + 内存哈希表）与由它派生的
    榜单/筛选/分类/资金流已整体下线（2026-10-26）。目录外代码一律 `FundNotSupported`。
    """

    # 详情接口默认返回的净值条数：约 2 年交易日，覆盖前端「近1月~近2年」走势区间
    DEFAULT_NAV_LIMIT = 500
    MAX_NAV_LIMIT = 5000

    def __init__(self, fund_nav=None, fund_meta=None):
        # 依赖注入：测试可完全绕开 DB / 网络（接入方案 §4.10）
        self._fund_nav = fund_nav
        self._fund_meta = fund_meta

    @property
    def fund_nav(self):
        if self._fund_nav is None:
            from server.services.fund_nav_service import FundNavService

            self._fund_nav = FundNavService()
        return self._fund_nav

    @property
    def fund_meta(self):
        if self._fund_meta is None:
            from server.services.fund_meta_service import FundMetaService

            self._fund_meta = FundMetaService()
        return self._fund_meta

    # ==================== 搜索与名称解析（只在支持目录内） ====================

    def search_catalog(self, keyword: str, limit: int = 10) -> List[Dict]:
        """按代码或名称搜索支持目录内的场外基金。

        产品只做场外基金：场内 ETF 不在目录内，**搜代码不会有任何结果**；
        搜名称（如「红利」「沪深300」）返回名称/代码匹配的场外基金。
        返回项含最新净值与日涨幅（来自 DB），不含实时行情。
        """
        metas = self.fund_meta.search(keyword, limit=limit)
        if not metas:
            return []

        codes = [m.fund_code for m in metas]
        latest = self.fund_nav.get_latest_batch(codes)
        results = []
        for meta in metas:
            nav = latest.get(meta.fund_code)
            results.append({
                "code": meta.fund_code,
                "name": meta.fund_name,
                "fund_type": meta.ftype,
                # 契约里规模是字符串（沿用上游「12.34亿元」式的历史口径）
                "net_asset_scale": (
                    str(meta.net_asset_scale) if meta.net_asset_scale is not None else None
                ),
                "nav": self._safe_float(nav.unit_nav) if nav else None,
                "nav_date": nav.nav_date.isoformat() if nav else None,
            })
        logger.info(f"搜索目录: keyword={keyword}, 命中 {len(results)} 条")
        return results

    def _resolve_fund_code(self, fund_name: str) -> Optional[str]:
        """基金名称 → 目录内基金代码（模糊匹配，取分数最高者）。

        只在 `fund_catalog` 内解析：场外联接基金的名称通常带「联接」，
        与场内 ETF 的前缀高度重叠，靠上游全量列表反而更容易挑错。
        """
        query = fund_name.replace("ETF", "").replace("etf", "").strip()
        candidates = self.fund_meta.search(query or fund_name, limit=20)
        if not candidates:
            logger.warning(f"目录内没有匹配的基金: {fund_name}")
            return None

        def _key(meta):
            score, is_exact = self._score_match(query, meta.fund_name)
            return (is_exact, score)

        best = max(candidates, key=_key)
        logger.debug(f"模糊匹配: {fund_name} -> {best.fund_code}")
        return best.fund_code

    def _ensure_in_catalog(self, fund_code: str) -> None:
        """目录外代码直接抛 `FundNotSupported`（API 映射 404），不触网上游。"""
        from server.services.fund_nav_service import FundNotSupported

        if not self.fund_nav.in_catalog(fund_code):
            raise FundNotSupported(fund_code)

    @staticmethod
    def _score_match(query: str, fund_name: str) -> tuple[float, bool]:
        """计算查询与基金名的匹配分数，返回 (score, is_exact)"""
        name_clean = fund_name.replace("ETF", "").replace("etf", "").strip()

        if query in name_clean:
            return 1.0 + len(query) / max(len(name_clean), 1), True
        if name_clean in query:
            return 1.0 + len(name_clean) / max(len(query), 1), True

        common = sum(1 for c in query if c in name_clean)
        score = common / max(len(query), len(name_clean), 1)
        return score, False

    def query(self, question: str) -> Optional[Dict]:
        """
        从问题中提取基金名称，查询事实数据。
        返回结构化 dict 或 None（无法识别/查询失败）。
        """
        fund_name = self._extract_fund_name(question)
        if not fund_name:
            return None

        fund_code = self._resolve_fund_code(fund_name)
        if not fund_code:
            logger.warning(f"无法识别基金: {fund_name}")
            return None

        # 判断用户想查什么（2026-10-26：实时行情分支已随 30s 轮询下线，
        # 「涨跌幅/行情」类问题落在净值分支，用最新净值回答）
        data = {}

        if any(kw in question for kw in ("费率", "管理费", "托管费", "申购费", "赎回费", "费用")):
            data.update(self._query_fees(fund_code))
        if any(kw in question for kw in ("净值", "多少钱", "价格", "涨跌幅", "涨幅", "跌幅", "行情", "涨多少", "跌多少")):
            data.update(self._query_nav(fund_code))
        if any(kw in question for kw in ("规模", "多大")):
            data.update(self._query_overview(fund_code))

        # 如果没有指定具体数据，返回全部
        if not data:
            data = self._query_overview(fund_code)

        if data:
            data["fund_code"] = fund_code
            data["fund_name"] = fund_name
            data["source"] = "api"
        return data if data else None

    def _extract_fund_name(self, question: str) -> Optional[str]:
        """从问题中提取基金名称片段"""
        # 去掉常见问句尾部
        q = re.sub(r"(的|是多少|费率|管理费|托管费|净值|规模|怎么样|是什么|多少|请问|有没有)", "", question)
        q = q.strip()

        # 从问题中提取可能的基金名（连续中文+ETF）
        match = re.search(r"([一-龥]+(?:ETF|etf)?)", q)
        if match and len(match.group(1)) >= 4:
            return match.group(1)
        return None

    def _query_fees(self, fund_code: str) -> Dict:
        """查询基金费率"""
        try:
            import akshare as ak
            df = ak.fund_overview_em(symbol=fund_code)
            if df.empty:
                return {}
            row = df.iloc[0]
            return {
                "management_fee": self._clean_rate(str(row.get("管理费率", ""))),
                "custody_fee": self._clean_rate(str(row.get("托管费率", ""))),
                "subscription_fee": self._clean_rate(str(row.get("最高认购费率", ""))),
                "redemption_fee": self._clean_rate(str(row.get("最高赎回费率", ""))),
            }
        except Exception as e:
            logger.error(f"查询费率失败 ({fund_code}): {e}")
            return {}

    def _query_nav(self, fund_code: str) -> Dict:
        """查询基金最新净值，只读 DB（`FundNavService.get_latest`）。

        目录外代码不查、也不回退上游（2026-10-26 决策）：回退会让「搜不到、买不了」
        的场内 ETF 在问答里「看得见」。由 `FundNavService.in_catalog` 统一判定。
        """
        self._ensure_in_catalog(fund_code)
        try:
            latest = self.fund_nav.get_latest(fund_code)
        except Exception as e:
            logger.error(f"读取最新净值失败 ({fund_code}): {e}")
            return {}
        if latest is None:
            logger.info(f"目录内基金暂无最新净值: {fund_code}")
            return {}
        return {
            "nav": str(latest.unit_nav),
            "nav_date": latest.nav_date.isoformat(),
        }

    def _query_overview(self, fund_code: str) -> Dict:
        """查询基金概览（含费率+规模+管理人等）"""
        try:
            import akshare as ak
            df = ak.fund_overview_em(symbol=fund_code)
            if df.empty:
                return {}
            row = df.iloc[0]
            return {
                "management_fee": self._clean_rate(str(row.get("管理费率", ""))),
                "custody_fee": self._clean_rate(str(row.get("托管费率", ""))),
                "subscription_fee": self._clean_rate(str(row.get("最高认购费率", ""))),
                "redemption_fee": self._clean_rate(str(row.get("最高赎回费率", ""))),
                "scale": str(row.get("净资产规模", "")),
                # P13 修正：基金管理人=公司，基金经理人=经理；
                # 旧版把「基金管理人」标成 fund_manager，问答里会把公司说成经理。
                "manager_company": str(row.get("基金管理人", "")),
                "fund_manager": str(row.get("基金经理人", "")),
                "custodian": str(row.get("基金托管人", "")),
                "fund_type": str(row.get("基金类型", "")),
            }
        except Exception as e:
            logger.error(f"查询概览失败 ({fund_code}): {e}")
            return {}

    @staticmethod
    def _clean_rate(rate_str: str) -> str:
        """清理费率字符串，提取百分比数字"""
        if not rate_str or rate_str == "---":
            return ""
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", rate_str)
        return f"{match.group(1)}%" if match else rate_str

    # ==================== 数据源适配（新浪） ====================

    @staticmethod
    def _to_sina_symbol(fund_code: str) -> str:
        """裸 6 位代码 → 新浪代码：512890 → sh512890，159915 → sz159915"""
        c = str(fund_code).strip().lower()
        if c[:2] in ("sh", "sz", "bj"):
            return c
        # 上交所：5(ETF/基金)、6(股票)；深交所：0/1(基金)、3(创业板)
        return ("sh" if c[:1] in ("5", "6") else "sz") + c

    # ==================== K线历史数据查询方法 ====================

    def query_kline(
        self,
        fund_code: str,
        period: str = "daily",
        start_date: str = None,
        end_date: str = None,
        limit: int = None
    ) -> List[Dict]:
        """
        查询ETF历史K线数据（带文件缓存，历史数据只增不改，可缓存1天）

        数据源：ak.fund_etf_hist_sina（新浪只有日线，周/月线由日线重采样，见 _resample_kline）
        缓存的是**归一化后的内部列名**（date/open/close/... ），不再缓存上游原始列，
        避免换源后命中旧缓存导致列名对不上。

        参数:
            fund_code: 基金代码（如 "512890"）
            period: K线周期（daily/weekly/monthly）
            start_date: 起始日期
            end_date: 结束日期
            limit: 返回数据条数限制

        返回:
            K线数据列表
        """
        # 尝试从文件缓存读取
        cached = self._load_kline_cache(fund_code, period)
        if cached is not None:
            df = cached
        else:
            try:
                import akshare as ak
                logger.info(f"查询K线数据: {fund_code}, period={period}")
                symbol = self._to_sina_symbol(fund_code)
                df = ak.fund_etf_hist_sina(symbol=symbol)
                if df is None or df.empty:
                    logger.warning(f"K线数据为空: {fund_code}")
                    return []
                # 先归一化成内部列名（并补出涨跌额/涨跌幅/振幅），再按需重采样
                df = self._normalize_kline(df)
                if period in ("weekly", "monthly"):
                    df = self._resample_kline(df, period)
                elif period != "daily":
                    logger.warning(f"未知K线周期 {period}，按日线返回")
                self._save_kline_cache(fund_code, period, df)
            except Exception as e:
                logger.error(f"查询K线数据失败: {e}")
                return []

        # 日期过滤
        if start_date:
            df = df[df['date'] >= start_date]
        if end_date:
            df = df[df['date'] <= end_date]

        # 数量限制
        if limit:
            df = df.tail(limit)

        # 转换为列表（NaN → 0.0，保证 KlineData 的非 Optional float 契约）
        def num(val) -> float:
            try:
                f = float(val)
            except (TypeError, ValueError):
                return 0.0
            return 0.0 if f != f else f

        results = []
        for _, row in df.iterrows():
            results.append({
                "date": str(row['date']),
                "open": num(row['open']),
                "close": num(row['close']),
                "high": num(row['high']),
                "low": num(row['low']),
                "volume": num(row['volume']),
                "amount": num(row['amount']),
                "amplitude": num(row['amplitude']),
                "change_pct": num(row['change_pct']),
                "change": num(row['change']),
                "turnover_rate": num(row['turnover_rate']),
            })

        logger.info(f"返回K线数据: {len(results)} 条")
        return results

    def query_kline_by_name(
        self,
        fund_name: str,
        period: str = "daily",
        start_date: str = None,
        end_date: str = None,
        limit: int = None
    ) -> List[Dict]:
        """
        按基金名称查询K线数据

        参数:
            fund_name: 基金名称（如 "华泰柏瑞红利低波ETF"）
            period: K线周期（daily/weekly/monthly）
            start_date: 起始日期
            end_date: 结束日期
            limit: 返回数据条数限制

        返回:
            K线数据列表
        """
        fund_code = self._resolve_fund_code(fund_name)
        if not fund_code:
            logger.warning(f"无法识别基金名称: {fund_name}")
            return []
        return self.query_kline(fund_code, period, start_date, end_date, limit)

    # ==================== 基金详细信息查询方法 ====================

    def query_detail(self, fund_code: str, nav_limit: int = DEFAULT_NAV_LIMIT) -> Optional[Dict]:
        """查询基金详细信息。

        目录外代码抛 `FundNotSupported`（API 映射 404），**不回退上游**。
        详情不再返回 `realtime`（2026-10-26 起无实时行情数据源），
        前端改用 `nav_history` 的最新一条展示净值。

        参数:
            fund_code: 基金代码（如 "110020"）
            nav_limit: 返回的历史净值条数上限；None 表示返回全量

        返回:
            详情字典：基本信息、费率、规模、历史净值
        """
        self._ensure_in_catalog(fund_code)

        result = {
            "code": fund_code,
            "source": "api",
        }

        # 1. 基本信息（概览）
        overview = self._query_detail_overview(fund_code)
        if overview:
            result.update(overview)

        # 2. 历史净值（默认近2年，够前端切分多月/年区间走势）
        nav_history = self._query_nav_history(fund_code, limit=nav_limit)
        if nav_history:
            result["nav_history"] = nav_history

        return result if len(result) > 2 else None

    def _query_detail_overview(self, fund_code: str) -> Optional[Dict]:
        """查询ETF详细概览信息。

        除 `is_qdii` 外全部来自上游（托管人/业绩基准/分红不在本地表内，见接入方案 §4.9）；
        `is_qdii` 是唯一的新增字段，读本地主数据，缺失时返回 `None` 而不是猜。
        """
        is_qdii = None
        try:
            meta = self.fund_meta.get(fund_code)
            if meta is not None:
                is_qdii = meta.is_qdii
        except Exception as e:
            logger.warning(f"读取本地基金元数据失败（{fund_code}），is_qdii 留空: {e}")

        try:
            import akshare as ak
            logger.info(f"查询ETF详细概览: {fund_code}")
            df = ak.fund_overview_em(symbol=fund_code)

            if df.empty:
                return None

            row = df.iloc[0]

            return {
                # QDII 标识（来自 fund.is_qdii；未知为 None）
                "is_qdii": is_qdii,
                # 基本信息
                "full_name": str(row.get("基金全称", "")),
                "short_name": str(row.get("基金简称", "")),
                "code": str(row.get("基金代码", "")).replace("（主代码）", ""),
                "fund_type": str(row.get("基金类型", "")),

                # 发行与成立
                "issue_date": str(row.get("发行日期", "")),
                "establish_date": str(row.get("成立日期/规模", "")),

                # 规模
                "net_asset_scale": str(row.get("净资产规模", "")),
                "share_scale": str(row.get("份额规模", "")),

                # 管理机构
                "manager_company": str(row.get("基金管理人", "")),
                "custodian": str(row.get("基金托管人", "")),
                "fund_manager": str(row.get("基金经理人", "")),

                # 分红
                "dividend_history": str(row.get("成立来分红", "")),

                # 费率
                "management_fee": self._clean_rate(str(row.get("管理费率", ""))),
                "custody_fee": self._clean_rate(str(row.get("托管费率", ""))),
                "subscription_fee": self._clean_rate(str(row.get("最高认购费率", ""))),
                "purchase_fee": self._clean_rate(str(row.get("最高申购费率", ""))),
                "redemption_fee": self._clean_rate(str(row.get("最高赎回费率", ""))),

                # 投资标的
                "benchmark": str(row.get("业绩比较基准", "")),
                "tracking_target": str(row.get("跟踪标的", "")),
            }

        except Exception as e:
            logger.error(f"查询ETF详细概览失败: {e}")
            return None

    def _query_nav_history(self, fund_code: str, limit: int = None) -> List[Dict]:
        """查询历史净值记录，**只读 DB**（`FundNavService.get_history`）。

        首次访问会做一次读穿透补齐历史；补数失败抛 `FundNavUnavailable`（API 映射 503），
        **不返回片段**冒充完整历史。目录外代码抛 `FundNotSupported`（404），
        不再回退 `ak.fund_open_fund_info_em`（2026-10-26 决策）。

        参数:
            fund_code: 基金代码
            limit: 只取最近 N 条；None 表示全量（老基金可达数千条）

        返回:
            [{"date", "nav", "accumulated_nav", "daily_growth"}]；无数据返回 []
        """
        from server.services.fund_nav_service import FundNavUnavailable

        self._ensure_in_catalog(fund_code)
        try:
            points = self.fund_nav.get_history(fund_code, limit=limit)
        except FundNavUnavailable:
            # 历史不可用是「暂时取不到」，不是「没有历史」：上抛让 API 返回 503
            raise
        except Exception as e:
            logger.error(f"读取历史净值失败 ({fund_code}): {e}")
            return []

        logger.info(f"返回历史净值 {len(points)} 条（DB）: {fund_code}")
        return [
            {
                "date": point.nav_date.isoformat(),
                "nav": self._safe_float(point.unit_nav),
                "accumulated_nav": self._safe_float(point.accumulated_nav),
                "daily_growth": self._safe_float(point.daily_growth),
            }
            for point in points
        ]


    @staticmethod
    def _safe_float(val) -> Optional[float]:
        """安全转换为浮点数"""
        try:
            v = float(val)
            return v if v == v else None  # NaN check
        except (ValueError, TypeError):
            return None

    # ==================== K线归一化 / 重采样 ====================

    @staticmethod
    def _with_derived_kline_fields(df: pd.DataFrame) -> pd.DataFrame:
        """补出涨跌额/涨跌幅/振幅（相对上一根收盘计算），换手率无来源填 0"""
        prev_close = df["close"].shift(1)
        df["change"] = (df["close"] - prev_close).fillna(0.0)
        df["change_pct"] = ((df["close"] - prev_close) / prev_close * 100).fillna(0.0).round(4)
        df["amplitude"] = ((df["high"] - df["low"]) / prev_close * 100).fillna(0.0).round(4)
        df["turnover_rate"] = 0.0
        return df

    @staticmethod
    def _normalize_kline(df: pd.DataFrame) -> pd.DataFrame:
        """把上游日K归一化成内部列名，并补出 change / change_pct / amplitude

        新浪原始列：date open high low close volume amount postVol postAmt
        内部列：    date open high low close volume amount change change_pct amplitude turnover_rate
        """
        out = pd.DataFrame({
            "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df["volume"], errors="coerce"),
            "amount": pd.to_numeric(df["amount"], errors="coerce"),
        })
        # 上游顺序不保证；升序是 K 线契约（重采样、涨跌幅都依赖前一根）
        out = out.sort_values("date").reset_index(drop=True)
        return FinanceApiService._with_derived_kline_fields(out)

    @staticmethod
    def _resample_kline(df: pd.DataFrame, period: str) -> pd.DataFrame:
        """日线 → 周线(W-FRI) / 月线(ME)

        新浪只有日线接口，周/月线由日线聚合：open=区间首、high=区间最高、
        low=区间最低、close=区间末、volume/amount=求和，再重算涨跌幅/振幅。

        日期取区间内**最后一个实际交易日**（同 Yahoo/多数行情源），不用区间末日标签：
        用 W-FRI/ME 的区间末日会把本周标成还没到的周五（如今天 10-13 标出 10-16），
        前端按日期过滤或画时间轴会把它当越界数据丢掉。
        """
        rule = {"weekly": "W-FRI", "monthly": "ME"}[period]
        indexed = df.set_index(pd.to_datetime(df["date"]))
        indexed["_d"] = indexed.index  # 取组内最后一个交易日用的辅助列
        agg = indexed.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "amount": "sum",
            "_d": "last",
        }).dropna(subset=["close"])
        out = pd.DataFrame({
            "date": agg["_d"].dt.strftime("%Y-%m-%d"),
            "open": agg["open"].to_numpy(),
            "high": agg["high"].to_numpy(),
            "low": agg["low"].to_numpy(),
            "close": agg["close"].to_numpy(),
            "volume": agg["volume"].to_numpy(),
            "amount": agg["amount"].to_numpy(),
        })
        return FinanceApiService._with_derived_kline_fields(out)

    # ==================== K线文件缓存方法 ====================

    @staticmethod
    def _kline_cache_path(fund_code: str, period: str) -> str:
        """K线缓存文件路径（文件名带数据源标识，避免换源后与旧缓存串味）"""
        os.makedirs(KLINE_CACHE_DIR, exist_ok=True)
        safe_code = fund_code.replace("/", "_")
        return f"{KLINE_CACHE_DIR}/{safe_code}_{period}_{KLINE_SOURCE}.json"

    @staticmethod
    def _load_kline_cache(fund_code: str, period: str) -> Optional[pd.DataFrame]:
        """从文件加载K线缓存，过期返回 None"""
        path = FinanceApiService._kline_cache_path(fund_code, period)
        try:
            if not os.path.exists(path):
                return None
            mtime = os.path.getmtime(path)
            if time.time() - mtime > KLINE_CACHE_TTL:
                logger.debug(f"K线缓存过期: {fund_code} {period}")
                os.remove(path)
                return None
            df = pd.read_json(path, orient="split")
            # read_json 会把 date 列从字符串还原成 Timestamp，str() 后变成
            # "2026-10-12 00:00:00" —— 与未命中缓存时（"%Y-%m-%d"）格式不一致。
            # 统一回纯日期，保证缓存命中与否返回同一契约。
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            logger.info(f"K线缓存命中: {fund_code} {period} ({len(df)} 条)")
            return df
        except Exception as e:
            logger.warning(f"K线缓存读取失败: {e}")
            return None

    @staticmethod
    def _save_kline_cache(fund_code: str, period: str, df: pd.DataFrame) -> None:
        """将K线数据保存到文件缓存"""
        path = FinanceApiService._kline_cache_path(fund_code, period)
        try:
            df.to_json(path, orient="split", force_ascii=False)
            logger.info(f"K线缓存已保存: {path} ({len(df)} 条)")
        except Exception as e:
            logger.warning(f"K线缓存保存失败: {e}")

    # ==================== 分时图数据方法 ====================

    def query_intraday(self, fund_code: str) -> List[Dict]:
        """查询当日分时图数据。

        数据源：ak.stock_zh_a_minute（新浪）——返回约 1970 根的**滚动窗口**，跨多个
        交易日，必须按「今天」过滤，否则分时图会把十几天的走势画成一天。

        2026-10-26：删除了「用实时行情 + 日K线模拟」的降级分支——它依赖已下线的
        30 秒行情缓存，且生成的是**伪造数据**。取不到当日分钟线时返回空列表，
        由前端展示「暂无分时数据」。

        参数:
            fund_code: 基金代码

        返回:
            分时数据列表，每条包含：time(时间), price(价格), avg_price(均价),
            volume(成交量), amount(成交额), change_pct(相对昨收的累计涨跌幅)
        """
        try:
            import akshare as ak
            symbol = self._to_sina_symbol(fund_code)
            df = ak.stock_zh_a_minute(symbol=symbol, period='1', adjust='')
            if df is None or df.empty:
                return []
            today = beijing_now().strftime("%Y-%m-%d")
            df = df[df['day'].astype(str).str.startswith(today)]
            if df.empty:
                logger.info(f"当日无分时数据: {fund_code}")
                return []

            prev_close = self._prev_close_for_intraday(fund_code)
            results = []
            for _, row in df.iterrows():
                price = self._safe_float(row.get('close', 0)) or 0
                volume = self._safe_float(row.get('volume', 0)) or 0
                amount = self._safe_float(row.get('amount', 0)) or 0
                # day 形如 "2026-10-13 09:31:00"，只保留 HH:MM
                stamp = str(row.get('day', ''))
                results.append({
                    "time": stamp[11:16] if len(stamp) >= 16 else stamp,
                    "price": price,
                    "open": self._safe_float(row.get('open', 0)),
                    "high": self._safe_float(row.get('high', 0)),
                    "low": self._safe_float(row.get('low', 0)),
                    "volume": volume,
                    "amount": amount,
                    "avg_price": round(amount / volume, 4) if volume else price,
                    "change_pct": round((price - prev_close) / prev_close * 100, 2) if prev_close else 0,
                })
            logger.info(f"获取分时图数据: {fund_code}, {len(results)} 条")
            return results
        except Exception as e:
            logger.warning(f"分钟K线获取失败 ({fund_code}): {e}")
            return []

    def _prev_close_for_intraday(self, fund_code: str) -> float:
        """取昨收价（分时涨跌幅的基准）：日K里今天之前的最后一根。

        盘中新浪日K不含当日未收盘的 K 线，收盘后才含；所以按「日期 < 今天」
        取最后一根，盘中/盘后都拿到真正的昨收。
        """
        today = beijing_now().strftime("%Y-%m-%d")
        for bar in reversed(self.query_kline(fund_code, period='daily', limit=10)):
            if str(bar.get("date", "")) < today:
                return bar.get("close") or 0
        return 0

