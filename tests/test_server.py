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
