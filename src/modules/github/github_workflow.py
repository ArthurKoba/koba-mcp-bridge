from __future__ import annotations

from .contents import GitHubContentsClient
from .issues import GitHubIssueClient
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
