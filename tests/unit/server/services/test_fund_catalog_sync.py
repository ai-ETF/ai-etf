"""fund_catalog_sync 单元测试：场外 ETF 联接基金的筛选、组装与批量写入。

模块名称：server/services/fund_catalog_sync.py
所测功能：is_off_exchange_linked_fund（准入筛选）、resolve_delays（T+N 类别规则）、
         build_fee_rule / build_risk_profile（落库行组装）、run（统计与分批写入）
测试方法：纯函数直测 + 假客户端替身（不联网、不连 Supabase）。

准入原则：申购/赎回费率分档抓不到即**不写库**（宁可不支持，不用默认费率兜底）。
"""
import pytest

from server.services.fund_catalog_sync import (
    UPSERT_BATCH_SIZE,
    FundCatalogSync,
    build_fee_rule,
    build_risk_profile,
    is_off_exchange_linked_fund,
    resolve_delays,
)


# ==================== 准入筛选 ====================


@pytest.mark.parametrize("名称,类型", [
    ("易方达沪深300ETF联接A", "指数型-股票"),
    ("天弘中证光伏ETF联接C", "指数型-股票"),
    ("华夏恒生ETF联接A", "指数型-海外股票"),
    ("华安黄金ETF联接A", "指数型-其他"),
])
def test_场外ETF联接基金被纳入(名称, 类型):
    assert is_off_exchange_linked_fund(名称, 类型) is True


def test_改名后不含联接的基金_名称筛选识别不到():
    """161831 已更名为「银华恒生国企指数(QDII-LOF)A」，名称里没有「联接」。

    名称筛选对它无能为力 —— 这类基金靠 merge_candidates 与现有白名单求并集兜住，
    见 test_现有白名单中的基金不会被改名挤掉。
    """
    assert is_off_exchange_linked_fund("银华恒生国企指数(QDII-LOF)A", "指数型-海外股票") is False


def test_名称含指数且类型为指数型_即使无ETF字样也纳入():
    """部分老联接基金名称不带 ETF 字样。"""
    assert is_off_exchange_linked_fund("某某中证500指数联接A", "指数型-股票") is True


@pytest.mark.parametrize("名称", [
    "易方达沪深300ETF",             # 场内 ETF 本身，不是场外联接
    "天弘余额宝货币市场基金",        # 货基
    "易方达中债1-3年政金债",        # 债券
])
def test_非场外联接基金被排除(名称):
    assert is_off_exchange_linked_fund(名称, "指数型-股票") is False


@pytest.mark.parametrize("名称,原因", [
    ("广发纳斯达克100ETF联接美元(QDII)A", "外币份额：金额与净值口径不是人民币"),
    ("华夏恒生ETF联接现汇", "外币份额：现汇"),
    ("华夏恒生ETF联接现钞", "外币份额：现钞"),
    ("富国上证指数ETF联接A(后端)", "后端收费：申购费模型是前端"),
    ("南方中证500ETF联接(LOF)A(后端)", "后端收费"),
    ("某某沪深300ETF联接定开", "定期开放：封闭期内不可赎回"),
    ("某某沪深300ETF联接封闭", "封闭期"),
    ("某某沪深300ETF联接持有期", "持有期限制"),
    ("某某中债1-3年债券ETF联接A", "债券"),
])
def test_交易模型不适用的份额被排除(名称, 原因):
    assert is_off_exchange_linked_fund(名称, "指数型-股票") is False, 原因


def test_人民币份额不被外币规则误伤():
    """「人民币」份额是合法的境内计价份额，必须保留。"""
    assert is_off_exchange_linked_fund("易方达纳斯达克100ETF联接(QDII)C(人民币)", "指数型-海外股票") is True


# ==================== 候选合并：现有白名单兜底 ====================


