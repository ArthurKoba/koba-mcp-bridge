from __future__ import annotations

import os
from datetime import UTC, datetime

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from . import __version__

mcp = MCPServer(
    "koba-mcp-bridge",
    version=__version__,
    instructions=(
        "Koba MCP Bridge exposes controlled local tools and long-running worker tasks to MCP clients."
    ),
)


@mcp.tool()
def bridge_ping() -> dict[str, str]:
    """Check that the bridge is alive and reachable."""
    return {
        "status": "ok",
        "service": "koba-mcp-bridge",
        "version": __version__,
        "time": datetime.now(UTC).isoformat(),
    }


@mcp.tool()
def bridge_capabilities() -> dict[str, object]:
    """Return the currently enabled high-level bridge capabilities."""
    return {
        "workers": [],
        "features": ["mcp", "streamable-http", "opentelemetry"],
        "status": "bootstrap",
    }


def _transport_security() -> TransportSecuritySettings | None:
    raw_hosts = os.getenv("MCP_ALLOWED_HOSTS", "").strip()
    raw_origins = os.getenv("MCP_ALLOWED_ORIGINS", "").strip()

    if not raw_hosts:
        return None

    hosts = [item.strip() for item in raw_hosts.split(",") if item.strip()]
    origins = [item.strip() for item in raw_origins.split(",") if item.strip()]

    return TransportSecuritySettings(
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


app = mcp.streamable_http_app(
    host="0.0.0.0",
    transport_security=_transport_security(),
)
