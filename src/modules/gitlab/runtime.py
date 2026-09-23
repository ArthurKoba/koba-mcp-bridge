from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, private_http_app

from .gitlab_tools import register_gitlab_tools

mcp = build_private_mcp("gitlab-mcp")

register_gitlab_tools(
    mcp,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = private_http_app(mcp)
