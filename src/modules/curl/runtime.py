from __future__ import annotations

from common.runtime_annotations import READ_ONLY_LOCAL, WRITE_EXTERNAL
from common.runtime_common import build_private_mcp, private_http_app

from .tools import register_curl_tools

mcp = build_private_mcp("curl")

register_curl_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_EXTERNAL,
)

app = private_http_app(mcp)
