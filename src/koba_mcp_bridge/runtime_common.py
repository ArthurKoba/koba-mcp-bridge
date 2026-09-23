from __future__ import annotations

from fastmcp import FastMCP


def build_private_mcp(name: str) -> FastMCP:
    return FastMCP(name)
