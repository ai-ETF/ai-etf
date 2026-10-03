"""
场外 ETF 联接基金白名单批量同步

背景：`fund_fee_rules` 表是场外基金交易的唯一准入点（查不到规则即拒绝交易），
原本 21 条靠手工维护，无法覆盖市面上大部分场外基金。本模块把它升级为
「程序化白名单同步」：

    全量基金列表 -> 筛出 ETF 联接基金 -> 逐只抓费率/基础信息
    -> 推导风险画像 -> 幂等 upsert 进 fund_fee_rules + fund_risk_profiles

数据来源与解析规则见 server/services/fund_fee_source.py（已用现有 21 条种子回归验证）。

准入原则（与 fund_fee_service「交易规则不能靠猜」一致）：
- 申购状态**如实落库**（开放申购/限大额/暂停申购/封闭期…），能否申购由交易侧按
  subscribe_status 判定（portfolio_service.apply_purchase）；只有状态本身抓不到才整只跳过
- 限大额的「单日累计申购上限」来自 MAXSG 字段并落库，交易时校验
- 申购或赎回费率分档抓不到/为空的不写入 —— 宁可不支持，也不用默认费率兜底
- 货币基金不适用（净值恒 1.0、无申购起点），由 portfolio_service.MONEY_FUND_CODE 特例维护

T+N 采用「按类别判定」而非逐只抓页面：jjfl 页对所有基金都显示 T+1（QDII 也是），
不可用；类别规则经现有种子实证 —— 境内 (1,3)、QDII (2,7)、货基 (1,1)。
"""
import logging
import time
from typing import Optional

from server.services.fund_fee_service import LIMITED_SUBSCRIBE_STATUS
from server.services.fund_fee_source import (
    DEFAULT_COMMISSION_RATE,
    fetch_basic_info,
    fetch_jjfl,
    parse_share_class,
)
from server.services.fund_risk_classifier import classify_fund

logger = logging.getLogger(__name__)

# ==================== 筛选规则 ====================

LINKED_KEYWORD = "联接"

# 名称含这些词的即使带「联接」也不纳入。两类原因：
# 1) 交易模型不适用：货币/债券（非指数联接）、定开/封闭/持有期（封闭期内不可赎回）
# 2) 计价币种不是人民币：美元/现汇/现钞 —— 申购金额与净值都是人民币口径，
#    混入外币份额会导致金额与净值错配
# 3) 后端收费：purchase_fee_tiers 模型是前端收费，后端份额的费率表结构不同
SKIP_NAME_KEYWORDS = (
    "货币", "债券", "定开", "封闭", "持有期",
    "美元", "现汇", "现钞", "港币", "欧元", "日元",
    "后端",
)

# 申购状态常量来自 fund_fee_service（同步侧与交易侧共用同一份定义）。
# 注意：写入白名单**不再**以「状态是否可申购」为门槛 —— 状态一律如实落库，
# 能不能买交给交易侧判定（见 portfolio_service.apply_purchase）。
# 这样「限大额但上限抓不到」和「基金转暂停申购」都能在库里留下痕迹，
# 而不是被静默跳过。

# ==================== T+N 类别规则（与种子一致） ====================

CONFIRM_DELAY_DOMESTIC = 1
SETTLE_DELAY_DOMESTIC = 3
CONFIRM_DELAY_QDII = 2
SETTLE_DELAY_QDII = 7

# ==================== 同步参数 ====================

DEFAULT_REQUEST_INTERVAL = 0.3   # 逐只抓取的间隔（秒），避免被数据源限流
UPSERT_BATCH_SIZE = 50           # 每批写库条数
PROGRESS_LOG_EVERY = 50


def is_off_exchange_linked_fund(fund_name: str, fund_type: str = "") -> bool:
    """
    判断是否属于「场外 ETF 联接基金」。

    规则：名称含「联接」，且名称含 ETF 或基金类型为指数型；
    名称含 货币/债券/定开/封闭/持有期 的排除。
    """
    name = (fund_name or "").strip()
    if not name or LINKED_KEYWORD not in name:
        return False
    if any(kw in name for kw in SKIP_NAME_KEYWORDS):
        return False
    return "ETF" in name.upper() or "指数" in (fund_type or "")


def resolve_delays(market_score: int) -> tuple:
    """按市场属性推导 (申购确认天数, 赎回到账天数)。market_score=3 即 QDII/跨境。"""
    if market_score == 3:
        return CONFIRM_DELAY_QDII, SETTLE_DELAY_QDII
    return CONFIRM_DELAY_DOMESTIC, SETTLE_DELAY_DOMESTIC


