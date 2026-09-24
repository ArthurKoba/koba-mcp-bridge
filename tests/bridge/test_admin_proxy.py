from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from bridge.admin_proxy import AdminProxy


def test_admin_proxy_is_registered_as_request_handler() -> None:
    proxy = AdminProxy("http://control-plane:8000")
    app = Starlette(routes=[Route("/admin", proxy.handle, methods=["GET"])])

    route = app.routes[0]
    assert isinstance(route, Route)
    assert route.endpoint == proxy.handle


@pytest.mark.asyncio
async def test_admin_proxy_rewrites_internal_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            request = httpx.Request("GET", "http://control-plane:8000/admin")
            return httpx.Response(
                307,
                headers={"location": "http://control-plane:8000/admin/"},
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    proxy = AdminProxy("http://control-plane:8000")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/admin",
            "raw_path": b"/admin",
            "query_string": b"",
            "headers": [(b"host", b"mcp.koba-nexus.ru")],
            "client": ("127.0.0.1", 1234),
            "server": ("mcp.koba-nexus.ru", 443),
            "http_version": "1.1",
        }
    )

    response = await proxy.handle(request)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/"
