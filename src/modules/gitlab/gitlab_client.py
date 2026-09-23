from __future__ import annotations

from .errors import GitLabError
from .issues import GitLabIssueClient
from .merge_requests import GitLabMergeRequestClient
from .models import GitLabProfile
from .pipelines import GitLabPipelineClient
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


__all__ = ["GitLabClient", "GitLabError", "GitLabProfile"]
