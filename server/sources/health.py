"""域名级健康状态机与接口级软降级。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.4 / §5.2 / §5.3 / §5.4。

**熔断单位是域名，不是源**：上游拒绝我们时拒的是出口/域名，同一域名下的所有接口
会一起挂；反过来，某个接口返回 200 + 空数据时，只有该源可疑，域名必须保持健康。
这条区分是整个适配器的地基（§5.2）。

状态存储是**进程内内存**，不持久化：

- 熔断是分钟级短期状态，重启后重新学习的成本很低；
- 持久化反而要处理「重启后旧状态把好域名锁死」的问题（设计文档 Q5）。
"""
import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from server.sources import events
from server.sources.config import AdapterConfig
from server.sources.models import DOMAIN_LEVEL_KINDS, Source, SourceError


@dataclass
class DomainHealth:
    """一个域名的健康状态（设计文档 §4.4 的字段 + 实现所需的内部字段）。"""

    domain: str
    state: str = "closed"              # closed | open | half_open
    consecutive_failures: int = 0
    cooldown_until: float = 0.0        # monotonic 时间戳
    last_success_at: Optional[float] = None
    last_failure_at: Optional[float] = None
    last_failure_kind: Optional[str] = None
    last_error: Optional[str] = None
    # 内部状态：当前冷却时长、半开恢复确认计数、每个源已用的试探次数
    cooldown_seconds: float = 0.0
    recovery_successes: int = 0
    probe_used: dict = field(default_factory=dict)


@dataclass
class SourceHealth:
    """单个源的接口级健康状态（接口级失败只影响这个源，不影响域名）。"""

    source: str
    degraded_until: float = 0.0        # monotonic 时间戳
    last_failure_at: Optional[float] = None
    last_failure_kind: Optional[str] = None
    last_error: Optional[str] = None


