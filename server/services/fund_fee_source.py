"""
场外基金费率数据源（eastmoney 天天基金）

用途：为 fund_catalog_sync 提供「场外 ETF 联接基金」的费率与基础信息，
把手工维护的 fund_fee_rules 白名单升级为程序化同步。

数据来源：
1. 基金档案-购买信息页 https://fundf10.eastmoney.com/jjfl_{code}.html
   - 申购费率   -> purchase_fee_tiers（**取平台优惠费率**，即 "原费率|优惠费率" 的后者）
   - 赎回费率   -> redemption_fee_tiers
   - 运作费用   -> management_fee_rate / custody_fee_rate / sales_service_fee_rate
   - 申购与赎回金额 -> min_purchase_amount
   - 交易状态   -> 申购状态（仅「开放申购」可交易）
2. 移动端基础信息 API FundMNBasicInformation
   - SHORTNAME / FTYPE / INDEXNAME / INDEXCODE（供风险分类）
   - MAXSG（单日累计申购上限，供「限大额」基金校验；开放申购基金返回哨兵值 -> None）

解析规则已用现有 21 条种子数据回归验证：申购费率 21/21、赎回费率 20/21 一致
（唯一差异为货币基金 000198，属特例，同步时排除）。

注意：货基不适用本模块（净值恒 1.0，赎回表含「强制赎回费」长文本条款，
且无申购起点），由代码内 MONEY_FUND_CODE 特例维护。
"""
import logging
import re
from io import StringIO
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

JJFL_URL = "https://fundf10.eastmoney.com/jjfl_{code}.html"
BASIC_URL = (
    "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNBasicInformation"
    "?FCODE={code}&deviceid=1&plat=Iphone&product=EFund&version=1"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fundf10.eastmoney.com/",
}
TIMEOUT = 15

# 平台佣金（与现有种子一致，平台级常量，非基金属性）
DEFAULT_COMMISSION_RATE = 0.0003


# ==================== 数值解析工具（纯函数，可单测） ====================

def _num_cn(text) -> Optional[float]:
    """'100万元' -> 1000000.0, '1000元' -> 1000.0, '---' -> None"""
    if not text:
        return None
    s = str(text).replace(",", "").strip()
    m = re.search(r"([\d.]+)\s*万", s)
    if m:
        return float(m.group(1)) * 10000
    m = re.search(r"([\d.]+)", s)
    return float(m.group(1)) if m else None


def _pct(text) -> Optional[float]:
    """'1.20%' -> 0.012；'每笔1000元' / '---' -> None"""
    m = re.search(r"([\d.]+)\s*%", str(text or ""))
    return _rnd(float(m.group(1)) / 100) if m else None


def _fixed_fee(text) -> Optional[float]:
    """'每笔1000元' -> 1000.0，否则 None"""
    m = re.search(r"每笔\s*([\d.]+)\s*元", str(text or ""))
    return float(m.group(1)) if m else None


# 金额上界："小于100万元" / "小于等于500万元" / "小于1000元"
_AMOUNT_BOUND_RE = re.compile(r"小于\s*(?:等于)?\s*([\d.]+)\s*(万)?\s*元")

# 持有期限表述：限定词 + 数值 + 单位（年/个月/月/天）
_TERM_RE = re.compile(r"(大于等于|大于|小于等于|小于)?\s*(\d+(?:\.\d+)?)\s*(年|个月|月|天)")

# 期限单位换算成天（1年=365天，1个月=30天，与现有种子数据一致）
_UNIT_DAYS = {"年": 365, "个月": 30, "月": 30, "天": 1}


def _bound_value(match) -> float:
    """把 _AMOUNT_BOUND_RE 的匹配结果换算成元"""
    value = float(match.group(1))
    return value * 10000 if match.group(2) else value


def _term_days(num, unit) -> int:
    """期限 -> 天数：('1', '年') -> 365"""
    return int(round(float(num) * _UNIT_DAYS[unit]))


def _rnd(x: float) -> float:
    """消除浮点误差：0.0007000000000000001 -> 0.0007"""
    return round(x, 8)


def _amount(x: Optional[float]):
    """金额归一为 int（1000000.0 -> 1000000），保持与非金额值可比"""
    if x is None:
        return None
    return int(x) if float(x).is_integer() else x


