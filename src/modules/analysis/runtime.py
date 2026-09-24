from __future__ import annotations

from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import AnalysisSettings, ManagementClientSettings, PrivateRuntimeSettings

from .provider import AnalysisToolProvider

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_analysis_settings = AnalysisSettings()

mcp = build_private_mcp("analysis", _management)
mcp.add_provider(AnalysisToolProvider(_analysis_settings))

app = private_http_app(mcp, _private_settings)
