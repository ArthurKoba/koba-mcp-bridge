from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .secrets import secret_reference_available, secrets_status


def register_secrets_tools(
    mcp: FastMCP,
    read_annotations: Any,
) -> None:
    @mcp.tool(title="Secrets status", annotations=read_annotations)
    def secrets_status_tool(authenticate: bool = False) -> dict[str, Any]:
        """Return Infisical bootstrap/configuration status without exposing secrets."""
        return secrets_status(authenticate=authenticate)

    @mcp.tool(title="Secrets check reference", annotations=read_annotations)
    def secrets_check_reference(secret_ref: str) -> dict[str, Any]:
        """Verify that a secret reference resolves without returning its plaintext value."""
        return secret_reference_available(secret_ref)
