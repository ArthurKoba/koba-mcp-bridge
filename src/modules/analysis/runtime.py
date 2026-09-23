from __future__ import annotations

from common.runtime_common import build_private_mcp, private_http_app

from .provider import AnalysisToolProvider

mcp = build_private_mcp("analysis")
mcp.add_provider(AnalysisToolProvider())

app = private_http_app(mcp)
