from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette

from .account_client import ControlPlaneClient
from .settings import ControlPlaneClientSettings, PrivateRuntimeSettings
from .tool_telemetry import ToolTelemetryMiddleware


def control_plane_client(settings: ControlPlaneClientSettings) -> ControlPlaneClient:
    return ControlPlaneClient(settings)


def build_private_mcp(
    name: str,
    control_plane: ControlPlaneClient | None = None,
) -> FastMCP:
    middleware = (
        [ToolTelemetryMiddleware(name, control_plane)]
        if control_plane is not None
        else []
    )
    return FastMCP(name, middleware=middleware)


def private_http_app(mcp: FastMCP, settings: PrivateRuntimeSettings) -> Starlette:
    return mcp.http_app(
        path="/mcp",
        allowed_hosts=list(settings.http.allowed_hosts),
        allowed_origins=list(settings.http.allowed_origins),
    )
