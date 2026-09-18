from __future__ import annotations

import base64
import io
import tarfile

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


def test_list_is_paginated(root):
    artifact_storage.artifact_write_text_impl("inbox/a.txt", "a")
    artifact_storage.artifact_write_text_impl("inbox/b.txt", "b")
    page = artifact_storage.artifact_list_impl("inbox", offset=1, limit=1)
    assert page["total"] == 2
    assert len(page["entries"]) == 1
    assert page["truncated"] is False



class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._buffer = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def geturl(self) -> str:
        return "https://files.example.invalid/attachment.bin"

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def test_import_file_from_https_source(root, monkeypatch):
    payload = b"firmware-bytes"
    monkeypatch.setattr(
        artifact_storage,
        "_validate_https_source",
        lambda source: None,
    )
    monkeypatch.setattr(
        artifact_storage.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(payload),
    )

    result = artifact_storage.artifact_import_file_impl(
        "https://files.example.invalid/attachment.bin",
        "inbox/attachment.bin",
    )

    assert result["success"] is True
    assert result["size_bytes"] == len(payload)
    assert (root / "inbox" / "attachment.bin").read_bytes() == payload


def test_extract_tgz_on_artifact_storage(root):
    archive = root / "inbox" / "workspace.tgz"
    payload = b"ELF-test"
    with tarfile.open(archive, mode="w:gz") as handle:
        info = tarfile.TarInfo("rootfs/usr/bin/Sofia")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))

    result = artifact_storage.artifact_extract_archive_impl(
        "inbox/workspace.tgz",
        "workspaces/svi252b",
    )

    assert result["files"] == 1
    assert result["total_bytes"] == len(payload)
    extracted = root / "workspaces" / "svi252b" / "rootfs" / "usr" / "bin" / "Sofia"
    assert extracted.read_bytes() == payload


def test_extract_archive_rejects_path_traversal(root):
    archive = root / "inbox" / "bad.tgz"
    with tarfile.open(archive, mode="w:gz") as handle:
        payload = b"x"
        info = tarfile.TarInfo("../escape")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))

    with pytest.raises(artifact_storage.ArtifactError, match="escapes destination"):
        artifact_storage.artifact_extract_archive_impl(
            "inbox/bad.tgz",
            "workspaces/bad",
        )

    assert not (root / "workspaces" / "bad").exists()
