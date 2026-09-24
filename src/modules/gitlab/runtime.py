from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import (
    ManagementClientSettings,
    GitLabSettings,
    PrivateRuntimeSettings,
)

from .gitlab_tools import register_gitlab_tools
from .tool_context import GitLabRuntimeContext

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_context = GitLabRuntimeContext(_management, GitLabSettings())

mcp = build_private_mcp("gitlab", _management)

register_gitlab_tools(
    mcp,
    _context,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
