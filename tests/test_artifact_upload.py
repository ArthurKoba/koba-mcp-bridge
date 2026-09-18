from __future__ import annotations

import base64

from koba_mcp_bridge.artifact_store import ArtifactStore
from koba_mcp_bridge.artifact_upload import ArtifactUpload


def test_upload_provider_persists_to_artifact_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024))

    provider = ArtifactUpload()
    files = [
        {
            "name": "firmware.bin",
            "type": "application/octet-stream",
            "size": 8,
            "data": base64.b64encode(b"firmware").decode("ascii"),
        }
    ]

    listed = provider.on_store(files, None)

    assert len(listed) == 1
    artifact_id = listed[0]["artifact_id"]
    assert artifact_id.startswith("sha256:")
    assert ArtifactStore().path_for(artifact_id).read_bytes() == b"firmware"


def test_upload_provider_reads_by_artifact_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024))

    saved = ArtifactStore().put_bytes(b"abc", "sample.bin")
    provider = ArtifactUpload()
    result = provider.on_read(saved["artifact_id"], None)

    assert result["artifact_id"] == saved["artifact_id"]
    assert result["name"] == "sample.bin"
    assert result["content_base64"] == base64.b64encode(b"abc").decode("ascii")
