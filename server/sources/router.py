"""源路由器：按能力选源、逐个尝试、失败分类、熔断与换源日志。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.2 / §5.1。

调用侧（缓存服务、业务代码）只依赖本类，**永远不知道数据来自哪个源**（G2）。
换源是「偏好排序 + 逐一尝试」，不是「主源 + 备源」的硬绑定（G3）：

    for src in pick("history"):
        try: return src.fetch_history(code)
        except SourceError: record_failure(...); continue
        except Exception: record_failure(UNEXPECTED); continue  # 记 ERROR + 堆栈
    raise AllSourcesFailed(...)        # 绝不静默返回空
"""
import threading
import time
from typing import Any, Callable, Optional

from server.sources import events
from server.sources.config import AdapterConfig, override_rank
from server.sources.health import HealthTracker
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
)
from server.sources.registry import Registry, default_registry


class SourceRouter:
    """对调用侧冻结的取数入口。"""

    def __init__(
        self,
        registry: Optional[Registry] = None,
        health: Optional[HealthTracker] = None,
        config: Optional[AdapterConfig] = None,
    ):
        self._config = config or AdapterConfig.from_env()
        self._registry = registry or default_registry()
        self._health = health or HealthTracker(self._config)
        # 「不回切」：记住每个能力上次成功的源，下次优先用它。
        # 进程重启后清空，回到默认偏好（设计文档 §5.4 / Q2）。
        self._last_good: dict[str, str] = {}
        self._last_good_lock = threading.Lock()

    # ==================== 对调用侧的公开接口（冻结） ====================

    def fetch_history(self, code: str) -> list[NavPoint]:
        """全量历史，按 `nav_date` 升序。"""
        self._validate_code(code)
        result, _ = self._run(
            CAP_HISTORY,
            code,
            lambda source: source.fetch_history(code),
            require_non_empty=True,
        )
        return self._normalize_points(result, None)

    def fetch_history_recent(self, code: str, limit: int) -> list[NavPoint]:
        """最近 `limit` 条净值，按 `nav_date` 升序。"""
        self._validate_code(code)
        if limit < 1:
            raise ValueError(f"limit 必须 >= 1: {limit}")
        result, _ = self._run(
            CAP_HISTORY_RECENT,
            code,
            lambda source: source.fetch_history(code, limit=limit),
            require_non_empty=True,
        )
        return self._normalize_points(result, limit)

    def fetch_latest(self, code: str) -> NavPoint:
        """最新一条净值（按 `nav_date` 取最大，不假设源返回的顺序）。"""
        self._validate_code(code)
        result, _ = self._run(
            CAP_LATEST,
            code,
            lambda source: source.fetch_history(code, limit=1),
            require_non_empty=True,
        )
        points = self._normalize_points(result, None)
        return points[-1]

    def fetch_latest_batch(self, codes: list[str]) -> dict[str, list[NavPoint]]:
        """批量最新净值。

        源返回全市场数据，路由器按 `codes` 过滤（源不做白名单过滤，G5）。
        返回 `{code: [点, ...]}`；某个代码不在源的覆盖范围内时该 key 缺席。

        「零命中」仍算成功（返回 `{}`，不抛 `AllSourcesFailed`），但请求非空
        却过滤后为空时记 `batch_empty` WARNING，便于发现上游窗口/格式漂移。
        """
        normalized = [str(code).strip() for code in codes if str(code).strip()]
        if not normalized:
            raise ValueError("codes 不能为空")

        wanted = set(normalized)
        result, source = self._run(
            CAP_BATCH,
            None,
            lambda source: source.fetch_latest_batch(normalized),
            require_non_empty=False,
        )
        filtered: dict[str, list[NavPoint]] = {}
        for code, points in result.items():
            if code not in wanted or not points:
                continue
            filtered[code] = sorted(points, key=lambda p: p.nav_date)
        if not filtered:
            # 保持「批量空结果 = 成功」的契约（调用方据此继续降级），
            # 但请求非空却零命中通常是上游窗口/格式漂移，必须留痕。
            events.log_batch_empty(
                capability=CAP_BATCH,
                source=source.meta.name,
                domain=source.meta.domain,
                requested=len(normalized),
                returned=len(result),
                sample=normalized[:5],
            )
        return filtered

    def fetch_calendar(self) -> CalendarData:
        """交易日历（全量）。"""
        result, _ = self._run(
            CAP_CALENDAR,
            None,
            lambda source: source.fetch_calendar(),
            require_non_empty=True,
        )
        return result

    # ==================== 选源 ====================

    def pick(self, operation: str) -> list[Source]:
        """返回按偏好排序、且当前可用的候选源。"""
        candidates = self._registry.by_capability(operation)
        candidates = [
            source
            for source in candidates
            if source.meta.domain not in self._config.denylist
        ]
        candidates.sort(key=self._sort_key)
        usable = self._health.pick_usable(candidates)

        # 不回切：上次成功的源仍然可用时排在最前。
        with self._last_good_lock:
            last_good = self._last_good.get(operation)
        if last_good:
            for index, source in enumerate(usable):
                if source.meta.name == last_good:
                    if index > 0:
                        usable.insert(0, usable.pop(index))
                    break
        return usable

    def _sort_key(self, source: Source):
        override = override_rank(self._config, source.meta.name)
        # 显式覆盖 > 默认 priority > 源名（保证排序稳定）
        return (
            0 if override is not None else 1,
            override if override is not None else 0,
            source.meta.priority,
            source.meta.name,
        )

    # ==================== 逐个尝试 ====================

    def _run(
        self,
        operation: str,
        code: Optional[str],
        call: Callable[[Source], Any],
        require_non_empty: bool,
    ) -> tuple[Any, Source]:
        tried: list[dict] = []
        previous_failed: Optional[str] = None

        for source in self.pick(operation):
            if not self._health.allow_attempt(source):
                continue  # 半开额度用完 / 域名在冷静期

            started = time.monotonic()
            try:
                result = call(source)
                if require_non_empty and not result:
                    raise SourceError(
                        source.meta.name,
                        FailureKind.EMPTY_PAYLOAD,
                        "源返回空结果（未抛错）",
                    )
            except SourceError as error:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                events.log_source_result(
                    capability=operation,
                    source=source.meta.name,
                    domain=source.meta.domain,
                    ok=False,
                    kind=error.kind.value,
                    elapsed_ms=elapsed_ms,
                    error=error.message,
                    code=code,
                )
                self._health.record_failure(source, error)
                tried.append({
                    "source": source.meta.name,
                    "kind": error.kind.value,
                    "error": error.message,
                })
                previous_failed = source.meta.name
                continue
            except Exception as exc:
                # 源实现未按契约包装异常（KeyError / TypeError / NotImplementedError 等）。
                # 按接口级失败处理：只软降级该源，继续换源；日志 MUST 带堆栈，
                # 否则代码缺陷会被伪装成普通上游失败。
                error = SourceError(
                    source.meta.name,
                    FailureKind.UNEXPECTED,
                    f"{type(exc).__name__}: {exc}",
                )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                events.log_source_result(
                    capability=operation,
                    source=source.meta.name,
                    domain=source.meta.domain,
                    ok=False,
                    kind=error.kind.value,
                    elapsed_ms=elapsed_ms,
                    error=error.message,
                    code=code,
                    exc_info=True,
                )
                self._health.record_failure(source, error)
                tried.append({
                    "source": source.meta.name,
                    "kind": error.kind.value,
                    "error": error.message,
                })
                previous_failed = source.meta.name
                continue

            elapsed_ms = int((time.monotonic() - started) * 1000)
            self._health.record_success(source)
            with self._last_good_lock:
                self._last_good[operation] = source.meta.name
            events.log_source_result(
                capability=operation,
                source=source.meta.name,
                domain=source.meta.domain,
                ok=True,
                elapsed_ms=elapsed_ms,
                code=code,
            )
            if tried and previous_failed:
                events.log_source_switch(
                    capability=operation,
                    from_source=previous_failed,
                    to_source=source.meta.name,
                    reason=tried[-1]["kind"],
                    tried=[item["source"] for item in tried],
                    code=code,
                )
            return result, source

        events.log_all_sources_failed(operation, tried, code=code)
        raise AllSourcesFailed(operation, tried)

    # ==================== 工具 ====================

    @staticmethod
    def _validate_code(code: str) -> None:
        if not code or not str(code).strip():
            raise ValueError("基金代码不能为空")

    @staticmethod
    def _normalize_points(points: list[NavPoint], limit: Optional[int]) -> list[NavPoint]:
        """按日期升序、去重，并按需取最近 `limit` 条。"""
        ordered = sorted(points, key=lambda p: p.nav_date)
        deduped: list[NavPoint] = []
        for point in ordered:
            if deduped and deduped[-1].nav_date == point.nav_date:
                deduped[-1] = point
            else:
                deduped.append(point)
        if limit is not None:
            deduped = deduped[-limit:]
        return deduped
