from __future__ import annotations

from .curl_mcp_tools import register_curl_tools
from .runtime_annotations import READ_ONLY_LOCAL, WRITE_EXTERNAL
from .runtime_common import build_private_mcp, private_http_app

mcp = build_private_mcp("http-mcp")

register_curl_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_EXTERNAL,
)

app = private_http_app(mcp)
