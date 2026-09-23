from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from common.http_transport import HttpTransportError, PooledHttpTransport


class _Headers:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def items(self):
        return self._values.items()


class _Response:
    def __init__(
        self,
        body: bytes = b"{}",
        *,
        status: int = 200,
        will_close: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.will_close = will_close
        self.headers = _Headers(headers)
        self._body = body

    def read(self) -> bytes:
        return self._body


def test_transport_reuses_keepalive_connection() -> None:
    created = []

    class Connection:
        def request(self, *args, **kwargs) -> None:
            del args, kwargs

        def getresponse(self) -> _Response:
            return _Response(headers={"X-Test": "ok"})

        def close(self) -> None:
            return None

    def factory():
        connection = Connection()
        created.append(connection)
        return connection

    transport = PooledHttpTransport(factory)
    first = transport.request("GET", "/first")
    second = transport.request("GET", "/second")

    assert first.status == 200
    assert first.headers == {"X-Test": "ok"}
    assert second.body == b"{}"
    assert len(created) == 1
    assert transport.connection_count == 1
    assert transport.idle_connection_count == 1


def test_transport_allows_bounded_parallel_requests() -> None:
    created = []
    barrier = threading.Barrier(2)
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    class Connection:
        def request(self, *args, **kwargs) -> None:
            nonlocal active, max_active
            del args, kwargs
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            barrier.wait(timeout=2)

        def getresponse(self) -> _Response:
            nonlocal active
            with state_lock:
                active -= 1
            return _Response()

        def close(self) -> None:
            return None

    def factory():
        connection = Connection()
        created.append(connection)
        return connection

    transport = PooledHttpTransport(factory, max_connections=2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda target: transport.request("GET", target),
                ("/one", "/two"),
            )
        )

    assert [result.status for result in results] == [200, 200]
    assert max_active == 2
    assert len(created) == 2


def test_transport_reconnects_once_after_stale_connection() -> None:
    created = []

    class Connection:
        def __init__(self, fail: bool) -> None:
            self.fail = fail
            self.closed = False

        def request(self, *args, **kwargs) -> None:
            del args, kwargs
            if self.fail:
                self.fail = False
                raise OSError("stale keepalive")

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            self.closed = True

    def factory():
        connection = Connection(fail=not created)
        created.append(connection)
        return connection

    transport = PooledHttpTransport(factory)
    result = transport.request("GET", "/resource")

    assert result.status == 200
    assert len(created) == 2
    assert created[0].closed is True


def test_transport_discards_server_closed_connection() -> None:
    created = []

    class Connection:
        def request(self, *args, **kwargs) -> None:
            del args, kwargs

        def getresponse(self) -> _Response:
            return _Response(will_close=True)

        def close(self) -> None:
            return None

    def factory():
        connection = Connection()
        created.append(connection)
        return connection

    transport = PooledHttpTransport(factory)
    transport.request("GET", "/one")
    transport.request("GET", "/two")

    assert len(created) == 2
    assert transport.connection_count == 0
    assert transport.idle_connection_count == 0


def test_transport_surfaces_error_after_retry_budget() -> None:
    class Connection:
        def request(self, *args, **kwargs) -> None:
            del args, kwargs
            raise OSError("offline")

        def close(self) -> None:
            return None

    transport = PooledHttpTransport(Connection)

    with pytest.raises(HttpTransportError, match="failed after reconnect"):
        transport.request("GET", "/resource")