def build_fee_rule(code: str, jjfl: dict, basic: dict, risk: dict) -> Optional[dict]:
    """
    组装 fund_fee_rules 的一行。数据不完整（缺分档）返回 None，不写库。

    参数:
        code: 基金代码
        jjfl: fetch_jjfl 的返回值
        basic: fetch_basic_info 的返回值（可能为 None，此时退回代码做名称）
        risk: classify_fund 的返回值
    """
    purchase_tiers = jjfl.get("purchase_fee_tiers")
    redemption_tiers = jjfl.get("redemption_fee_tiers")
    if not purchase_tiers or not redemption_tiers:
        logger.warning(f"{code} 费率分档缺失，跳过（申购={purchase_tiers} 赎回={redemption_tiers}）")
        return None

    fund_name = (basic or {}).get("fund_name") or code
    confirm_delay, settle_delay = resolve_delays(risk["market"])

    return {
        "fund_code": code,
        "fund_name": fund_name,
        "fund_type": "of",
        "management_fee_rate": jjfl.get("management_fee_rate"),
        "custody_fee_rate": jjfl.get("custody_fee_rate"),
        "sales_service_fee_rate": jjfl.get("sales_service_fee_rate"),
        "min_purchase_amount": jjfl.get("min_purchase_amount"),
        # 「限大额」基金的单日累计申购上限；None = 无限额（开放申购基金即此）
        "max_purchase_amount": (basic or {}).get("max_purchase_amount"),
        # 申购状态如实落库；非「开放申购/限大额」的基金仍会被写入目录，
        # 但交易侧据此拒绝申购（只允许赎回）。sync_one 已保证此处非空。
        "subscribe_status": (jjfl.get("subscribe_status") or "").strip(),
        "commission_rate": DEFAULT_COMMISSION_RATE,
        "share_class": parse_share_class(fund_name),
        "purchase_fee_tiers": purchase_tiers,
        "redemption_fee_tiers": redemption_tiers,
        "confirm_delay": confirm_delay,
        "redeem_settle_delay": settle_delay,
    }


def build_risk_profile(code: str, risk: dict) -> dict:
    """组装 fund_risk_profiles 的一行（四维分 + 等级 + 中文标签）。"""
    return {
        "fund_code": code,
        "breadth_score": risk["breadth"],
        "volatility_score": risk["volatility"],
        "market_score": risk["market"],
        "board_score": risk["board"],
        "risk_level": risk["risk_level"],
        "risk_label": risk["risk_label"],
    }


