from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .gitlab_client import GitLabClient


def register_gitlab_issue_tools(
    mcp: FastMCP,
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab list issues", annotations=read_annotations)
    def list_issues(
        profile_id: str,
        project: str,
        state: str = "opened",
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List project issues."""
        return client_factory(profile_id).list_issues(project, state, search, page, per_page)

    @mcp.tool(title="GitLab get issue", annotations=read_annotations)
    def get_issue(
        profile_id: str,
        project: str,
        iid: int,
    ) -> JsonObject:
        """Read one project issue."""
        return client_factory(profile_id).get_issue(project, iid)

    @mcp.tool(title="GitLab create issue", annotations=write_annotations)
    def create_issue(
        profile_id: str,
        project: str,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Create a project issue."""
        return client_factory(profile_id).create_issue(project, title, description, labels)

    @mcp.tool(title="GitLab update issue", annotations=write_annotations)
    def update_issue(
        profile_id: str,
        project: str,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Update project issue metadata or state."""
        return client_factory(profile_id).update_issue(
            project, iid, title, description, state_event, labels
        )

    @mcp.tool(title="GitLab issue note", annotations=write_annotations)
    def add_issue_note(
        profile_id: str,
        project: str,
        iid: int,
        body: str,
    ) -> JsonObject:
        """Add a note/comment to an issue."""
        return client_factory(profile_id).add_issue_note(project, iid, body)
