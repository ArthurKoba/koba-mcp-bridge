from __future__ import annotations

from types import SimpleNamespace

import base64

import pytest

import koba_mcp_bridge.reverse_workflow as reverse_workflow
from koba_mcp_bridge.artifact_store import ArtifactError, ArtifactStore
from koba_mcp_bridge.reverse_workflow import (
    _decode_call_result,
    _decode_result,
    ghidra_import_artifact_impl,
)


@pytest.mark.asyncio
async def test_ghidra_import_artifact_dry_run_uses_artifact_id(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    saved = ArtifactStore().put_bytes(b"ELF", "Sofia")

    result = await ghidra_import_artifact_impl(
        saved["artifact_id"],
        project_folder="/firmware",
        auto_analyze=True,
        dry_run=True,
    )

    assert result == {
        "success": True,
        "dry_run": True,
        "artifact_id": saved["artifact_id"],
        "name": "Sofia",
        "project_folder": "/firmware",
        "language": None,
        "compiler_spec": None,
        "auto_analyze": True,
    }



def test_decode_result_parses_raw_ghidra_json_string() -> None:
    raw = (
        '{"has_project":true,"project_name":"spezvision_svi252b_hi3516cv200_stock",'
        '"file_count":0,"program_count":0,"project_server_bound":false}'
    )

    result = _decode_result(raw)

    assert result["has_project"] is True
    assert result["project_name"] == "spezvision_svi252b_hi3516cv200_stock"


def test_decode_result_parses_proxy_wrapped_ghidra_json_string() -> None:
    wrapped = {
        "result": (
            '{"has_project":true,"project_name":"camera",'
            '"file_count":0,"program_count":0}'
        )
    }

    result = _decode_result(wrapped)

    assert result["has_project"] is True
    assert result["project_name"] == "camera"



def test_decode_call_result_falls_back_to_text_content() -> None:
    result = SimpleNamespace(
        data=None,
        structured_content=None,
        content=[
            SimpleNamespace(
                text=(
                    '{"has_project":true,"project_name":"spezvision",'
                    '"file_count":0,"program_count":0}'
                )
            )
        ],
    )

    decoded = _decode_call_result(result)

    assert decoded["has_project"] is True
    assert decoded["project_name"] == "spezvision"


def test_decode_call_result_handles_structured_proxy_wrapper() -> None:
    result = SimpleNamespace(
        data=None,
        structured_content={
            "result": (
                '{"has_project":true,"project_name":"camera",'
                '"file_count":1,"program_count":1}'
            )
        },
        content=[],
    )

    decoded = _decode_call_result(result)

    assert decoded["has_project"] is True
    assert decoded["project_name"] == "camera"



def test_decode_result_recursively_unwraps_json_result_envelopes() -> None:
    raw = (
        '{"result":"{\\\"has_project\\\":true,'
        '\\\"project_name\\\":\\\"spezvision\\\"}"}'
    )

    decoded = _decode_result(raw)

    assert decoded["has_project"] is True
    assert decoded["project_name"] == "spezvision"


def test_decode_call_result_prefers_structured_content_over_lossy_data() -> None:
    result = SimpleNamespace(
        data={"value": "lossy"},
        structured_content={
            "result": (
                '{"has_project":true,"project_name":"spezvision",'
                '"file_count":0,"program_count":0}'
            )
        },
        content=[],
    )

    decoded = _decode_call_result(result)

    assert decoded["has_project"] is True
    assert decoded["project_name"] == "spezvision"



class _FakeGhidraClient:
    def __init__(self, artifact_sha256: str, *, import_error: str = "") -> None:
        self.artifact_sha256 = artifact_sha256
        self.import_error = import_error
        self.calls: list[tuple[str, dict]] = []
        self.received = bytearray()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def call_tool(self, name: str, payload: dict):
        self.calls.append((name, payload))
        if name == "get_project_info":
            body = {
                "has_project": True,
                "project_name": "camera",
                "file_count": 0,
                "program_count": 0,
            }
        elif name == "artifact_stage_begin":
            body = {
                "success": True,
                "stage_id": "stage-1",
                "chunk_bytes": 4,
            }
        elif name == "artifact_stage_write":
            assert payload["offset"] == len(self.received)
            chunk = base64.b64decode(payload["data_base64"])
            self.received.extend(chunk)
            body = {
                "success": True,
                "next_offset": len(self.received),
            }
        elif name == "artifact_stage_finish":
            body = {
                "success": True,
                "path": "/artifacts/.koba-stage/stage-1/Sofia",
                "sha256": self.artifact_sha256,
            }
        elif name == "import_file":
            if self.import_error:
                body = {"error": self.import_error}
            else:
                body = {"success": True, "program": "Sofia"}
        elif name == "artifact_stage_cancel":
            body = {"success": True, "cancelled": True}
        else:
            raise AssertionError(f"unexpected tool call: {name}")
        return SimpleNamespace(structured_content=body, data=None, content=[])


@pytest.mark.asyncio
async def test_ghidra_import_artifact_streams_through_backend_stage(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("GHIDRA_MCP_URL", "http://ghidra-mcp:8081/mcp")
    payload = b"ELF-STAGED"
    saved = ArtifactStore().put_bytes(payload, "Sofia")
    fake = _FakeGhidraClient(saved["sha256"])
    monkeypatch.setattr(reverse_workflow, "Client", lambda url: fake)

    result = await ghidra_import_artifact_impl(
        saved["artifact_id"],
        auto_analyze=False,
    )

    assert result["success"] is True
    assert result["project_name"] == "camera"
    assert bytes(fake.received) == payload
    assert [name for name, _ in fake.calls] == [
        "get_project_info",
        "artifact_stage_begin",
        "artifact_stage_write",
        "artifact_stage_write",
        "artifact_stage_write",
        "artifact_stage_finish",
        "import_file",
        "artifact_stage_cancel",
    ]
    refs = ArtifactStore().references(
        consumer_type="ghidra-project",
        consumer_id="camera",
    )
    assert [ref["artifact_id"] for ref in refs] == [saved["artifact_id"]]


@pytest.mark.asyncio
async def test_ghidra_import_artifact_does_not_reference_backend_failure(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("GHIDRA_MCP_URL", "http://ghidra-mcp:8081/mcp")
    saved = ArtifactStore().put_bytes(b"ELF", "Sofia")
    fake = _FakeGhidraClient(saved["sha256"], import_error="import exploded")
    monkeypatch.setattr(reverse_workflow, "Client", lambda url: fake)

    with pytest.raises(ArtifactError, match="import exploded"):
        await ghidra_import_artifact_impl(
            saved["artifact_id"],
            auto_analyze=False,
        )

    assert fake.calls[-1][0] == "artifact_stage_cancel"
    refs = ArtifactStore().references(
        consumer_type="ghidra-project",
        consumer_id="camera",
    )
    assert refs == []
