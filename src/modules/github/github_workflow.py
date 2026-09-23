from __future__ import annotations

from .contents import GitHubContentsClient
from .issues import GitHubIssueClient
from .policy import (
    protected_branches_from_env as protected_branches_from_env,
)
from .policy import required_checks_from_env as required_checks_from_env
from .pulls import GitHubPullClient
from .refs import GitHubRefsClient
from .runs import GitHubRunClient


class GitHubDevClient(
    GitHubContentsClient,
    GitHubRefsClient,
    GitHubPullClient,
    GitHubIssueClient,
    GitHubRunClient,
):
    """Complete development client assembled from independent GitHub capabilities."""
