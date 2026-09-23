from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .github_actions import GitHubActionsClient

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp.types import ToolAnnotations


def register_github_workflow_tools(
    mcp: FastMCP,
    client_factory: Callable[[], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    """Register the extended GitHub development workflow tools."""
    from .content_tools import register_github_content_tools
    from .issue_tools import register_github_issue_tools
    from .pull_tools import register_github_pull_tools
    from .ref_tools import register_github_ref_tools
    from .run_tools import register_github_run_tools

    register_github_content_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_github_ref_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_github_pull_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
    )
    register_github_issue_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
    )
    register_github_run_tools(
        mcp,
        client_factory,
        read_annotations,
    )
