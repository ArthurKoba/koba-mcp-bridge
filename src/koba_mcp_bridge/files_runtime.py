from __future__ import annotations

from .file_tools import register_file_tools
from .runtime_annotations import (
    DESTRUCTIVE_LOCAL,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
)
from .runtime_common import build_private_mcp, private_http_app

mcp = build_private_mcp("koba-files")

register_file_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
    DESTRUCTIVE_LOCAL,
)

app = private_http_app(mcp)
