from __future__ import annotations

import base64
import hashlib

import pytest

from koba_mcp_bridge.artifact_ingress import ArtifactUploadManager
from koba_mcp_bridge.artifact_store import ArtifactError, ArtifactStore


@pytest.fixture
def manager(tmp_path, monkeypatch) -> ArtifactUploadManager:
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_UPLOAD_MAX_BYTES", str(16 * 1024 * 1024))
    monkeypatch.setenv("ARTIFACT_UPLOAD_CHUNK_BYTES", str(64 * 1024))
    value = ArtifactUploadManager()
    value.ensure()
    return value


def _write(manager: ArtifactUploadManager, upload_id: str, offset: int, data: bytes):
    return manager.write(
        upload_id,
        offset=offset,
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def test_agent_upload_begin_write_finish(manager: ArtifactUploadManager) -> None:
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
    artifact = finished["artifact"]

    assert finished["completed"] is True
    assert finished["already_committed"] is False
    assert artifact["artifact_id"] == f"sha256:{expected}"
    assert ArtifactStore().path_for(artifact["artifact_id"]).read_bytes() == payload

    status = manager.status(begun["upload_id"])
    assert status["committed"] is True
    assert status["artifact_id"] == artifact["artifact_id"]


def test_finish_is_idempotent_after_commit(manager: ArtifactUploadManager) -> None:
    payload = b"idempotent"
    begun = manager.begin("idempotent.bin", size_bytes=len(payload))
    _write(manager, begun["upload_id"], 0, payload)

    first = manager.finish(begun["upload_id"])
    second = manager.finish(begun["upload_id"])

    assert second["already_committed"] is True
    assert second["artifact"]["artifact_id"] == first["artifact"]["artifact_id"]


def test_agent_upload_is_resumable_across_manager_instances(
    manager: ArtifactUploadManager,
) -> None:
    payload = b"abcdef"
    begun = manager.begin("resume.bin", size_bytes=len(payload))
    _write(manager, begun["upload_id"], 0, payload[:3])

    resumed = ArtifactUploadManager().status(begun["upload_id"])
    assert resumed["bytes_received"] == 3
    assert resumed["next_offset"] == 3
    assert resumed["remaining_bytes"] == 3

    _write(ArtifactUploadManager(), begun["upload_id"], 3, payload[3:])
    finished = ArtifactUploadManager().finish(begun["upload_id"])
    assert ArtifactStore().path_for(
        finished["artifact"]["artifact_id"]
    ).read_bytes() == payload


def test_status_recovers_bytes_written_before_metadata_commit(
    manager: ArtifactUploadManager,
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
    assert ArtifactStore().path_for(
        finished["artifact"]["artifact_id"]
    ).read_bytes() == payload


def test_agent_upload_rejects_wrong_offset(manager: ArtifactUploadManager) -> None:
    begun = manager.begin("ordered.bin", size_bytes=4)
    _write(manager, begun["upload_id"], 0, b"ab")

    with pytest.raises(ArtifactError, match="offset mismatch"):
        _write(manager, begun["upload_id"], 0, b"cd")

    assert manager.status(begun["upload_id"])["next_offset"] == 2


def test_agent_upload_rejects_incomplete_finish(manager: ArtifactUploadManager) -> None:
    begun = manager.begin("incomplete.bin", size_bytes=4)
    _write(manager, begun["upload_id"], 0, b"ab")

    with pytest.raises(ArtifactError, match="incomplete"):
        manager.finish(begun["upload_id"])

    assert manager.status(begun["upload_id"])["bytes_received"] == 2


def test_agent_upload_sha_mismatch_can_be_cancelled(manager: ArtifactUploadManager) -> None:
    payload = b"actual"
    begun = manager.begin(
        "checksum.bin",
        size_bytes=len(payload),
        expected_sha256=hashlib.sha256(b"different").hexdigest(),
    )
    _write(manager, begun["upload_id"], 0, payload)

    with pytest.raises(ArtifactError, match="SHA-256 mismatch"):
        manager.finish(begun["upload_id"])

    cancelled = manager.cancel(begun["upload_id"])
    assert cancelled["cancelled"] is True
    assert cancelled["discarded_bytes"] == len(payload)
    assert manager.cancel(begun["upload_id"])["already_absent"] is True


def test_cancel_does_not_remove_committed_artifact(manager: ArtifactUploadManager) -> None:
    payload = b"committed"
    begun = manager.begin("committed.bin", size_bytes=len(payload))
    _write(manager, begun["upload_id"], 0, payload)
    finished = manager.finish(begun["upload_id"])

    cancelled = manager.cancel(begun["upload_id"])

    assert cancelled["already_committed"] is True
    assert cancelled["artifact_id"] == finished["artifact"]["artifact_id"]
    assert ArtifactStore().path_for(cancelled["artifact_id"]).read_bytes() == payload


def test_agent_upload_deduplicates_identical_files(
    manager: ArtifactUploadManager,
) -> None:
    payload = b"same-object"
    artifact_ids = []

    for name in ("first.bin", "second.bin"):
        begun = manager.begin(name, size_bytes=len(payload))
        _write(manager, begun["upload_id"], 0, payload)
        artifact_ids.append(manager.finish(begun["upload_id"])["artifact"]["artifact_id"])

    assert artifact_ids[0] == artifact_ids[1]
    info = ArtifactStore().info(artifact_ids[0])
    assert {alias["name"] for alias in info["aliases"]} == {"first.bin", "second.bin"}


def test_upload_list_recovers_open_and_completed_sessions(
    manager: ArtifactUploadManager,
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
    manager: ArtifactUploadManager,
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

    with pytest.raises(ArtifactError, match="does not exist"):
        manager.status(stale_open["upload_id"])
    with pytest.raises(ArtifactError, match="does not exist"):
        manager.status(stale_completed["upload_id"])

    artifact_id = committed["artifact"]["artifact_id"]
    assert ArtifactStore().path_for(artifact_id).read_bytes() == b"z"