def test_现有白名单中的基金不会被改名挤掉():
    """核心防回归：161831 改名后名称筛选识别不到，必须靠白名单并集保留。"""
    名称候选 = [{"code": "110020", "name": "易方达沪深300ETF联接A", "ftype": "指数型-股票"}]
    合并 = FundCatalogSync.merge_candidates(名称候选, ["110020", "161831"])
    代码 = [c["code"] for c in 合并]
    assert 代码 == ["110020", "161831"]


def test_合并结果按代码排序且不重复():
    名称候选 = [
        {"code": "110020", "name": "易方达沪深300ETF联接A", "ftype": "指数型-股票"},
        {"code": "000051", "name": "华夏沪深300ETF联接A", "ftype": "指数型-股票"},
    ]
    合并 = FundCatalogSync.merge_candidates(名称候选, ["110020"])
    assert [c["code"] for c in 合并] == ["000051", "110020"]


def test_白名单并集条目可被后续抓取补齐名称():
    """并集新加入的条目只是占位（name 为空），由 sync_one 抓真实名称覆盖。"""
    合并 = FundCatalogSync.merge_candidates([], ["161831"])
    assert 合并 == [{"code": "161831", "name": "", "ftype": ""}]


# ==================== T+N 类别规则 ====================


def test_QDII基金用T加2确认七日到账():
    assert resolve_delays(3) == (2, 7)


def test_境内基金用T加1确认三日到账():
    assert resolve_delays(1) == (1, 3)


# ==================== 落库行组装 ====================

完整jjfl = {
    "purchase_fee_tiers": [{"rate": 0.001, "amount": 5000000}, {"rate": 0, "fixed_fee": 1000}],
    "redemption_fee_tiers": [{"days": 7, "rate": 0.015}, {"days": 7, "rate": 0.0, "inclusive": True}],
    "management_fee_rate": 0.005,
    "custody_fee_rate": 0.001,
    "sales_service_fee_rate": 0.0,
    "min_purchase_amount": 10.0,
    "subscribe_status": "开放申购",
    "redeem_status": "开放赎回",
}
风险_境内 = {"breadth": 2, "volatility": 2, "market": 1, "board": 1,
             "risk_level": "aggressive", "risk_label": "较高风险", "needs_review": False}


def test_组装费率规则_完整数据():
    rule = build_fee_rule("110020", 完整jjfl, {"fund_name": "易方达沪深300ETF联接A"}, 风险_境内)
    assert rule["fund_code"] == "110020"
    assert rule["fund_name"] == "易方达沪深300ETF联接A"
    assert rule["fund_type"] == "of"
    assert rule["share_class"] == "A"
    assert rule["min_purchase_amount"] == 10.0
    assert rule["management_fee_rate"] == 0.005
    assert rule["confirm_delay"] == 1
    assert rule["redeem_settle_delay"] == 3
    assert rule["purchase_fee_tiers"] == 完整jjfl["purchase_fee_tiers"]
    assert rule["redemption_fee_tiers"] == 完整jjfl["redemption_fee_tiers"]


def test_组装费率规则_QDII走T加2七日():
    rule = build_fee_rule("000071", 完整jjfl, {"fund_name": "华夏恒生ETF联接A"},
                           dict(风险_境内, market=3))
    assert (rule["confirm_delay"], rule["redeem_settle_delay"]) == (2, 7)


def test_缺少申购分档_拒绝写库():
    jjfl = dict(完整jjfl, purchase_fee_tiers=[])
    assert build_fee_rule("110020", jjfl, {"fund_name": "某某联接A"}, 风险_境内) is None


def test_缺少赎回分档_拒绝写库():
    """货币基金即此形态（赎回表无期限表述），必须拒绝而非按免赎回费放行。"""
    jjfl = dict(完整jjfl, redemption_fee_tiers=[])
    assert build_fee_rule("000198", jjfl, {"fund_name": "天弘余额宝货币市场基金"}, 风险_境内) is None


def test_基础信息缺失时退化为用代码作名称():
    rule = build_fee_rule("110020", 完整jjfl, None, 风险_境内)
    assert rule["fund_name"] == "110020"


