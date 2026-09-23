from __future__ import annotations

import io
import sqlite3
import tarfile

import pytest

from koba_mcp_bridge.file_store import FileError, FileStore


@pytest.fixture
def store(tmp_path, monkeypatch) -> FileStore:
    monkeypatch.setenv("FILE_ROOT", str(tmp_path))
    monkeypatch.setenv("FILE_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024))
    monkeypatch.setenv("FILE_MAX_EXTRACT_FILES", "100")
    monkeypatch.setenv("FILE_MAX_EXTRACT_BYTES", str(16 * 1024 * 1024))
    value = FileStore()
    value.ensure()
    return value


def test_content_addressed_deduplication(store: FileStore) -> None:
    first = store.put_bytes(b"same-bytes", "one.bin")
    second = store.put_bytes(b"same-bytes", "two.bin")

    assert first["file_id"] == second["file_id"]
    info = store.info(first["file_id"])
    assert {alias["name"] for alias in info["aliases"]} == {"one.bin", "two.bin"}
    assert store.path_for(first["file_id"]).read_bytes() == b"same-bytes"


def test_file_read_uses_id_not_path(store: FileStore) -> None:
    saved = store.put_bytes(b"abcdef", "sample.bin")
    chunk = store.read(saved["file_id"], offset=2, length=3)

    assert chunk["bytes_read"] == 3
    assert chunk["next_offset"] == 5
    assert chunk["eof"] is False


def test_reference_blocks_delete_until_released(store: FileStore) -> None:
    saved = store.put_bytes(b"firmware", "firmware.bin")
    file_id = saved["file_id"]

    store.add_reference(
        file_id,
        consumer_type="ghidra-project",
        consumer_id="camera",
        role="source",
    )

    with pytest.raises(FileError, match="referenced"):
        store.delete(file_id)

    released = store.release_reference(
        file_id,
        consumer_type="ghidra-project",
        consumer_id="camera",
        role="source",
    )
    assert released["released"] is True
    assert store.delete(file_id)["deleted"] is True


def test_extract_archive_creates_collection(store: FileStore, tmp_path) -> None:
    archive_path = tmp_path / "workspace.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"ELF-SOFIA"
        info = tarfile.TarInfo("rootfs/usr/bin/Sofia")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    archive_file = store.put_file(archive_path, name="workspace.tgz")
    extracted = store.extract(archive_file["file_id"])

    assert extracted["files"] == 1
    resolved = store.collection_resolve(
        extracted["collection_id"],
        "rootfs/usr/bin/Sofia",
    )
    assert store.path_for(resolved["file_id"]).read_bytes() == b"ELF-SOFIA"


def test_extract_archive_rejects_traversal(store: FileStore, tmp_path) -> None:
    archive_path = tmp_path / "bad.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"x"
        info = tarfile.TarInfo("../escape")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    archive_file = store.put_file(archive_path, name="bad.tgz")

    with pytest.raises(FileError, match="unsafe archive path"):
        store.extract(archive_file["file_id"])


def test_gc_only_selects_unreferenced_files(store: FileStore) -> None:
    unused = store.put_bytes(b"unused", "unused.bin")
    used = store.put_bytes(b"used", "used.bin")
    store.add_reference(
        used["file_id"],
        consumer_type="worker",
        consumer_id="job-1",
        role="input",
    )

    preview = store.gc(dry_run=True)

    assert unused["file_id"] in preview["candidates"]
    assert used["file_id"] not in preview["candidates"]


def test_collection_delete_releases_members_for_gc(store: FileStore, tmp_path) -> None:
    archive_path = tmp_path / "workspace-delete.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"member-bytes"
        info = tarfile.TarInfo("lib/libcamera.so")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    source = store.put_file(archive_path, name="workspace-delete.tgz")
    extracted = store.extract(source["file_id"])
    member = store.collection_resolve(
        extracted["collection_id"],
        "lib/libcamera.so",
    )

    before = store.gc(dry_run=True)
    assert member["file_id"] not in before["candidates"]
    assert source["file_id"] not in before["candidates"]

    deleted = store.collection_delete(extracted["collection_id"])
    assert deleted["deleted"] is True

    after = store.gc(dry_run=True)
    assert member["file_id"] in after["candidates"]
    assert source["file_id"] in after["candidates"]


def test_existing_database_is_migrated_to_files_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FILE_ROOT", str(tmp_path))
    database = tmp_path / "index.sqlite3"
    db = sqlite3.connect(database)
    db.executescript(
        """
        CREATE TABLE artifacts (
            artifact_id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE aliases (
            artifact_id TEXT NOT NULL,
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, name, source)
        );
        CREATE TABLE collections (
            collection_id TEXT PRIMARY KEY,
            source_artifact_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE collection_items (
            collection_id TEXT NOT NULL,
            path TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            PRIMARY KEY (collection_id, path)
        );
        CREATE TABLE artifact_refs (
            artifact_id TEXT NOT NULL,
            consumer_type TEXT NOT NULL,
            consumer_id TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, consumer_type, consumer_id, role)
        );
        CREATE INDEX idx_collection_artifact
            ON collection_items(artifact_id);
        """
    )
    file_id = "sha256:" + "a" * 64
    db.execute(
        "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?)",
        (file_id, "a" * 64, "firmware.bin", "application/octet-stream", 4, "now"),
    )
    db.execute(
        "INSERT INTO aliases VALUES (?, ?, ?, ?)",
        (file_id, "firmware.bin", "upload", "now"),
    )
    db.commit()
    db.close()

    store = FileStore()
    store.ensure()

    info = store.info(file_id)
    assert info["file_id"] == file_id
    assert info["name"] == "firmware.bin"

    db = sqlite3.connect(database)
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    schema = "\n".join(
        row[0] or ""
        for row in db.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
    )
    db.close()

    assert {"files", "aliases", "collections", "collection_items", "file_refs"} <= tables
    assert "artifacts" not in tables
    assert "artifact_id" not in schema
    assert "source_artifact_id" not in schema
    assert "artifact_refs" not in schema
