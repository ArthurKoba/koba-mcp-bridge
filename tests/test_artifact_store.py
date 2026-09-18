from __future__ import annotations

import io
import tarfile

import pytest

from koba_mcp_bridge.artifact_store import ArtifactError, ArtifactStore


@pytest.fixture
def store(tmp_path, monkeypatch) -> ArtifactStore:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024))
    monkeypatch.setenv("ARTIFACT_MAX_EXTRACT_FILES", "100")
    monkeypatch.setenv("ARTIFACT_MAX_EXTRACT_BYTES", str(16 * 1024 * 1024))
    value = ArtifactStore()
    value.ensure()
    return value


def test_content_addressed_deduplication(store: ArtifactStore) -> None:
    first = store.put_bytes(b"same-bytes", "one.bin")
    second = store.put_bytes(b"same-bytes", "two.bin")

    assert first["artifact_id"] == second["artifact_id"]
    info = store.info(first["artifact_id"])
    assert {alias["name"] for alias in info["aliases"]} == {"one.bin", "two.bin"}
    assert store.path_for(first["artifact_id"]).read_bytes() == b"same-bytes"


def test_artifact_read_uses_id_not_path(store: ArtifactStore) -> None:
    saved = store.put_bytes(b"abcdef", "sample.bin")
    chunk = store.read(saved["artifact_id"], offset=2, length=3)

    assert chunk["bytes_read"] == 3
    assert chunk["next_offset"] == 5
    assert chunk["eof"] is False


def test_reference_blocks_delete_until_released(store: ArtifactStore) -> None:
    saved = store.put_bytes(b"firmware", "firmware.bin")
    artifact_id = saved["artifact_id"]

    store.add_reference(
        artifact_id,
        consumer_type="ghidra-project",
        consumer_id="camera",
        role="source",
    )

    with pytest.raises(ArtifactError, match="referenced"):
        store.delete(artifact_id)

    released = store.release_reference(
        artifact_id,
        consumer_type="ghidra-project",
        consumer_id="camera",
        role="source",
    )
    assert released["released"] is True
    assert store.delete(artifact_id)["deleted"] is True


def test_extract_archive_creates_collection(store: ArtifactStore, tmp_path) -> None:
    archive_path = tmp_path / "workspace.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"ELF-SOFIA"
        info = tarfile.TarInfo("rootfs/usr/bin/Sofia")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    archive_artifact = store.put_file(archive_path, name="workspace.tgz")
    extracted = store.extract(archive_artifact["artifact_id"])

    assert extracted["files"] == 1
    resolved = store.collection_resolve(
        extracted["collection_id"],
        "rootfs/usr/bin/Sofia",
    )
    assert store.path_for(resolved["artifact_id"]).read_bytes() == b"ELF-SOFIA"


def test_extract_archive_rejects_traversal(store: ArtifactStore, tmp_path) -> None:
    archive_path = tmp_path / "bad.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"x"
        info = tarfile.TarInfo("../escape")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    archive_artifact = store.put_file(archive_path, name="bad.tgz")

    with pytest.raises(ArtifactError, match="unsafe archive path"):
        store.extract(archive_artifact["artifact_id"])


def test_gc_only_selects_unreferenced_artifacts(store: ArtifactStore) -> None:
    unused = store.put_bytes(b"unused", "unused.bin")
    used = store.put_bytes(b"used", "used.bin")
    store.add_reference(
        used["artifact_id"],
        consumer_type="worker",
        consumer_id="job-1",
        role="input",
    )

    preview = store.gc(dry_run=True)

    assert unused["artifact_id"] in preview["candidates"]
    assert used["artifact_id"] not in preview["candidates"]