def test_组装风险画像():
    profile = build_risk_profile("110020", 风险_境内)
    assert profile == {
        "fund_code": "110020",
        "breadth_score": 2,
        "volatility_score": 2,
        "market_score": 1,
        "board_score": 1,
        "risk_level": "aggressive",
        "risk_label": "较高风险",
    }


# ==================== 批量同步：统计与分批写入 ====================

class _假表:
    def __init__(self, 记录, 表名):
        self._记录, self._表名 = 记录, 表名

    def upsert(self, rows, on_conflict=None):
        self._记录.append((self._表名, rows, on_conflict))
        return self

    def execute(self):
        return self


class _假客户端:
    def __init__(self):
        self.记录 = []

    def table(self, name):
        return _假表(self.记录, name)


def _假结果(code):
    return {
        "fee_rule": {"fund_code": code},
        "risk_profile": {"fund_code": code},
        "needs_review": False,
    }


def _跑同步(每只结果):
    """用假客户端 + 假 sync_one 跑一次同步，返回 (统计, 写入记录)。"""
    svc = FundCatalogSync()
    svc._client = _假客户端()
    svc.sync_one = lambda code: 每只结果.get(code)
    stats = svc.run(codes=list(每只结果), interval=0)
    return stats, svc._client.记录


def test_同步统计区分写入与跳过():
    每只结果 = {"000001": _假结果("000001"), "000002": None, "000003": _假结果("000003")}
    stats, _ = _跑同步(每只结果)
    assert stats["discovered"] == 3
    assert stats["synced"] == 2
    assert stats["skipped"] == 1
    assert stats["failed"] == 0
    assert sorted(stats["codes"]) == ["000001", "000003"]


def test_单只抓取异常计入失败且不中断整批():
    svc = FundCatalogSync()
    svc._client = _假客户端()

    def _有时抛错(code):
        if code == "000002":
            raise RuntimeError("抓取超时")
        return _假结果(code)

    svc.sync_one = _有时抛错
    stats = svc.run(codes=["000001", "000002", "000003"], interval=0)
    assert stats["synced"] == 2
    assert stats["failed"] == 1
    assert "000002" not in stats["codes"]


def test_写入两张表且按fund_code幂等覆盖():
    _, 记录 = _跑同步({"000001": _假结果("000001")})
    表名 = [r[0] for r in 记录]
    assert 表名 == ["fund_fee_rules", "fund_risk_profiles"]
    assert all(r[2] == "fund_code" for r in 记录)
    assert 记录[0][1] == [{"fund_code": "000001"}]


def test_超过批次上限时分多次写入():
    """数千只基金逐只 upsert 会打爆请求数，必须按 UPSERT_BATCH_SIZE 分批。"""
    数量 = UPSERT_BATCH_SIZE * 2 + 1
    每只结果 = {f"{i:06d}": _假结果(f"{i:06d}") for i in range(数量)}
    stats, 记录 = _跑同步(每只结果)

    assert stats["synced"] == 数量
    每表批次数 = len(记录) // 2
    assert 每表批次数 == 3                      # 50 + 50 + 1
    assert [len(r[1]) for r in 记录 if r[0] == "fund_fee_rules"] == [50, 50, 1]


def test_无数据时不写库():
    svc = FundCatalogSync()
    svc._client = _假客户端()
    svc.sync_one = lambda code: None
    svc.run(codes=["000001"], interval=0)
    assert svc._client.记录 == []


# ==================== 准入：申购状态 ====================


def _jjfl状态(状态):
    return {
        "purchase_fee_tiers": [{"rate": 0.001, "amount": 1000000}],
        "redemption_fee_tiers": [{"days": 7, "rate": 0.015}],
        "management_fee_rate": 0.005,
        "custody_fee_rate": 0.001,
        "sales_service_fee_rate": 0.0,
        "min_purchase_amount": 10.0,
        "subscribe_status": 状态,
        "redeem_status": "开放赎回",
    }


