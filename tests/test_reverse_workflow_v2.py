from __future__ import annotations

import pytest

from koba_mcp_bridge.artifact_store import ArtifactStore
from koba_mcp_bridge.reverse_workflow import _decode_result, ghidra_import_artifact_impl


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
