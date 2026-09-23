from __future__ import annotations

from .gitlab_tools import register_gitlab_tools
from mcp_common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from mcp_common.runtime_common import build_private_mcp, private_http_app

mcp = build_private_mcp("gitlab-mcp")

register_gitlab_tools(
    mcp,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = private_http_app(mcp)
