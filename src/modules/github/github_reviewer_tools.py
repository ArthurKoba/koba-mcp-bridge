from __future__ import annotations

from collections.abc import Callable
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_collab import GitHubCollabClient
from .models import ReviewComment


def register_github_reviewer_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubCollabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register a narrow read/review surface for an independent reviewer GitHub App."""

    @mcp.tool(title="GitHub reviewer list repositories", annotations=read_annotations)
    def github_reviewer_list_repositories() -> dict[str, object]:
        """List repositories currently granted to the reviewer GitHub App installation."""
        return client_factory().list_repositories()

    @mcp.tool(title="GitHub reviewer status", annotations=read_annotations)
    def github_reviewer_status(repository: str) -> dict[str, object]:
        """Verify the independent reviewer App installation for one repository."""
        return client_factory().status(repository)

    @mcp.tool(title="GitHub reviewer get file", annotations=read_annotations)
    def github_reviewer_get_file(
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, object]:
        """Read one UTF-8 file for review."""
        return client_factory().get_file(repository, path, ref)

    @mcp.tool(title="GitHub reviewer get binary file", annotations=read_annotations)
    def github_reviewer_get_binary_file(
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, object]:
        """Read one file as base64 for binary review."""
        return client_factory().get_binary_file(repository, path, ref)

    @mcp.tool(title="GitHub reviewer list directory", annotations=read_annotations)
    def github_reviewer_list_directory(
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> dict[str, object]:
        """List a directory for review."""
        return client_factory().list_directory(repository, path, ref)

    @mcp.tool(title="GitHub reviewer list branches", annotations=read_annotations)
    def github_reviewer_list_branches(repository: str) -> dict[str, object]:
        """List branches without exposing branch mutation."""
        return client_factory().list_branches(repository)

    @mcp.tool(title="GitHub reviewer list tags", annotations=read_annotations)
    def github_reviewer_list_tags(
        repository: str,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, object]:
        """List repository tags without exposing tag mutation."""
        return client_factory().list_tags(repository, per_page, page)

    @mcp.tool(title="GitHub reviewer compare refs", annotations=read_annotations)
    def github_reviewer_compare(
        repository: str,
        base: str,
        head: str,
    ) -> dict[str, object]:
        """Compare two refs for review."""
        return client_factory().compare(repository, base, head)

    @mcp.tool(title="GitHub reviewer list commits", annotations=read_annotations)
    def github_reviewer_list_commits(
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        """Read commit history for independent review."""
        return client_factory().list_commits(repository, ref, path, per_page, page)

    @mcp.tool(title="GitHub reviewer get commit", annotations=read_annotations)
    def github_reviewer_get_commit(repository: str, ref: str) -> dict[str, object]:
        """Read one commit and changed-file patches."""
        return client_factory().get_commit(repository, ref)

    @mcp.tool(title="GitHub reviewer search code", annotations=read_annotations)
    def github_reviewer_search_code(
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> dict[str, object]:
        """Search code inside one repository installed for the reviewer App."""
        return client_factory().search_code(repository, query, per_page, page)

    @mcp.tool(title="GitHub reviewer list pull requests", annotations=read_annotations)
    def github_reviewer_list_pull_requests(
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        """List pull requests available for review."""
        return client_factory().list_pull_requests(repository, state, per_page, page)

    @mcp.tool(title="GitHub reviewer get pull request", annotations=read_annotations)
    def github_reviewer_get_pull_request(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """Read pull request metadata."""
        return client_factory().get_pull_request(repository, number)

    @mcp.tool(title="GitHub reviewer pull files", annotations=read_annotations)
    def github_reviewer_pull_files(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """Read changed files and patches for a pull request."""
        return client_factory().list_pull_files(repository, number)

    @mcp.tool(title="GitHub reviewer list reviews", annotations=read_annotations)
    def github_reviewer_list_reviews(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """List existing review submissions."""
        return client_factory().list_reviews(repository, number)

    @mcp.tool(title="GitHub reviewer list review threads", annotations=read_annotations)
    def github_reviewer_list_review_threads(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """List inline review threads and resolution state."""
        return client_factory().list_review_threads(repository, number)

    @mcp.tool(title="GitHub reviewer inline comments", annotations=read_annotations)
    def github_reviewer_list_review_comments(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """List flat inline review comments for a pull request."""
        return client_factory().list_review_comments(repository, number)

    @mcp.tool(title="GitHub reviewer conversation comments", annotations=read_annotations)
    def github_reviewer_list_conversation_comments(
        repository: str,
        number: int,
    ) -> dict[str, object]:
        """Read top-level PR conversation comments."""
        return client_factory().list_conversation_comments(repository, number)

    @mcp.tool(title="GitHub reviewer check runs", annotations=read_annotations)
    def github_reviewer_check_runs(repository: str, ref: str) -> dict[str, object]:
        """Read CI check-runs for a commit/ref."""
        return client_factory().check_runs(repository, ref)

    @mcp.tool(title="GitHub reviewer required checks", annotations=read_annotations)
    def github_reviewer_required_checks(
        repository: str,
        ref: str,
    ) -> dict[str, object]:
        """Verify configured required checks before approval."""
        return client_factory().assert_required_checks(repository, ref)

    @mcp.tool(title="GitHub reviewer workflow runs", annotations=read_annotations)
    def github_reviewer_workflow_runs(
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> dict[str, object]:
        """List Actions workflow runs for review diagnostics."""
        return client_factory().list_workflow_runs(
            repository,
            branch,
            status,
            per_page,
            page,
        )

    @mcp.tool(title="GitHub reviewer workflow jobs", annotations=read_annotations)
    def github_reviewer_workflow_jobs(
        repository: str,
        run_id: int,
    ) -> dict[str, object]:
        """List jobs for one Actions workflow run."""
        return client_factory().list_workflow_jobs(repository, run_id)

    @mcp.tool(title="GitHub reviewer rich review", annotations=write_annotations)
    def github_reviewer_create_review(
        repository: str,
        number: int,
        event: str,
        body: str,
        comments: list[ReviewComment] | None = None,
        commit_id: str | None = None,
    ) -> dict[str, object]:
        """Submit COMMENT, APPROVE, or REQUEST_CHANGES with optional inline comments."""
        return client_factory().create_review_with_comments(
            repository,
            number,
            event,
            body,
            comments,
            commit_id,
        )

    @mcp.tool(title="GitHub reviewer reply to comment", annotations=write_annotations)
    def github_reviewer_reply_to_review_comment(
        repository: str,
        number: int,
        comment_id: int,
        body: str,
    ) -> dict[str, object]:
        """Reply inside an inline review thread."""
        return client_factory().reply_to_review_comment(
            repository,
            number,
            comment_id,
            body,
        )

    @mcp.tool(title="GitHub reviewer set thread state", annotations=write_annotations)
    def github_reviewer_set_review_thread_resolved(
        repository: str,
        thread_id: str,
        resolved: bool,
    ) -> dict[str, object]:
        """Resolve or reopen one review thread."""
        return client_factory().set_review_thread_resolved(
            repository,
            thread_id,
            resolved,
        )
