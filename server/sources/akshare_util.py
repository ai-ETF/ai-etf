"""akshare 调用的超时兜底。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.5 硬约束 3。

akshare 的部分函数（交易日历、HTML 表格、混淆串解码）内部 `requests.get` **没有
timeout**，上游卡住会把调用线程一直挂住。这里用 `ThreadPoolExecutor` +
`future.result(timeout)` 让**调用方**能按时返回并记 `TIMEOUT`。

**局限必须说清**：它不能杀死底层线程，超时后那个线程仍可能在后台跑完。这是过渡
方案，不是真超时；能自解析的源一律用 `requests` 的真 timeout。
"""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable

from server.sources.models import FailureKind, SourceError

logger = logging.getLogger(__name__)


def run_akshare_with_timeout(
    source_name: str,
    timeout: float,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """在独立线程里调用 akshare 函数，超时抛 `SourceError(TIMEOUT)`。"""
    # 每次调用单独建池：akshare 调用是低频动作，没必要维护长驻线程池。
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"akshare-{source_name}")
    future = executor.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        raise SourceError(
            source_name,
            FailureKind.TIMEOUT,
            f"akshare 调用超过 {timeout}s（底层线程无法被强制终止，仅为兜底）",
        ) from exc
    except SourceError:
        raise
    except Exception as exc:  # akshare 内部异常类型不稳定，统一按连接/上游异常处理
        logger.warning("akshare 调用异常 %s: %s: %s", source_name, type(exc).__name__, exc)
        raise SourceError(
            source_name,
            FailureKind.CONNECTION_ERROR,
            f"{type(exc).__name__}: {exc}",
        ) from exc
    finally:
        # wait=False：不阻塞调用方；超时线程由解释器在结束时回收。
        executor.shutdown(wait=False, cancel_futures=True)
