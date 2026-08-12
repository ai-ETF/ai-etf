from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class UploadRequest(BaseModel):
    """
    上传请求的数据模型
    定义了上传文档API的请求体结构
    """
    url: str  # 要上传的文档URL
    source: Optional[str] = None  # 文档来源（可选）


class UploadResponse(BaseModel):
    """
    上传响应的数据模型
    定义了上传文档API的响应体结构
    """
    success: bool  # 上传是否成功
    doc_id: Optional[str]  # 生成的文档ID（如果成功）


class AskRequest(BaseModel):
    """
    问答请求的数据模型
    定义了提问API的请求体结构
    """
    question: str  # 用户的问题
    doc_id: Optional[str] = None  # 限制搜索范围的文档ID（可选）


class Chunk(BaseModel):
    """
    文本块的数据模型
    用于表示检索到的相关文本块
    """
    chunk_id: str  # 文本块ID
    text: str  # 文本内容
    score: float  # 与问题的相似度得分


class AskResponse(BaseModel):
    """
    问答响应的数据模型
    定义了提问API的响应体结构
    """
    prompt: str  # 构建的完整提示词
    decision: Optional[Any]  # 决策结果（意图、输出格式等）
    top_chunks: Optional[List[Chunk]]  # 相关的文本块列表


class ProcessFileFromEdgeRequest(BaseModel):
    """
    Edge Function发送的文件处理请求数据模型
    """
    file_id: str
    user_id: str
    download_url: str
    doc_type: Optional[str] = "general_document"
    parse_strategy: Optional[Dict[str, Any]] = None


# ==================== 实时行情数据模型（新增） ====================

class MarketData(BaseModel):
    """ETF实时行情数据模型"""
    # 基础信息
    code: str
    name: str
    data_date: str
    update_time: str

    # 基础行情
    price: float
    change: float
    change_pct: float
    prev_close: float

    # 日内行情
    open: float
    high: float
    low: float
    amplitude: float

    # 成交数据
    volume: float
    amount: float
    turnover_rate: float
    volume_ratio: float

    # 盘口数据
    bid_price: float
    ask_price: float
    outer_vol: float
    inner_vol: float
    order_ratio: float

    # 资金流向
    main_inflow: float
    main_inflow_pct: float

    # 市值数据
    latest_shares: float
    float_mv: float
    total_mv: float

    # 数据来源
    source: Optional[str] = "api"


class MarketResponse(BaseModel):
    """行情查询响应"""
    data: Optional[MarketData] = None
    error: Optional[str] = None


class RankingItem(BaseModel):
    """榜单单项数据（精简版行情）"""
    code: str
    name: str
    price: float
    change: float
    change_pct: float
    turnover_rate: float
    amount: float


class RankingResponse(BaseModel):
    """榜单查询响应"""
    total: int
    items: List[RankingItem]


class RankingRequest(BaseModel):
    """榜单查询请求"""
    sort_by: str = "涨跌幅"  # 排序字段
    top_n: int = 10  # 返回数量
    order: str = "desc"  # 排序方向: desc-从高到低, asc-从低到高


# ==================== K线数据模型（新增） ====================

class KlineData(BaseModel):
    """单条K线数据"""
    date: str  # 日期
    open: float  # 开盘价
    close: float  # 收盘价
    high: float  # 最高价
    low: float  # 最低价
    volume: float  # 成交量
    amount: float  # 成交额
    amplitude: float  # 振幅
    change_pct: float  # 涨跌幅
    change: float  # 涨跌额
    turnover_rate: float  # 换手率


class KlineResponse(BaseModel):
    """K线数据响应"""
    code: str  # 基金代码
    name: Optional[str] = None  # 基金名称
    period: str  # K线周期（daily/weekly/monthly）
    total: int  # 数据条数
    items: List[KlineData]  # K线数据列表


class KlineRequest(BaseModel):
    """K线数据查询请求"""
    fund_code: Optional[str] = None  # 基金代码
    fund_name: Optional[str] = None  # 基金名称（二选一）
    period: str = "daily"  # K线周期：daily/weekly/monthly
    start_date: Optional[str] = None  # 起始日期（格式：2024-01-01）
    end_date: Optional[str] = None  # 结束日期（格式：2024-12-31）
    limit: Optional[int] = None  # 返回数据条数限制


# ==================== 自选股数据模型（新增） ====================

class WatchlistItem(BaseModel):
    """自选股单项"""
    id: str  # 记录ID
    user_id: str  # 用户ID
    fund_code: str  # 基金代码
    fund_name: Optional[str] = None  # 基金名称
    sort_order: int = 0  # 排序
    created_at: str  # 添加时间

    # 实时行情（可选，查询列表时填充）
    price: Optional[float] = None
    change_pct: Optional[float] = None
    change: Optional[float] = None


