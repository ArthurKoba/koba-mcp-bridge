from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_actions import GitHubActionsClient


def register_github_issue_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub agent list issues", annotations=read_annotations)
    def github_agent_list_issues(
        account_id: str,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        """List issues, excluding pull requests."""
        return client_factory(account_id).list_issues(repository, state, per_page, page)

    @mcp.tool(title="GitHub agent get issue", annotations=read_annotations)
    def github_agent_get_issue(account_id: str, repository: str, number: int) -> JsonObject:
        """Read one issue."""
        return client_factory(account_id).get_issue(repository, number)

    @mcp.tool(title="GitHub agent create issue", annotations=write_annotations)
    def github_agent_create_issue(
        account_id: str,
        repository: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Create an issue inside an allowlisted repository."""
        return client_factory(account_id).create_issue(repository, title, body, labels)

    @mcp.tool(title="GitHub agent update issue", annotations=write_annotations)
    def github_agent_update_issue(
        account_id: str,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Update an issue inside an allowlisted repository."""
        return client_factory(account_id).update_issue(
            repository, number, title, body, state, labels
        )

    @mcp.tool(title="GitHub agent issue comment", annotations=write_annotations)
    def github_agent_add_issue_comment(
        account_id: str,
        repository: str,
        number: int,
        body: str,
    ) -> JsonObject:
        """Add a comment to an issue."""
        return client_factory(account_id).add_issue_comment(repository, number, body)
