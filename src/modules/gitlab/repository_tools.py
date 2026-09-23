from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .gitlab_client import GitLabClient
from .models import GitLabCommitAction


def register_gitlab_repository_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab get file", annotations=read_annotations)
    def get_file(
        account_id: str,
        project: str,
        path: str,
        ref: str = "main",
    ) -> JsonObject:
        """Read one UTF-8 repository file."""
        return client_factory(account_id).get_file(project, path, ref)

    @mcp.tool(title="GitLab repository tree", annotations=read_annotations)
    def list_tree(
        account_id: str,
        project: str,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List repository tree entries."""
        return client_factory(account_id).list_tree(
            project, path, ref, recursive, page, per_page
        )

    @mcp.tool(title="GitLab code search", annotations=read_annotations)
    def search_code(
        account_id: str,
        project: str,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """Search repository blobs inside one project."""
        return client_factory(account_id).search_code(project, search, ref, page, per_page)

    @mcp.tool(title="GitLab put file", annotations=write_annotations)
    def put_file(
        account_id: str,
        project: str,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        """Create or update one UTF-8 file on a non-protected branch."""
        return client_factory(account_id).put_file(
            project, path, content, branch, commit_message, last_commit_id
        )

    @mcp.tool(title="GitLab delete file", annotations=destructive_annotations)
    def delete_file(
        account_id: str,
        project: str,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        """Delete one file on a non-protected branch."""
        return client_factory(account_id).delete_file(
            project, path, branch, commit_message, last_commit_id
        )

    @mcp.tool(title="GitLab atomic commit", annotations=write_annotations)
    def commit_actions(
        account_id: str,
        project: str,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> JsonObject:
        """Create one atomic multi-file commit using GitLab repository commit actions."""
        return client_factory(account_id).commit_actions(
            project, branch, commit_message, actions, start_branch
        )

    @mcp.tool(title="GitLab list branches", annotations=read_annotations)
    def list_branches(
        account_id: str,
        project: str,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List repository branches."""
        return client_factory(account_id).list_branches(project, search, page, per_page)

    @mcp.tool(title="GitLab create branch", annotations=write_annotations)
    def create_branch(
        account_id: str,
        project: str,
        branch: str,
        ref: str,
    ) -> JsonObject:
        """Create a non-protected branch from a ref."""
        return client_factory(account_id).create_branch(project, branch, ref)

    @mcp.tool(title="GitLab delete branch", annotations=destructive_annotations)
    def delete_branch(
        account_id: str,
        project: str,
        branch: str,
    ) -> JsonObject:
        """Delete a non-protected repository branch."""
        return client_factory(account_id).delete_branch(project, branch)

    @mcp.tool(title="GitLab compare refs", annotations=read_annotations)
    def compare(
        account_id: str,
        project: str,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> JsonObject:
        """Compare two repository refs."""
        return client_factory(account_id).compare(project, from_ref, to_ref, straight)
