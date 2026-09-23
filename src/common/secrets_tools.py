from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .secrets import SecretError, SecretReference, secret_reference_available
from .secrets import secrets_status as _secrets_status


def register_secrets_tools(
    mcp: FastMCP,
    read_annotations: Any,
) -> None:
    @mcp.tool(title="Secrets status", annotations=read_annotations)
    def secrets_status(authenticate: bool = False) -> dict[str, Any]:
        """Return Infisical bootstrap/configuration status without exposing secrets."""
        return _secrets_status(authenticate=authenticate)

    @mcp.tool(title="Secrets check reference", annotations=read_annotations)
    def secrets_check_reference(secret_ref: str) -> dict[str, Any]:
        """Verify an Infisical reference without returning its plaintext value."""
        reference = SecretReference.parse(secret_ref)
        if reference.scheme != "infisical":
            raise SecretError(
                "MCP reference checks are restricted to infisical:// references"
            )
        return secret_reference_available(secret_ref)
