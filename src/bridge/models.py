from __future__ import annotations

from typing import Literal

from common.models import StrictModel


class BridgePing(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["mcp-bridge"] = "mcp-bridge"
    version: str
    time: str


class BridgeBuildInfo(StrictModel):
    service: Literal["mcp-bridge"] = "mcp-bridge"
    version: str
    commit: str
    built_at: str
    started_at: str
    python: str


class BridgeCapabilities(StrictModel):
    backends: list[str]
    public_surfaces: list[str]
    features: list[str]
    status: Literal["active"] = "active"
