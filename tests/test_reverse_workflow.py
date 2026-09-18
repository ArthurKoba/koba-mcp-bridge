from __future__ import annotations

import pytest

from koba_mcp_bridge.reverse_workflow import ghidra_import_artifact_impl


@pytest.mark.asyncio
async def test_ghidra_import_artifact_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    source = tmp_path / "workspaces" / "svi252b" / "Sofia"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"ELF")

    result = await ghidra_import_artifact_impl(
        "workspaces/svi252b/Sofia",
        project_folder="/firmware",
        auto_analyze=True,
        dry_run=True,
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["artifact_path"] == "workspaces/svi252b/Sofia"
    assert result["server_path"] == str(source)
    assert result["project_folder"] == "/firmware"
