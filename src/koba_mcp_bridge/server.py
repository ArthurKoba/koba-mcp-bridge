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
        "Koba MCP Bridge exposes controlled local tools and long-running "
        "worker tasks to MCP clients."
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


def _split_env(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _transport_security() -> TransportSecuritySettings:
    return TransportSecuritySettings(
        allowed_hosts=_split_env(
            "MCP_ALLOWED_HOSTS",
            "localhost:*,127.0.0.1:*,[::1]:*",
        ),
        allowed_origins=_split_env(
            "MCP_ALLOWED_ORIGINS",
            "http://localhost:*,http://127.0.0.1:*,http://[::1]:*",
        ),
    )


app = mcp.streamable_http_app(
    host="0.0.0.0",
    transport_security=_transport_security(),
)
