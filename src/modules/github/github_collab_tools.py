from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_collab import GitHubCollabClient


def register_github_collab_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitHubCollabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register collaboration and review-thread workflow tools."""

    @mcp.tool(title="GitHub agent merge working branches", annotations=write_annotations)
    def github_agent_merge_branch(
        account_id: str,
        repository: str,
        base: str,
        head: str,
        commit_message: str | None = None,
    ) -> JsonObject:
        """Merge one ref into a non-protected working branch."""
        return client_factory(account_id).merge_branch(repository, base, head, commit_message)

    @mcp.tool(title="GitHub agent request reviewers", annotations=write_annotations)
    def github_agent_request_reviewers(
        account_id: str,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> JsonObject:
        """Request users or teams to review a pull request."""
        return client_factory(account_id).request_reviewers(
            repository,
            number,
            reviewers,
            team_reviewers,
        )

    @mcp.tool(title="GitHub agent remove requested reviewers", annotations=write_annotations)
    def github_agent_remove_requested_reviewers(
        account_id: str,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> JsonObject:
        """Remove user/team review requests from a pull request."""
        return client_factory(account_id).remove_requested_reviewers(
            repository,
            number,
            reviewers,
            team_reviewers,
        )

    @mcp.tool(title="GitHub agent update review comment", annotations=write_annotations)
    def github_agent_update_review_comment(
        account_id: str,
        repository: str,
        comment_id: int,
        body: str,
    ) -> JsonObject:
        """Replace the body of an inline review comment."""
        return client_factory(account_id).update_review_comment(repository, comment_id, body)

    @mcp.tool(title="GitHub agent reply to review comment", annotations=write_annotations)
    def github_agent_reply_to_review_comment(
        account_id: str,
        repository: str,
        number: int,
        comment_id: int,
        body: str,
    ) -> JsonObject:
        """Reply inside an inline review comment thread."""
        return client_factory(account_id).reply_to_review_comment(
            repository,
            number,
            comment_id,
            body,
        )

    @mcp.tool(title="GitHub agent list review threads", annotations=read_annotations)
    def github_agent_list_review_threads(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List inline review threads including resolved/outdated state."""
        return client_factory(account_id).list_review_threads(repository, number)

    @mcp.tool(title="GitHub agent set review thread state", annotations=write_annotations)
    def github_agent_set_review_thread_resolved(
        account_id: str,
        repository: str,
        thread_id: str,
        resolved: bool,
    ) -> JsonObject:
        """Resolve or unresolve one inline review thread."""
        return client_factory(account_id).set_review_thread_resolved(
            repository,
            thread_id,
            resolved,
        )

    @mcp.tool(title="GitHub agent mark pull ready", annotations=write_annotations)
    def github_agent_mark_pull_ready_for_review(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """Mark a draft pull request ready for review."""
        return client_factory(account_id).mark_pull_ready_for_review(repository, number)

    @mcp.tool(title="GitHub agent required reviews", annotations=read_annotations)
    def github_agent_required_reviews(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """Verify configured independent reviewer approvals before merge."""
        return client_factory(account_id).assert_required_reviews(repository, number)
