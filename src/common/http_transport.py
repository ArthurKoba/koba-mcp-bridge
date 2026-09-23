from __future__ import annotations

import http.client
import queue
import threading
from collections.abc import Callable, Mapping

from .models import StrictModel


class HttpTransportError(RuntimeError):
    """Raised when the shared HTTP transport cannot complete a request."""


class HttpTransportResponse(StrictModel):
    status: int
    headers: dict[str, str]
    body: bytes
    will_close: bool


ConnectionFactory = Callable[[], http.client.HTTPConnection]


class PooledHttpTransport:
    """Small thread-safe HTTP/1.1 connection pool with one reconnect retry."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        max_connections: int = 8,
        acquire_timeout: float = 30.0,
    ) -> None:
        self._connection_factory = connection_factory
        self._max_connections = max(1, int(max_connections))
        self._acquire_timeout = float(acquire_timeout)
        self._connections: queue.LifoQueue[http.client.HTTPConnection] = queue.LifoQueue()
        self._connection_count = 0
        self._lock = threading.Lock()

    @property
    def connection_count(self) -> int:
        with self._lock:
            return self._connection_count

    @property
    def idle_connection_count(self) -> int:
        return self._connections.qsize()

    def _acquire(self) -> http.client.HTTPConnection:
        try:
            return self._connections.get_nowait()
        except queue.Empty:
            pass

        create_new = False
        with self._lock:
            if self._connection_count < self._max_connections:
                self._connection_count += 1
                create_new = True

        if create_new:
            try:
                return self._connection_factory()
            except Exception:
                with self._lock:
                    self._connection_count -= 1
                raise

        try:
            return self._connections.get(timeout=self._acquire_timeout)
        except queue.Empty as exc:
            raise HttpTransportError(
                "timed out waiting for an available HTTP connection"
            ) from exc

    def _release(
        self,
        connection: http.client.HTTPConnection,
        *,
        reusable: bool,
    ) -> None:
        if reusable:
            self._connections.put(connection)
            return
        try:
            connection.close()
        finally:
            with self._lock:
                self._connection_count = max(0, self._connection_count - 1)

    def request(
        self,
        method: str,
        target: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        reconnect_retries: int = 1,
    ) -> HttpTransportResponse:
        attempts = max(0, int(reconnect_retries)) + 1
        last_error: OSError | http.client.HTTPException | None = None

        for attempt in range(attempts):
            connection = self._acquire()
            try:
                connection.request(
                    method,
                    target,
                    body=body,
                    headers=dict(headers or {}),
                )
                response = connection.getresponse()
                raw = response.read()
                response_headers = dict(response.headers.items())
                result = HttpTransportResponse(
                    status=response.status,
                    headers=response_headers,
                    body=raw,
                    will_close=response.will_close,
                )
                self._release(connection, reusable=not response.will_close)
                return result
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc
                self._release(connection, reusable=False)
                if attempt + 1 >= attempts:
                    break

        raise HttpTransportError(
            f"HTTP request failed after reconnect: {last_error}"
        ) from last_error
