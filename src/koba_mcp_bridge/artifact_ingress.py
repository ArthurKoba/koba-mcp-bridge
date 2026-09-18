from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactError, ArtifactStore, upload_max_bytes

_DEFAULT_CHUNK_BYTES = 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat()


def upload_chunk_bytes() -> int:
    raw = os.getenv("ARTIFACT_UPLOAD_CHUNK_BYTES", str(_DEFAULT_CHUNK_BYTES)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ArtifactError("ARTIFACT_UPLOAD_CHUNK_BYTES must be an integer") from exc
    if value < 64 * 1024 or value > 8 * 1024 * 1024:
        raise ArtifactError(
            "ARTIFACT_UPLOAD_CHUNK_BYTES must be between 65536 and 8388608"
        )
    return value


def _normalize_upload_id(upload_id: str) -> str:
    value = upload_id.strip().casefold()
    if not value.startswith("upload:"):
        raise ArtifactError("upload_id must use the upload:<uuid> form")
    raw = value.removeprefix("upload:")
    try:
        parsed = uuid.UUID(raw)
    except ValueError as exc:
        raise ArtifactError("upload_id contains an invalid UUID") from exc
    return f"upload:{parsed}"


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ArtifactError("name must not be empty")
    if len(value) > 255:
        raise ArtifactError("name must not exceed 255 characters")
    if "/" in value or "\\" in value or any(ord(ch) < 32 for ch in value):
        raise ArtifactError("name must be a plain file name without path separators")
    return value


def _validate_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if not digest:
        return ""
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ArtifactError("expected_sha256 must be a 64-character hexadecimal digest")
    return digest


class ArtifactUploadManager:
    def __init__(self, store: ArtifactStore | None = None) -> None:
        self.store = store or ArtifactStore()
        self.directory = self.store.root / "uploads"
        self.database = self.store.root / "uploads.sqlite3"

    def ensure(self) -> None:
        self.store.ensure()
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS upload_sessions (
                    upload_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    expected_size INTEGER NOT NULL,
                    expected_sha256 TEXT NOT NULL,
                    bytes_received INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_upload_updated_at
                    ON upload_sessions(updated_at);
                """
            )

    @contextmanager
    def _connect(self):
        self.store.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _part_path(self, upload_id: str) -> Path:
        normalized = _normalize_upload_id(upload_id)
        raw = normalized.removeprefix("upload:")
        return self.directory / f"{raw}.part"

    def _row(self, upload_id: str) -> sqlite3.Row:
        normalized = _normalize_upload_id(upload_id)
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ArtifactError("upload session does not exist")
        return row

    def begin(
        self,
        name: str,
        size_bytes: int,
        mime_type: str = "",
        expected_sha256: str = "",
    ) -> dict[str, Any]:
        self.ensure()
        clean_name = _validate_name(name)
        if size_bytes < 0 or size_bytes > upload_max_bytes():
            raise ArtifactError(
                f"size_bytes must be between 0 and {upload_max_bytes()}"
            )
        expected = _validate_sha256(expected_sha256)
        upload_id = f"upload:{uuid.uuid4()}"
        now = _now()
        part = self._part_path(upload_id)
        part.touch(exist_ok=False)
        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO upload_sessions (
                        upload_id,
                        name,
                        mime_type,
                        expected_size,
                        expected_sha256,
                        bytes_received,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        upload_id,
                        clean_name,
                        mime_type.strip(),
                        size_bytes,
                        expected,
                        now,
                        now,
                    ),
                )
        except Exception:
            with suppress(FileNotFoundError):
                part.unlink()
            raise
        return self.status(upload_id)

    def status(self, upload_id: str) -> dict[str, Any]:
        row = self._row(upload_id)
        part = self._part_path(str(row["upload_id"]))
        file_size = part.stat().st_size if part.exists() else -1
        received = int(row["bytes_received"])
        expected = int(row["expected_size"])
        if file_size != received:
            raise ArtifactError("upload session metadata does not match staged bytes")
        return {
            "upload_id": str(row["upload_id"]),
            "name": str(row["name"]),
            "mime_type": str(row["mime_type"]),
            "expected_size": expected,
            "expected_sha256": str(row["expected_sha256"]),
            "bytes_received": received,
            "next_offset": received,
            "remaining_bytes": expected - received,
            "complete": received == expected,
            "chunk_bytes": upload_chunk_bytes(),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def write(
        self,
        upload_id: str,
        offset: int,
        data_base64: str,
    ) -> dict[str, Any]:
        normalized = _normalize_upload_id(upload_id)
        if offset < 0:
            raise ArtifactError("offset must be non-negative")
        try:
            payload = base64.b64decode(data_base64, validate=True)
        except Exception as exc:
            raise ArtifactError("data_base64 is not valid base64") from exc
        if not payload:
            raise ArtifactError("upload chunk must not be empty")
        chunk_limit = upload_chunk_bytes()
        if len(payload) > chunk_limit:
            raise ArtifactError(f"decoded chunk exceeds {chunk_limit} bytes")

        self.ensure()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise ArtifactError("upload session does not exist")

            current = int(row["bytes_received"])
            expected = int(row["expected_size"])
            if offset != current:
                raise ArtifactError(
                    f"offset mismatch: expected {current}, received {offset}"
                )
            if current + len(payload) > expected:
                raise ArtifactError("chunk exceeds declared upload size")

            part = self._part_path(normalized)
            if not part.is_file() or part.stat().st_size != current:
                raise ArtifactError("upload session staged bytes are inconsistent")
            with part.open("ab") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            next_offset = current + len(payload)
            db.execute(
                """
                UPDATE upload_sessions
                SET bytes_received = ?, updated_at = ?
                WHERE upload_id = ?
                """,
                (next_offset, _now(), normalized),
            )

        return self.status(normalized)

    def finish(self, upload_id: str) -> dict[str, Any]:
        normalized = _normalize_upload_id(upload_id)
        row = self._row(normalized)
        part = self._part_path(normalized)
        if not part.is_file():
            raise ArtifactError("upload staged bytes are missing")

        expected_size = int(row["expected_size"])
        received = int(row["bytes_received"])
        actual_size = part.stat().st_size
        if received != expected_size or actual_size != expected_size:
            raise ArtifactError(
                f"upload is incomplete: received {received} of {expected_size} bytes"
            )

        digest = hashlib.sha256()
        with part.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_sha256 = digest.hexdigest()
        expected_sha256 = str(row["expected_sha256"])
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise ArtifactError(
                "upload SHA-256 mismatch: "
                f"expected {expected_sha256}, found {actual_sha256}"
            )

        artifact = self.store.put_file(
            part,
            name=str(row["name"]),
            mime_type=str(row["mime_type"]),
            source="agent-upload",
            consume=True,
        )
        if str(artifact["sha256"]) != actual_sha256:
            raise ArtifactError("artifact store returned an unexpected SHA-256")

        with self._connect() as db:
            db.execute(
                "DELETE FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            )

        return {
            "upload_id": normalized,
            "artifact": artifact,
            "completed": True,
        }

    def cancel(self, upload_id: str) -> dict[str, Any]:
        normalized = _normalize_upload_id(upload_id)
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                "SELECT bytes_received FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                return {"upload_id": normalized, "already_absent": True}
            bytes_received = int(row["bytes_received"])
            db.execute(
                "DELETE FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            )
        with suppress(FileNotFoundError):
            self._part_path(normalized).unlink()
        return {
            "upload_id": normalized,
            "cancelled": True,
            "discarded_bytes": bytes_received,
        }

    def list(self, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        if offset < 0:
            raise ArtifactError("offset must be non-negative")
        if limit <= 0 or limit > 1000:
            raise ArtifactError("limit must be between 1 and 1000")
        self.ensure()
        with self._connect() as db:
            total = int(
                db.execute("SELECT COUNT(*) FROM upload_sessions").fetchone()[0]
            )
            rows = db.execute(
                """
                SELECT *
                FROM upload_sessions
                ORDER BY updated_at DESC, upload_id
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        items = []
        for row in rows:
            received = int(row["bytes_received"])
            expected = int(row["expected_size"])
            items.append(
                {
                    "upload_id": str(row["upload_id"]),
                    "name": str(row["name"]),
                    "mime_type": str(row["mime_type"]),
                    "expected_size": expected,
                    "bytes_received": received,
                    "remaining_bytes": expected - received,
                    "complete": received == expected,
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
            )
        return {
            "items": items,
            "offset": offset,
            "limit": limit,
            "total": total,
            "truncated": offset + len(items) < total,
        }

    def gc(
        self,
        max_age_hours: int = 24,
        dry_run: bool = True,
        limit: int = 1000,
    ) -> dict[str, Any]:
        if max_age_hours <= 0 or max_age_hours > 24 * 365:
            raise ArtifactError("max_age_hours must be between 1 and 8760")
        if limit <= 0 or limit > 10_000:
            raise ArtifactError("limit must be between 1 and 10000")
        self.ensure()
        cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT upload_id, bytes_received, updated_at
                FROM upload_sessions
                WHERE updated_at <= ?
                ORDER BY updated_at
                LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()
        candidates = [
            {
                "upload_id": str(row["upload_id"]),
                "bytes_received": int(row["bytes_received"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
        if dry_run:
            return {
                "dry_run": True,
                "max_age_hours": max_age_hours,
                "candidates": candidates,
                "count": len(candidates),
            }

        deleted = []
        for item in candidates:
            upload_id = str(item["upload_id"])
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    """
                    SELECT updated_at, bytes_received
                    FROM upload_sessions
                    WHERE upload_id = ?
                    """,
                    (upload_id,),
                ).fetchone()
                if row is None or str(row["updated_at"]) > cutoff:
                    continue
                bytes_received = int(row["bytes_received"])
                db.execute(
                    "DELETE FROM upload_sessions WHERE upload_id = ?",
                    (upload_id,),
                )
            with suppress(FileNotFoundError):
                self._part_path(upload_id).unlink()
            deleted.append(
                {
                    "upload_id": upload_id,
                    "discarded_bytes": bytes_received,
                }
            )

        return {
            "dry_run": False,
            "max_age_hours": max_age_hours,
            "deleted": deleted,
            "count": len(deleted),
        }

    def active_count(self) -> int:
        self.ensure()
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM upload_sessions").fetchone()[0])
