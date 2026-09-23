from __future__ import annotations

from common.runtime_common import build_private_mcp, control_plane_client, private_http_app
from common.settings import AnalysisSettings, ControlPlaneClientSettings, PrivateRuntimeSettings

from .provider import AnalysisToolProvider

_private_settings = PrivateRuntimeSettings()
_control_plane = control_plane_client(ControlPlaneClientSettings())
_analysis_settings = AnalysisSettings()

mcp = build_private_mcp("analysis", _control_plane)
mcp.add_provider(AnalysisToolProvider(_analysis_settings))

app = private_http_app(mcp, _private_settings)
