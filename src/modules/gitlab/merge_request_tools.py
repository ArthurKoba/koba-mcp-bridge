from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .gitlab_client import GitLabClient


def register_gitlab_merge_request_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab list merge requests", annotations=read_annotations)
    def list_merge_requests(
        profile_id: str,
        project: str,
        state: str = "opened",
        source_branch: str = "",
        target_branch: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List merge requests for one project."""
        return client_factory(profile_id).list_merge_requests(
            project,
            state,
            source_branch,
            target_branch,
            page,
            per_page,
        )

    @mcp.tool(title="GitLab get merge request", annotations=read_annotations)
    def get_merge_request(
        profile_id: str,
        project: str,
        iid: int,
    ) -> JsonObject:
        """Read one merge request."""
        return client_factory(profile_id).get_merge_request(project, iid)

    @mcp.tool(title="GitLab create merge request", annotations=write_annotations)
    def create_merge_request(
        profile_id: str,
        project: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        remove_source_branch: bool = False,
        squash: bool = False,
        draft: bool = False,
    ) -> JsonObject:
        """Create a merge request inside one GitLab project."""
        return client_factory(profile_id).create_merge_request(
            project,
            source_branch,
            target_branch,
            title,
            description,
            remove_source_branch,
            squash,
            draft,
        )

    @mcp.tool(title="GitLab update merge request", annotations=write_annotations)
    def update_merge_request(
        profile_id: str,
        project: str,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        target_branch: str | None = None,
        remove_source_branch: bool | None = None,
        squash: bool | None = None,
    ) -> JsonObject:
        """Update merge request metadata or state."""
        return client_factory(profile_id).update_merge_request(
            project,
            iid,
            title,
            description,
            state_event,
            target_branch,
            remove_source_branch,
            squash,
        )

    @mcp.tool(title="GitLab merge merge request", annotations=write_annotations)
    def merge_merge_request(
        profile_id: str,
        project: str,
        iid: int,
        sha: str = "",
        squash: bool | None = None,
        should_remove_source_branch: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> JsonObject:
        """Merge a merge request, optionally pinning the expected source SHA."""
        return client_factory(profile_id).merge_merge_request(
            project,
            iid,
            sha,
            squash,
            should_remove_source_branch,
            merge_when_pipeline_succeeds,
            merge_commit_message,
            squash_commit_message,
        )
