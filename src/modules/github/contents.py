from __future__ import annotations

from .content_api import GitHubContentApiClient
from .git_mutations import GitHubGitMutationClient


class GitHubContentsClient(GitHubContentApiClient, GitHubGitMutationClient):
    """Repository content facade composed from Contents API and Git Data capabilities."""
