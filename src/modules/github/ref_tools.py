from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .github_actions import GitHubActionsClient


def register_github_ref_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub agent list commits", annotations=read_annotations)
    def github_agent_list_commits(
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        """List commit history, optionally filtered by ref and path."""
        return client_factory().list_commits(repository, ref, path, per_page, page)

    @mcp.tool(title="GitHub agent get commit", annotations=read_annotations)
    def github_agent_get_commit(repository: str, ref: str) -> JsonObject:
        """Read one commit including changed-file statistics and patches when available."""
        return client_factory().get_commit(repository, ref)

    @mcp.tool(title="GitHub agent delete branch", annotations=destructive_annotations)
    def github_agent_delete_branch(repository: str, branch: str) -> JsonObject:
        """Delete a non-protected branch."""
        return client_factory().delete_branch(repository, branch)

    @mcp.tool(title="GitHub agent rename branch", annotations=write_annotations)
    def github_agent_rename_branch(
        repository: str,
        branch: str,
        new_name: str,
    ) -> JsonObject:
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
    ) -> JsonObject:
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
    ) -> JsonObject:
        """List repository tags."""
        return client_factory().list_tags(repository, per_page, page)

    @mcp.tool(title="GitHub agent create tag", annotations=write_annotations)
    def github_agent_create_tag(
        repository: str,
        tag: str,
        target_ref: str,
        message: str | None = None,
    ) -> JsonObject:
        """Create a lightweight or annotated tag at a commit/ref."""
        return client_factory().create_tag(repository, tag, target_ref, message)

    @mcp.tool(title="GitHub agent delete tag", annotations=destructive_annotations)
    def github_agent_delete_tag(repository: str, tag: str) -> JsonObject:
        """Delete one repository tag ref."""
        return client_factory().delete_tag(repository, tag)
