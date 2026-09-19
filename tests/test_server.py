import base64

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
        "artifact_status",
        "artifact_ingest_file",
        "artifact_upload_begin",
        "artifact_upload_list",
        "artifact_upload_status",
        "artifact_upload_write",
        "artifact_upload_finish",
        "artifact_upload_cleanup",
        "artifact_upload_cancel",
        "artifact_list",
        "artifact_info",
        "artifact_read",
        "artifact_create_text",
        "artifact_extract",
        "artifact_collection_list",
        "artifact_collection_delete",
        "artifact_collection_resolve",
        "artifact_references",
        "artifact_release_reference",
        "artifact_delete",
        "artifact_gc",
        "ghidra_import_artifact",
        "ghidra_project_sources",
        "ghidra_export_program_artifact",
        "ghidra_archive_project_artifact",
        "curl_presets",
        "curl_request",
        "curl_download",
        "curl_stream_capture",
    }
    assert expected <= names

    ingest_tool = next(tool for tool in tools if tool.name == "artifact_ingest_file")
    descriptor = ingest_tool.model_dump(by_alias=True)
    assert descriptor["_meta"]["openai/fileParams"] == ["file"]
    assert descriptor["inputSchema"]["properties"]["file"]["type"] == "object"
    assert "download_url" in descriptor["inputSchema"]["properties"]["file"]["properties"]


@pytest.mark.asyncio
async def test_agent_upload_round_trip_over_mcp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024))
    monkeypatch.setenv("ARTIFACT_UPLOAD_CHUNK_BYTES", str(64 * 1024))
    payload = b"mcp-agent-upload"

    async with Client(mcp) as client:
        begun = await client.call_tool(
            "artifact_upload_begin",
            {
                "name": "probe.bin",
                "size_bytes": len(payload),
            },
        )
        upload_id = begun.data["upload_id"]
        written = await client.call_tool(
            "artifact_upload_write",
            {
                "upload_id": upload_id,
                "offset": 0,
                "data_base64": base64.b64encode(payload).decode("ascii"),
            },
        )
        assert written.data["complete"] is True

        finished = await client.call_tool(
            "artifact_upload_finish",
            {"upload_id": upload_id},
        )

    artifact = finished.data["artifact"]
    assert artifact["artifact_id"].startswith("sha256:")
    assert artifact["size_bytes"] == len(payload)



def test_github_oauth_values_prefer_infisical_convention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        ("github/oauth", "CLIENT_ID"): "client-id-from-infisical",
        ("github/oauth", "CLIENT_SECRET"): "client-secret-from-infisical",
        ("github/oauth", "JWT_SIGNING_KEY"): "jwt-from-infisical",
        ("github/oauth", "ALLOWED_USERS"): "ArthurKoba,ReviewerBot",
    }
    monkeypatch.setattr(
        server_module,
        "resolve_config_secret",
        lambda path, name: values[(path, name)],
    )
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_ID", "legacy-client-id")
    monkeypatch.setenv("OAUTH_ALLOWED_GITHUB_USERS", "legacy-user")

    assert server_module._github_oauth_value(
        "CLIENT_ID",
        "OAUTH_GITHUB_CLIENT_ID",
    ) == "client-id-from-infisical"
    assert server_module._allowed_github_users() == {
        "arthurkoba",
        "reviewerbot",
    }

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

def test_github_oauth_failure_preserves_infisical_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_secret(path: str, name: str) -> str:
        del path, name
        raise server_module.SecretError("Infisical API HTTP 403: denied")

    monkeypatch.setattr(server_module, "resolve_config_secret", fail_secret)
    monkeypatch.delenv("OAUTH_GITHUB_CLIENT_ID", raising=False)

    with pytest.raises(RuntimeError, match="Infisical API HTTP 403"):
        server_module._github_oauth_value(
            "CLIENT_ID",
            "OAUTH_GITHUB_CLIENT_ID",
        )

