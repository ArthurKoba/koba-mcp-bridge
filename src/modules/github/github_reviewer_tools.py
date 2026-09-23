from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_actions import GitHubActionsClient
from .models import ReviewComment


def register_github_reviewer_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register a narrow read/review surface for an independent reviewer GitHub App."""

    @mcp.tool(title="GitHub reviewer list repositories", annotations=read_annotations)
    def github_reviewer_list_repositories(account_id: str) -> JsonObject:
        """List repositories currently granted to the reviewer GitHub App installation."""
        return client_factory(account_id).list_repositories()

    @mcp.tool(title="GitHub reviewer status", annotations=read_annotations)
    def github_reviewer_status(account_id: str, repository: str) -> JsonObject:
        """Verify the independent reviewer App installation for one repository."""
        return client_factory(account_id).status(repository)

    @mcp.tool(title="GitHub reviewer get file", annotations=read_annotations)
    def github_reviewer_get_file(
        account_id: str,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> JsonObject:
        """Read one UTF-8 file for review."""
        return client_factory(account_id).get_file(repository, path, ref)

    @mcp.tool(title="GitHub reviewer get binary file", annotations=read_annotations)
    def github_reviewer_get_binary_file(
        account_id: str,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> JsonObject:
        """Read one file as base64 for binary review."""
        return client_factory(account_id).get_binary_file(repository, path, ref)

    @mcp.tool(title="GitHub reviewer list directory", annotations=read_annotations)
    def github_reviewer_list_directory(
        account_id: str,
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> JsonObject:
        """List a directory for review."""
        return client_factory(account_id).list_directory(repository, path, ref)

    @mcp.tool(title="GitHub reviewer list branches", annotations=read_annotations)
    def github_reviewer_list_branches(account_id: str, repository: str) -> JsonObject:
        """List branches without exposing branch mutation."""
        return client_factory(account_id).list_branches(repository)

    @mcp.tool(title="GitHub reviewer list tags", annotations=read_annotations)
    def github_reviewer_list_tags(
        account_id: str,
        repository: str,
        per_page: int = 100,
        page: int = 1,
    ) -> JsonObject:
        """List repository tags without exposing tag mutation."""
        return client_factory(account_id).list_tags(repository, per_page, page)

    @mcp.tool(title="GitHub reviewer compare refs", annotations=read_annotations)
    def github_reviewer_compare(
        account_id: str,
        repository: str,
        base: str,
        head: str,
    ) -> JsonObject:
        """Compare two refs for review."""
        return client_factory(account_id).compare(repository, base, head)

    @mcp.tool(title="GitHub reviewer list commits", annotations=read_annotations)
    def github_reviewer_list_commits(
        account_id: str,
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        """Read commit history for independent review."""
        return client_factory(account_id).list_commits(repository, ref, path, per_page, page)

    @mcp.tool(title="GitHub reviewer get commit", annotations=read_annotations)
    def github_reviewer_get_commit(account_id: str, repository: str, ref: str) -> JsonObject:
        """Read one commit and changed-file patches."""
        return client_factory(account_id).get_commit(repository, ref)

    @mcp.tool(title="GitHub reviewer search code", annotations=read_annotations)
    def github_reviewer_search_code(
        account_id: str,
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> JsonObject:
        """Search code inside one repository installed for the reviewer App."""
        return client_factory(account_id).search_code(repository, query, per_page, page)

    @mcp.tool(title="GitHub reviewer list pull requests", annotations=read_annotations)
    def github_reviewer_list_pull_requests(
        account_id: str,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        """List pull requests available for review."""
        return client_factory(account_id).list_pull_requests(repository, state, per_page, page)

    @mcp.tool(title="GitHub reviewer get pull request", annotations=read_annotations)
    def github_reviewer_get_pull_request(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """Read pull request metadata."""
        return client_factory(account_id).get_pull_request(repository, number)

    @mcp.tool(title="GitHub reviewer pull files", annotations=read_annotations)
    def github_reviewer_pull_files(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """Read changed files and patches for a pull request."""
        return client_factory(account_id).list_pull_files(repository, number)

    @mcp.tool(title="GitHub reviewer list reviews", annotations=read_annotations)
    def github_reviewer_list_reviews(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List existing review submissions."""
        return client_factory(account_id).list_reviews(repository, number)

    @mcp.tool(title="GitHub reviewer list review threads", annotations=read_annotations)
    def github_reviewer_list_review_threads(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List inline review threads and resolution state."""
        return client_factory(account_id).list_review_threads(repository, number)

    @mcp.tool(title="GitHub reviewer inline comments", annotations=read_annotations)
    def github_reviewer_list_review_comments(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List flat inline review comments for a pull request."""
        return client_factory(account_id).list_review_comments(repository, number)

    @mcp.tool(title="GitHub reviewer conversation comments", annotations=read_annotations)
    def github_reviewer_list_conversation_comments(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """Read top-level PR conversation comments."""
        return client_factory(account_id).list_conversation_comments(repository, number)

    @mcp.tool(title="GitHub reviewer check runs", annotations=read_annotations)
    def github_reviewer_check_runs(account_id: str, repository: str, ref: str) -> JsonObject:
        """Read CI check-runs for a commit/ref."""
        return client_factory(account_id).check_runs(repository, ref)

    @mcp.tool(title="GitHub reviewer required checks", annotations=read_annotations)
    def github_reviewer_required_checks(
        account_id: str,
        repository: str,
        ref: str,
    ) -> JsonObject:
        """Verify configured required checks before approval."""
        return client_factory(account_id).assert_required_checks(repository, ref)

    @mcp.tool(title="GitHub reviewer workflow runs", annotations=read_annotations)
    def github_reviewer_workflow_runs(
        account_id: str,
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> JsonObject:
        """List Actions workflow runs for review diagnostics."""
        return client_factory(account_id).list_workflow_runs(
            repository,
            branch,
            status,
            per_page,
            page,
        )

    @mcp.tool(title="GitHub reviewer workflow jobs", annotations=read_annotations)
    def github_reviewer_workflow_jobs(
        account_id: str,
        repository: str,
        run_id: int,
    ) -> JsonObject:
        """List jobs for one Actions workflow run."""
        return client_factory(account_id).list_workflow_jobs(repository, run_id)

    @mcp.tool(title="GitHub reviewer rich review", annotations=write_annotations)
    def github_reviewer_create_review(
        account_id: str,
        repository: str,
        number: int,
        event: str,
        body: str,
        comments: list[ReviewComment] | None = None,
        commit_id: str | None = None,
    ) -> JsonObject:
        """Submit COMMENT, APPROVE, or REQUEST_CHANGES with optional inline comments."""
        return client_factory(account_id).create_review_with_comments(
            repository,
            number,
            event,
            body,
            comments,
            commit_id,
        )

    @mcp.tool(title="GitHub reviewer reply to comment", annotations=write_annotations)
    def github_reviewer_reply_to_review_comment(
        account_id: str,
        repository: str,
        number: int,
        comment_id: int,
        body: str,
    ) -> JsonObject:
        """Reply inside an inline review thread."""
        return client_factory(account_id).reply_to_review_comment(
            repository,
            number,
            comment_id,
            body,
        )

    @mcp.tool(title="GitHub reviewer set thread state", annotations=write_annotations)
    def github_reviewer_set_review_thread_resolved(
        account_id: str,
        repository: str,
        thread_id: str,
        resolved: bool,
    ) -> JsonObject:
        """Resolve or reopen one review thread."""
        return client_factory(account_id).set_review_thread_resolved(
            repository,
            thread_id,
            resolved,
        )
