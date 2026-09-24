from __future__ import annotations

from fastmcp.server import create_proxy

from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import (
    GhidraSettings,
    ManagementClientSettings,
    PrivateRuntimeSettings,
)

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_ghidra_settings = GhidraSettings()

mcp = build_private_mcp("ghidra", _management)
mcp.mount(
    server=create_proxy(
        _ghidra_settings.backend_url,
        name="ghidra-native",
        mode="auto",
    )
)

app = private_http_app(mcp, _private_settings)
