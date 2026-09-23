from __future__ import annotations


class SecretError(RuntimeError):
    """Raised when MCP Bridge cannot resolve a configured secret reference."""
