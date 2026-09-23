from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .gitlab_client import GitLabClient
from .profiles import GitLabProfileRegistry


def register_gitlab_profile_tools(
    mcp: FastMCP,
    registry_factory: Callable[[], GitLabProfileRegistry],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab profiles", annotations=read_annotations)
    def profiles() -> JsonObject:
        """List configured GitLab connection/account profiles without exposing tokens."""
        return registry_factory().list()

    @mcp.tool(title="GitLab profile status", annotations=read_annotations)
    def profile_status(profile_id: str) -> JsonObject:
        """Verify one explicit GitLab profile and report the authenticated account."""
        return client_factory(profile_id).profile_status()

    @mcp.tool(title="GitLab list projects", annotations=read_annotations)
    def list_projects(
        profile_id: str,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List projects visible to the selected GitLab profile/account."""
        return client_factory(profile_id).list_projects(
            search, membership, owned, min_access_level, page, per_page
        )

    @mcp.tool(title="GitLab project status", annotations=read_annotations)
    def project_status(profile_id: str, project: str) -> JsonObject:
        """Read project metadata using a numeric project id or path_with_namespace."""
        return client_factory(profile_id).project_status(project)
