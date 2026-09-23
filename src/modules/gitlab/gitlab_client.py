from __future__ import annotations

from .credentials import SecretError, resolve_config_secret
from .errors import GitLabError
from .issues import GitLabIssueClient
from .merge_requests import GitLabMergeRequestClient
from .models import GitLabProfile
from .pipelines import GitLabPipelineClient
from .profiles import GitLabProfileRegistry
from .projects import GitLabProjectClient
from .repository import GitLabRepositoryClient


class GitLabClient(
    GitLabProjectClient,
    GitLabRepositoryClient,
    GitLabMergeRequestClient,
    GitLabIssueClient,
    GitLabPipelineClient,
):
    """Complete GitLab provider assembled from independent API capabilities."""


__all__ = [
    "GitLabClient",
    "GitLabError",
    "GitLabProfile",
    "GitLabProfileRegistry",
    "SecretError",
    "resolve_config_secret",
]
