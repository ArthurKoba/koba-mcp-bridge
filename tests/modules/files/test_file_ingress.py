from __future__ import annotations

import base64
import hashlib
import io
import urllib.parse

import pytest

from common.settings import FileSettings
from modules.files.file_store import FileError, FileStore
from modules.files.upload_manager import FileUploadManager


@pytest.fixture
def manager(tmp_path) -> FileUploadManager:
    store = FileStore(
        settings=FileSettings(
            root=tmp_path,
            upload_max_bytes=16 * 1024 * 1024,
            upload_chunk_bytes=64 * 1024,
        )
    )
    value = FileUploadManager(store)
    value.ensure()
    return value


def _write(manager: FileUploadManager, upload_id: str, offset: int, data: bytes):
    return manager.write(
        upload_id,
        offset=offset,
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def test_agent_upload_begin_write_finish(manager: FileUploadManager) -> None:
    payload = b"firmware-image"
    expected = hashlib.sha256(payload).hexdigest()
    begun = manager.begin(
        "firmware.bin",
        size_bytes=len(payload),
        mime_type="application/octet-stream",
        expected_sha256=expected,
    )

    written = _write(manager, begun["upload_id"], 0, payload)
    assert written["complete"] is True
    assert written["committed"] is False
    assert written["next_offset"] == len(payload)

    finished = manager.finish(begun["upload_id"])
    file = finished["file"]

    assert finished["completed"] is True
    assert finished["already_committed"] is False
    assert file["file_id"] == f"sha256:{expected}"
    assert manager.store.path_for(file["file_id"]).read_bytes() == payload

    status = manager.status(begun["upload_id"])
    assert status["committed"] is True
    assert status["file_id"] == file["file_id"]


def test_finish_is_idempotent_after_commit(manager: FileUploadManager) -> None:
    payload = b"idempotent"
    begun = manager.begin("idempotent.bin", size_bytes=len(payload))
    _write(manager, begun["upload_id"], 0, payload)

    first = manager.finish(begun["upload_id"])
    second = manager.finish(begun["upload_id"])

    assert second["already_committed"] is True
    assert second["file"]["file_id"] == first["file"]["file_id"]


def test_agent_upload_is_resumable_across_manager_instances(
    manager: FileUploadManager,
) -> None:
    payload = b"abcdef"
    begun = manager.begin("resume.bin", size_bytes=len(payload))
    _write(manager, begun["upload_id"], 0, payload[:3])

    resumed = FileUploadManager(manager.store).status(begun["upload_id"])
    assert resumed["bytes_received"] == 3
    assert resumed["next_offset"] == 3
    assert resumed["remaining_bytes"] == 3

    _write(FileUploadManager(manager.store), begun["upload_id"], 3, payload[3:])
    finished = FileUploadManager(manager.store).finish(begun["upload_id"])
    assert manager.store.path_for(
        finished["file"]["file_id"]
    ).read_bytes() == payload


def test_status_recovers_bytes_written_before_metadata_commit(
    manager: FileUploadManager,
) -> None:
    payload = b"recover-me"
    begun = manager.begin("recover.bin", size_bytes=len(payload))
    part = manager._part_path(begun["upload_id"])

    with part.open("ab") as handle:
        handle.write(payload)
        handle.flush()

    recovered = manager.status(begun["upload_id"])
    assert recovered["bytes_received"] == len(payload)
    assert recovered["next_offset"] == len(payload)
    assert recovered["complete"] is True

    finished = manager.finish(begun["upload_id"])
    assert manager.store.path_for(
        finished["file"]["file_id"]
    ).read_bytes() == payload


def test_agent_upload_rejects_wrong_offset(manager: FileUploadManager) -> None:
    begun = manager.begin("ordered.bin", size_bytes=4)
    _write(manager, begun["upload_id"], 0, b"ab")

    with pytest.raises(FileError, match="offset mismatch"):
        _write(manager, begun["upload_id"], 0, b"cd")

    assert manager.status(begun["upload_id"])["next_offset"] == 2


def test_agent_upload_rejects_incomplete_finish(manager: FileUploadManager) -> None:
    begun = manager.begin("incomplete.bin", size_bytes=4)
    _write(manager, begun["upload_id"], 0, b"ab")

    with pytest.raises(FileError, match="incomplete"):
        manager.finish(begun["upload_id"])

    assert manager.status(begun["upload_id"])["bytes_received"] == 2


def test_agent_upload_sha_mismatch_can_be_cancelled(manager: FileUploadManager) -> None:
    payload = b"actual"
    begun = manager.begin(
        "checksum.bin",
        size_bytes=len(payload),
        expected_sha256=hashlib.sha256(b"different").hexdigest(),
    )
    _write(manager, begun["upload_id"], 0, payload)

    with pytest.raises(FileError, match="SHA-256 mismatch"):
        manager.finish(begun["upload_id"])

    cancelled = manager.cancel(begun["upload_id"])
    assert cancelled["cancelled"] is True
    assert cancelled["discarded_bytes"] == len(payload)
    assert manager.cancel(begun["upload_id"])["already_absent"] is True


def test_cancel_does_not_remove_committed_file(manager: FileUploadManager) -> None:
    payload = b"committed"
    begun = manager.begin("committed.bin", size_bytes=len(payload))
    _write(manager, begun["upload_id"], 0, payload)
    finished = manager.finish(begun["upload_id"])

    cancelled = manager.cancel(begun["upload_id"])

    assert cancelled["already_committed"] is True
    assert cancelled["file_id"] == finished["file"]["file_id"]
    assert manager.store.path_for(cancelled["file_id"]).read_bytes() == payload


def test_agent_upload_deduplicates_identical_files(
    manager: FileUploadManager,
) -> None:
    payload = b"same-object"
    file_ids = []

    for name in ("first.bin", "second.bin"):
        begun = manager.begin(name, size_bytes=len(payload))
        _write(manager, begun["upload_id"], 0, payload)
        file_ids.append(manager.finish(begun["upload_id"])["file"]["file_id"])

    assert file_ids[0] == file_ids[1]
    info = manager.store.info(file_ids[0])
    assert {alias["name"] for alias in info["aliases"]} == {"first.bin", "second.bin"}


def test_upload_list_recovers_open_and_completed_sessions(
    manager: FileUploadManager,
) -> None:
    open_session = manager.begin("open.bin", size_bytes=1)
    completed = manager.begin("completed.bin", size_bytes=1)
    _write(manager, completed["upload_id"], 0, b"x")
    manager.finish(completed["upload_id"])

    all_sessions = manager.list()
    ids = {item["upload_id"] for item in all_sessions["sessions"]}
    assert open_session["upload_id"] in ids
    assert completed["upload_id"] in ids

    open_only = manager.list(state="open")
    assert [item["upload_id"] for item in open_only["sessions"]] == [
        open_session["upload_id"]
    ]

    completed_only = manager.list(state="completed")
    assert [item["upload_id"] for item in completed_only["sessions"]] == [
        completed["upload_id"]
    ]


def test_upload_cleanup_removes_only_stale_session_state(
    manager: FileUploadManager,
) -> None:
    active = manager.begin("active.bin", size_bytes=1)
    stale_open = manager.begin("stale-open.bin", size_bytes=1)
    stale_completed = manager.begin("stale-completed.bin", size_bytes=1)
    _write(manager, stale_completed["upload_id"], 0, b"z")
    committed = manager.finish(stale_completed["upload_id"])

    with manager._connect() as db:
        db.execute(
            """
            UPDATE upload_sessions
            SET updated_at = ?
            WHERE upload_id IN (?, ?)
            """,
            (
                "2000-01-01T00:00:00+00:00",
                stale_open["upload_id"],
                stale_completed["upload_id"],
            ),
        )

    preview = manager.cleanup(older_than_hours=1, dry_run=True)
    assert {item["upload_id"] for item in preview["sessions"]} == {
        stale_open["upload_id"],
        stale_completed["upload_id"],
    }

    cleaned = manager.cleanup(older_than_hours=1, dry_run=False)
    assert cleaned["count"] == 2
    assert manager.status(active["upload_id"])["committed"] is False

    with pytest.raises(FileError, match="does not exist"):
        manager.status(stale_open["upload_id"])
    with pytest.raises(FileError, match="does not exist"):
        manager.status(stale_completed["upload_id"])

    file_id = committed["file"]["file_id"]
    assert manager.store.path_for(file_id).read_bytes() == b"z"


class _FakeAttachmentResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        self._buffer = io.BytesIO(payload)
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": content_type,
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def geturl(self) -> str:
        return "https://files.example.invalid/download/token"

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def test_attachment_ingress_streams_directly_to_file_store(
    tmp_path,
    monkeypatch,
) -> None:
    from modules.files import file_ingress

    store = FileStore(
        settings=FileSettings(root=tmp_path, upload_max_bytes=16 * 1024 * 1024)
    )

    payload = b"chat-attachment-bytes"
    digest = hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(
        file_ingress,
        "_validate_remote_file_url",
        urllib.parse.urlsplit,
    )
    monkeypatch.setattr(
        file_ingress,
        "_open_remote_file",
        lambda request: _FakeAttachmentResponse(
            payload,
            content_type="application/x-firmware",
        ),
    )

    result = file_ingress.ingest_file(
        file={
            "download_url": "https://files.example.invalid/download/token",
            "file_id": "file-test",
            "file_name": "Sofia",
            "mime_type": "application/x-firmware",
        },
        expected_size=len(payload),
        expected_sha256=digest,
        store=store,
    )

    file = result["file"]
    assert result["transport"] == "client-file"
    assert file["file_id"] == f"sha256:{digest}"
    assert file["name"] == "Sofia"
    assert file["mime_type"] == "application/x-firmware"
    assert store.path_for(file["file_id"]).read_bytes() == payload


def test_attachment_ingress_rejects_checksum_mismatch_without_committing(
    tmp_path,
    monkeypatch,
) -> None:
    from modules.files import file_ingress

    store = FileStore(
        settings=FileSettings(root=tmp_path, upload_max_bytes=16 * 1024 * 1024)
    )

    payload = b"actual"
    monkeypatch.setattr(
        file_ingress,
        "_validate_remote_file_url",
        urllib.parse.urlsplit,
    )
    monkeypatch.setattr(
        file_ingress,
        "_open_remote_file",
        lambda request: _FakeAttachmentResponse(payload),
    )

    with pytest.raises(FileError, match="SHA-256 mismatch"):
        file_ingress.ingest_file(
            file={
                "download_url": "https://files.example.invalid/download/token",
                "file_id": "file-test",
                "file_name": "bad.bin",
            },
            expected_size=len(payload),
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
            store=store,
        )

    assert store.list()["total"] == 0


def test_attachment_ingress_rejects_non_https_source(tmp_path, monkeypatch) -> None:
    from modules.files import file_ingress

    store = FileStore(settings=FileSettings(root=tmp_path))
    with pytest.raises(FileError, match="HTTPS attachment URL"):
        file_ingress.ingest_file(
            file={
                "download_url": "/mnt/data/local.bin",
                "file_id": "file-local",
                "file_name": "local.bin",
            },
            store=store,
        )
