from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_LOCAL,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
)
from common.runtime_common import build_private_mcp, private_http_app

from .file_tools import register_file_tools

mcp = build_private_mcp("files")

register_file_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
    DESTRUCTIVE_LOCAL,
)

app = private_http_app(mcp)
