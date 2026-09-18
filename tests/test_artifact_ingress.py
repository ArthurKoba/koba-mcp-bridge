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


def test_agent_upload_begin_write_finish(manager: ArtifactUploadManager) -> None:
    payload = b"firmware-image"
    expected = hashlib.sha256(payload).hexdigest()
    begun = manager.begin(
        "firmware.bin",
        size_bytes=len(payload),
        mime_type="application/octet-stream",
        expected_sha256=expected,
    )

    written = manager.write(
        begun["upload_id"],
        offset=0,
        data_base64=base64.b64encode(payload).decode("ascii"),
    )
    assert written["complete"] is True
    assert written["next_offset"] == len(payload)

    finished = manager.finish(begun["upload_id"])
    artifact = finished["artifact"]

    assert finished["completed"] is True
    assert artifact["artifact_id"] == f"sha256:{expected}"
    assert ArtifactStore().path_for(artifact["artifact_id"]).read_bytes() == payload

    with pytest.raises(ArtifactError, match="does not exist"):
        manager.status(begun["upload_id"])


def test_agent_upload_is_resumable_across_manager_instances(
    manager: ArtifactUploadManager,
) -> None:
    payload = b"abcdef"
    begun = manager.begin("resume.bin", size_bytes=len(payload))
    manager.write(
        begun["upload_id"],
        offset=0,
        data_base64=base64.b64encode(payload[:3]).decode("ascii"),
    )

    resumed = ArtifactUploadManager().status(begun["upload_id"])
    assert resumed["bytes_received"] == 3
    assert resumed["next_offset"] == 3
    assert resumed["remaining_bytes"] == 3

    ArtifactUploadManager().write(
        begun["upload_id"],
        offset=3,
        data_base64=base64.b64encode(payload[3:]).decode("ascii"),
    )
    finished = ArtifactUploadManager().finish(begun["upload_id"])
    assert ArtifactStore().path_for(
        finished["artifact"]["artifact_id"]
    ).read_bytes() == payload


def test_agent_upload_rejects_wrong_offset(manager: ArtifactUploadManager) -> None:
    begun = manager.begin("ordered.bin", size_bytes=4)
    manager.write(
        begun["upload_id"],
        offset=0,
        data_base64=base64.b64encode(b"ab").decode("ascii"),
    )

    with pytest.raises(ArtifactError, match="offset mismatch"):
        manager.write(
            begun["upload_id"],
            offset=0,
            data_base64=base64.b64encode(b"cd").decode("ascii"),
        )

    assert manager.status(begun["upload_id"])["next_offset"] == 2


def test_agent_upload_rejects_incomplete_finish(manager: ArtifactUploadManager) -> None:
    begun = manager.begin("incomplete.bin", size_bytes=4)
    manager.write(
        begun["upload_id"],
        offset=0,
        data_base64=base64.b64encode(b"ab").decode("ascii"),
    )

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
    manager.write(
        begun["upload_id"],
        offset=0,
        data_base64=base64.b64encode(payload).decode("ascii"),
    )

    with pytest.raises(ArtifactError, match="SHA-256 mismatch"):
        manager.finish(begun["upload_id"])

    cancelled = manager.cancel(begun["upload_id"])
    assert cancelled["cancelled"] is True
    assert cancelled["discarded_bytes"] == len(payload)
    assert manager.cancel(begun["upload_id"])["already_absent"] is True


def test_agent_upload_deduplicates_identical_files(
    manager: ArtifactUploadManager,
) -> None:
    payload = b"same-object"
    artifact_ids = []

    for name in ("first.bin", "second.bin"):
        begun = manager.begin(name, size_bytes=len(payload))
        manager.write(
            begun["upload_id"],
            offset=0,
            data_base64=base64.b64encode(payload).decode("ascii"),
        )
        artifact_ids.append(manager.finish(begun["upload_id"])["artifact"]["artifact_id"])

    assert artifact_ids[0] == artifact_ids[1]
    info = ArtifactStore().info(artifact_ids[0])
    assert {alias["name"] for alias in info["aliases"]} == {"first.bin", "second.bin"}



def test_upload_list_and_gc_abandoned_sessions(
    manager: ArtifactUploadManager,
) -> None:
    active = manager.begin("active.bin", size_bytes=1)
    abandoned = manager.begin("abandoned.bin", size_bytes=1)

    with manager._connect() as db:
        db.execute(
            """
            UPDATE upload_sessions
            SET updated_at = ?
            WHERE upload_id = ?
            """,
            ("2000-01-01T00:00:00+00:00", abandoned["upload_id"]),
        )

    listed = manager.list()
    ids = {item["upload_id"] for item in listed["items"]}
    assert active["upload_id"] in ids
    assert abandoned["upload_id"] in ids

    preview = manager.gc(max_age_hours=1, dry_run=True)
    assert [item["upload_id"] for item in preview["candidates"]] == [
        abandoned["upload_id"]
    ]

    collected = manager.gc(max_age_hours=1, dry_run=False)
    assert collected["count"] == 1
    assert collected["deleted"][0]["upload_id"] == abandoned["upload_id"]
    assert manager.status(active["upload_id"])["bytes_received"] == 0
    with pytest.raises(ArtifactError, match="does not exist"):
        manager.status(abandoned["upload_id"])
