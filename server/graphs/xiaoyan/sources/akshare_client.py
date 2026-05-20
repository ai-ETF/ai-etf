"""
akshare 数据源客户端

封装 akshare 库，获取 ETF 估值、资金流向、成分股等结构化数据。
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)


class AkshareClient:
    """
    akshare ETF 数据客户端

    获取估值、资金流向、成分股等结构化数据。
    注意：akshare 接口可能有调用频率限制，建议配合缓存使用。
    """

    def __init__(self):
        self._akshare = None

    @property
    def ak(self):
        """延迟加载 akshare 模块"""
        if self._akshare is None:
            try:
                import akshare as ak
                self._akshare = ak
            except ImportError:
                logger.error("akshare 未安装，请运行: pip install akshare")
                raise
        return self._akshare

    async def get_etf_spot(self, symbol: str) -> Dict[str, Any]:
        """
        获取 ETF 实时行情

        Args:
            symbol: ETF 代码，如 "510150"

        Returns:
            行情数据字典
        """
        try:
            df = self.ak.fund_etf_spot_em()
            etf_info = df[df["代码"] == symbol]

            if etf_info.empty:
                logger.warning(f"未找到 ETF: {symbol}")
                return {}

            row = etf_info.iloc[0].to_dict()
            return {
                "symbol": symbol,
                "name": row.get("名称", ""),
                "price": float(row.get("最新价", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
                "volume": float(row.get("成交量", 0)),
                "amount": float(row.get("成交额", 0)),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"获取 ETF 行情失败 {symbol}: {e}")
            return {}

    async def get_etf_valuation(
        self,
        symbol: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取 ETF 估值数据（PE、PB、分位）

        注意：akshare 的估值数据接口有限，部分数据需要通过指数估值接口获取。

        Args:
            symbol: ETF 代码
            name: ETF 名称（用于匹配指数）

        Returns:
            估值数据字典
        """
        result = {
            "symbol": symbol,
            "pe": None,
            "pb": None,
            "pe_percentile": None,
            "pb_percentile": None,
            "interpretation": "",
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            # 尝试获取指数估值数据
            # 对于消费类 ETF，可以尝试获取中证消费指数的估值
            df = self.ak.index_value_hist_funddb()

            # 根据名称匹配指数
            if name:
                # 常见 ETF 名称到指数名称的映射
                name_mapping = {
                    "消费": "中证消费",
                    "医药": "中证医药",
                    "科技": "中证科技",
                    "银行": "中证银行",
                    "证券": "中证证券",
                    "军工": "中证军工",
                    "新能源": "中证新能源",
                    "芯片": "国证芯片",
                    "半导体": "国证芯片",
                    "白酒": "中证白酒",
                }

                index_name = None
                for keyword, index in name_mapping.items():
                    if keyword in name:
                        index_name = index
                        break

                if index_name:
                    index_data = df[df["指数代码"].str.contains(index_name, na=False)]
                    if not index_data.empty:
                        row = index_data.iloc[-1].to_dict()
                        result["pe"] = float(row.get("市盈率", 0) or 0)
                        result["pb"] = float(row.get("市净率", 0) or 0)
                        result["pe_percentile"] = row.get("PE百分位", "")
                        result["interpretation"] = f"参考{index_name}指数估值"

        except Exception as e:
            logger.warning(f"获取指数估值失败 {symbol}: {e}")

        return result

    async def get_etf_fund_flow(
        self,
        symbol: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取 ETF 资金流向数据

        Args:
            symbol: ETF 代码
            days: 统计天数

        Returns:
            资金流向数据
        """
        result = {
            "symbol": symbol,
            "days": days,
            "net_flow": None,
            "trend": "unknown",
            "interpretation": "",
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            df = self.ak.fund_etf_fund_daily_em(symbol=symbol)

            if df.empty:
                logger.warning(f"未获取到资金流向数据: {symbol}")
                return result

            # 取最近 N 天数据
            recent = df.head(days)

            if "净流入" in recent.columns:
                net_flow = recent["净流入"].sum()
                result["net_flow"] = float(net_flow)

                if net_flow > 0:
                    result["trend"] = "inflow"
                    result["interpretation"] = f"近{days}天净流入{abs(net_flow)/1e8:.2f}亿"
                else:
                    result["trend"] = "outflow"
                    result["interpretation"] = f"近{days}天净流出{abs(net_flow)/1e8:.2f}亿"

                # 检查流出是否放缓
                if len(recent) >= 10:
                    first_half = recent.head(days // 2)["净流入"].sum()
                    second_half = recent.tail(days // 2)["净流入"].sum()
                    if first_half < second_half:
                        result["trend"] = "outflow_slowing"
                        result["interpretation"] += "，流出速度放缓"

        except Exception as e:
            logger.error(f"获取资金流向失败 {symbol}: {e}")

        return result

    async def get_etf_composition(self, symbol: str) -> Dict[str, Any]:
        """
        获取 ETF 成分股/持仓

        Args:
            symbol: ETF 代码

        Returns:
            成分股数据
        """
        result = {
            "symbol": symbol,
            "holdings": [],
            "total_holdings": 0,
            "top_industries": [],
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            # 尝试获取 ETF 持仓明细
            df = self.ak.fund_etf_detail_info_sina(symbol=symbol)

            if df.empty:
                logger.warning(f"未获取到成分股数据: {symbol}")
                return result

            holdings = df.to_dict("records")
            result["holdings"] = holdings[:10]  # 只保留前10
            result["total_holdings"] = len(holdings)

            # 统计行业分布
            if "行业" in df.columns:
                industry_counts = df["行业"].value_counts().head(5).to_dict()
                result["top_industries"] = [
                    {"industry": k, "count": v}
                    for k, v in industry_counts.items()
                ]

        except Exception as e:
            logger.error(f"获取成分股失败 {symbol}: {e}")

        return result

    async def get_etf_info(self, symbol: str) -> Dict[str, Any]:
        """
        获取 ETF 基金基本信息

        Args:
            symbol: ETF 代码

        Returns:
            基金信息
        """
        result = {
            "symbol": symbol,
            "name": "",
            "type": "",
            "manager": "",
            "scale": None,
            "inception_date": None,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            df = self.ak.fund_etf_fund_info_em(symbol=symbol)

            if df.empty:
                return result

            info = df.to_dict("records")[0] if not df.empty else {}

            result["name"] = info.get("基金简称", "")
            result["type"] = info.get("基金类型", "")
            result["manager"] = info.get("基金管理人", "")
            result["scale"] = info.get("基金规模")

        except Exception as e:
            logger.warning(f"获取 ETF 信息失败 {symbol}: {e}")

        return result

    async def health_check(self) -> Dict[str, Any]:
        """
        检查 akshare 数据源健康状态

        Returns:
            健康状态信息
        """
        status = {
            "status": "unknown",
            "latency_ms": None,
            "error": None,
        }

        try:
            import time
            start = time.time()

            df = self.ak.fund_etf_spot_em()

            latency = (time.time() - start) * 1000
            status["latency_ms"] = round(latency, 2)

            if len(df) > 0:
                status["status"] = "ok"
            else:
                status["status"] = "degraded"
                status["error"] = "返回数据为空"

        except Exception as e:
            status["status"] = "down"
            status["error"] = str(e)

        return status

    async def collect_brief_data(
        self,
        targets: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        收集简要数据（估值、基本面、资金流向）

        Args:
            targets: 标的代码列表

        Returns:
            {symbol: data} 格式的数据
        """
        result = {}

        for symbol in targets:
            data = {
                "valuation": await self.get_etf_valuation(symbol),
                "fund_flow": await self.get_etf_fund_flow(symbol),
                "composition": await self.get_etf_composition(symbol),
            }
            result[symbol] = data

        return result


# 全局单例
_client: Optional[AkshareClient] = None


def get_akshare_client() -> AkshareClient:
    """获取 AkshareClient 单例"""
    global _client
    if _client is None:
        _client = AkshareClient()
    return _client
