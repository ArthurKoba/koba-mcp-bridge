from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .secrets import SecretError, SecretReference, secret_reference_available
from .secrets import secrets_status as _secrets_status
from .types import JsonObject


def register_secrets_tools(
    mcp: FastMCP,
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="Secrets status", annotations=read_annotations)
    def secrets_status(authenticate: bool = False) -> JsonObject:
        """Return Infisical bootstrap/configuration status without exposing secrets."""
        return _secrets_status(authenticate=authenticate)

    @mcp.tool(title="Secrets check reference", annotations=read_annotations)
    def secrets_check_reference(secret_ref: str) -> JsonObject:
        """Verify an Infisical reference without returning its plaintext value."""
        reference = SecretReference.parse(secret_ref)
        if reference.scheme != "infisical":
            raise SecretError(
                "MCP reference checks are restricted to infisical:// references"
            )
        return secret_reference_available(secret_ref)
