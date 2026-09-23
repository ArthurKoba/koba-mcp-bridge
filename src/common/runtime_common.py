from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette

from .settings import PrivateRuntimeSettings


def build_private_mcp(name: str) -> FastMCP:
    return FastMCP(name)


def private_http_app(mcp: FastMCP, settings: PrivateRuntimeSettings) -> Starlette:
    return mcp.http_app(
        path="/mcp",
        allowed_hosts=list(settings.http.allowed_hosts),
        allowed_origins=list(settings.http.allowed_origins),
    )