def _基础信息(上限=None):
    return {
        "fund_name": "天弘恒生科技ETF联接A",
        "ftype": "指数型-海外股票",
        "index_name": "恒生科技指数",
        "index_code": "HSTECH",
        "max_purchase_amount": 上限,
    }


def _打桩数据源(monkeypatch, 状态, 上限=None):
    from server.services import fund_catalog_sync as mod
    monkeypatch.setattr(mod, "fetch_jjfl", lambda code: _jjfl状态(状态))
    monkeypatch.setattr(mod, "fetch_basic_info", lambda code: _基础信息(上限))


@pytest.mark.parametrize("状态,上限", [("开放申购", None), ("限大额", 1000.0)])
def test_可交易申购状态被准入(monkeypatch, 状态, 上限):
    """「限大额」是「开放申购 + 单日上限」，用户买不超过上限的金额本应成交。"""
    _打桩数据源(monkeypatch, 状态, 上限=上限)
    assert FundCatalogSync().sync_one("012348") is not None


@pytest.mark.parametrize("状态", ["暂停申购", "封闭期", "认购期"])
def test_不可申购状态仍写入并如实记录(monkeypatch, 状态):
    """状态写入目录、能否买交给交易侧判定。

    这样基金从「开放申购」转为「暂停申购」时，库里那行的状态会跟着更新
    （原先整只跳过 → 旧行原封不动 → 依然可买）。
    """
    _打桩数据源(monkeypatch, 状态)
    result = FundCatalogSync().sync_one("012348")
    assert result is not None
    assert result["fee_rule"]["subscribe_status"] == 状态


def test_未取到申购状态时拒绝写入(monkeypatch):
    """状态抓不到 = 这次抓取不可信，整只跳过（fail-closed）。

    与「暂停申购」的区别：那是抓到了真实状态，可以如实落库。
    """
    _打桩数据源(monkeypatch, "")
    assert FundCatalogSync().sync_one("012348") is None


@pytest.mark.parametrize("状态", ["开放申购", "限大额"])
def test_申购状态如实落库(monkeypatch, 状态):
    _打桩数据源(monkeypatch, 状态, 上限=1000.0 if 状态 == "限大额" else None)
    assert FundCatalogSync().sync_one("012348")["fee_rule"]["subscribe_status"] == 状态


def test_限大额基金的上限落库(monkeypatch):
    _打桩数据源(monkeypatch, "限大额", 上限=1000.0)
    result = FundCatalogSync().sync_one("012348")
    assert result["fee_rule"]["max_purchase_amount"] == 1000.0


def test_开放申购基金上限为空(monkeypatch):
    """开放申购基金 MAXSG 为哨兵值，解析后为 None（无限额）。"""
    _打桩数据源(monkeypatch, "开放申购", 上限=None)
    result = FundCatalogSync().sync_one("110020")
    assert result["fee_rule"]["max_purchase_amount"] is None


# ---------- 限大额却拿不到上限：写入但标记为不可申购 ----------


def test_限大额但取不到上限时仍写入(monkeypatch):
    """「限大额」取不到上限只可能是 MAXSG 解析失败。此时不写库会让它彻底消失，
    写库又怕 NULL 被当成无限额 —— 折中是写库但状态=限大额、上限=NULL，
    交易侧据此拒绝申购。于是它变成一条可查询的待干预记录。
    """
    _打桩数据源(monkeypatch, "限大额", 上限=None)
    result = FundCatalogSync().sync_one("012348")

    assert result is not None
    assert result["fee_rule"]["subscribe_status"] == "限大额"
    assert result["fee_rule"]["max_purchase_amount"] is None


def test_限大额且基础信息整体缺失时仍写入(monkeypatch):
    """fetch_basic_info 整体失败（basic=None）同样拿不到上限 —— 同样写库并标记。"""
    from server.services import fund_catalog_sync as mod
    monkeypatch.setattr(mod, "fetch_jjfl", lambda code: _jjfl状态("限大额"))
    monkeypatch.setattr(mod, "fetch_basic_info", lambda code: None)
    result = FundCatalogSync().sync_one("012348")

    assert result is not None
    assert result["fee_rule"]["subscribe_status"] == "限大额"
    assert result["fee_rule"]["max_purchase_amount"] is None


