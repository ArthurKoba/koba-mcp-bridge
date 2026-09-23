from __future__ import annotations

from mcp_common.runtime_annotations import READ_ONLY_LOCAL, WRITE_LOCAL
from mcp_common.runtime_common import build_private_mcp, private_http_app

from .reverse_workflow import register_reverse_workflow_tools

mcp = build_private_mcp("analysis-mcp")

register_reverse_workflow_tools(
    mcp,
    READ_ONLY_LOCAL,
    WRITE_LOCAL,
)

app = private_http_app(mcp)
