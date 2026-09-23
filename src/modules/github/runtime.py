from __future__ import annotations

from functools import lru_cache

from common.runtime_annotations import (
    DESTRUCTIVE_EXTERNAL,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
from common.runtime_common import build_private_mcp, private_http_app

from .github_actions_tools import register_github_actions_tools
from .github_collab_tools import register_github_collab_tools
from .github_core_tools import register_github_core_tools
from .github_identity import GitHubPrettyIdentityClient
from .github_review_tools import register_github_review_tools
from .github_reviewer import (
    github_reviewer_client,
    github_reviewer_configured,
)
from .github_reviewer_tools import register_github_reviewer_tools
from .github_tools import register_github_workflow_tools


@lru_cache(maxsize=1)
def github_agent_client() -> GitHubPrettyIdentityClient:
    return GitHubPrettyIdentityClient.from_infisical()


mcp = build_private_mcp("github-mcp")

register_github_core_tools(
    mcp,
    github_agent_client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_workflow_tools(
    mcp,
    github_agent_client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)
register_github_review_tools(
    mcp,
    github_agent_client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_collab_tools(
    mcp,
    github_agent_client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
)
register_github_actions_tools(
    mcp,
    github_agent_client,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    DESTRUCTIVE_EXTERNAL,
)

if github_reviewer_configured():
    register_github_reviewer_tools(
        mcp,
        github_reviewer_client,
        READ_EXTERNAL,
        WRITE_EXTERNAL,
    )

app = private_http_app(mcp)
