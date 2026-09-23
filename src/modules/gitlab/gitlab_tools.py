from __future__ import annotations

from typing import TYPE_CHECKING

from .tool_context import GitLabRuntimeContext

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp.types import ToolAnnotations


def register_gitlab_tools(
    mcp: FastMCP,
    context: GitLabRuntimeContext,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    from .issue_tools import register_gitlab_issue_tools
    from .merge_request_tools import register_gitlab_merge_request_tools
    from .pipeline_tools import register_gitlab_pipeline_tools
    from .profile_tools import register_gitlab_profile_tools
    from .repository_tools import register_gitlab_repository_tools

    register_gitlab_profile_tools(
        mcp,
        context.accounts,
        context.client,
        read_annotations,
    )
    register_gitlab_repository_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_gitlab_merge_request_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
    )
    register_gitlab_issue_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
    )
    register_gitlab_pipeline_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
