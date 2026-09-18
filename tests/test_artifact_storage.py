from __future__ import annotations

import base64

import pytest

from koba_mcp_bridge import artifact_storage


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_MAX_CHUNK_BYTES", "4096")
    artifact_storage.ensure_artifact_layout()
    return tmp_path


def test_layout(root):
    assert (root / "inbox").is_dir()
    assert (root / "exports").is_dir()
    assert (root / "scripts").is_dir()


def test_path_escape_and_absolute_path_rejected(root):
    with pytest.raises(artifact_storage.ArtifactError):
        artifact_storage._resolve("../outside")
    with pytest.raises(artifact_storage.ArtifactError):
        artifact_storage._resolve("/etc/passwd")


def test_chunk_upload_download_and_hash(root):
    one = artifact_storage.artifact_upload_chunk_impl(
        "inbox/test.bin", base64.b64encode(b"abc").decode(), offset=0, truncate=True
    )
    two = artifact_storage.artifact_upload_chunk_impl(
        "inbox/test.bin", base64.b64encode(b"defgh").decode(), offset=one["next_offset"]
    )
    assert two["size_bytes"] == 8

    info = artifact_storage.artifact_info_impl("inbox/test.bin", sha256=True)
    assert len(info["sha256"]) == 64

    out = artifact_storage.artifact_download_chunk_impl("inbox/test.bin", 0, 4096)
    assert base64.b64decode(out["data_base64"]) == b"abcdefgh"
    assert out["eof"] is True


def test_offset_mismatch_rejected(root):
    artifact_storage.artifact_upload_chunk_impl(
        "inbox/test.bin", base64.b64encode(b"abc").decode(), offset=0, truncate=True
    )
    with pytest.raises(artifact_storage.ArtifactError, match="offset mismatch"):
        artifact_storage.artifact_upload_chunk_impl(
            "inbox/test.bin", base64.b64encode(b"x").decode(), offset=1
        )


def test_write_text_and_delete(root):
    saved = artifact_storage.artifact_write_text_impl("scripts/Probe.java", "class Probe {}")
    assert saved["path"] == "scripts/Probe.java"
    assert artifact_storage.artifact_delete_impl("scripts/Probe.java")["deleted"] is True


def test_standard_dirs_are_protected(root):
    with pytest.raises(artifact_storage.ArtifactError, match="cannot be deleted"):
        artifact_storage.artifact_delete_impl("inbox", recursive=True)
