"""
场外基金风险画像自动分类（按基金属性推导四维得分）

背景：现有 fund_risk_profiles 的 20 条是人工打分（见
docs/交易风险提示/基金风险等级划分设计文档.md），无法规模化。
本模块把设计文档第二章的判定标准实现为「关键词规则」，用于新增基金自动分级。

与 fund_risk_scores.py 的分工：
- 本模块：基金属性（名称/跟踪标的/类型）-> 四维得分
- fund_risk_scores.py：四维得分 -> risk_level / risk_label（纯函数，复用）

维度取值（严格遵循设计文档）：
- breadth  指数广度：1=宽基跨行业, 2=单一行业, 3=窄基主题/概念/风格
- volatility 波动属性：1=大盘价值/防御, 2=消费/周期, 3=高成长/TMT/新能源/商品
- market   市场属性：1=纯A股, 3=QDII/跨境
- board    板块特征：1=主板, 3=科创板/创业板

命中不到规则时给出保守兜底，并置 needs_review=True 供人工复核。
"""
import logging
from typing import Optional

from server.services.fund_risk_scores import calc_risk_level, get_risk_label

logger = logging.getLogger(__name__)

# ==================== 关键词库（按「更具体优先」排序） ====================

# 市场属性：QDII/跨境（market=3）
_MARKET_QDII = [
    "恒生", "港股", "H股", "香港", "纳斯达克", "标普", "道琼斯", "中概",
    "QDII", "海外", "美国", "德国", "日本", "法国", "英国", "欧洲", "亚太",
    "越南", "印度", "沙特", "全球", "国际", "中韩", "中日",
]

# 板块特征：科创板/创业板（board=3）
_BOARD_GROWTH = ["科创", "创业", "北证", "新三板"]

# 指数广度=3：窄基主题/概念/风格（成分股少、赛道极窄）
_BREADTH_THEME = [
    "科创50", "科创100", "科创板50", "创业板", "创业板指",
    "光伏", "新能源", "锂电", "储能", "电池", "氢能", "碳中和", "风电",
    "半导体", "芯片", "集成电路", "消费电子", "面板",
    "人工智能", "AI", "机器人", "云计算", "大数据", "信息安全", "网络安全",
    "游戏", "动漫", "元宇宙", "区块链", "数字经济",
    "军工", "国防", "航天", "航空",
    "创新药", "疫苗", "器械",
    "稀土", "黄金", "贵金属",
    "5G", "智能汽车", "自动驾驶", "汽车电子",
    "种业", "转基因", "恒生科技",
]

# 指数广度=2：单一行业
_BREADTH_INDUSTRY = [
    "银行", "证券", "券商", "保险", "非银", "金融",
    "地产", "房地产", "建筑", "建材", "基建", "工程",
    "通信", "电子", "计算机", "软件", "传媒",
    "汽车", "机械", "化工", "钢铁", "电力", "公用",
    "家电", "家用电器", "消费", "零售", "旅游", "酒店", "纺织", "服装",
    "交通运输", "物流", "港口", "航运", "机场", "高速",
    "采掘", "造纸", "包装", "环保", "水务", "燃气",
    "食品饮料", "食品", "饮料", "白酒",
    "医药", "医疗", "生物",
    "农业", "养殖", "畜牧",
    "有色", "煤炭", "石油", "油气",
]

# 指数广度=1：宽基跨行业
_BREADTH_BROAD = [
    "沪深300", "中证500", "中证1000", "中证800", "中证A500", "中证A50",
    "上证50", "上证180", "上证380", "深证100", "深证成指", "中证100",
    "科创综指", "创业板50", "MSCI", "全指", "A50", "A500",
    "恒生", "纳斯达克100", "标普500",
]

# 波动属性=1：大盘价值/防御
# 注意：此处不放通用的 "国企"——"恒生中国企业" 会被 "国企" 误命中（国|企 相邻），
# 实际该指数是周期/成长属性。需要用完整词 "恒生国企" 精确匹配。
_VOL_DEFENSIVE = [
    "银行", "保险", "非银", "红利", "低波", "公用", "电力", "水务", "燃气",
    "恒生国企", "央企", "上证50", "沪深300", "中证红利", "价值",
]

# 波动属性=2：消费/周期
_VOL_CYCLICAL = [
    "食品饮料", "食品", "饮料", "消费", "家电", "家用电器", "白酒",
    "基建", "建筑", "建材", "地产", "房地产", "工程",
    "汽车", "机械", "化工", "钢铁", "有色", "煤炭", "采掘", "石油",
    "交通运输", "物流", "零售", "旅游", "酒店", "纺织", "服装", "农业", "养殖",
    "医药", "医疗", "恒生", "恒生中国企业",
]

# 波动属性=3：高成长/TMT/新能源/商品
_VOL_GROWTH = [
    "科创", "创业", "北证", "光伏", "新能源", "锂电", "储能", "电池", "氢能",
    "碳中和", "风电", "半导体", "芯片", "集成电路", "电子", "计算机", "通信",
    "5G", "人工智能", "AI", "机器人", "云计算", "大数据", "信息安全",
    "游戏", "传媒", "军工", "国防", "证券", "券商",
    "稀土", "黄金", "贵金属", "油气", "智能汽车", "自动驾驶",
]


def _first_match(text: str, keywords: list) -> Optional[str]:
    for kw in keywords:
        if kw in text:
            return kw
    return None


def classify_fund(fund_name: str, index_name: str = "", ftype: str = "") -> dict:
    """
    按基金属性推导四维得分。

    参数:
        fund_name: 基金简称（如 "易方达沪深300ETF联接A"）
        index_name: 跟踪标的指数名（如 "沪深300指数"，可空）
        ftype: 基金类型（如 "指数型-股票" / "指数型-海外股票"，可空）

    返回:
        {
          "breadth", "volatility", "market", "board": int,
          "risk_level", "risk_label": str,
          "needs_review": bool,          # 有维度未命中规则
        }
    """
    text = f"{fund_name} {index_name}".strip()
    ftype_text = ftype or ""

    # 市场属性：QDII/跨境
    is_qdii = bool(_first_match(text, _MARKET_QDII)) or ("海外" in ftype_text) or ("QDII" in ftype_text.upper())
    market = 3 if is_qdii else 1

    # 板块特征：科创/创业
    board = 3 if _first_match(text, _BOARD_GROWTH) else 1

    # 指数广度：主题(3) > 行业(2) > 宽基(1)，均不命中则默认 2（单一行业）并标记复核
    needs_review = False
    if _first_match(text, _BREADTH_THEME):
        breadth = 3
    elif _first_match(text, _BREADTH_INDUSTRY):
        breadth = 2
    elif _first_match(text, _BREADTH_BROAD):
        breadth = 1
    else:
        breadth = 2
        needs_review = True

    # 波动属性：防御(1) > 周期(2) > 成长(3)，均不命中则默认 2
    if _first_match(text, _VOL_DEFENSIVE):
        volatility = 1
    elif _first_match(text, _VOL_GROWTH):
        volatility = 3
    elif _first_match(text, _VOL_CYCLICAL):
        volatility = 2
    else:
        volatility = 2
        needs_review = True

    risk_level = calc_risk_level(breadth=breadth, volatility=volatility,
                                 market=market, board=board)
    return {
        "breadth": breadth,
        "volatility": volatility,
        "market": market,
        "board": board,
        "risk_level": risk_level,
        "risk_label": get_risk_label(risk_level),
        "needs_review": needs_review,
    }
