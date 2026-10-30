"""多源数据源适配器。

设计文档：`docs/20-设计/行情/数据源多源适配器.md`

对外只需要认两个东西：

- `SourceRouter`：取数入口（`fetch_history` / `fetch_history_recent` /
  `fetch_latest` / `fetch_latest_batch` / `fetch_calendar`）；
- 归一化模型：`NavPoint` / `CalendarData`。

源名、域名、熔断、HTTP、上游字段名都在这一层内部，调用侧对换源无感（G2）。
"""
import threading
from typing import Optional

from server.sources.config import AdapterConfig
from server.sources.health import DomainHealth, HealthTracker, SourceHealth
from server.sources.models import (
    CAP_BATCH,
    CAP_CALENDAR,
    CAP_HISTORY,
    CAP_HISTORY_RECENT,
    CAP_LATEST,
    AllSourcesFailed,
    CalendarData,
    FailureKind,
    NavPoint,
    Source,
    SourceError,
    SourceMeta,
)
from server.sources.registry import Registry, default_registry, default_sources
from server.sources.router import SourceRouter

__all__ = [
    "AdapterConfig",
    "AllSourcesFailed",
    "CalendarData",
    "DomainHealth",
    "FailureKind",
    "HealthTracker",
    "NavPoint",
    "Registry",
    "Source",
    "SourceError",
    "SourceHealth",
    "SourceMeta",
    "SourceRouter",
    "default_registry",
    "default_sources",
    "get_router",
    "CAP_HISTORY",
    "CAP_HISTORY_RECENT",
    "CAP_LATEST",
    "CAP_BATCH",
    "CAP_CALENDAR",
]

_default_router: Optional[SourceRouter] = None
_default_router_lock = threading.Lock()


def get_router() -> SourceRouter:
    """进程内默认路由器（懒加载）。

    健康状态是进程内短期状态，必须由全项目共享同一个实例才有意义；
    各调用方不要自己 new `SourceRouter`。
    """
    global _default_router
    if _default_router is None:
        with _default_router_lock:
            if _default_router is None:
                _default_router = SourceRouter()
    return _default_router


def reset_router() -> None:
    """丢弃默认路由器（测试专用）。"""
    global _default_router
    with _default_router_lock:
        _default_router = None
