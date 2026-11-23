"""自解析源共用的 HTTP 取数基类。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.5。

净值线（`em_*`）**自解析直连**，用 `requests.Session` + 显式 `timeout`，不再经过
akshare。这里只做「请求 + 把异常收敛成 `SourceError`」，解析与字段映射留在各自的源里。

线程安全：`requests.Session` 不保证跨线程安全，这里用 `threading.local` 让每个线程
持有自己的 Session（进程内调度器线程与请求线程互不干扰）。
"""
import threading
from typing import Any, Mapping, Optional

import requests

from server.sources.models import BaseSource, FailureKind, SourceError

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "*/*",
}


class HttpSource(BaseSource):
    """所有自解析 HTTP 源的基类。

    子类只需要声明 `meta`，并按需覆盖 `headers` / `encoding`。
    """

    headers: Mapping[str, str] = DEFAULT_HEADERS
    encoding: Optional[str] = "utf-8"

    def __init__(self) -> None:
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.headers)
            self._local.session = session
        return session

    def _get(
        self,
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> requests.Response:
        """发起 GET，所有网络/HTTP 错误都转成带分类的 `SourceError`。

        `timeout` 来自 `SourceMeta.timeout`，是**真超时**（连接 + 读取），
        不是 akshare 那种无 timeout 的裸调用。
        """
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.meta.timeout,
            )
        except requests.Timeout as exc:
            raise SourceError(
                self.meta.name,
                FailureKind.TIMEOUT,
                f"GET {url} 超过 {self.meta.timeout}s: {exc}",
            ) from exc
        except requests.ConnectionError as exc:
            raise SourceError(
                self.meta.name,
                FailureKind.CONNECTION_ERROR,
                f"GET {url} 连接失败: {exc}",
            ) from exc
        except requests.RequestException as exc:
            raise SourceError(
                self.meta.name,
                FailureKind.CONNECTION_ERROR,
                f"GET {url} 请求异常: {type(exc).__name__}: {exc}",
            ) from exc

        if response.status_code == 403:
            raise SourceError(
                self.meta.name, FailureKind.HTTP_403, f"GET {url} 返回 403（域名被拒）"
            )
        if response.status_code == 429:
            raise SourceError(
                self.meta.name, FailureKind.HTTP_429, f"GET {url} 返回 429（限速）"
            )
        if 500 <= response.status_code < 600:
            raise SourceError(
                self.meta.name,
                FailureKind.HTTP_5XX,
                f"GET {url} 返回 {response.status_code}",
            )
        if response.status_code >= 400:
            raise SourceError(
                self.meta.name,
                FailureKind.INVALID_REQUEST,
                f"GET {url} 返回 {response.status_code}",
            )

        if self.encoding:
            response.encoding = self.encoding
        return response

    def _get_text(self, url: str, **kwargs: Any) -> str:
        return self._get(url, **kwargs).text

    def _get_json(self, url: str, **kwargs: Any) -> Any:
        response = self._get(url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(
                self.meta.name,
                FailureKind.PARSE_ERROR,
                f"GET {url} 返回内容不是合法 JSON: {exc}",
            ) from exc