# 单日累计申购上限的「无限额」哨兵：开放申购的基金返回 1000 亿元
# （实测 110020/000071/161831 均为 100000000000）。用阈值判定而非等值比较 ——
# 哨兵值本身没有语义，哪天被调整成别的数也不该让逻辑失效。
UNLIMITED_MAX_SG_THRESHOLD = 1e10


def parse_max_purchase_amount(value) -> Optional[float]:
    """
    移动端 MAXSG 字段 -> 单日累计申购上限（元）。

    MAXSG 即天天基金页面「日累计申购限额」，实测：
    - 开放申购基金 -> 100000000000（哨兵，视为无限额）
    - 限大额基金   -> 真实上限（如 012348 为 1000）

    返回 None 表示无限额（哨兵值 / 缺字段 / 非法值 / 非正数）。
    """
    if value is None:
        return None
    try:
        amount = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if amount <= 0 or amount >= UNLIMITED_MAX_SG_THRESHOLD:
        return None
    return _amount(amount)


SHARE_CLASS_LETTERS = ("A", "C", "E", "I", "Y", "D", "F", "H", "R")


def parse_share_class(fund_name: str) -> str:
    """
    从基金简称解析份额类别：结尾为份额字母则取之，否则默认 'A'。

    注：share_class 是展示字段（varchar(1)，无 CHECK 约束，代码不参与计费），
    解析不到时默认 'A' 不会影响交易，因此不做复杂推断。
    """
    name = (fund_name or "").strip().upper()
    if name and name[-1] in SHARE_CLASS_LETTERS:
        return name[-1]
    return "A"


# ==================== 费率分档解析（纯函数，可单测） ====================

def parse_purchase_tiers(rows) -> list:
    """
    申购费率分档。rows 为 (适用金额文本, 费率文本) 序列。

    规则（已回归验证）：
    - 费率取「平台优惠费率」：文本含 '|' 时取最后一段（原费率|优惠费率）
    - '每笔N元' -> {"rate": 0, "fixed_fee": N}，作为无金额兜底档（放最后）
    - '小于X万元' -> {"rate", "amount": X*10000}（_match_purchase_tier 按 amount 命中）
    - '大于等于X万元'(末档) -> {"rate", "amount", "inclusive": True}
    - '---'（如 C 类全免） -> {"rate": 0}（匹配所有金额的兜底档）
    """
    tiers, universal = [], None
    for amount_text, rate_text in rows:
        parts = [p.strip() for p in str(rate_text).split("|")]
        use = parts[-1] if len(parts) > 1 else parts[0]   # 平台优惠费率
        fixed = _fixed_fee(use)
        if fixed is not None:
            universal = {"rate": 0, "fixed_fee": fixed}
            continue
        rate = _pct(use)
        if rate is None:
            continue
        text = str(amount_text)
        up = _AMOUNT_BOUND_RE.search(text)
        if up:
            tiers.append({"rate": rate, "amount": _amount(_bound_value(up))})
        elif "大于" in text:
            tiers.append({"rate": rate, "amount": _amount(_num_cn(text)), "inclusive": True})
        else:
            universal = {"rate": rate}
    if universal is not None:
        tiers.append(universal)
    return tiers


def parse_redemption_tiers(rows) -> list:
    """
    赎回费率分档。rows 为 (适用期限文本, 赎回费率文本) 序列。

    days 为该档的「排他上界」，即下一档的起始持有天数：
    - 页面期限可能用 年/个月/天 混合表述，统一折算为天（1年=365天，1个月=30天，
      与现有种子一致：1年档写作 {"days": 365}，2年档写作 {"days": 730}）
    - '大于等于A，小于B' 取上界 B；'小于B' 同样取 B
    - '小于等于N天' -> N+1（"≤N天"的排他上界是 N+1，已回归验证）
    - 末档 '大于等于N'（无上界）-> {"days": N, rate, "inclusive": True}
    - 无任何期限表述（如"不限"）-> 丢弃该行，不臆造档位
    """
    tiers = []
    for days_text, rate_text in rows:
        rate = _pct(rate_text)
        if rate is None:
            continue
        terms = _TERM_RE.findall(str(days_text))
        if not terms:
            logger.warning(f"赎回费率行无期限表述，已丢弃: {days_text!r} -> {rate_text!r}")
            continue
        upper = [t for t in terms if t[0] in ("小于", "小于等于")]
        if upper:
            qual, num, unit = upper[-1]
            days = _term_days(num, unit)
            if qual == "小于等于" and unit == "天":
                days += 1
            tiers.append({"days": days, "rate": rate})
        else:
            _, num, unit = terms[-1]
            tiers.append({"days": _term_days(num, unit), "rate": rate, "inclusive": True})
    return tiers


