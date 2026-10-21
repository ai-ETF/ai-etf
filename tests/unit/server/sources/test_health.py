"""域名健康状态机与接口级软降级单元测试。

模块名称：server/sources/health.py
所测功能：连续失败熔断、冷却期过滤、半开试探与恢复确认、指数退避封顶、
         接口级失败只降级该源、域名之间故障隔离。
测试方法：注入 `FakeClock` 驱动 `time.monotonic`，`FakeSource` 只提供 `SourceMeta`；
         不联网、不连数据库。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.4 / §5.2 / §5.3 / §5.4 与 §8.1。
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


def _tracker(clock, **overrides):
    params = dict(
        failure_threshold=3,
        cooldown_base=60.0,
        cooldown_max=1800.0,
        half_open_probes=1,
        recovery_confirm=2,
        interface_degrade_cooldown=60.0,
    )
    params.update(overrides)
    return HealthTracker(config=AdapterConfig(**params), clock=clock)


@pytest.fixture
def tracker(clock):
    return _tracker(clock)


def _fail(tracker, source, kind=FailureKind.TIMEOUT, message="boom"):
    tracker.record_failure(source, SourceError(source.meta.name, kind, message))


# ==================== 熔断：正常路径与边界 ====================


def test_连续三次域级失败进入熔断(tracker):
    source = FakeSource("a", "domain-a")

    for _ in range(3):
        _fail(tracker, source)

    health = tracker.domain_snapshot("domain-a")
    assert health.state == "open"
    assert health.consecutive_failures == 3
    assert health.last_failure_kind == FailureKind.TIMEOUT.value


def test_自定义阈值两次失败即熔断(clock):
    tracker = _tracker(clock, failure_threshold=2)
    source = FakeSource("a", "domain-a")

    _fail(tracker, source)
    assert tracker.domain_snapshot("domain-a").state == "closed"

    _fail(tracker, source)
    assert tracker.domain_snapshot("domain-a").state == "open"


def test_冷却期内该域名下所有源都被跳过(tracker, clock):
    a = FakeSource("a", "domain-a")
    b = FakeSource("b", "domain-a")
    for _ in range(3):
        _fail(tracker, a)

    assert tracker.pick_usable([a, b]) == []

    clock.advance(59)
    assert tracker.pick_usable([a, b]) == []


def test_冷却结束后进入半开不消耗额度(tracker, clock):
    source = FakeSource("a", "domain-a")
    for _ in range(3):
        _fail(tracker, source)

    clock.advance(60)

    assert tracker.pick_usable([source]) == [source]
    assert tracker.domain_snapshot("domain-a").state == "half_open"
    # pick 只是判定，不扣额度；额度在真正发请求前的 allow_attempt 扣
    assert tracker.allow_attempt(source) is True
    assert tracker.allow_attempt(source) is False


def test_半开时同域名两个源各放行一次试探(tracker, clock):
    a = FakeSource("a", "domain-a")
    b = FakeSource("b", "domain-a")
    for _ in range(3):
        _fail(tracker, a)

    clock.advance(60)
    assert tracker.pick_usable([a, b]) == [a, b]

    assert tracker.allow_attempt(a) is True
    assert tracker.allow_attempt(a) is False
    assert tracker.allow_attempt(b) is True
    assert tracker.allow_attempt(b) is False


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

    # 成功后重新给一轮试探额度，单源域名也能凑齐恢复确认
    assert tracker.allow_attempt(source) is True
    tracker.record_success(source)

    health = tracker.domain_snapshot("domain-a")
    assert health.state == "closed"
    assert health.consecutive_failures == 0
    assert health.recovery_successes == 0


def test_恢复确认次数可由配置提高(clock):
    tracker = _tracker(clock, recovery_confirm=3)
    source = FakeSource("a", "domain-a")
    for _ in range(3):
        _fail(tracker, source)
    clock.advance(60)
    tracker.pick_usable([source])

    for successes in (1, 2):
        assert tracker.allow_attempt(source) is True
        tracker.record_success(source)
        health = tracker.domain_snapshot("domain-a")
        assert health.state == "half_open"
        assert health.recovery_successes == successes

    assert tracker.allow_attempt(source) is True
    tracker.record_success(source)
    assert tracker.domain_snapshot("domain-a").state == "closed"


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


def test_冷却翻倍在cooldown_max封顶(clock):
    tracker = _tracker(clock, cooldown_base=60.0, cooldown_max=120.0)
    source = FakeSource("a", "domain-a")
    for _ in range(3):
        _fail(tracker, source)

    clock.advance(60)
    tracker.pick_usable([source])
    assert tracker.allow_attempt(source) is True
    _fail(tracker, source)
    assert tracker.domain_snapshot("domain-a").cooldown_seconds == 120.0

    clock.advance(120)
    tracker.pick_usable([source])
    assert tracker.allow_attempt(source) is True
    _fail(tracker, source)
    assert tracker.domain_snapshot("domain-a").cooldown_seconds == 120.0


# ==================== 接口级失败：只降级该源 ====================


def test_接口级失败只降级该源域名仍健康(tracker):
    bad = FakeSource("bad", "domain-a")
    good = FakeSource("good", "domain-a")

    for _ in range(3):
        _fail(tracker, bad, kind=FailureKind.EMPTY_PAYLOAD, message="200 但空数据")

    health = tracker.domain_snapshot("domain-a")
    assert health.state == "closed"
    assert health.consecutive_failures == 0

    # 有其它健康候选时跳过被软降级的源
    assert tracker.pick_usable([bad, good]) == [good]
    # 唯一候选仍要尝试，不能因为软降级直接变成 AllSourcesFailed
    assert tracker.pick_usable([bad]) == [bad]


def test_接口级失败软降级到期后不再跳过(clock):
    tracker = _tracker(clock)
    bad = FakeSource("bad", "domain-a")
    good = FakeSource("good", "domain-a")

    _fail(tracker, bad, kind=FailureKind.PARSE_ERROR)
    assert tracker.pick_usable([bad, good]) == [good]

    clock.advance(60)
    assert tracker.pick_usable([bad, good]) == [bad, good]


def test_接口级失败解除(tracker):
    source = FakeSource("a", "domain-a")
    _fail(tracker, source, kind=FailureKind.EMPTY_PAYLOAD)
    assert tracker.pick_usable([source]) == [source]

    tracker.record_success(source)
    assert tracker.source_snapshot("a").degraded_until == 0.0


# ==================== 域名隔离与恢复 ====================


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
