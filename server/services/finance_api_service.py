import logging
import re
import time
from typing import Optional, Dict, List

import pandas as pd

logger = logging.getLogger(__name__)


class FinanceApiService:
    """通过 AkShare 查询 ETF 基金的费率、净值、规模、实时行情等事实数据"""

    # 已知基金名称 → 代码的快捷映射（高频使用的基金）
    KNOWN_FUNDS = {
        "华泰柏瑞中证红利低波": "512890",
        "华泰柏瑞红利低波": "512890",
        "红利低波ETF华泰柏瑞": "512890",
        "南方标普红利低波50": "515450",
        "南方标普中国A股大盘红利低波50": "515450",
        "红利低波50ETF南方": "515450",
        "沪深300ETF华泰柏瑞": "510300",
        "华泰柏瑞沪深300": "510300",
    }

    # 实时行情缓存（全量数据较大，缓存5秒）
    _spot_cache: Optional[pd.DataFrame] = None
    _spot_cache_time: float = 0
    CACHE_TTL = 5  # 缓存有效期（秒）

    def __init__(self):
        self._fund_list_cache: Optional[list] = None

    def _get_fund_list(self) -> list:
        """获取全量 ETF 基金列表（带缓存）"""
        if self._fund_list_cache is not None:
            return self._fund_list_cache
        try:
            import akshare as ak
            df = ak.fund_name_em()
            # 列: 基金代码, 拼音缩写, 基金简称, 基金类型, 拼音全称
            self._fund_list_cache = df.values.tolist()
            logger.info(f"基金列表加载成功，共 {len(self._fund_list_cache)} 只基金")
        except Exception as e:
            logger.error(f"加载基金列表失败: {e}")
            self._fund_list_cache = []
        return self._fund_list_cache

    def _resolve_fund_code(self, fund_name: str) -> Optional[str]:
        """基金名称 → 基金代码"""
        for known_name, code in self.KNOWN_FUNDS.items():
            if known_name in fund_name or fund_name in known_name:
                logger.debug(f"快捷映射命中: {fund_name} -> {code}")
                return code

        query = fund_name.replace("ETF", "").replace("etf", "").strip()
        candidates = self._collect_fund_candidates(query)
        if not candidates:
            return None

        best = max(candidates, key=lambda c: (c["is_exact"], c["score"], c["is_etf"]))
        logger.debug(f"模糊匹配: {fund_name} -> {best['code']} (score={best['score']:.2f})")
        return best["code"]

    def _collect_fund_candidates(self, query: str) -> list[dict]:
        """从基金列表中筛选所有可匹配的候选基金"""
        candidates = []
        for row in self._get_fund_list():
            code = str(row[0])
            name = str(row[2]) if len(row) > 2 else ""
            fund_type = str(row[3]) if len(row) > 3 else ""

            if "联接" in name or "联接" in fund_type:
                continue

            score, is_exact = self._score_match(query, name)
            if score > 0.5:
                candidates.append({
                    "code": code,
                    "score": score,
                    "is_exact": is_exact,
                    "is_etf": code.startswith(("51", "15", "16", "58")),
                })
        return candidates

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

        # 判断用户想查什么
        data = {}

        # 新增：行情查询（优先级最高）
        if any(kw in question for kw in ("涨跌幅", "涨幅", "跌幅", "现在价格", "实时", "行情", "涨多少", "跌多少", "现在多少钱")):
            spot_data = self.query_spot(fund_code)
            if spot_data:
                return spot_data
            # 行情查询失败，继续尝试其他数据

        if any(kw in question for kw in ("费率", "管理费", "托管费", "申购费", "赎回费", "费用")):
            data.update(self._query_fees(fund_code))
        if any(kw in question for kw in ("净值", "多少钱", "价格")):
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

        # 尝试匹配已知基金名
        for name in self.KNOWN_FUNDS:
            if name in question:
                return name

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
        """查询基金最新净值"""
        try:
            import akshare as ak
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df.empty:
                return {}
            latest = df.iloc[-1]
            return {
                "nav": str(latest.get("单位净值", "")),
                "nav_date": str(latest.get("净值日期", "")),
            }
        except Exception as e:
            logger.error(f"查询净值失败 ({fund_code}): {e}")
            return {}

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
                "fund_manager": str(row.get("基金管理人", "")),
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

    # ==================== 实时行情查询方法（新增） ====================

    def _get_spot_data(self) -> pd.DataFrame:
        """获取全量ETF实时行情（带缓存）"""
        now = time.time()
        if self._spot_cache is not None and (now - self._spot_cache_time) < self.CACHE_TTL:
            logger.debug(f"使用缓存的实时行情数据（缓存时间: {self.CACHE_TTL}秒）")
            return self._spot_cache

        try:
            import akshare as ak
            logger.info("正在获取全量ETF实时行情...")
            df = ak.fund_etf_spot_em()
            self._spot_cache = df
            self._spot_cache_time = now
            logger.info(f"获取实时行情成功，共 {len(df)} 只ETF")
            return df
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return pd.DataFrame()

    def query_spot(self, fund_code: str) -> Optional[Dict]:
        """
        查询单只ETF实时行情

        参数:
            fund_code: 基金代码（如 "512890"）

        返回:
            行情数据字典，失败返回 None
        """
        df = self._get_spot_data()
        if df.empty:
            return None

        row = df[df['代码'] == fund_code]
        if row.empty:
            logger.warning(f"未找到基金代码: {fund_code}")
            return None

        return self._format_spot_data(row.iloc[0])

    def query_spot_by_name(self, fund_name: str) -> Optional[Dict]:
        """
        按基金名称查询实时行情

        参数:
            fund_name: 基金名称（如 "华泰柏瑞红利低波ETF"）

        返回:
            行情数据字典，失败返回 None
        """
        fund_code = self._resolve_fund_code(fund_name)
        if not fund_code:
            logger.warning(f"无法识别基金名称: {fund_name}")
            return None
        return self.query_spot(fund_code)

    def query_ranking(self, sort_by: str = '涨跌幅', top_n: int = 10, ascending: bool = False) -> List[Dict]:
        """
        查询ETF涨幅榜/跌幅榜

        参数:
            sort_by: 排序字段（如 '涨跌幅', '成交额', '换手率'）
            top_n: 返回数量（默认10）
            ascending: 排序方向（False=从高到低，True=从低到高）

        返回:
            行情数据列表
        """
        df = self._get_spot_data()
        if df.empty:
            return []

        # 确保排序字段存在
        if sort_by not in df.columns:
            logger.warning(f"排序字段 '{sort_by}' 不存在，使用默认字段 '涨跌幅'")
            sort_by = '涨跌幅'

        df_sorted = df.sort_values(by=sort_by, ascending=ascending)
        results = []
        for _, row in df_sorted.head(top_n).iterrows():
            results.append(self._format_spot_data(row))

        logger.debug(f"返回 {len(results)} 条榜单数据（排序: {sort_by}, 升序: {ascending}）")
        return results

    def _format_spot_data(self, row) -> Dict:
        """
        格式化单行行情数据

        参数:
            row: pandas Series（一行数据）

        返回:
            格式化后的行情数据字典
        """
        def safe_float(val, default=0.0):
            """安全转换为浮点数"""
            try:
                return float(val) if pd.notna(val) else default
            except (ValueError, TypeError):
                return default

        def safe_str(val, default=""):
            """安全转换为字符串"""
            return str(val) if pd.notna(val) else default

        return {
            # 基础信息
            "code": safe_str(row.get('代码', '')),
            "name": safe_str(row.get('名称', '')),
            "data_date": safe_str(row.get('数据日期', '')),
            "update_time": safe_str(row.get('更新时间', '')),

            # 基础行情
            "price": safe_float(row.get('最新价', 0)),
            "change": safe_float(row.get('涨跌额', 0)),
            "change_pct": safe_float(row.get('涨跌幅', 0)),
            "prev_close": safe_float(row.get('昨收', 0)),

            # 日内行情
            "open": safe_float(row.get('开盘价', 0)),
            "high": safe_float(row.get('最高价', 0)),
            "low": safe_float(row.get('最低价', 0)),
            "amplitude": safe_float(row.get('振幅', 0)),

            # 成交数据
            "volume": safe_float(row.get('成交量', 0)),
            "amount": safe_float(row.get('成交额', 0)),
            "turnover_rate": safe_float(row.get('换手率', 0)),
            "volume_ratio": safe_float(row.get('量比', 0)),

            # 盘口数据
            "bid_price": safe_float(row.get('买一', 0)),
            "ask_price": safe_float(row.get('卖一', 0)),
            "outer_vol": safe_float(row.get('外盘', 0)),
            "inner_vol": safe_float(row.get('内盘', 0)),
            "order_ratio": safe_float(row.get('委比', 0)),

            # 资金流向
            "main_inflow": safe_float(row.get('主力净流入-净额', 0)),
            "main_inflow_pct": safe_float(row.get('主力净流入-净占比', 0)),

            # 市值数据
            "latest_shares": safe_float(row.get('最新份额', 0)),
            "float_mv": safe_float(row.get('流通市值', 0)),
            "total_mv": safe_float(row.get('总市值', 0)),

            # 标记数据来源
            "source": "api",
        }

    # ==================== K线历史数据查询方法（新增） ====================

    def query_kline(
        self,
        fund_code: str,
        period: str = "daily",
        start_date: str = None,
        end_date: str = None,
        limit: int = None
    ) -> List[Dict]:
        """
        查询ETF历史K线数据

        参数:
            fund_code: 基金代码（如 "512890"）
            period: K线周期，可选值：
                - "daily": 日K线（默认）
                - "weekly": 周K线
                - "monthly": 月K线
            start_date: 起始日期（格式：2024-01-01），可选
            end_date: 结束日期（格式：2024-12-31），可选
            limit: 返回数据条数限制，可选

        返回:
            K线数据列表，每条包含：日期、开盘、收盘、最高、最低、成交量、成交额、振幅、涨跌幅、涨跌额、换手率
        """
        try:
            import akshare as ak
            logger.info(f"查询K线数据: {fund_code}, period={period}")

            # 调用 AkShare API
            df = ak.fund_etf_hist_em(symbol=fund_code, period=period, adjust='')

            if df.empty:
                logger.warning(f"K线数据为空: {fund_code}")
                return []

            # 日期过滤
            if start_date:
                df = df[df['日期'] >= start_date]
            if end_date:
                df = df[df['日期'] <= end_date]

            # 数量限制
            if limit:
                df = df.tail(limit)

            # 转换为列表
            results = []
            for _, row in df.iterrows():
                results.append({
                    "date": str(row['日期']),
                    "open": float(row['开盘']),
                    "close": float(row['收盘']),
                    "high": float(row['最高']),
                    "low": float(row['最低']),
                    "volume": float(row['成交量']),
                    "amount": float(row['成交额']),
                    "amplitude": float(row['振幅']),
                    "change_pct": float(row['涨跌幅']),
                    "change": float(row['涨跌额']),
                    "turnover_rate": float(row['换手率']),
                })

            logger.info(f"返回K线数据: {len(results)} 条")
            return results

        except Exception as e:
            logger.error(f"查询K线数据失败: {e}")
            return []

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

    # ==================== ETF详细信息查询方法（新增） ====================

    def query_detail(self, fund_code: str) -> Optional[Dict]:
        """
        查询ETF详细信息（完整版）

        参数:
            fund_code: 基金代码（如 "512890"）

        返回:
            ETF详细信息字典，包含：基本信息、实时行情、费率、规模等
        """
        result = {
            "code": fund_code,
            "source": "api",
        }

        # 1. 基本信息（概览）
        overview = self._query_detail_overview(fund_code)
        if overview:
            result.update(overview)

        # 2. 实时行情
        spot = self.query_spot(fund_code)
        if spot:
            result["realtime"] = spot

        # 3. 历史净值（最近5条）
        nav_history = self._query_nav_history(fund_code, limit=5)
        if nav_history:
            result["nav_history"] = nav_history

        return result if len(result) > 2 else None

    def _query_detail_overview(self, fund_code: str) -> Optional[Dict]:
        """查询ETF详细概览信息"""
        try:
            import akshare as ak
            logger.info(f"查询ETF详细概览: {fund_code}")
            df = ak.fund_overview_em(symbol=fund_code)

            if df.empty:
                return None

            row = df.iloc[0]

            return {
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

    def _query_nav_history(self, fund_code: str, limit: int = 5) -> List[Dict]:
        """查询历史净值记录"""
        try:
            import akshare as ak
            df = ak.fund_etf_fund_info_em()

            if df.empty:
                return []

            # 筛选最近的记录
            df = df.tail(limit)

            results = []
            for _, row in df.iterrows():
                results.append({
                    "date": str(row.get("净值日期", "")),
                    "nav": float(row.get("单位净值", 0)) if pd.notna(row.get("单位净值")) else None,
                    "accumulated_nav": float(row.get("累计净值", 0)) if pd.notna(row.get("累计净值")) else None,
                    "daily_growth": float(row.get("日增长率", 0)) if pd.notna(row.get("日增长率")) else None,
                })

            return results

        except Exception as e:
            logger.error(f"查询历史净值失败: {e}")
            return []

    # ==================== ETF搜索/筛选方法（新增） ====================

    def search_etf(
        self,
        keyword: str,
        top_n: int = 10,
        include_quote: bool = True
    ) -> List[Dict]:
        """
        搜索ETF（按名称或代码模糊匹配）

        参数:
            keyword: 关键词（名称或代码片段）
            top_n: 返回数量
            include_quote: 是否包含实时行情

        返回:
            匹配的ETF列表
        """
        # 使用实时行情数据做搜索，因为 fund_etf_spot_em 包含所有ETF的代码和名称
        df = self._get_spot_data()
        if df.empty:
            return []

        keyword_lower = keyword.lower()

        # 在代码和名称中模糊匹配
        mask = (
            df['代码'].astype(str).str.contains(keyword)
            | df['名称'].str.contains(keyword, na=False, case=False)
        )

        matched = df[mask].head(top_n)

        results = []
        for _, row in matched.iterrows():
            item = {
                "code": str(row.get('代码', '')),
                "name": str(row.get('名称', '')),
                "fund_type": None,  # 实时行情数据不包含基金类型
                "net_asset_scale": None,
                "management_fee": None,
                "tracking_target": None,
            }

            if include_quote:
                item["price"] = self._safe_float(row.get('最新价'))
                item["change_pct"] = self._safe_float(row.get('涨跌幅'))
                item["change"] = self._safe_float(row.get('涨跌额'))

            results.append(item)

        logger.info(f"搜索ETF: keyword={keyword}, 匹配到 {len(results)} 条")
        return results

    def filter_etf(self, filters: dict) -> List[Dict]:
        """
        按条件筛选ETF（基于实时行情数据）

        参数:
            filters: 筛选条件字典
                - keyword: 关键词
                - max_fee: 最大管理费率（需要从概览数据获取）
                - min_scale_billion: 最小规模（亿）
                - max_scale_billion: 最大规模（亿）
                - min_return: 最小涨跌幅
                - max_return: 最大涨跌幅
                - top_n: 返回数量
                - sort_by: 排序字段
                - sort_order: 排序方向

        返回:
            符合条件的ETF列表
        """
        df = self._get_spot_data()
        if df.empty:
            return []

        keyword = filters.get("keyword", "ETF")
        min_return = filters.get("min_return")
        max_return = filters.get("max_return")
        sort_by = filters.get("sort_by", "涨跌幅")
        sort_order = filters.get("sort_order", "desc")
        top_n = filters.get("top_n", 20)

        # 1. 关键词过滤
        if keyword:
            df = df[
                df['代码'].astype(str).str.contains(keyword)
                | df['名称'].str.contains(keyword, na=False, case=False)
            ]

        # 2. 涨跌幅过滤
        if min_return is not None:
            df = df[df['涨跌幅'] >= min_return]
        if max_return is not None:
            df = df[df['涨跌幅'] <= max_return]

        # 3. 排序
        if sort_by in df.columns:
            ascending = (sort_order == "asc")
            df = df.sort_values(by=sort_by, ascending=ascending)

        # 4. 取前N条
        df = df.head(top_n)

        # 转换为列表
        results = []
        for _, row in df.iterrows():
            results.append({
                "code": str(row.get('代码', '')),
                "name": str(row.get('名称', '')),
                "price": self._safe_float(row.get('最新价')),
                "change_pct": self._safe_float(row.get('涨跌幅')),
                "change": self._safe_float(row.get('涨跌额')),
                "fund_type": None,
                "net_asset_scale": None,
                "tracking_target": None,
            })

        logger.info(f"筛选ETF: 条件={filters}, 返回 {len(results)} 条")
        return results

    def get_categories(self) -> List[Dict]:
        """
        获取ETF分类列表（按基金类型分组）

        返回:
            分类列表，每个分类包含名称、类型、数量
        """
        # 使用实时行情数据统计
        df = self._get_spot_data()
        if df.empty:
            return []

        # 从名称中提取分类关键词
        categories = {
            "红": "红利ETF",
            "红利": "红利ETF",
            "股息": "红利ETF",
            "科技": "科技ETF",
            "创新": "科创ETF",
            "科创": "科创ETF",
            "半导体": "半导体ETF",
            "芯片": "半导体ETF",
            "消费": "消费ETF",
            "医药": "医药ETF",
            "医疗": "医药ETF",
            "新能源": "新能源ETF",
            "光伏": "新能源ETF",
            "碳中和": "碳中和ETF",
            "证券": "券商ETF",
            "券商": "券商ETF",
            "银行": "银行ETF",
            "地产": "地产ETF",
            "军工": "军工ETF",
            "通信": "通信ETF",
            "5G": "科技ETF",
            "AI": "科技ETF",
            "人工智能": "科技ETF",
            "传媒": "传媒ETF",
            "游戏": "传媒ETF",
            "黄金": "商品ETF",
            "油气": "商品ETF",
            "能源": "商品ETF",
            "煤炭": "商品ETF",
            "农业": "农业ETF",
            "养殖": "农业ETF",
            "食品": "消费ETF",
            "白酒": "消费ETF",
            "汽车": "汽车ETF",
            "智能驾驶": "汽车ETF",
            "恒生": "港股ETF",
            "港股": "港股ETF",
            "H股": "港股ETF",
            "纳斯达克": "跨境ETF",
            "标普": "跨境ETF",
            "跨境": "跨境ETF",
            "QDII": "跨境ETF",
            "沪深300": "宽基ETF",
            "中证500": "宽基ETF",
            "中证1000": "宽基ETF",
            "上证50": "宽基ETF",
            "创业板": "宽基ETF",
            "科创50": "宽基ETF",
            "A50": "宽基ETF",
            "双创": "宽基ETF",
        }

        category_counts = {}
        for _, row in df.iterrows():
            name = str(row.get('名称', ''))
            matched = False
            for kw, cat in categories.items():
                if kw in name:
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                    matched = True
                    break
            if not matched:
                # 未匹配的归为"其他ETF"
                category_counts["其他ETF"] = category_counts.get("其他ETF", 0) + 1

        results = []
        for cat_name, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            results.append({
                "category": cat_name,
                "fund_type": cat_name,
                "count": count,
            })

        logger.info(f"获取分类列表: 共 {len(results)} 个分类, {len(df)} 只基金")
        return results

    def get_category_funds(self, category: str, top_n: int = 50) -> List[Dict]:
        """
        获取指定分类下的ETF列表

        参数:
            category: 分类名称（如"红利ETF"、"科技ETF"）
            top_n: 返回数量

        返回:
            该分类下的ETF列表（含实时行情）
        """
        df = self._get_spot_data()
        if df.empty:
            return []

        # 分类名称反向查找关键词
        category_keywords = {
            "红利ETF": ["红利", "股息", "红"],
            "科技ETF": ["科技", "创新", "5G", "AI", "人工智能", "科创"],
            "半导体ETF": ["半导体", "芯片"],
            "消费ETF": ["消费", "食品", "白酒"],
            "医药ETF": ["医药", "医疗"],
            "新能源ETF": ["新能源", "光伏", "碳中和"],
            "券商ETF": ["证券", "券商"],
            "银行ETF": ["银行"],
            "地产ETF": ["地产"],
            "军工ETF": ["军工"],
            "通信ETF": ["通信"],
            "传媒ETF": ["传媒", "游戏"],
            "商品ETF": ["黄金", "油气", "能源", "煤炭"],
            "农业ETF": ["农业", "养殖"],
            "汽车ETF": ["汽车", "智能驾驶"],
            "港股ETF": ["恒生", "港股", "H股"],
            "跨境ETF": ["纳斯达克", "标普", "跨境", "QDII"],
            "宽基ETF": ["沪深300", "中证500", "中证1000", "上证50", "创业板", "科创50", "A50", "双创"],
            "其他ETF": [],
        }

        keywords = category_keywords.get(category, [])
        if not keywords:
            # 如果分类没有关键词，也匹配名称中包含分类名的
            keywords = [category.replace("ETF", "")]

        # 筛选
        mask = df['名称'].str.contains('|'.join(keywords), na=False, case=False)
        filtered = df[mask].head(top_n)

        results = []
        for _, row in filtered.iterrows():
            results.append({
                "code": str(row.get('代码', '')),
                "name": str(row.get('名称', '')),
                "price": self._safe_float(row.get('最新价')),
                "change_pct": self._safe_float(row.get('涨跌幅')),
                "change": self._safe_float(row.get('涨跌额')),
            })

        logger.info(f"获取分类ETF: category={category}, 返回 {len(results)} 条")
        return results

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        """安全转换为浮点数"""
        try:
            v = float(val)
            return v if v == v else None  # NaN check
        except (ValueError, TypeError):
            return None

    # ==================== 分时图数据方法（新增） ====================

    def query_intraday(self, fund_code: str) -> List[Dict]:
        """
        查询当日分时图数据

        优先从 AkShare 分钟接口获取，失败则用日K线模拟。

        参数:
            fund_code: 基金代码

        返回:
            分时数据列表，每条包含：time(时间), price(价格), avg_price(均价),
            volume(成交量), amount(成交额), change_pct(累计涨跌幅)
        """
        # 方案1: 尝试从分钟K线获取
        try:
            import akshare as ak
            df = ak.fund_etf_hist_min_em(symbol=fund_code, period='1', adjust='')
            if df is not None and not df.empty:
                results = []
                for _, row in df.iterrows():
                    results.append({
                        "time": str(row.get('时间', '')),
                        "price": self._safe_float(row.get('收盘', 0)),
                        "open": self._safe_float(row.get('开盘', 0)),
                        "high": self._safe_float(row.get('最高', 0)),
                        "low": self._safe_float(row.get('最低', 0)),
                        "volume": self._safe_float(row.get('成交量', 0)),
                        "amount": self._safe_float(row.get('成交额', 0)),
                    })
                if results:
                    # 计算均价和涨跌幅
                    first_price = results[0]["price"] or 0
                    for r in results:
                        r["avg_price"] = r["amount"] / r["volume"] if r["volume"] else r["price"]
                        r["change_pct"] = round(((r["price"] - first_price) / first_price) * 100, 2) if first_price else 0
                    logger.info(f"获取分时图数据(真实): {fund_code}, {len(results)} 条")
                    return results
        except Exception as e:
            logger.warning(f"分钟K线获取失败，降级方案: {e}")

        # 方案2: 用实时行情 + 日K线模拟当日分时走势
        return self._generate_intraday_fallback(fund_code)

    def _generate_intraday_fallback(self, fund_code: str) -> List[Dict]:
        """生成模拟分时走势（基于当日实时行情和昨日K线）"""
        spot = self.query_spot(fund_code)
        if not spot:
            return []

        # 获取当日K线数据（包含昨收）
        kline = self.query_kline(fund_code, period='daily', limit=2)

        prev_close = spot.get('prev_close', 0)
        current_price = spot.get('price', 0)
        open_price = spot.get('open', prev_close)
        high_price = spot.get('high', current_price)
        low_price = spot.get('low', current_price)
        total_volume = spot.get('volume', 0)
        total_amount = spot.get('amount', 0)

        # 如果日K线有数据，用日K线的开盘价
        if kline and len(kline) >= 1:
            today_kline = kline[-1]
            if today_kline.get('open'):
                open_price = today_kline['open']

        # 模拟生成约240个时间点（A股4小时交易 = 240分钟）
        import random
        random.seed(hash(fund_code) % 10000)  # 固定种子使结果可复现

        num_points = 240
        # 用正弦曲线模拟价格走势
        import math

        results = []
        for i in range(num_points):
            # 时间：09:30 ~ 15:00
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            time_str = f"{hour:02d}:{minute:02d}"

            # 模拟价格走势（开盘->随机波动->收盘）
            progress = i / num_points
            # 用正弦波 + 随机噪声模拟价格波动
            wave = math.sin(progress * math.pi * 2) * 0.3
            noise = random.uniform(-0.1, 0.1)
            price_factor = progress + (wave + noise) * 0.02
            simulated_price = round(open_price + (current_price - open_price) * price_factor, 3)

            # 确保价格在合理范围内
            simulated_price = max(low_price * 0.995, min(high_price * 1.005, simulated_price))

            # 模拟成交量（开盘和收盘时成交量较大）
            volume_factor = 1 - abs(progress - 0.5) * 1.2
            volume_factor = max(0.3, volume_factor)
            simulated_volume = int(total_volume / num_points * volume_factor * random.uniform(0.5, 1.5))

            # 累计涨跌幅（相对于昨收）
            change_pct = round(((simulated_price - prev_close) / prev_close) * 100, 2) if prev_close else 0

            results.append({
                "time": time_str,
                "price": simulated_price,
                "avg_price": round((simulated_price + open_price) / 2, 3),
                "volume": simulated_volume,
                "change_pct": change_pct,
            })

        logger.info(f"生成分时图数据(模拟): {fund_code}, {len(results)} 条")
        return results

    # ==================== 资金流向数据方法（新增） ====================

    def query_money_flow(self, fund_code: str) -> Optional[Dict]:
        """
        查询ETF资金流向（从实时行情数据中提取）

        参数:
            fund_code: 基金代码

        返回:
            资金流向数据字典
        """
        # 实时行情中已包含主力/大单/中单/小单净流入数据
        spot = self.query_spot(fund_code)
        if not spot:
            return None

        result = {
            "code": fund_code,
            "name": spot.get("name", ""),
            "price": spot.get("price", 0),
            "change_pct": spot.get("change_pct", 0),
            "main_inflow": spot.get("main_inflow", 0),
            "main_inflow_pct": spot.get("main_inflow_pct", 0),
            "amount": spot.get("amount", 0),
            "outer_vol": spot.get("outer_vol", 0),
            "inner_vol": spot.get("inner_vol", 0),
            "order_ratio": spot.get("order_ratio", 0),
            "update_time": spot.get("update_time", ""),
        }

        # 计算净流入（外盘 - 内盘）
        outer = spot.get("outer_vol", 0) or 0
        inner = spot.get("inner_vol", 0) or 0
        result["net_flow"] = outer - inner

        logger.info(f"查询资金流向: {fund_code}, 主力净流入={result['main_inflow']}")
        return result

    def query_money_flow_ranking(self, top_n: int = 20, ascending: bool = False) -> List[Dict]:
        """
        查询资金流向排行榜

        参数:
            top_n: 返回数量
            ascending: 排序方向（False=净流入从高到低，True=净流出从高到低）

        返回:
            资金流向排行榜
        """
        df = self._get_spot_data()
        if df.empty:
            return []

        sort_col = '主力净流入-净额'
        if sort_col not in df.columns:
            return []

        df_sorted = df.sort_values(by=sort_col, ascending=ascending)
        results = []
        for _, row in df_sorted.head(top_n).iterrows():
            results.append({
                "code": str(row.get('代码', '')),
                "name": str(row.get('名称', '')),
                "price": self._safe_float(row.get('最新价')),
                "change_pct": self._safe_float(row.get('涨跌幅')),
                "main_inflow": self._safe_float(row.get('主力净流入-净额')),
                "main_inflow_pct": self._safe_float(row.get('主力净流入-净占比')),
                "large_inflow": self._safe_float(row.get('大单净流入-净额')),
                "medium_inflow": self._safe_float(row.get('中单净流入-净额')),
                "small_inflow": self._safe_float(row.get('小单净流入-净额')),
                "amount": self._safe_float(row.get('成交额')),
                "turnover_rate": self._safe_float(row.get('换手率')),
            })

        logger.info(f"查询资金流向榜: top_n={top_n}, 返回 {len(results)} 条")
        return results