# ==================== 页面抓取 ====================

def _read_sections(soup) -> dict:
    """把 jjfl 页各 <h4> 小节标题 -> DataFrame 收集起来"""
    sections = {}
    for h in soup.find_all("h4", class_="t"):
        title = re.sub(r"\s+", " ", h.get_text(strip=True))
        table = h.find_next("table")
        if table is None:
            continue
        try:
            sections[title] = pd.read_html(StringIO(str(table)))[0]
        except Exception as e:
            logger.debug(f"解析小节 {title} 表格失败: {e}")
    return sections


def _kv_pairs(df: pd.DataFrame) -> dict:
    """把「键值交替」的宽表（0/1,2/3...）拍平成 {键: 值}"""
    flat = {}
    for r in range(df.shape[0]):
        for c in range(0, df.shape[1] - 1, 2):
            key = str(df.iloc[r, c]).strip()
            val = str(df.iloc[r, c + 1]).strip()
            if key and key != "nan":
                flat[key] = val
    return flat


def fetch_jjfl(code: str) -> Optional[dict]:
    """
    抓取并解析基金档案-购买信息页。

    返回:
        {
          "purchase_fee_tiers": list, "redemption_fee_tiers": list,
          "management_fee_rate": float, "custody_fee_rate": float,
          "sales_service_fee_rate": float, "min_purchase_amount": float|None,
          "subscribe_status": str, "redeem_status": str,
        }
        或 None（页面结构异常）
    """
    try:
        resp = requests.get(JJFL_URL.format(code=code), headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = "utf-8"
    except Exception as e:
        logger.warning(f"抓取 {code} 购买信息页失败: {e}")
        return None

    sections = _read_sections(BeautifulSoup(resp.text, "html.parser"))
    if not sections:
        logger.warning(f"{code} 购买信息页无有效小节")
        return None

    out = {}
    try:
        if "申购费率" in sections:
            df = sections["申购费率"]
            out["purchase_fee_tiers"] = parse_purchase_tiers(
                zip(df.iloc[:, 0], df.iloc[:, 1])
            )
        if "赎回费率" in sections:
            df = sections["赎回费率"]
            out["redemption_fee_tiers"] = parse_redemption_tiers(
                zip(df.iloc[:, 0], df.iloc[:, 1])
            )
        if "运作费用" in sections:
            kv = _kv_pairs(sections["运作费用"])
            out["management_fee_rate"] = _pct(kv.get("管理费率", ""))
            out["custody_fee_rate"] = _pct(kv.get("托管费率", ""))
            out["sales_service_fee_rate"] = _pct(kv.get("销售服务费率", ""))
        if "申购与赎回金额" in sections:
            kv = _kv_pairs(sections["申购与赎回金额"])
            out["min_purchase_amount"] = _num_cn(kv.get("申购起点", ""))
        if "交易状态" in sections:
            kv = _kv_pairs(sections["交易状态"])
            out["subscribe_status"] = kv.get("申购状态", "")
            out["redeem_status"] = kv.get("赎回状态", "")
    except Exception as e:
        logger.warning(f"解析 {code} 费率小节异常: {e}")
        return None
    return out


def fetch_basic_info(code: str) -> Optional[dict]:
    """
    抓取移动端基础信息，用于基金名称 / 类型 / 跟踪标的（供风险分类）与申购上限。

    返回: {"fund_name", "ftype", "index_name", "index_code", "max_purchase_amount"}
          或 None（max_purchase_amount 为 None 表示无限额）
    """
    try:
        resp = requests.get(BASIC_URL.format(code=code), headers=HEADERS, timeout=TIMEOUT)
        data = (resp.json() or {}).get("Datas") or {}
    except Exception as e:
        logger.warning(f"抓取 {code} 基础信息失败: {e}")
        return None
    if not data:
        return None
    return {
        "fund_name": data.get("SHORTNAME") or "",
        "ftype": data.get("FTYPE") or "",
        "index_name": data.get("INDEXNAME") or "",
        "index_code": data.get("INDEXCODE") or "",
        "max_purchase_amount": parse_max_purchase_amount(data.get("MAXSG")),
    }
