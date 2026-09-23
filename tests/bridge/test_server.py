import pytest
from fastmcp import Client

import bridge.server as server_module
from bridge.server import (
    _mount_aggregate_backends,
    app,
    mcp,
)


@pytest.mark.asyncio
async def test_bridge_ping() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_ping", {})

    assert result.data is not None
    assert result.data["status"] == "ok"
    assert result.data["service"] == "mcp-bridge"


@pytest.mark.asyncio
async def test_bridge_build_info() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_build_info", {})

    assert result.data is not None
    assert result.data["service"] == "mcp-bridge"
    assert result.data["version"]
    assert result.data["commit"]
    assert result.data["built_at"]
    assert result.data["started_at"]
    assert result.data["python"]


def test_github_oauth_is_infisical_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        ("github/oauth", "CLIENT_ID"): "client-id",
        ("github/oauth", "CLIENT_SECRET"): "client-secret",
        ("github/oauth", "JWT_SIGNING_KEY"): "jwt",
        ("github/oauth", "ALLOWED_USERS"): "ArthurKoba,ReviewerBot",
    }
    monkeypatch.setattr(
        server_module,
        "resolve_config_secret",
        lambda path, name: values[(path, name)],
    )

    assert server_module._github_oauth_value("CLIENT_ID") == "client-id"
    assert server_module._allowed_github_users() == {
        "arthurkoba",
        "reviewerbot",
    }


def test_github_oauth_failure_preserves_infisical_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_secret(path: str, name: str) -> str:
        del path, name
        raise server_module.SecretError("Infisical API HTTP 403: denied")

    monkeypatch.setattr(server_module, "resolve_config_secret", fail_secret)

    with pytest.raises(RuntimeError, match="Infisical API HTTP 403"):
        server_module._github_oauth_value("CLIENT_ID")


def test_aggregate_mounts_expected_proxy_namespaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    mounted: list[tuple[object, str | None]] = []
    proxy = object()

    def fake_create_proxy(target: str, **settings: str) -> object:
        calls.append((target, settings))
        return proxy

    class DummyServer:
        def mount(
            self,
            *,
            server: object,
            namespace: str | None = None,
        ) -> None:
            mounted.append((server, namespace))

    monkeypatch.setattr(server_module, "create_proxy", fake_create_proxy)

    backends = {
        "github": "http://github:8000/mcp",
        "gitlab": "http://gitlab:8000/mcp",
        "files": "http://files:8000/mcp",
        "http": "http://http:8000/mcp",
        "analysis": "http://analysis:8000/mcp",
    }
    _mount_aggregate_backends(DummyServer(), backends)  # type: ignore[arg-type]

    assert calls == [
        (
            "http://github:8000/mcp",
            {"name": "github-backend", "mode": "auto"},
        ),
        (
            "http://files:8000/mcp",
            {"name": "files-backend", "mode": "auto"},
        ),
        (
            "http://http:8000/mcp",
            {"name": "http-backend", "mode": "auto"},
        ),
        (
            "http://analysis:8000/mcp",
            {"name": "analysis-backend", "mode": "auto"},
        ),
        (
            "http://gitlab:8000/mcp",
            {"name": "gitlab-backend", "mode": "auto"},
        ),
    ]
    assert mounted == [
        (proxy, None),
        (proxy, None),
        (proxy, None),
        (proxy, None),
        (proxy, "gitlab"),
    ]


def test_http_app_mounts_all_public_surfaces() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {
        "/github",
        "/gitlab",
        "/files",
        "/http",
        "/analysis",
    } <= paths
