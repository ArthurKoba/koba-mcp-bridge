from __future__ import annotations

from types import SimpleNamespace

import pytest

import modules.analysis.provider as provider_module
from common.settings import AnalysisSettings
from modules.analysis.provider import AnalysisProviderError, AnalysisToolProvider


def _backend_tool(name: str = "decompile_function"):
    return SimpleNamespace(
        name=name,
        title="Behavior view",
        description="Decompile function and inspect callers",
        input_schema={
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Function name",
                },
                "include_callers": {
                    "type": "boolean",
                    "default": False,
                },
                "program": {"type": "string"},
            },
            "required": ["function_name", "program"],
        },
    )


@pytest.mark.asyncio
async def test_provider_adapts_live_backend_catalog(monkeypatch) -> None:
    seen_urls: list[str] = []

    class FakeClient:
        def __init__(self, url: str) -> None:
            seen_urls.append(url)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def list_tools(self):
            return [_backend_tool()]

    monkeypatch.setattr(provider_module, "Client", FakeClient)

    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://ghidra.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    tools = await provider._list_tools()

    assert seen_urls == ["http://ghidra.internal/mcp"]
    assert len(tools) == 1

    tool = tools[0]
    assert tool.name == "inspect_action_behavior"
    assert "inspect behavior" in tool.description
    assert "inbound actions" in tool.description

    properties = tool.parameters["properties"]
    assert set(properties) == {
        "action_name",
        "include_inbound_actions",
        "program",
    }
    assert tool.parameters["required"] == ["action_name", "program"]


def test_provider_rejects_tool_alias_collisions() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://ghidra.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )

    with pytest.raises(AnalysisProviderError, match="tool alias collision"):
        provider._adapt_catalog(
            [
                _backend_tool("decompile_function"),
                _backend_tool("inspect_action_behavior"),
            ]
        )
