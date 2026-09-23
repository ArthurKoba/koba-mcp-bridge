from __future__ import annotations

from typing import TYPE_CHECKING

from .gitlab_client import GitLabProfileRegistry
from .tool_context import (
    clear_runtime_cache as _clear_runtime_cache,
    client as _client,
    registry as _registry,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp.types import ToolAnnotations


def register_gitlab_tools(
    mcp: FastMCP,
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
        _registry,
        _client,
        read_annotations,
    )
    register_gitlab_repository_tools(
        mcp,
        _client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_gitlab_merge_request_tools(
        mcp,
        _client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_gitlab_issue_tools(
        mcp,
        _client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_gitlab_pipeline_tools(
        mcp,
        _client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )


__all__ = [
    "GitLabProfileRegistry",
    "_clear_runtime_cache",
    "_client",
    "_registry",
    "register_gitlab_tools",
]
