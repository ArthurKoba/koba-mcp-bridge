from __future__ import annotations

from collections.abc import Callable
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_workflow import GitHubDevClient
from .models import AtomicChange, CopySpec


def register_github_workflow_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubDevClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    """Register the extended GitHub development workflow tools."""

    @mcp.tool(title="GitHub agent list directory", annotations=read_annotations)
    def github_agent_list_directory(
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> dict[str, object]:
        """List one repository directory at an optional ref."""
        return client_factory().list_directory(repository, path, ref)

    @mcp.tool(title="GitHub agent get binary file", annotations=read_annotations)
    def github_agent_get_binary_file(
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, object]:
        """Read one repository file as base64 without UTF-8 conversion."""
        return client_factory().get_binary_file(repository, path, ref)

    @mcp.tool(title="GitHub agent put binary file", annotations=write_annotations)
    def github_agent_put_binary_file(
        repository: str,
        path: str,
        content_base64: str,
        message: str,
        branch: str,
    ) -> dict[str, object]:
        """Create or replace one binary file from base64 content."""
        return client_factory().put_binary_file(
            repository,
            path,
            content_base64,
            message,
            branch,
        )

    @mcp.tool(
        title="GitHub agent copy/move existing files",
        annotations=destructive_annotations,
    )
    def github_agent_copy_files(
        repository: str,
        source_ref: str,
        branch: str,
        message: str,
        copies: list[CopySpec],
        expected_head_sha: str | None = None,
        operation: str = "copy",
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Copy or move existing Git blobs between paths/refs without transferring bytes."""
        return client_factory().copy_files(
            repository,
            source_ref,
            branch,
            message,
            copies,
            expected_head_sha,
            operation,
            overwrite,
        )

    @mcp.tool(title="GitHub agent atomic commit", annotations=write_annotations)
    def github_agent_commit_files(
        repository: str,
        branch: str,
        message: str,
        changes: list[AtomicChange],
        expected_head_sha: str | None = None,
    ) -> dict[str, object]:
        """Commit multiple text/binary file changes atomically using Git Data objects."""
        return client_factory().commit_files(
            repository,
            branch,
            message,
            changes,
            expected_head_sha,
        )

    @mcp.tool(title="GitHub agent list commits", annotations=read_annotations)
    def github_agent_list_commits(
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        """List commit history, optionally filtered by ref and path."""
        return client_factory().list_commits(repository, ref, path, per_page, page)

    @mcp.tool(title="GitHub agent get commit", annotations=read_annotations)
    def github_agent_get_commit(repository: str, ref: str) -> dict[str, object]:
        """Read one commit including changed-file statistics and patches when available."""
        return client_factory().get_commit(repository, ref)

    @mcp.tool(title="GitHub agent delete branch", annotations=destructive_annotations)
    def github_agent_delete_branch(repository: str, branch: str) -> dict[str, object]:
        """Delete a non-protected branch."""
        return client_factory().delete_branch(repository, branch)

    @mcp.tool(title="GitHub agent rename branch", annotations=write_annotations)
    def github_agent_rename_branch(
        repository: str,
        branch: str,
        new_name: str,
    ) -> dict[str, object]:
        """Rename a non-protected branch to another non-protected name."""
        return client_factory().rename_branch(repository, branch, new_name)

    @mcp.tool(title="GitHub agent reset branch", annotations=destructive_annotations)
    def github_agent_reset_branch(
        repository: str,
        branch: str,
        target_ref: str,
        expected_head_sha: str,
        allow_protected_branch: bool = False,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Reset a branch to an existing ancestor commit after CAS validation.

        Protected branches require explicit allow_protected_branch=true. The operation
        defaults to dry-run and refuses non-ancestor targets.
        """
        return client_factory().reset_branch(
            repository,
            branch,
            target_ref,
            expected_head_sha,
            allow_protected_branch,
            dry_run,
        )

    @mcp.tool(title="GitHub agent list tags", annotations=read_annotations)
    def github_agent_list_tags(
        repository: str,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, object]:
        """List repository tags."""
        return client_factory().list_tags(repository, per_page, page)

    @mcp.tool(title="GitHub agent create tag", annotations=write_annotations)
    def github_agent_create_tag(
        repository: str,
        tag: str,
        target_ref: str,
        message: str | None = None,
    ) -> dict[str, object]:
        """Create a lightweight or annotated tag at a commit/ref."""
        return client_factory().create_tag(repository, tag, target_ref, message)

    @mcp.tool(title="GitHub agent delete tag", annotations=destructive_annotations)
    def github_agent_delete_tag(repository: str, tag: str) -> dict[str, object]:
        """Delete one repository tag ref."""
        return client_factory().delete_tag(repository, tag)

    @mcp.tool(title="GitHub agent search code", annotations=read_annotations)
    def github_agent_search_code(
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> dict[str, object]:
        """Search code only inside one allowlisted repository."""
        return client_factory().search_code(repository, query, per_page, page)

    @mcp.tool(title="GitHub agent list pull requests", annotations=read_annotations)
    def github_agent_list_pull_requests(
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        """List same-repository pull requests."""
        return client_factory().list_pull_requests(repository, state, per_page, page)

    @mcp.tool(title="GitHub agent get pull request", annotations=read_annotations)
    def github_agent_get_pull_request(repository: str, number: int) -> dict[str, object]:
        """Read pull request metadata."""
        return client_factory().get_pull_request(repository, number)

    @mcp.tool(title="GitHub agent create pull request", annotations=write_annotations)
    def github_agent_create_pull_request(
        repository: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> dict[str, object]:
        """Create a pull request whose head/base branches are in the same repository."""
        return client_factory().create_pull_request(
            repository,
            title,
            head,
            base,
            body,
            draft,
        )

    @mcp.tool(title="GitHub agent update pull request", annotations=write_annotations)
    def github_agent_update_pull_request(
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
    ) -> dict[str, object]:
        """Update title/body/state/base of a same-repository pull request."""
        return client_factory().update_pull_request(
            repository,
            number,
            title,
            body,
            state,
            base,
        )

    @mcp.tool(title="GitHub agent pull request files", annotations=read_annotations)
    def github_agent_pull_files(repository: str, number: int) -> dict[str, object]:
        """List changed files and patches for a pull request."""
        return client_factory().list_pull_files(repository, number)

    @mcp.tool(title="GitHub agent pull request comment", annotations=write_annotations)
    def github_agent_add_pull_comment(
        repository: str,
        number: int,
        body: str,
    ) -> dict[str, object]:
        """Add a top-level conversation comment to a pull request."""
        return client_factory().add_pull_comment(repository, number, body)

    @mcp.tool(title="GitHub agent list reviews", annotations=read_annotations)
    def github_agent_list_reviews(repository: str, number: int) -> dict[str, object]:
        """List submitted reviews for a pull request."""
        return client_factory().list_reviews(repository, number)

    @mcp.tool(title="GitHub agent create review", annotations=write_annotations)
    def github_agent_create_review(
        repository: str,
        number: int,
        event: str,
        body: str,
    ) -> dict[str, object]:
        """Submit APPROVE, REQUEST_CHANGES, or COMMENT review feedback."""
        return client_factory().create_review(repository, number, event, body)

    @mcp.tool(title="GitHub agent update pull branch", annotations=write_annotations)
    def github_agent_update_pull_branch(
        repository: str,
        number: int,
        expected_head_sha: str | None = None,
    ) -> dict[str, object]:
        """Update a pull request branch with changes from its base branch."""
        return client_factory().update_pull_branch(repository, number, expected_head_sha)

    @mcp.tool(title="GitHub agent check runs", annotations=read_annotations)
    def github_agent_check_runs(repository: str, ref: str) -> dict[str, object]:
        """List check-runs for a commit/ref."""
        return client_factory().check_runs(repository, ref)

    @mcp.tool(title="GitHub agent required checks", annotations=read_annotations)
    def github_agent_required_checks(repository: str, ref: str) -> dict[str, object]:
        """Verify configured required check-runs are completed successfully."""
        return client_factory().assert_required_checks(repository, ref)

    @mcp.tool(title="GitHub agent merge pull request", annotations=write_annotations)
    def github_agent_merge_pull_request(
        repository: str,
        number: int,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, object]:
        """Merge a same-repository PR only after configured required checks pass."""
        return client_factory().merge_pull_request(
            repository,
            number,
            merge_method,
            commit_title,
            commit_message,
        )

    @mcp.tool(title="GitHub agent list issues", annotations=read_annotations)
    def github_agent_list_issues(
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> dict[str, object]:
        """List issues, excluding pull requests."""
        return client_factory().list_issues(repository, state, per_page, page)

    @mcp.tool(title="GitHub agent get issue", annotations=read_annotations)
    def github_agent_get_issue(repository: str, number: int) -> dict[str, object]:
        """Read one issue."""
        return client_factory().get_issue(repository, number)

    @mcp.tool(title="GitHub agent create issue", annotations=write_annotations)
    def github_agent_create_issue(
        repository: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, object]:
        """Create an issue inside an allowlisted repository."""
        return client_factory().create_issue(repository, title, body, labels)

    @mcp.tool(title="GitHub agent update issue", annotations=write_annotations)
    def github_agent_update_issue(
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, object]:
        """Update an issue inside an allowlisted repository."""
        return client_factory().update_issue(
            repository,
            number,
            title,
            body,
            state,
            labels,
        )

    @mcp.tool(title="GitHub agent issue comment", annotations=write_annotations)
    def github_agent_add_issue_comment(
        repository: str,
        number: int,
        body: str,
    ) -> dict[str, object]:
        """Add a comment to an issue."""
        return client_factory().add_issue_comment(repository, number, body)

    @mcp.tool(title="GitHub agent workflow runs", annotations=read_annotations)
    def github_agent_workflow_runs(
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> dict[str, object]:
        """List GitHub Actions workflow runs."""
        return client_factory().list_workflow_runs(
            repository,
            branch,
            status,
            per_page,
            page,
        )

    @mcp.tool(title="GitHub agent workflow jobs", annotations=read_annotations)
    def github_agent_workflow_jobs(repository: str, run_id: int) -> dict[str, object]:
        """List jobs for one GitHub Actions workflow run."""
        return client_factory().list_workflow_jobs(repository, run_id)
