from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette

from .config import env_list


def build_private_mcp(name: str) -> FastMCP:
    return FastMCP(name)


def private_http_app(mcp: FastMCP) -> Starlette:
    return mcp.http_app(
        path="/mcp",
        allowed_hosts=env_list(
            "PRIVATE_MCP_ALLOWED_HOSTS",
            (
                "localhost:*,127.0.0.1:*,[::1]:*,"
                "github:*,gitlab:*,files:*,curl:*,analysis:*"
            ),
        ),
        allowed_origins=env_list(
            "PRIVATE_MCP_ALLOWED_ORIGINS",
            "http://localhost:*,http://127.0.0.1:*,http://[::1]:*",
        ),
    )
