"""多源适配器的归一化模型与错误类型。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.2（冻结契约）。

本模块是**全项目对「源」的唯一定义处**：

- `HTTP` / `akshare` / `HTML、JS 解析` / `上游字段名` 只允许出现在 `Source` 实现里；
- 其它所有层（路由、缓存服务、业务代码）只看到这里的归一化模型。

改动这里的模型（`NavPoint` / `CalendarData` / `FailureKind`）属于契约变更，
必须同步修改设计文档与所有消费者。
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

# ==================== 能力名 ====================
# 与设计文档 §4.2 保持一致；能力名一旦变化，缓存文档 / 日历文档两边同时改。
CAP_HISTORY = "history"
CAP_HISTORY_RECENT = "history_recent"
CAP_LATEST = "latest"
CAP_BATCH = "batch"
CAP_CALENDAR = "calendar"


@dataclass(frozen=True)
class SourceMeta:
    """源的元信息。`domain` 是熔断单位，不是源名。"""

    name: str                      # "em_pingzhongdata"，全局唯一，写进数据行的 source 列
    domain: str                    # "fund.eastmoney.com"，熔断单位
    capabilities: frozenset[str]   # history / history_recent / latest / batch / calendar
    priority: int = 100            # 同能力下的默认偏好序（小者优先），可被环境变量覆盖
    timeout: float = 15.0          # 强制超时（秒）
    description: str = ""          # 给运维看的：这个源是什么、有什么坑


@dataclass(frozen=True)
class NavPoint:
    """净值点的归一化模型。

    `nav_date` 是**净值归属日**，不是拉取日；跨源混写同一行时靠 `source` 留痕。
    `daily_growth` 的单位是**百分数**（-0.27 表示 -0.27%），与上游字段一致。
    """

    fund_code: str
    nav_date: date
    unit_nav: Optional[Decimal]
    accumulated_nav: Optional[Decimal]
    daily_growth: Optional[Decimal]
    source: str


@dataclass(frozen=True)
class CalendarData:
    """交易日历源的归一化输出。"""

    trading_days: frozenset[date]
    coverage_start: date
    coverage_end: date
    source: str


class FailureKind(str, Enum):
    """失败分类。域级 / 接口级的区分见设计文档 §5.2。"""

    TIMEOUT = "TIMEOUT"
    HTTP_403 = "HTTP_403"
    HTTP_5XX = "HTTP_5XX"
    HTTP_429 = "HTTP_429"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    EMPTY_PAYLOAD = "EMPTY_PAYLOAD"
    PARSE_ERROR = "PARSE_ERROR"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    INVALID_REQUEST = "INVALID_REQUEST"
    # 源实现未按契约包装的异常（KeyError / TypeError 等代码缺陷）。
    # 默认按接口级处理：只降级该源并继续换源，日志以 ERROR + 堆栈暴露。
    UNEXPECTED = "UNEXPECTED"


# 域级失败：连接层被拒 / 超时 / 限速 —— 整个域名可疑，该域名下所有源一起熔断。
# 接口级失败：连接成功但内容不对 —— 只有这一个源可疑，域名不动。
DOMAIN_LEVEL_KINDS = frozenset({
    FailureKind.TIMEOUT,
    FailureKind.HTTP_403,
    FailureKind.HTTP_5XX,
    FailureKind.HTTP_429,
    FailureKind.CONNECTION_ERROR,
})


class SourceError(Exception):
    """单个源取数失败。必须携带源名与失败分类，便于路由分类和日志排查。"""

    def __init__(self, source: str, kind: FailureKind, message: str):
        self.source = source
        self.kind = kind
        self.message = message
        super().__init__(f"[{source}] {kind.value}: {message}")


class AllSourcesFailed(Exception):
    """某个能力下所有候选源都失败。

    `tried` 形如 `[{"source": ..., "kind": ..., "error": ...}]`。
    **调用方不得把它静默改成空列表**（设计文档 §5.1）。
    """

    def __init__(self, capability: str, tried: list[dict]):
        self.capability = capability
        self.tried = tried
        detail = "；".join(
            f"{item['source']}={item['kind']}({item['error']})" for item in tried
        ) or "没有可用的候选源"
        super().__init__(f"能力 {capability} 的所有源均失败: {detail}")


@runtime_checkable
class Source(Protocol):
    """源实现接口。HTTP / akshare / 解析只允许出现在这一层。"""

    meta: SourceMeta

    def fetch_history(self, code: str, limit: Optional[int] = None) -> list[NavPoint]:
        """history / history_recent / latest 三种能力共用。

        - limit=None：全量历史，只有声明 history 的源可以接受；
        - limit=N：最近 N 条，history / history_recent / latest 都可以接受；
        - latest 源在 limit=N 时返回最新一条（N 必须 >= 1）。
        """

    def fetch_latest_batch(self, codes: list[str]) -> dict[str, list[NavPoint]]:
        """batch 能力。每个代码返回该源在批量窗口内的全部点（通常是最近两天）。"""

    def fetch_calendar(self) -> CalendarData:
        """calendar 能力。"""


class BaseSource:
    """`Source` 的默认实现：未实现的能力显式抛 NotImplementedError。

    **不静默返回空** —— 静默空会被路由器当成「成功但没数据」，
    把真正的实现缺失伪装成上游空响应（设计文档 §4.2）。
    """

    meta: SourceMeta

    def fetch_history(self, code: str, limit: Optional[int] = None) -> list[NavPoint]:
        raise NotImplementedError(f"{self.meta.name} 不支持 history 能力")

    def fetch_latest_batch(self, codes: list[str]) -> dict[str, list[NavPoint]]:
        raise NotImplementedError(f"{self.meta.name} 不支持 batch 能力")

    def fetch_calendar(self) -> CalendarData:
        raise NotImplementedError(f"{self.meta.name} 不支持 calendar 能力")


# ==================== 解析工具（纯函数，可单测） ====================

def to_decimal(value: Any) -> Optional[Decimal]:
    """把上游的字符串/数字转成 Decimal；空值、`--`、`---`、非法值返回 None。

    用 Decimal 而不是 float：净值会写进 numeric(18,6)，避免二进制浮点误差。
    """
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "-", "--", "---", "nan", "NaN", "None", "null"):
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None
