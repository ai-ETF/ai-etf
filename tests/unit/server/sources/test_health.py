"""域名健康状态机单测（设计文档 §8.1）。

核心断言是「域级 vs 接口级」的分界：

- 域级失败（TIMEOUT 等）会让整个域名熔断，域名下所有源一起被跳过；
- 接口级失败（EMPTY_PAYLOAD 等）只软降级该源，域名必须保持 closed。

不联网、不连数据库。
"""
import pytest

from server.sources.config import AdapterConfig
from server.sources.health import HealthTracker
from server.sources.models import FailureKind, SourceError, SourceMeta


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSource:
    def __init__(self, name: str, domain: str, priority: int = 100):
        self.meta = SourceMeta(
            name=name,
            domain=domain,
            capabilities=frozenset({"history"}),
            priority=priority,
        )


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def tracker(clock):
    config = AdapterConfig(
        failure_threshold=3,
        cooldown_base=60.0,
        cooldown_max=1800.0,
        half_open_probes=1,
        recovery_confirm=2,
        interface_degrade_cooldown=60.0,
    )
    return HealthTracker(config=config, clock=clock)


def _fail(tracker, source, kind=FailureKind.TIMEOUT, message="boom"):
    tracker.record_failure(source, SourceError(source.meta.name, kind, message))


def test_连续三次域级失败进入熔断(tracker):
    source = FakeSource("a", "domain-a")
    for _ in range(3):
        _fail(tracker, source)

    health = tracker.domain_snapshot("domain-a")
    assert health.state == "open"
    assert health.consecutive_failures == 3


def test_冷却期内该域名下所有源都被跳过(tracker, clock):
    a = FakeSource("a", "domain-a")
    b = FakeSource("b", "domain-a")
    for _ in range(3):
        _fail(tracker, a)

    assert tracker.pick_usable([a, b]) == []

    clock.advance(59)
    assert tracker.pick_usable([a, b]) == []


def test_冷却结束后进入半开并放行一次试探(tracker, clock):
    source = FakeSource("a", "domain-a")
    for _ in range(3):
        _fail(tracker, source)

    clock.advance(60)
    assert tracker.pick_usable([source]) == [source]
    assert tracker.domain_snapshot("domain-a").state == "half_open"

    assert tracker.allow_attempt(source) is True
    assert tracker.allow_attempt(source) is False  # 每个源每轮只放行 1 次


def test_半开试探连续成功两次才恢复(tracker, clock):
    source = FakeSource("a", "domain-a")
    for _ in range(3):
        _fail(tracker, source)

    clock.advance(60)
    tracker.pick_usable([source])

    assert tracker.allow_attempt(source) is True
    tracker.record_success(source)
    assert tracker.domain_snapshot("domain-a").state == "half_open"
    assert tracker.domain_snapshot("domain-a").recovery_successes == 1

    # 成功后重新给一轮试探额度，单源也能凑齐恢复确认
    assert tracker.allow_attempt(source) is True
    tracker.record_success(source)

    health = tracker.domain_snapshot("domain-a")
    assert health.state == "closed"
    assert health.consecutive_failures == 0
    assert health.recovery_successes == 0


def test_半开试探失败冷却翻倍(tracker, clock):
    source = FakeSource("a", "domain-a")
    for _ in range(3):
        _fail(tracker, source)

    clock.advance(60)
    tracker.pick_usable([source])
    assert tracker.allow_attempt(source) is True

    _fail(tracker, source)

    health = tracker.domain_snapshot("domain-a")
    assert health.state == "open"
    assert health.cooldown_seconds == 120.0
    assert health.cooldown_until == clock.now + 120.0


def test_接口级失败只降级该源域名仍健康(tracker):
    bad = FakeSource("bad", "domain-a")
    good = FakeSource("good", "domain-a")

    for _ in range(3):
        _fail(tracker, bad, kind=FailureKind.EMPTY_PAYLOAD, message="200 但空数据")

    health = tracker.domain_snapshot("domain-a")
    assert health.state == "closed"          # 域名没被拖下水
    assert health.consecutive_failures == 0  # 接口级失败不计域名连续失败

    # 有其它健康候选时跳过被软降级的源
    assert tracker.pick_usable([bad, good]) == [good]
    # 唯一候选仍要尝试，不能因为软降级直接变成 AllSourcesFailed
    assert tracker.pick_usable([bad]) == [bad]


def test_接口级失败解除(tracker):
    source = FakeSource("a", "domain-a")
    _fail(tracker, source, kind=FailureKind.EMPTY_PAYLOAD)
    assert tracker.pick_usable([source]) == [source]  # 唯一候选仍可试

    tracker.record_success(source)
    assert tracker.source_snapshot("a").degraded_until == 0.0


def test_切断域名A域名B完全不受影响(tracker):
    a = FakeSource("a", "domain-a")
    b = FakeSource("b", "domain-b")

    for _ in range(3):
        _fail(tracker, a)

    assert tracker.domain_snapshot("domain-a").state == "open"
    assert tracker.domain_snapshot("domain-b").state == "closed"
    assert tracker.pick_usable([b]) == [b]


def test_成功一次清零连续失败计数(tracker):
    source = FakeSource("a", "domain-a")
    _fail(tracker, source)
    _fail(tracker, source)
    tracker.record_success(source)

    assert tracker.domain_snapshot("domain-a").consecutive_failures == 0

    _fail(tracker, source)
    assert tracker.domain_snapshot("domain-a").state == "closed"
