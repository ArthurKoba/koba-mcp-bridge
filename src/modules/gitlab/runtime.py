from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, control_plane_client, private_http_app
from common.settings import (
    ControlPlaneClientSettings,
    GitLabSettings,
    PrivateRuntimeSettings,
)

from .gitlab_tools import register_gitlab_tools
from .tool_context import GitLabRuntimeContext

_private_settings = PrivateRuntimeSettings()
_control_plane = control_plane_client(ControlPlaneClientSettings())
_context = GitLabRuntimeContext(_control_plane, GitLabSettings())

mcp = build_private_mcp("gitlab", _control_plane)

register_gitlab_tools(
    mcp,
    _context,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