class WatchlistAddRequest(BaseModel):
    """添加自选股请求（user_id 从 JWT 中获取）"""
    fund_code: str  # 基金代码
    fund_name: Optional[str] = None  # 基金名称（可选，系统自动获取）


class WatchlistRemoveRequest(BaseModel):
    """移除自选股请求（user_id 从 JWT 中获取）"""
    fund_code: str  # 基金代码


class WatchlistListRequest(BaseModel):
    """查询自选股列表请求（user_id 从 JWT 中获取）"""
    include_quote: bool = True  # 是否包含实时行情


class WatchlistResponse(BaseModel):
    """自选股列表响应"""
    total: int  # 总数
    items: List[WatchlistItem]  # 自选股列表


class WatchlistActionResponse(BaseModel):
    """自选股操作响应"""
    success: bool
    message: str
    item: Optional[WatchlistItem] = None


# ==================== ETF详细信息数据模型（新增） ====================

class NavHistoryItem(BaseModel):
    """历史净值单项"""
    date: str
    nav: Optional[float] = None  # 单位净值
    accumulated_nav: Optional[float] = None  # 累计净值
    daily_growth: Optional[float] = None  # 日增长率


class EtfDetailResponse(BaseModel):
    """ETF详细信息响应"""
    # 基本信息
    code: str
    full_name: Optional[str] = None  # 基金全称
    short_name: Optional[str] = None  # 基金简称
    fund_type: Optional[str] = None  # 基金类型

    # 发行与成立
    issue_date: Optional[str] = None  # 发行日期
    establish_date: Optional[str] = None  # 成立日期

    # 规模
    net_asset_scale: Optional[str] = None  # 净资产规模
    share_scale: Optional[str] = None  # 份额规模

    # 管理机构
    manager_company: Optional[str] = None  # 基金管理人（公司）
    custodian: Optional[str] = None  # 基金托管人
    fund_manager: Optional[str] = None  # 基金经理

    # 分红
    dividend_history: Optional[str] = None  # 成立来分红

    # 费率
    management_fee: Optional[str] = None
    custody_fee: Optional[str] = None
    subscription_fee: Optional[str] = None
    purchase_fee: Optional[str] = None
    redemption_fee: Optional[str] = None

    # 投资标的
    benchmark: Optional[str] = None  # 业绩比较基准
    tracking_target: Optional[str] = None  # 跟踪标的

    # 实时行情（可选）
    realtime: Optional[MarketData] = None

    # 历史净值（可选）
    nav_history: Optional[List[NavHistoryItem]] = None

    # 数据来源
    source: str = "api"


# ==================== ETF搜索/筛选数据模型（新增） ====================

class SearchRequest(BaseModel):
    """ETF搜索请求"""
    keyword: str  # 搜索关键词（名称或代码）
    top_n: int = 10  # 返回数量
    include_quote: bool = True  # 是否包含实时行情


class SearchItem(BaseModel):
    """ETF搜索单项"""
    code: str  # 基金代码
    name: str  # 基金名称

    # 实时行情（可选）
    price: Optional[float] = None
    change_pct: Optional[float] = None
    change: Optional[float] = None

    # 基础信息（可选）
    fund_type: Optional[str] = None  # 基金类型
    net_asset_scale: Optional[str] = None  # 净资产规模
    management_fee: Optional[str] = None  # 管理费
    tracking_target: Optional[str] = None  # 跟踪标的


class SearchResponse(BaseModel):
    """搜索响应"""
    total: int  # 匹配总数
    items: List[SearchItem]  # 搜索结果


class FilterRequest(BaseModel):
    """ETF筛选请求"""
    # 关键词
    keyword: Optional[str] = "ETF"  # 搜索关键词

    # 费率筛选
    max_fee: Optional[float] = None  # 最大管理费率（%）

    # 规模筛选
    min_scale_billion: Optional[float] = None  # 最小净资产规模（亿）
    max_scale_billion: Optional[float] = None  # 最大净资产规模（亿）

    # 基金分类
    fund_category: Optional[str] = None  # 基金分类（指数型-股票/债券/货币/混合）
    tracking_target: Optional[str] = None  # 跟踪标的名称

    # 涨跌幅筛选
    min_return: Optional[float] = None  # 最小涨跌幅（%）
    max_return: Optional[float] = None  # 最大涨跌幅（%）

    # 分红筛选
    has_dividend: Optional[bool] = None  # 是否有分红

    # 结果控制
    top_n: int = 20
    sort_by: str = "涨跌幅"  # 排序字段
    sort_order: str = "desc"  # 排序方向


class FundCategory(BaseModel):
    """基金分类"""
    category: str  # 分类名称
    fund_type: str  # 类型字符串（用于筛选）
    count: int  # 该类基金数量


