"""源注册表：源名 -> Source，能力 -> [Source]。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.3。

新增一个源的边际成本（G1）：写一个类 + 在 `SOURCES` 注册一行 + 一条契约测试。
调用侧、状态机、日志、配置一行都不用改。
"""
from typing import Iterable, Optional

from server.sources.models import (
    CAP_BATCH,
    CAP_CALENDAR,
    CAP_HISTORY,
    CAP_HISTORY_RECENT,
    CAP_LATEST,
    Source,
    SourceMeta,
)

# 路由的「操作名」-> 该操作可以接受的能力集合。
# 例如 fetch_latest 可以退而使用 history / history_recent 源（它们同样能给出最新点）。
OPERATION_CAPABILITIES: dict[str, frozenset] = {
    "history": frozenset({CAP_HISTORY}),
    "history_recent": frozenset({CAP_HISTORY, CAP_HISTORY_RECENT}),
    "latest": frozenset({CAP_HISTORY, CAP_HISTORY_RECENT, CAP_LATEST}),
    "batch": frozenset({CAP_BATCH}),
    "calendar": frozenset({CAP_CALENDAR}),
}


class Registry:
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def register(self, source: Source) -> None:
        name = source.meta.name
        if name in self._sources:
            raise ValueError(f"源名重复注册: {name}")
        self._sources[name] = source

    def get(self, name: str) -> Optional[Source]:
        return self._sources.get(name)

    def all(self) -> list[Source]:
        return list(self._sources.values())

    def by_capability(self, operation: str) -> list[Source]:
        """返回支持该操作的候选源（未按偏好排序，排序由路由器负责）。"""
        accepted = OPERATION_CAPABILITIES.get(operation)
        if accepted is None:
            raise ValueError(f"未知能力/操作: {operation}")
        return [
            source
            for source in self._sources.values()
            if source.meta.capabilities & accepted
        ]

    @classmethod
    def with_sources(cls, sources: Iterable[Source]) -> "Registry":
        registry = cls()
        for source in sources:
            registry.register(source)
        return registry


def default_sources() -> list[Source]:
    """默认源清单。**新增源只需要在这里加一行。**"""
    # 延迟 import：避免 registry 模块在 import 时就加载所有 HTTP/akshare 依赖。
    from server.sources.em_fund_jjjz import EmFundJjjzSource
    from server.sources.em_lsjz import EmLsjzSource
    from server.sources.em_mobile import EmMobileSource
    from server.sources.em_pingzhongdata import EmPingzhongdataSource
    from server.sources.sina_trade_date import SinaTradeDateSource

    return [
        EmPingzhongdataSource(),
        EmFundJjjzSource(),
        EmLsjzSource(),
        EmMobileSource(),
        SinaTradeDateSource(),
    ]


def default_registry() -> Registry:
    return Registry.with_sources(default_sources())
