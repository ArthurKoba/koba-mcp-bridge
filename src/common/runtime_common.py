from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette

from .management_client import ManagementClient
from .settings import ManagementClientSettings, PrivateRuntimeSettings
from .tool_telemetry import ToolTelemetryMiddleware


def management_client(settings: ManagementClientSettings) -> ManagementClient:
    return ManagementClient(settings)


def build_private_mcp(
    name: str,
    management: ManagementClient | None = None,
) -> FastMCP:
    middleware = (
        [ToolTelemetryMiddleware(name, management)]
        if management is not None
        else []
    )
    return FastMCP(name, middleware=middleware)


def private_http_app(mcp: FastMCP, settings: PrivateRuntimeSettings) -> Starlette:
    return mcp.http_app(
        path="/mcp",
        allowed_hosts=list(settings.http.allowed_hosts),
        allowed_origins=list(settings.http.allowed_origins),
    )