class CategoryListResponse(BaseModel):
    """分类列表响应"""
    total_categories: int
    total_funds: int
    items: List[FundCategory]


class FundListResponse(BaseModel):
    """分类下基金列表响应"""
    category: str  # 分类名称
    total: int  # 基金数量
    items: List[SearchItem]  # 基金列表


# ==================== 分时图数据模型（新增） ====================

class IntradayPoint(BaseModel):
    """分时图数据点"""
    time: str  # 时间（如 09:31）
    price: float  # 当前价格
    avg_price: Optional[float] = None  # 均价
    volume: Optional[float] = None  # 成交量
    amount: Optional[float] = None  # 成交额
    change_pct: Optional[float] = None  # 累计涨跌幅


class IntradayResponse(BaseModel):
    """分时图数据响应"""
    code: str  # 基金代码
    name: Optional[str] = None  # 基金名称
    date: str  # 数据日期
    prev_close: float  # 昨收
    open: float  # 今开
    current: float  # 当前价
    high: float  # 最高
    low: float  # 最低
    change_pct: float  # 涨跌幅
    total_volume: float  # 总成交量
    total_amount: float  # 总成交额
    data_source: str  # 数据来源（real=真实数据, simulated=模拟数据）
    items: List[IntradayPoint]  # 分时数据点


# ==================== 资金流向数据模型（新增） ====================

class MoneyFlowData(BaseModel):
    """单只ETF资金流向"""
    code: str  # 基金代码
    name: str  # 基金名称
    price: Optional[float] = None  # 最新价
    change_pct: Optional[float] = None  # 涨跌幅

    # 主力资金
    main_inflow: Optional[float] = None  # 主力净流入（元）
    main_inflow_pct: Optional[float] = None  # 主力净流入占比

    # 买卖盘
    outer_vol: Optional[float] = None  # 外盘（主动买入）
    inner_vol: Optional[float] = None  # 内盘（主动卖出）
    net_flow: Optional[float] = None  # 净买入（外盘-内盘）
    order_ratio: Optional[float] = None  # 委比

    # 成交
    amount: Optional[float] = None  # 成交额
    update_time: Optional[str] = None  # 更新时间


class MoneyFlowRankingItem(BaseModel):
    """资金流向榜单项"""
    code: str
    name: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    main_inflow: Optional[float] = None  # 主力净流入
    main_inflow_pct: Optional[float] = None  # 主力净流入占比
    large_inflow: Optional[float] = None  # 大单净流入
    medium_inflow: Optional[float] = None  # 中单净流入
    small_inflow: Optional[float] = None  # 小单净流入
    amount: Optional[float] = None  # 成交额
    turnover_rate: Optional[float] = None  # 换手率


class MoneyFlowRankingResponse(BaseModel):
    """资金流向榜响应"""
    total: int
    items: List[MoneyFlowRankingItem]


# ==================== 场外基金持仓交易数据模型（旧版，兼容保留） ====================

class BuyRequest(BaseModel):
    """场外基金申购请求（按金额）- 旧版兼容"""
    fund_code: str  # 基金代码
    amount: float   # 申购金额（元）
    price: Optional[float] = None  # 净值（不传则自动获取）


class SellRequest(BaseModel):
    """场外基金赎回请求（按份额）- 旧版兼容"""
    fund_code: str  # 基金代码
    quantity: float  # 赎回份额
    price: Optional[float] = None  # 净值（不传则自动获取）


class TradeData(BaseModel):
    """成交数据 - 旧版兼容"""
    fund_code: str
    fund_name: str
    amount: float  # 申购金额/赎回金额
    fee: float
    net_amount: Optional[float] = None  # 净申购金额/净赎回金额
    price: float  # 净值
    quantity: Optional[float] = None  # 份额（确认后填入）
    hold_days: Optional[int] = None
    trade_pnl: Optional[float] = None
    position_qty: Optional[float] = None
    cost_price: Optional[float] = None
    confirm_date: Optional[str] = None
    available_date: Optional[str] = None
    cash_remaining: Optional[float] = None
    frozen_cash: Optional[float] = None
    status: str = "completed"
    trade_time: Optional[str] = None


class TradeResponse(BaseModel):
    """买卖响应 - 旧版兼容"""
    success: bool
    message: str
    data: Optional[TradeData] = None


# ==================== 场外基金交易数据模型（新版，申购/赎回术语） ====================

class PurchaseRequest(BaseModel):
    """场外基金申购请求（按金额申购）"""
    fund_code: str  # 基金代码
    amount: float   # 申购金额（元）
    price: Optional[float] = None  # 净值（不传则自动获取）


class RedeemRequest(BaseModel):
    """场外基金赎回请求（按份额赎回）"""
    fund_code: str  # 基金代码
    quantity: float  # 赎回份额
    price: Optional[float] = None  # 净值（不传则自动获取）