def test_开放申购且基础信息缺失时仍准入(monkeypatch):
    """无限额是「开放申购」的合法值，不能与解析失败混为一谈 —— 缺失不拦。"""
    from server.services import fund_catalog_sync as mod
    monkeypatch.setattr(mod, "fetch_jjfl", lambda code: _jjfl状态("开放申购"))
    monkeypatch.setattr(mod, "fetch_basic_info", lambda code: None)
    assert FundCatalogSync().sync_one("110020") is not None


def test_组装费率规则_带单日累计上限():
    rule = build_fee_rule(
        "012348",
        dict(完整jjfl, subscribe_status="限大额"),
        {"fund_name": "天弘恒生科技ETF联接A", "max_purchase_amount": 1000.0},
        风险_境内,
    )
    assert rule["max_purchase_amount"] == 1000.0
    assert rule["subscribe_status"] == "限大额"


def test_组装费率规则_基础信息缺失时上限为空():
    rule = build_fee_rule("110020", 完整jjfl, None, 风险_境内)
    assert rule["max_purchase_amount"] is None



# ==================== 非空列空值策略（2026-10-03 生产事故回归） ====================
#
# fund_fee_rules 的运作费率/申购起点都是 NOT NULL 列。显式写入 None 会覆盖列 DEFAULT
# 并触发 23502，异常抛穿 run() → 整轮同步中止（生产实测崩于第 50 只，正是首次 flush）。


def test_销售服务费率缺失时按A类语义落0():
    """A 类不收销售服务费（列注释即「A类=0」）—— 落 0.0 是业务事实，不是猜。"""
    jjfl = dict(完整jjfl, sales_service_fee_rate=None)
    rule = build_fee_rule("110020", jjfl, {"fund_name": "某某ETF联接A"}, 风险_境内)
    assert rule is not None
    assert rule["sales_service_fee_rate"] == 0.0


def test_销售服务费率有值时不被兜底覆盖():
    """C 类有销售服务费，不能被 0.0 抹掉。"""
    jjfl = dict(完整jjfl, sales_service_fee_rate=0.002)
    rule = build_fee_rule("001595", jjfl, {"fund_name": "某某ETF联接C"}, 风险_境内)
    assert rule["sales_service_fee_rate"] == 0.002


@pytest.mark.parametrize("字段,说明", [
    ("management_fee_rate", "管理费率"),
    ("custody_fee_rate", "托管费率"),
    ("min_purchase_amount", "申购起点"),
])
def test_交易规则字段缺失时跳整只基金(字段, 说明):
    """这些都是真实交易规则，页面缺失即不可信 —— fail-closed 跳过，不写库。"""
    jjfl = dict(完整jjfl, **{字段: None})
    assert build_fee_rule("110020", jjfl, {"fund_name": "某某ETF联接A"}, 风险_境内) is None


def test_组装结果不含非空列的None():
    """回归：任一组装出的行里，fund_fee_rules 的非空列都不得为 None。"""
    rule = build_fee_rule(
        "110020", dict(完整jjfl, sales_service_fee_rate=None), None, 风险_境内
    )
    for 列 in ("fund_code", "fund_name", "fund_type", "share_class",
               "management_fee_rate", "custody_fee_rate", "sales_service_fee_rate",
               "min_purchase_amount", "confirm_delay", "redeem_settle_delay",
               "commission_rate", "purchase_fee_tiers", "redemption_fee_tiers"):
        assert rule[列] is not None, f"{列} 为 None 会触发 NOT NULL 约束"


# ==================== 写入降级：单只坏数据不拖垮整轮 ====================

