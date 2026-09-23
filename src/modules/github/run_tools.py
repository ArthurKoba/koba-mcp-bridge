from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_actions import GitHubActionsClient


def register_github_run_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub agent workflow runs", annotations=read_annotations)
    def github_agent_workflow_runs(
        account_id: str,
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> JsonObject:
        """List GitHub Actions workflow runs."""
        return client_factory(account_id).list_workflow_runs(
            repository, branch, status, per_page, page
        )

    @mcp.tool(title="GitHub agent workflow jobs", annotations=read_annotations)
    def github_agent_workflow_jobs(account_id: str, repository: str, run_id: int) -> JsonObject:
        """List jobs for one GitHub Actions workflow run."""
        return client_factory(account_id).list_workflow_jobs(repository, run_id)