class HealthTracker:
    """按域名维护熔断状态，按源维护接口级软降级。

    `clock` 默认 `time.monotonic`，测试可注入假时钟以驱动冷却/半开。
    """

    def __init__(
        self,
        config: Optional[AdapterConfig] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._config = config or AdapterConfig.from_env()
        self._clock = clock
        self._domains: dict[str, DomainHealth] = {}
        self._sources: dict[str, SourceHealth] = {}
        self._lock = threading.RLock()

    # ==================== 查询 ====================

    def _domain(self, domain: str) -> DomainHealth:
        health = self._domains.get(domain)
        if health is None:
            health = DomainHealth(domain=domain)
            self._domains[domain] = health
        return health

    def _source(self, name: str) -> SourceHealth:
        health = self._sources.get(name)
        if health is None:
            health = SourceHealth(source=name)
            self._sources[name] = health
        return health

    def _is_degraded(self, source_name: str, now: float) -> bool:
        return self._source(source_name).degraded_until > now

    def pick_usable(self, sources: list[Source]) -> list[Source]:
        """过滤掉当前不可用的源（域名熔断 / 接口级降级）。

        半开状态**只在这里判定**，不消耗试探额度；真正的额度在 `allow_attempt`
        里按「每个源各 1 次」扣减，避免「pick 到了但没轮上尝试」把额度耗光。
        """
        with self._lock:
            now = self._clock()
            domain_usable: list[Source] = []
            for source in sources:
                health = self._domain(source.meta.domain)
                if health.state == "open":
                    if now < health.cooldown_until:
                        continue
                    self._open_to_half_open(health, now, source.meta.name)
                domain_usable.append(source)

            healthy = [
                s for s in domain_usable if not self._is_degraded(s.meta.name, now)
            ]
            # 接口级降级是软过滤：只有存在其它健康候选时才跳过被降级源。
            # 否则唯一候选会被降级直接变成 AllSourcesFailed，掩盖了「源其实还能试」。
            return healthy if healthy else domain_usable

    def allow_attempt(self, source: Source) -> bool:
        """是否允许真正向该源发起请求；半开时按源扣减试探额度。"""
        with self._lock:
            now = self._clock()
            health = self._domain(source.meta.domain)
            if health.state == "open":
                if now < health.cooldown_until:
                    return False
                self._open_to_half_open(health, now, source.meta.name)
            if health.state == "half_open":
                used = health.probe_used.get(source.meta.name, 0)
                if used >= self._config.half_open_probes:
                    return False
                health.probe_used[source.meta.name] = used + 1
            return True

    # ==================== 状态变更 ====================

    def record_success(self, source: Source) -> None:
        with self._lock:
            now = self._clock()
            health = self._domain(source.meta.domain)
            health.last_success_at = now
            # 接口级降级解除（成功的源确实恢复了）
            self._sources.pop(source.meta.name, None)

            if health.state == "half_open":
                health.recovery_successes += 1
                if health.recovery_successes >= self._config.recovery_confirm:
                    self._close(health)
                else:
                    # 还没确认恢复：重新给所有源一轮试探额度，让下一次调用继续确认。
                    # 不重置的话，单源域名在「每个源 1 次试探」的规则下永远凑不齐
                    # SOURCE_RECOVERY_CONFIRM 次成功，会卡死在 half_open。
                    health.probe_used.clear()
            elif health.state == "open":
                # 理论上 open 不放行；保守按「半开首次成功」处理，避免状态卡死。
                health.state = "half_open"
                health.recovery_successes = 1
            else:
                # 域名下任意源成功即视为域名恢复（域名是故障单位）
                health.consecutive_failures = 0
                health.recovery_successes = 0
                health.cooldown_seconds = 0.0

    def record_failure(self, source: Source, error: SourceError) -> None:
        with self._lock:
            now = self._clock()
            source_health = self._source(source.meta.name)
            source_health.last_failure_at = now
            source_health.last_failure_kind = error.kind.value
            source_health.last_error = error.message

            if error.kind in DOMAIN_LEVEL_KINDS:
                self._record_domain_failure(source.meta.domain, error, now)
            else:
                # 接口级失败：只让该源软降级，域名状态完全不动。
                source_health.degraded_until = now + self._config.interface_degrade_cooldown

    def _record_domain_failure(
        self, domain: str, error: SourceError, now: float
    ) -> None:
        health = self._domain(domain)
        health.consecutive_failures += 1
        health.last_failure_at = now
        health.last_failure_kind = error.kind.value
        health.last_error = error.message

        if health.state == "half_open":
            # 试探失败：冷却翻倍（上限 SOURCE_COOLDOWN_MAX）
            health.cooldown_seconds = min(
                max(health.cooldown_seconds * 2, self._config.cooldown_base),
                self._config.cooldown_max,
            )
            self._open(health, now, error.kind.value)
            return

        if health.state == "open":
            # 已在冷静期；保持原状态，不重复累计冷却。
            return

        if health.consecutive_failures >= self._config.failure_threshold:
            health.cooldown_seconds = self._config.cooldown_base
            self._open(health, now, error.kind.value)

    def _open(self, health: DomainHealth, now: float, trigger: str) -> None:
        previous = health.state
        health.state = "open"
        health.cooldown_until = now + health.cooldown_seconds
        health.recovery_successes = 0
        health.probe_used.clear()
        events.log_domain_state(
            domain=health.domain,
            from_state=previous,
            to_state="open",
            consecutive_failures=health.consecutive_failures,
            cooldown_until=health.cooldown_until,
            trigger=trigger,
        )

    def _open_to_half_open(
        self, health: DomainHealth, now: float, probe_source: str
    ) -> None:
        previous = health.state
        health.state = "half_open"
        health.recovery_successes = 0
        health.probe_used.clear()
        events.log_domain_state(
            domain=health.domain,
            from_state=previous,
            to_state="half_open",
            consecutive_failures=health.consecutive_failures,
            probe_source=probe_source,
        )

    def _close(self, health: DomainHealth) -> None:
        previous = health.state
        health.state = "closed"
        health.consecutive_failures = 0
        health.recovery_successes = 0
        health.cooldown_seconds = 0.0
        health.cooldown_until = 0.0
        health.probe_used.clear()
        events.log_domain_state(
            domain=health.domain,
            from_state=previous,
            to_state="closed",
            consecutive_failures=0,
        )

    # ==================== 观测 / 测试辅助 ====================

    def domain_snapshot(self, domain: str) -> DomainHealth:
        with self._lock:
            return copy.copy(self._domain(domain))

    def source_snapshot(self, name: str) -> SourceHealth:
        with self._lock:
            return copy.copy(self._source(name))

    def reset(self) -> None:
        """清空所有健康状态（测试专用）。"""
        with self._lock:
            self._domains.clear()
            self._sources.clear()