class FundCatalogSync:
    """场外 ETF 联接基金白名单同步服务"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase
            self._client = get_supabase()
        return self._client

    # ==================== 基金发现 ====================

    @staticmethod
    def merge_candidates(by_name: list, existing_codes) -> list:
        """
        名称筛选结果 ∪ 现有白名单代码，按代码去重。

        并上现有白名单是为了兜住「改名后名称不再含关键词」的基金 ——
        例如 161831 银华恒生中国企业ETF联接，天天基金现已更名为
        「银华恒生国企指数(QDII-LOF)A」，名称里没有「联接」二字。
        若不并集，一次同步就会把这类已支持的基金挤出白名单。
        """
        merged = {c["code"]: c for c in by_name}
        for code in existing_codes:
            merged.setdefault(str(code), {"code": str(code), "name": "", "ftype": ""})
        return sorted(merged.values(), key=lambda x: x["code"])

    @staticmethod
    def _discover_by_name() -> list:
        """从全量基金列表按名称/类型筛出候选场外 ETF 联接基金。"""
        import akshare as ak

        df = ak.fund_name_em()
        # 列: 基金代码, 拼音缩写, 基金简称, 基金类型, 拼音全称
        out = []
        for code, _py, name, ftype, _py_full in df.values.tolist():
            if is_off_exchange_linked_fund(name, ftype):
                out.append({"code": str(code), "name": str(name), "ftype": str(ftype)})
        logger.info(f"全量基金 {len(df)} 只 → 名称筛出候选 {len(out)} 只")
        return out

    def _existing_whitelist_codes(self) -> list:
        """读取现有白名单的全部基金代码（分页，避免 PostgREST 单次返回上限截断）。"""
        if not self.client:
            return []
        codes, start, page = [], 0, 1000
        while True:
            resp = (
                self.client.table("fund_fee_rules")
                .select("fund_code")
                .order("fund_code")
                .range(start, start + page - 1)
                .execute()
            )
            batch = resp.data or []
            codes.extend(r["fund_code"] for r in batch if r.get("fund_code"))
            if len(batch) < page:
                return codes
            start += page

    def discover_linked_funds(self) -> list:
        """
        得到本次同步的目标基金列表（名称筛选 ∪ 现有白名单）。

        返回: [{"code", "name", "ftype"}]，按代码排序
        """
        targets = self.merge_candidates(self._discover_by_name(), self._existing_whitelist_codes())
        logger.info(f"本次同步目标基金 {len(targets)} 只")
        return targets

    # ==================== 单只处理 ====================

    def sync_one(self, code: str) -> Optional[dict]:
        """
        抓取并组装单只基金的两张表记录。

        返回: {"fee_rule": dict, "risk_profile": dict, "needs_review": bool}
              或 None（不满足准入条件，原因已记日志）
        """
        jjfl = fetch_jjfl(code)
        if not jjfl:
            logger.warning(f"{code} 购买信息页抓取失败，跳过")
            return None

        # 状态解析不出来 = 这次抓取不可信，整只跳过（fail-closed）。
        # 与「暂停申购」不同：那种是抓到了真实状态，如实落库即可；
        # 这里是连状态都没抓到，不能凭残缺数据写库。
        status = (jjfl.get("subscribe_status") or "").strip()
        if not status:
            logger.warning(f"{code} 未取到申购状态，跳过（不写入白名单）")
            return None

        basic = fetch_basic_info(code)
        fund_name = (basic or {}).get("fund_name") or code

        # 「限大额」按定义必然有上限值，取不到只可能是 MAXSG 解析失败（接口改版/网络异常）。
        # 此时仍然写库（状态=限大额、上限=NULL），但写下的是一条「不可申购」的记录 ——
        # 交易侧见 5.2/6.x 的判定会拒绝申购。这样它既不会漏进「无限额」的口子，
        # 又能在库里被查到：
        #   SELECT * FROM fund_fee_rules WHERE subscribe_status='限大额' AND max_purchase_amount IS NULL;
        if status == LIMITED_SUBSCRIBE_STATUS and (basic or {}).get("max_purchase_amount") is None:
            logger.warning(
                f"{code} 申购状态为「限大额」但未取到单日申购上限（MAXSG 解析失败）；"
                f"仍写入白名单，但该基金将被拒绝申购，需人工干预"
            )

        risk = classify_fund(
            fund_name,
            index_name=(basic or {}).get("index_name", ""),
            ftype=(basic or {}).get("ftype", ""),
        )

        fee_rule = build_fee_rule(code, jjfl, basic, risk)
        if fee_rule is None:
            return None

        return {
            "fee_rule": fee_rule,
            "risk_profile": build_risk_profile(code, risk),
            "needs_review": risk["needs_review"],
        }

    # ==================== 批量同步 ====================

    def run(self, codes: Optional[list] = None, limit: Optional[int] = None,
            interval: float = DEFAULT_REQUEST_INTERVAL) -> dict:
        """
        执行一次全量（或指定代码）同步。

        参数:
            codes: 指定基金代码列表；为空则自动发现全部场外 ETF 联接基金
            limit: 最多处理多少只（调试用），None 表示不限
            interval: 逐只抓取间隔（秒）

        返回: 统计 dict（discovered/synced/skipped/failed/needs_review/codes）
        """
        if codes is None:
            targets = self.discover_linked_funds()
        else:
            targets = [{"code": c, "name": "", "ftype": ""} for c in codes]

        if limit is not None:
            targets = targets[:limit]

        stats = {
            "discovered": len(targets),
            "synced": 0,
            "skipped": 0,
            "failed": 0,
            "needs_review": 0,
            "codes": [],
        }
        pending_fee, pending_risk = [], []

        for i, item in enumerate(targets, 1):
            code = item["code"]
            try:
                result = self.sync_one(code)
            except Exception as e:
                logger.error(f"{code} 同步异常: {e}", exc_info=True)
                stats["failed"] += 1
                continue

            if result is None:
                stats["skipped"] += 1
            else:
                pending_fee.append(result["fee_rule"])
                pending_risk.append(result["risk_profile"])
                stats["synced"] += 1
                stats["codes"].append(code)
                if result["needs_review"]:
                    stats["needs_review"] += 1
                    logger.warning(f"{code} {item['name']} 有维度未命中分类规则，风险分待人工复核")

            if len(pending_fee) >= UPSERT_BATCH_SIZE:
                self._flush(pending_fee, pending_risk)
                pending_fee, pending_risk = [], []

            if i % PROGRESS_LOG_EVERY == 0:
                logger.info(f"[同步进度] {i}/{len(targets)} 已同步={stats['synced']} "
                            f"跳过={stats['skipped']} 失败={stats['failed']}")

            if interval:
                time.sleep(interval)

        self._flush(pending_fee, pending_risk)
        logger.info(
            f"[同步完成] 发现 {stats['discovered']}，写入 {stats['synced']}，"
            f"跳过 {stats['skipped']}，失败 {stats['failed']}，待复核 {stats['needs_review']}"
        )
        return stats

    def _flush(self, fee_rules: list, risk_profiles: list):
        """批量 upsert 两张表（fund_code 唯一，覆盖式更新，与 seed.sql 约定一致）"""
        if not fee_rules:
            return
        if not self.client:
            raise RuntimeError("数据库不可用，白名单同步中止")
        self.client.table("fund_fee_rules").upsert(
            fee_rules, on_conflict="fund_code"
        ).execute()
        self.client.table("fund_risk_profiles").upsert(
            risk_profiles, on_conflict="fund_code"
        ).execute()
        logger.debug(f"写入 {len(fee_rules)} 条费率规则 + 风险画像")
