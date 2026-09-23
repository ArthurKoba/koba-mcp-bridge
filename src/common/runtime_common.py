from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP


def build_private_mcp(name: str) -> FastMCP:
    return FastMCP(name)


def _split_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def private_http_app(mcp: FastMCP) -> Any:
    return mcp.http_app(
        path="/mcp",
        allowed_hosts=_split_env(
            "PRIVATE_MCP_ALLOWED_HOSTS",
            (
                "localhost:*,127.0.0.1:*,[::1]:*,"
                "github:*,gitlab:*,files:*,curl:*,analysis:*"
            ),
        ),
        allowed_origins=_split_env(
            "PRIVATE_MCP_ALLOWED_ORIGINS",
            "http://localhost:*,http://127.0.0.1:*,http://[::1]:*",
        ),
    )
