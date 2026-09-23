from __future__ import annotations

import urllib.parse

from .github_agent import GitHubAppClient
from .policy import require_mutable_branch


class GitHubRepositoryClientBase(GitHubAppClient):
    """Base for repository capabilities that share GitHub policy and path encoding."""

    def _assert_mutable_branch(self, branch: str) -> str:
        return require_mutable_branch(branch)

    @staticmethod
    def _quote(value: str) -> str:
        return urllib.parse.quote(value, safe="")

    @staticmethod
    def _path(path: str) -> str:
        return urllib.parse.quote(path.strip("/"), safe="/")
