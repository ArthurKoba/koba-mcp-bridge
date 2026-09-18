import pytest
from fastmcp import Client

import koba_mcp_bridge.server as server_module
from koba_mcp_bridge.server import _configured_backends, _mount_backends, mcp


@pytest.mark.asyncio
async def test_bridge_ping() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_ping", {})

    assert result.data is not None
    assert result.data["status"] == "ok"
    assert result.data["service"] == "koba-mcp-bridge"


@pytest.mark.asyncio
async def test_bridge_build_info() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("bridge_build_info", {})

    assert result.data is not None
    assert result.data["service"] == "koba-mcp-bridge"
    assert result.data["version"]
    assert result.data["commit"]
    assert result.data["built_at"]
    assert result.data["started_at"]
    assert result.data["python"]


@pytest.mark.asyncio
async def test_artifact_tools_are_registered() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    expected = {
        "file_manager",
        "list_files",
        "read_file",
        "artifact_status",
        "artifact_list",
        "artifact_info",
        "artifact_read",
        "artifact_create_text",
        "artifact_extract",
        "artifact_collection_list",
        "artifact_collection_resolve",
        "artifact_references",
        "artifact_release_reference",
        "artifact_delete",
        "artifact_gc",
        "ghidra_import_artifact",
        "ghidra_project_sources",
        "ghidra_export_program_artifact",
        "ghidra_archive_project_artifact",
    }
    assert expected <= names

    retired = {
        "artifact_mkdir",
        "artifact_write_text",
        "artifact_upload_chunk",
        "artifact_import_file",
        "artifact_extract_archive",
        "artifact_download_chunk",
    }
    assert names.isdisjoint(retired)


@pytest.mark.asyncio
async def test_browser_write_probe_is_retired() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert "github_write_probe" not in names


def test_configured_backends_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GHIDRA_MCP_URL", raising=False)
    assert _configured_backends() == {}


def test_configured_backends_ghidra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHIDRA_MCP_URL", "http://ghidra-mcp:8081/mcp")
    assert _configured_backends() == {"ghidra": "http://ghidra-mcp:8081/mcp"}


def test_mounted_backend_negotiates_protocol_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "http://ghidra-mcp:8081/mcp"
    calls: list[tuple[str, dict[str, str]]] = []
    mounted: list[tuple[object, str]] = []
    proxy = object()

    def fake_create_proxy(target: str, **settings: str) -> object:
        calls.append((target, settings))
        return proxy

    class DummyServer:
        def mount(self, *, server: object, namespace: str) -> None:
            mounted.append((server, namespace))

    monkeypatch.setenv("GHIDRA_MCP_URL", url)
    monkeypatch.setattr(server_module, "create_proxy", fake_create_proxy)

    assert _mount_backends(DummyServer()) == {"ghidra": url}  # type: ignore[arg-type]
    assert calls == [(url, {"name": "ghidra-backend", "mode": "auto"})]
    assert mounted == [(proxy, "ghidra")]
