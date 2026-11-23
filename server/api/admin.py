"""管理接口：交易日历的人工刷新与核验。

设计依据：`docs/20-设计/基金与交易/交易日历缓存.md` §4.4。

- 鉴权：`X-Admin-Token` 与 `ADMIN_API_TOKEN` 常量时间比较；未配置返回 503（默认关闭）；
- 刷新：`POST /admin/trading-calendar/refresh`，必须带 `Idempotency-Key`；
- 核验：`GET /admin/trading-calendar/status`，只读，不触上游。

接口在服务进程内执行刷新，成功后原子替换内存快照，不需要重启。
"""
import hmac
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from server.services.trading_calendar import (
    CalendarDataInvalid,
    CalendarRefreshTimeout,
    RefreshInProgress,
    get_calendar_cache,
)
from server.sources.models import AllSourcesFailed, FailureKind

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/trading-calendar", tags=["admin"])


def require_admin_token(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """管理凭证校验：未配置凭证时接口默认关闭（503）。"""
    expected = os.getenv("ADMIN_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="管理接口未启用（未配置 ADMIN_API_TOKEN）")
    if not x_admin_token or not hmac.compare_digest(
        x_admin_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="管理凭证无效")


@router.post("/refresh")
def refresh_calendar(
    dry_run: bool = Query(default=False, description="只预览 diff，不写库、不替换内存"),
    idempotency_key: Optional[str] = Header(
        default=None, alias="Idempotency-Key",
        description="调用方提供，仅用于日志追踪；整表替换天然幂等",
    ),
    _: None = Depends(require_admin_token),
):
    """人工全量刷新交易日历。

    单一源 `sina_trade_date`；成功后一次 RPC 事务性整表替换并原子替换内存。
    失败时旧快照与内存原样保留，`state.last_error` 尽力记录。
    """
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="缺少 Idempotency-Key")

    request_id = uuid.uuid4().hex
    cache = get_calendar_cache()
    logger.info(
        "[交易日历] 收到刷新请求 request_id=%s dry_run=%s idempotency_key=%s",
        request_id, dry_run, idempotency_key,
    )

    try:
        result = cache.refresh(dry_run=dry_run)
    except RefreshInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CalendarRefreshTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except CalendarDataInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except AllSourcesFailed as exc:
        timed_out = any(
            item.get("kind") == FailureKind.TIMEOUT.value for item in exc.tried
        )
        raise HTTPException(
            status_code=504 if timed_out else 502,
            detail={
                "message": "交易日历源失败，未写库",
                "capability": exc.capability,
                "tried": exc.tried,
            },
        )
    except Exception as exc:
        logger.exception("[交易日历] 刷新失败 request_id=%s", request_id)
        raise HTTPException(status_code=500, detail=f"刷新失败：{type(exc).__name__}: {exc}")

    return {
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "dry_run": result.dry_run,
        "coverage_start": result.coverage_start.isoformat(),
        "coverage_end": result.coverage_end.isoformat(),
        "source": result.source,
        "stats": result.stats,
        "diff": result.diff,
        "diff_truncated": result.diff_truncated,
        "elapsed_ms": result.elapsed_ms,
    }


@router.get("/status")
def calendar_status(_: None = Depends(require_admin_token)):
    """只读核验：内存快照、覆盖区间、最后成功/失败、行数统计。

    不访问上游数据源；DB 读取失败时在响应里带 `db_error`，不掩盖。
    """
    report = get_calendar_cache().describe()
    report["request_id"] = uuid.uuid4().hex
    return report
