from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_review import GitHubReviewClient


def register_github_review_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubReviewClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register rebase and detailed review tools."""

    @mcp.tool(title="GitHub agent update pull branch with method", annotations=write_annotations)
    def github_agent_update_pull_branch_method(
        repository: str,
        number: int,
        method: str = "MERGE",
        expected_head_sha: str | None = None,
    ) -> dict[str, object]:
        """Update a PR branch using MERGE or true REBASE through GitHub GraphQL."""
        return client_factory().update_pull_branch_graphql(
            repository,
            number,
            method,
            expected_head_sha,
        )

    @mcp.tool(title="GitHub agent rich pull review", annotations=write_annotations)
    def github_agent_create_review_with_comments(
        repository: str,
        number: int,
        event: str,
        body: str,
        comments: list[dict[str, Any]] | None = None,
        commit_id: str | None = None,
    ) -> dict[str, object]:
        """Submit non-decisive COMMENT review feedback with optional inline comments."""
        if event.strip().upper() != "COMMENT":
            raise ValueError("development agent may only submit COMMENT reviews")
        return client_factory().create_review_with_comments(
            repository,
            number,
            "COMMENT",
            body,
            comments,
            commit_id,
        )

    @mcp.tool(title="GitHub agent conversation comments", annotations=read_annotations)
    def github_agent_list_conversation_comments(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """List top-level issue/PR conversation comments."""
        return client_factory().list_conversation_comments(repository, number)

    @mcp.tool(title="GitHub agent inline review comments", annotations=read_annotations)
    def github_agent_list_review_comments(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """List inline review comments for a pull request."""
        return client_factory().list_review_comments(repository, number)
