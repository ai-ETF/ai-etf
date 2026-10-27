"""多源适配器的运行参数（环境变量 + 默认值）。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.3 / §5.3 / §5.5。

**不做热更新**：换源是低频运维动作，重启一次的成本远低于「运行时改配置导致状态
不一致」的风险；这与项目现有约定一致（`server/config/settings.py` 全部是环境变量 +
默认值）。
"""
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

# 优先顺序覆盖：语义是「排序」，不是「主/备绑定」。逗号分隔源名。
PRIORITY_ENV_VARS: Tuple[str, ...] = (
    "NAV_SOURCE_PRIORITY",
    "CALENDAR_SOURCE_PRIORITY",
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_csv(name: str) -> Tuple[str, ...]:
    raw = os.getenv(name) or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _parse_priority_overrides() -> Mapping[str, int]:
    """把各条线的偏好环境变量合并成 `源名 -> 排名`。

    同一个源只会出现在一条线里，所以合并不会冲突。未列出的源排在所有列出项之后，
    再按 `SourceMeta.priority` 排序。
    """
    overrides: dict[str, int] = {}
    rank = 0
    for var in PRIORITY_ENV_VARS:
        for name in _env_csv(var):
            if name not in overrides:
                overrides[name] = rank
                rank += 1
    return overrides


@dataclass(frozen=True)
class AdapterConfig:
    """熔断 / 降级参数。默认值来自设计文档 §5.3，均可在环境变量里覆盖。"""

    failure_threshold: int = 3
    cooldown_base: float = 60.0
    cooldown_max: float = 1800.0
    half_open_probes: int = 1
    recovery_confirm: int = 2
    # 接口级失败只降级该源，不碰域名；这里是它的软冷却时长。
    interface_degrade_cooldown: float = 60.0
    denylist: frozenset = field(default_factory=frozenset)
    priority_overrides: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "AdapterConfig":
        denylist = frozenset(_env_csv("SOURCE_DENYLIST"))
        return cls(
            failure_threshold=max(1, _env_int("SOURCE_FAILURE_THRESHOLD", 3)),
            cooldown_base=max(0.0, _env_float("SOURCE_COOLDOWN_BASE", 60.0)),
            cooldown_max=max(0.0, _env_float("SOURCE_COOLDOWN_MAX", 1800.0)),
            half_open_probes=max(1, _env_int("SOURCE_HALF_OPEN_PROBES", 1)),
            recovery_confirm=max(1, _env_int("SOURCE_RECOVERY_CONFIRM", 2)),
            interface_degrade_cooldown=max(
                0.0, _env_float("SOURCE_INTERFACE_DEGRADE_COOLDOWN", 60.0)
            ),
            denylist=denylist,
            priority_overrides=_parse_priority_overrides(),
        )


def override_rank(config: AdapterConfig, source_name: str) -> Optional[int]:
    """源在偏好覆盖里的排名；未显式覆盖返回 None。"""
    return config.priority_overrides.get(source_name)
