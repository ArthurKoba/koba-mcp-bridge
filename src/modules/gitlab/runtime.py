from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, private_http_app
from common.secrets import configure_secrets
from common.settings import GitLabSettings, InfisicalSettings, PrivateRuntimeSettings

from .gitlab_tools import register_gitlab_tools
from .tool_context import configure_runtime

_secrets_settings = InfisicalSettings()
configure_secrets(
    _secrets_settings.config(),
    cache_ttl_seconds=_secrets_settings.cache_ttl_seconds,
)
_private_settings = PrivateRuntimeSettings()
configure_runtime(GitLabSettings())

mcp = build_private_mcp("gitlab")

register_gitlab_tools(
    mcp,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
