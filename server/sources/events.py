"""结构化事件日志。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §7。

每次状态变化产生**一行可解析的 JSON**（message 就是 JSON 串），便于日后
`grep` / `jq` 统计「哪个源最常失败」「一天换了几次源」。日志落盘与采集是运维侧
的事，本模块只保证格式可解析（设计文档 Q10）。
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))


def _emit(event: str, level: int, *, exc_info: bool = False, **fields: Any) -> None:
    payload = {
        "event": event,
        "ts": datetime.now(BEIJING_TZ).isoformat(timespec="seconds"),
        **fields,
    }
    logger.log(
        level,
        json.dumps(payload, ensure_ascii=False, default=str),
        exc_info=exc_info,
    )


def log_source_result(
    capability: str,
    source: str,
    domain: str,
    ok: bool,
    elapsed_ms: int,
    kind: Optional[str] = None,
    error: Optional[str] = None,
    code: Optional[str] = None,
    exc_info: bool = False,
) -> None:
    """单次取数结果。成功 DEBUG（高频），普通失败 WARNING。

    `exc_info=True` 表示源抛了未按契约包装的异常（`FailureKind.UNEXPECTED`）：
    按 ERROR 记录并附完整堆栈，避免代码缺陷被当成普通上游失败。
    """
    if exc_info:
        level = logging.ERROR
    else:
        level = logging.DEBUG if ok else logging.WARNING
    _emit(
        "source_result",
        level,
        exc_info=exc_info,
        capability=capability,
        source=source,
        domain=domain,
        ok=ok,
        kind=kind,
        elapsed_ms=elapsed_ms,
        error=error,
        code=code,
    )


def log_batch_empty(
    capability: str,
    source: str,
    domain: str,
    requested: int,
    returned: int,
    sample: list[str],
) -> None:
    """批量请求非空、但过滤后一个代码都没命中。

    批量源本来就是「成功但可能零命中」，不能升级成 `AllSourcesFailed`；
    但零命中往往意味着源窗口/格式漂移（如 `showday` 变成空、代码列错位），
    必须留一条 WARNING 供运维发现。
    """
    _emit(
        "batch_empty",
        logging.WARNING,
        capability=capability,
        source=source,
        domain=domain,
        requested=requested,
        returned=returned,
        sample=sample,
    )


def log_domain_state(
    domain: str,
    from_state: str,
    to_state: str,
    consecutive_failures: int = 0,
    cooldown_until: Optional[float] = None,
    trigger: Optional[str] = None,
    probe_source: Optional[str] = None,
) -> None:
    """域名健康状态变化。熔断 / 试探 / 恢复都是可解析的一行。"""
    if to_state == "open":
        level = logging.ERROR
    else:
        level = logging.WARNING
    _emit(
        "domain_state",
        level,
        domain=domain,
        **{"from": from_state, "to": to_state},
        consecutive_failures=consecutive_failures,
        cooldown_until=cooldown_until,
        trigger=trigger,
        probe_source=probe_source,
    )


def log_source_switch(
    capability: str,
    from_source: str,
    to_source: str,
    reason: str,
    tried: list[str],
    code: Optional[str] = None,
) -> None:
    """从上一个失败的源切到下一个候选。"""
    _emit(
        "source_switch",
        logging.WARNING,
        capability=capability,
        **{"from": from_source, "to": to_source},
        reason=reason,
        tried=tried,
        code=code,
    )


def log_all_sources_failed(
    capability: str,
    tried: list[dict],
    code: Optional[str] = None,
) -> None:
    """最高优先级告警：这一刻这个能力完全没数据。"""
    _emit(
        "all_sources_failed",
        logging.ERROR,
        capability=capability,
        code=code,
        tried=tried,
    )
