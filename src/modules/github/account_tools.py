from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject


def register_github_account_tools(
    mcp: FastMCP,
    list_accounts: Callable[[str | None], JsonObject],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub accounts", annotations=read_annotations)
    def github_accounts(role: str | None = None) -> JsonObject:
        """List configured GitHub accounts without exposing credentials."""
        return list_accounts(role)
