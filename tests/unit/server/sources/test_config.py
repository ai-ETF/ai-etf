"""多源适配器运行参数单元测试。

模块名称：server/sources/config.py
所测功能：`AdapterConfig.from_env()` 的默认值、环境变量覆盖、非法值回退、
         数值下限夹紧、偏好排序合并、域名 denylist 解析。
测试方法：monkeypatch 环境变量后直接调用 `from_env()`；不联网、不读 `.env`。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.3 / §5.3 / §5.5。
"""
import pytest

from server.sources.config import AdapterConfig, override_rank

_ENV_NAMES = (
    "SOURCE_FAILURE_THRESHOLD",
    "SOURCE_COOLDOWN_BASE",
    "SOURCE_COOLDOWN_MAX",
    "SOURCE_HALF_OPEN_PROBES",
    "SOURCE_RECOVERY_CONFIRM",
    "SOURCE_INTERFACE_DEGRADE_COOLDOWN",
    "SOURCE_DENYLIST",
    "NAV_SOURCE_PRIORITY",
    "CALENDAR_SOURCE_PRIORITY",
)


@pytest.fixture
def clean_env(monkeypatch):
    """确保用例从「环境变量全部未设置」开始，不继承机器上的真实配置。"""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


# ==================== 正常数据：默认值 / 覆盖 ====================


def test_默认参数与设计文档一致(clean_env):
    config = AdapterConfig.from_env()

    assert config.failure_threshold == 3
    assert config.cooldown_base == 60.0
    assert config.cooldown_max == 1800.0
    assert config.half_open_probes == 1
    assert config.recovery_confirm == 2
    assert config.interface_degrade_cooldown == 60.0
    assert config.denylist == frozenset()
    assert config.priority_overrides == {}


def test_环境变量可以覆盖全部熔断参数(clean_env, monkeypatch):
    monkeypatch.setenv("SOURCE_FAILURE_THRESHOLD", "5")
    monkeypatch.setenv("SOURCE_COOLDOWN_BASE", "30")
    monkeypatch.setenv("SOURCE_COOLDOWN_MAX", "900")
    monkeypatch.setenv("SOURCE_HALF_OPEN_PROBES", "2")
    monkeypatch.setenv("SOURCE_RECOVERY_CONFIRM", "4")
    monkeypatch.setenv("SOURCE_INTERFACE_DEGRADE_COOLDOWN", "15")
    monkeypatch.setenv("SOURCE_DENYLIST", "push2delay.eastmoney.com")

    config = AdapterConfig.from_env()

    assert config.failure_threshold == 5
    assert config.cooldown_base == 30.0
    assert config.cooldown_max == 900.0
    assert config.half_open_probes == 2
    assert config.recovery_confirm == 4
    assert config.interface_degrade_cooldown == 15.0
    assert config.denylist == frozenset({"push2delay.eastmoney.com"})


# ==================== 异常 / 边界：非法值、下限 ====================


_FIELD_OF = {
    "SOURCE_FAILURE_THRESHOLD": "failure_threshold",
    "SOURCE_COOLDOWN_BASE": "cooldown_base",
    "SOURCE_HALF_OPEN_PROBES": "half_open_probes",
}


@pytest.mark.parametrize(
    "name,default",
    [
        ("SOURCE_FAILURE_THRESHOLD", 3),
        ("SOURCE_COOLDOWN_BASE", 60.0),
        ("SOURCE_HALF_OPEN_PROBES", 1),
    ],
)
def test_非法数值回退默认值(clean_env, monkeypatch, name, default):
    monkeypatch.setenv(name, "not-a-number")

    assert getattr(AdapterConfig.from_env(), _FIELD_OF[name]) == default


def test_阈值类参数被夹紧到合法下限(clean_env, monkeypatch):
    monkeypatch.setenv("SOURCE_FAILURE_THRESHOLD", "0")
    monkeypatch.setenv("SOURCE_HALF_OPEN_PROBES", "0")
    monkeypatch.setenv("SOURCE_RECOVERY_CONFIRM", "-2")
    monkeypatch.setenv("SOURCE_COOLDOWN_BASE", "-5")
    monkeypatch.setenv("SOURCE_INTERFACE_DEGRADE_COOLDOWN", "-1")

    config = AdapterConfig.from_env()

    assert config.failure_threshold == 1
    assert config.half_open_probes == 1
    assert config.recovery_confirm == 1
    assert config.cooldown_base == 0.0
    assert config.interface_degrade_cooldown == 0.0


def test_denylist过滤空白项(clean_env, monkeypatch):
    monkeypatch.setenv(
        "SOURCE_DENYLIST",
        "push2delay.eastmoney.com, , api.fund.eastmoney.com,",
    )

    assert AdapterConfig.from_env().denylist == frozenset(
        {"push2delay.eastmoney.com", "api.fund.eastmoney.com"}
    )


# ==================== 偏好排序 ====================


def test_偏好覆盖按环境变量顺序合并(clean_env, monkeypatch):
    monkeypatch.setenv("NAV_SOURCE_PRIORITY", "em_lsjz, em_pingzhongdata")
    monkeypatch.setenv("CALENDAR_SOURCE_PRIORITY", "sina_trade_date")

    config = AdapterConfig.from_env()

    assert override_rank(config, "em_lsjz") == 0
    assert override_rank(config, "em_pingzhongdata") == 1
    assert override_rank(config, "sina_trade_date") == 2
    assert override_rank(config, "em_mobile") is None


def test_偏好覆盖去重且保留首次排名(clean_env, monkeypatch):
    """同一个源重复出现时只记第一次，不能让后面的重复项挤掉其它源的排名。"""
    monkeypatch.setenv("NAV_SOURCE_PRIORITY", "em_lsjz,em_mobile,em_lsjz")

    config = AdapterConfig.from_env()

    assert override_rank(config, "em_lsjz") == 0
    assert override_rank(config, "em_mobile") == 1
