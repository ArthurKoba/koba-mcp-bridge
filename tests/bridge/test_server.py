import pytest
from fastmcp import Client

from bridge.server import app, mcp


@pytest.mark.asyncio
async def test_bridge_ping() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_ping", {})

    assert result.data is not None
    assert result.data["status"] == "ok"
    assert result.data["service"] == "mcp-bridge"


@pytest.mark.asyncio
async def test_bridge_root_is_map_not_backend_namespace() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert {
        "bridge_ping",
        "bridge_build_info",
        "bridge_backends",
        "bridge_tools",
        "bridge_call",
        "bridge_capabilities",
    } <= names
    assert "github_agent_status" not in names
    assert "accounts" not in names
    assert "file_status" not in names
    assert "curl_request" not in names


@pytest.mark.asyncio
async def test_bridge_capabilities_publish_single_origin_paths() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_capabilities", {})

    assert result.data is not None
    assert {
        "/mcp",
        "/github/mcp",
        "/gitlab/mcp",
        "/files/mcp",
        "/web/mcp",
        "/analysis/mcp",
        "/ghidra/mcp",
        "/admin",
    } <= set(result.data["public_surfaces"])


def test_http_app_mounts_expected_public_surfaces() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {
        "/github",
        "/gitlab",
        "/files",
        "/web",
        "/analysis",
        "/ghidra",
        "/admin",
        "/admin/{path:path}",
    } <= paths
    assert "/http" not in paths
    assert "/curl" not in paths
