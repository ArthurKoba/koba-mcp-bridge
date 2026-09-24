from __future__ import annotations

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, management_client, private_http_app
from common.settings import (
    GitHubPolicySettings,
    ManagementClientSettings,
    PrivateRuntimeSettings,
)

from .account_tools import register_github_account_tools
from .github_actions_tools import register_github_actions_tools
from .github_collab_tools import register_github_collab_tools
from .github_core_tools import register_github_core_tools
from .github_review_tools import register_github_review_tools
from .github_reviewer_tools import register_github_reviewer_tools
from .github_tools import register_github_workflow_tools
from .tool_context import GitHubRuntimeContext

_private_settings = PrivateRuntimeSettings()
_management = management_client(ManagementClientSettings())
_context = GitHubRuntimeContext(_management, GitHubPolicySettings())

mcp = build_private_mcp("github", _management)

register_github_account_tools(
    mcp,
    _context.list_accounts,
    _context.account_capabilities,
    READ_EXTERNAL,
)
register_github_core_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_workflow_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_review_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_collab_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_actions_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_reviewer_tools(
    mcp,
    _context.client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)

app = private_http_app(mcp, _private_settings)