class OrderResult(BaseModel):
    """申购/赎回订单结果"""
    fund_code: str
    fund_name: str
    amount: float  # 申购金额/赎回金额
    fee: float
    net_amount: Optional[float] = None  # 净申购金额/净赎回金额
    price: float  # 净值
    quantity: Optional[float] = None  # 份额（确认后填入）
    hold_days: Optional[int] = None
    trade_pnl: Optional[float] = None
    position_qty: Optional[float] = None
    cost_price: Optional[float] = None
    confirm_date: Optional[str] = None
    available_date: Optional[str] = None
    settle_date: Optional[str] = None  # 赎回到账日期
    cash_remaining: Optional[float] = None
    frozen_cash: Optional[float] = None
    status: str = "completed"
    trade_time: Optional[str] = None


class OrderResponse(BaseModel):
    """申购/赎回订单响应"""
    success: bool
    message: str
    data: Optional[OrderResult] = None


class PositionItem(BaseModel):
    """持仓单项"""
    id: str
    user_id: str
    fund_code: str
    fund_name: str
    quantity: float
    cost_price: float
    cost_value: Optional[float] = None
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    confirm_date: Optional[str] = None
    available_date: Optional[str] = None
    created_at: str
    updated_at: str


class PositionListResponse(BaseModel):
    """持仓列表响应"""
    total: int
    items: List[PositionItem]
    total_pnl: float
    total_position_value: float


class AccountSummaryResponse(BaseModel):
    """账户概况响应"""
    cash: float
    frozen_cash: float
    position_value: float
    total_assets: float
    total_pnl: float
    total_return_rate: float
    position_count: int


class TradeFlowItem(BaseModel):
    """交易流水单项"""
    id: str
    user_id: str
    fund_code: str
    fund_name: str
    direction: str
    amount: float
    price: float
    quantity: float
    fee: float
    trade_time: str


class TradeFlowResponse(BaseModel):
    """交易流水分页响应"""
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[TradeFlowItem]


class TradeFlowQueryParams(BaseModel):
    """交易流水查询参数"""
    fund_code: Optional[str] = None
    direction: Optional[str] = None
    page: int = 1
    page_size: int = 20


class SnapshotData(BaseModel):
    """快照数据"""
    snapshot_date: str
    total_assets: float
    cash: float
    position_value: float
    total_pnl: float
    total_return_rate: float


class SnapshotResponse(BaseModel):
    """快照响应"""
    success: bool
    message: str
    data: Optional[SnapshotData] = None


class DailyReturnItem(BaseModel):
    """每日收益率"""
    date: str
    total_assets: float
    cash: float
    position_value: float
    total_pnl: float
    total_return_rate: float
    daily_return: float


class DailyReturnResponse(BaseModel):
    """每日收益率响应"""
    items: List[DailyReturnItem]


# ==================== 风险画像数据模型（新增） ====================


class SubmitAnswerItem(BaseModel):
    """提交答案单项"""
    question_id: str  # 题目 ID（如 q1）
    value: str  # 选项值（如 A、B、C）


class SubmitRequest(BaseModel):
    """提交问卷请求"""
    questionnaire_id: str  # 问卷 ID
    answers: List[SubmitAnswerItem]  # 答案列表


class QuestionOption(BaseModel):
    """题目选项（前端可见，不含内部评分）"""
    text: str  # 选项文字
    value: str  # 选项值


class QuestionItem(BaseModel):
    """问卷题目（前端可见）"""
    id: str  # 题目 ID
    question: str  # 题目文字
    category: str  # 维度分类
    options: List[QuestionOption]  # 选项列表


class QuestionnaireResponse(BaseModel):
    """问卷响应"""
    id: str  # 问卷 ID
    version: str  # 版本号
    questions: List[QuestionItem]  # 题目列表
    total_questions: int  # 题目总数


class DimensionScores(BaseModel):
    """各维度得分"""
    investment_horizon: Optional[int] = None
    drawdown_tolerance: Optional[int] = None
    investment_experience: Optional[int] = None
    goal_orientation: Optional[int] = None
    knowledge_level: Optional[int] = None


class ProfileResult(BaseModel):
    """画像结果（前端可见）"""
    risk_level: str  # conservative / moderate / aggressive
    risk_label: str  # 保守型 / 稳健型 / 进取型
    total_score: float  # 加权总分
    dimension_scores: DimensionScores  # 各维度得分
    summary: str  # 画像解读文字
    created_at: Optional[str] = None  # 画像生成时间


class SubmitResponse(BaseModel):
    """提交问卷响应"""
    success: bool
    message: str
    profile: Optional[ProfileResult] = None


class ProfileResponse(BaseModel):
    """查询画像响应"""
    has_profile: bool
    profile: Optional[ProfileResult] = None