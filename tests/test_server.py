import pytest
from mcp import Client

from koba_mcp_bridge.server import mcp


@pytest.mark.asyncio
async def test_bridge_ping() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_ping", {})

    assert result.structured_content is not None
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["service"] == "koba-mcp-bridge"


@pytest.mark.asyncio
async def test_bridge_build_info() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_build_info", {})

    assert result.structured_content is not None
    assert result.structured_content["service"] == "koba-mcp-bridge"
    assert result.structured_content["version"]
    assert result.structured_content["commit"]
    assert result.structured_content["built_at"]
    assert result.structured_content["started_at"]
    assert result.structured_content["python"]
