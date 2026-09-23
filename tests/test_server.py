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
async def test_file_tools_are_registered() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    expected = {
        "file_status",
        "file_ingest",
        "file_upload_begin",
        "file_upload_list",
        "file_upload_status",
        "file_upload_write",
        "file_upload_finish",
        "file_upload_cleanup",
        "file_upload_cancel",
        "file_list",
        "file_info",
        "file_read",
        "file_create_text",
        "file_extract",
        "file_collection_list",
        "file_collection_delete",
        "file_collection_resolve",
        "file_references",
        "file_release_reference",
        "file_delete",
        "file_gc",
        "ghidra_import_file",
        "ghidra_project_sources",
        "ghidra_export_program_file",
        "ghidra_archive_project_file",
        "curl_presets",
        "curl_request",
        "curl_download",
        "curl_stream_capture",
    }
    assert expected <= names

    ingest_tool = next(tool for tool in tools if tool.name == "file_ingest")
    descriptor = ingest_tool.model_dump(by_alias=True)
    assert descriptor["_meta"]["openai/fileParams"] == ["file"]
    assert descriptor["inputSchema"]["properties"]["file"]["type"] == "object"
    assert "download_url" in descriptor["inputSchema"]["properties"]["file"]["properties"]


@pytest.mark.asyncio
async def test_agent_upload_round_trip_over_mcp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FILE_ROOT", str(tmp_path))
    monkeypatch.setenv("FILE_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024))
    monkeypatch.setenv("FILE_UPLOAD_CHUNK_BYTES", str(64 * 1024))
    payload = b"mcp-agent-upload"

    async with Client(mcp) as client:
        begun = await client.call_tool(
            "file_upload_begin",
            {
                "name": "probe.bin",
                "size_bytes": len(payload),
            },
        )
        upload_id = begun.data["upload_id"]
        written = await client.call_tool(
            "file_upload_write",
            {
                "upload_id": upload_id,
                "offset": 0,
                "data_base64": base64.b64encode(payload).decode("ascii"),
            },
        )
        assert written.data["complete"] is True

        finished = await client.call_tool(
            "file_upload_finish",
            {"upload_id": upload_id},
        )

    file = finished.data["file"]
    assert file["file_id"].startswith("sha256:")
    assert file["size_bytes"] == len(payload)



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
    monkeypatch.setenv("KOBA_GATEWAY_MODE", "embedded")
    monkeypatch.delenv("GHIDRA_MCP_URL", raising=False)
    assert _configured_backends() == {}


def test_configured_backends_ghidra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOBA_GATEWAY_MODE", "embedded")
    monkeypatch.setenv("GHIDRA_MCP_URL", "http://ghidra-mcp:8081/mcp")
    assert _configured_backends() == {
        "ghidra": {
            "url": "http://ghidra-mcp:8081/mcp",
            "namespace": "ghidra",
        }
    }


def test_configured_backends_proxy_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOBA_GATEWAY_MODE", "proxy")
    monkeypatch.setenv("GHIDRA_MCP_URL", "http://ghidra-mcp:8081/mcp")
    monkeypatch.setenv("GITHUB_MCP_URL", "http://github-mcp:8000/mcp")
    monkeypatch.setenv("GITLAB_MCP_URL", "http://gitlab-mcp:8000/mcp")
    monkeypatch.setenv("FILES_MCP_URL", "http://files-mcp:8000/mcp")
    monkeypatch.setenv("HTTP_MCP_URL", "http://http-mcp:8000/mcp")

    assert _configured_backends() == {
        "ghidra": {
            "url": "http://ghidra-mcp:8081/mcp",
            "namespace": "ghidra",
        },
        "github": {
            "url": "http://github-mcp:8000/mcp",
            "namespace": "",
        },
        "gitlab": {
            "url": "http://gitlab-mcp:8000/mcp",
            "namespace": "gitlab",
        },
        "files": {
            "url": "http://files-mcp:8000/mcp",
            "namespace": "",
        },
        "http": {
            "url": "http://http-mcp:8000/mcp",
            "namespace": "",
        },
    }


def test_proxy_mode_requires_all_runtime_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOBA_GATEWAY_MODE", "proxy")
    for name in ("GITHUB_MCP_URL", "GITLAB_MCP_URL", "FILES_MCP_URL", "HTTP_MCP_URL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="GITHUB_MCP_URL"):
        _configured_backends()


def test_mounted_backend_negotiates_protocol_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    mounted: list[tuple[object, str | None]] = []
    proxy = object()

    def fake_create_proxy(target: str, **settings: str) -> object:
        calls.append((target, settings))
        return proxy

    class DummyServer:
        def mount(
            self,
            *,
            server: object,
            namespace: str | None = None,
        ) -> None:
            mounted.append((server, namespace))

    monkeypatch.setenv("KOBA_GATEWAY_MODE", "proxy")
    monkeypatch.setenv("GITHUB_MCP_URL", "http://github-mcp:8000/mcp")
    monkeypatch.setenv("GITLAB_MCP_URL", "http://gitlab-mcp:8000/mcp")
    monkeypatch.setenv("FILES_MCP_URL", "http://files-mcp:8000/mcp")
    monkeypatch.setenv("HTTP_MCP_URL", "http://http-mcp:8000/mcp")
    monkeypatch.setenv("GHIDRA_MCP_URL", "http://ghidra-mcp:8081/mcp")
    monkeypatch.setattr(server_module, "create_proxy", fake_create_proxy)

    result = _mount_backends(DummyServer())  # type: ignore[arg-type]

    assert sorted(result) == ["files", "ghidra", "github", "gitlab", "http"]
    assert calls == [
        (
            "http://ghidra-mcp:8081/mcp",
            {"name": "ghidra-backend", "mode": "auto"},
        ),
        (
            "http://github-mcp:8000/mcp",
            {"name": "github-backend", "mode": "auto"},
        ),
        (
            "http://gitlab-mcp:8000/mcp",
            {"name": "gitlab-backend", "mode": "auto"},
        ),
        (
            "http://files-mcp:8000/mcp",
            {"name": "files-backend", "mode": "auto"},
        ),
        (
            "http://http-mcp:8000/mcp",
            {"name": "http-backend", "mode": "auto"},
        ),
    ]
    assert mounted == [
        (proxy, "ghidra"),
        (proxy, None),
        (proxy, "gitlab"),
        (proxy, None),
        (proxy, None),
    ]

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

