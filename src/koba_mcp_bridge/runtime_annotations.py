from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY_LOCAL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
READ_EXTERNAL = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE_EXTERNAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
WRITE_LOCAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
DESTRUCTIVE_EXTERNAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)
DESTRUCTIVE_LOCAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)
