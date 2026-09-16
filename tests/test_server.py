import pytest
from fastmcp import Client

from koba_mcp_bridge.server import _configured_backends, mcp


@pytest.mark.asyncio
async def test_bridge_ping() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_ping", {})

    assert result.data is not None
    assert result.data["status"] == "ok"
    assert result.data["service"] == "koba-mcp-bridge"


@pytest.mark.asyncio
async def test_bridge_build_info() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_build_info", {})

    assert result.data is not None
    assert result.data["service"] == "koba-mcp-bridge"
    assert result.data["version"]
    assert result.data["commit"]
    assert result.data["built_at"]
    assert result.data["started_at"]
    assert result.data["python"]


def test_configured_backends_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GHIDRA_MCP_URL", raising=False)
    assert _configured_backends() == {}


def test_configured_backends_ghidra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHIDRA_MCP_URL", "http://ghidra-mcp:8081/mcp")
    assert _configured_backends() == {"ghidra": "http://ghidra-mcp:8081/mcp"}