class _可失败假表:
    """execute() 时才抛错，且多行（批）写入整体失败 —— 与 PostgREST 批 upsert 的原子性一致。"""

    def __init__(self, 客户端, 表名):
        self._c, self._表名, self._待写 = 客户端, 表名, None

    def upsert(self, rows, on_conflict=None):
        self._待写 = rows
        return self

    def execute(self):
        rows = self._待写
        codes = [r["fund_code"] for r in rows]
        if len(rows) > 1:
            raise RuntimeError("整批写入失败（模拟 23502 非空约束）")
        code = codes[0] if codes else None
        if code and (code in self._c.坏费率 or
                     (self._表名 == "fund_risk_profiles" and code in self._c.坏画像)):
            raise RuntimeError(f"{code} 违反非空约束")
        self._c.记录.append((self._表名, rows))
        return self


class _可失败假客户端:
    def __init__(self, 坏费率=(), 坏画像=()):
        self.记录 = []
        self.坏费率 = set(坏费率)
        self.坏画像 = set(坏画像)

    def table(self, name):
        return _可失败假表(self, name)


def _跑同步_可失败(每只结果, 坏费率=(), 坏画像=()):
    svc = FundCatalogSync()
    svc._client = _可失败假客户端(坏费率, 坏画像)
    svc.sync_one = lambda code: 每只结果.get(code)
    stats = svc.run(codes=list(每只结果), interval=0)
    return stats, svc._client.记录


def test_批量写入失败时降级逐行_坏行计入失败且不中断():
    每只结果 = {"000001": _假结果("000001"), "000002": _假结果("000002")}
    stats, 记录 = _跑同步_可失败(每只结果, 坏费率={"000002"})

    assert stats["synced"] == 1
    assert stats["failed"] == 1
    assert stats["codes"] == ["000001"]
    写入的代码 = [r["fund_code"] for _, rows in 记录 for r in rows]
    assert "000002" not in 写入的代码           # 坏行不落库
    assert 写入的代码.count("000001") == 2      # 好行两张表都写入


def test_费率行失败的基金不写风险画像():
    """避免出现「有风险画像、无费率规则」的孤儿行。"""
    每只结果 = {"000001": _假结果("000001"), "000002": _假结果("000002")}
    _, 记录 = _跑同步_可失败(每只结果, 坏费率={"000002"})

    画像表写入 = [rows for 表名, rows in 记录 if 表名 == "fund_risk_profiles"]
    assert all(r["fund_code"] != "000002" for rows in 画像表写入 for r in rows)


def test_风险画像写入失败不影响该基金计入成功():
    """费率规则是交易准入的依据，画像只是提示材料 —— 画像失败不该让基金掉出白名单。"""
    每只结果 = {"000001": _假结果("000001"), "000002": _假结果("000002")}
    stats, 记录 = _跑同步_可失败(每只结果, 坏画像={"000002"})

    assert stats["synced"] == 2
    assert stats["failed"] == 0
    费率表写入 = [r["fund_code"] for 表名, rows in 记录
                  if 表名 == "fund_fee_rules" for r in rows]
    assert sorted(费率表写入) == ["000001", "000002"]


def test_dry_run只抓取不写库():
    svc = FundCatalogSync()
    svc._client = _假客户端()
    svc.sync_one = lambda code: _假结果(code)
    stats = svc.run(codes=["000001", "000002"], interval=0, dry_run=True)

    assert svc._client.记录 == []
    assert stats["synced"] == 2


# ==================== 并发锁 ====================

def test_同步锁互斥时抛SyncLockBusy(monkeypatch, tmp_path):
    from server.services import fund_catalog_sync as mod
    monkeypatch.setattr(mod, "SYNC_LOCK_PATH", str(tmp_path / "sync.lock"))

    with mod.sync_lock():
        with pytest.raises(mod.SyncLockBusy):
            with mod.sync_lock():
                pass


def test_同步锁释放后可再次获取(monkeypatch, tmp_path):
    from server.services import fund_catalog_sync as mod
    monkeypatch.setattr(mod, "SYNC_LOCK_PATH", str(tmp_path / "sync.lock"))

    with mod.sync_lock():
        pass
    with mod.sync_lock():
        pass
