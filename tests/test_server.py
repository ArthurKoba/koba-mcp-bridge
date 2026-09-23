import pytest
from fastmcp import Client

import koba_mcp_bridge.server as server_module
from koba_mcp_bridge.server import _configured_backends, _mount_backends, app, mcp


@pytest.mark.asyncio
async def test_bridge_ping() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_ping", {})

    assert result.data is not None
    assert result.data["status"] == "ok"
    assert result.data["service"] == "koba-mcp-gateway"


@pytest.mark.asyncio
async def test_bridge_build_info() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_build_info", {})

    assert result.data is not None
    assert result.data["service"] == "koba-mcp-gateway"
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


def test_configured_backends_use_canonical_private_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "GITHUB_MCP_URL",
        "FILES_MCP_URL",
        "HTTP_MCP_URL",
        "ANALYSIS_MCP_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert _configured_backends() == {
        "github": "http://github-mcp:8000/mcp",
        "files": "http://files-mcp:8000/mcp",
        "http": "http://http-mcp:8000/mcp",
        "analysis": "http://analysis-mcp:8000/mcp",
    }


def test_configured_backends_allow_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_MCP_URL", "http://github-alt:9000/mcp")
    monkeypatch.setenv("FILES_MCP_URL", "http://files-alt:9000/mcp")
    monkeypatch.setenv("HTTP_MCP_URL", "http://http-alt:9000/mcp")
    monkeypatch.setenv("ANALYSIS_MCP_URL", "http://analysis-alt:9000/mcp")

    assert _configured_backends() == {
        "github": "http://github-alt:9000/mcp",
        "files": "http://files-alt:9000/mcp",
        "http": "http://http-alt:9000/mcp",
        "analysis": "http://analysis-alt:9000/mcp",
    }


def test_mounted_backends_are_unprefixed_private_proxies(
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

    result = _mount_backends(DummyServer())  # type: ignore[arg-type]

    assert sorted(result) == ["analysis", "files", "github", "http"]
    assert calls == [
        (
            "http://github-mcp:8000/mcp",
            {"name": "github-backend", "mode": "auto"},
        ),
        (
            "http://files-mcp:8000/mcp",
            {"name": "files-backend", "mode": "auto"},
        ),
        (
            "http://http-mcp:8000/mcp",
            {"name": "http-backend", "mode": "auto"},
        ),
        (
            "http://analysis-mcp:8000/mcp",
            {"name": "analysis-backend", "mode": "auto"},
        ),
    ]
    assert mounted == [(proxy, None)] * 4


def test_http_app_mounts_dedicated_gitlab_endpoint() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/gitlab" in paths
