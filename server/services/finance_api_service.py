import logging
import re
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class FinanceApiService:
    """通过 AkShare 查询 ETF 基金的费率、净值、规模等事实数据"""

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
