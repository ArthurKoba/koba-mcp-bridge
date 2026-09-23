from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .gitlab_client import GitLabClient


def register_gitlab_profile_tools(
    mcp: FastMCP,
    accounts_factory: Callable[[], JsonObject],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab accounts", annotations=read_annotations)
    def accounts() -> JsonObject:
        """List configured GitLab accounts without exposing credentials."""
        return accounts_factory()

    @mcp.tool(title="GitLab account status", annotations=read_annotations)
    def account_status(account_id: str) -> JsonObject:
        """Verify one explicit GitLab account and report the authenticated user."""
        return client_factory(account_id).profile_status()

    @mcp.tool(title="GitLab list projects", annotations=read_annotations)
    def list_projects(
        account_id: str,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List projects visible to the selected GitLab account."""
        return client_factory(account_id).list_projects(
            search, membership, owned, min_access_level, page, per_page
        )

    @mcp.tool(title="GitLab project status", annotations=read_annotations)
    def project_status(account_id: str, project: str) -> JsonObject:
        """Read project metadata using a numeric project id or path_with_namespace."""
        return client_factory(account_id).project_status(project)
