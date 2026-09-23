from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from common.models import JsonObject

from .file_store import FileError, FileStore, upload_max_bytes
from .models import (
    FileInfo,
    UploadAlreadyAbsentResponse,
    UploadAlreadyCommittedResponse,
    UploadCancelResponse,
    UploadCleanupItem,
    UploadCleanupPreviewResponse,
    UploadCleanupResponse,
    UploadFinishResponse,
    UploadListResponse,
    UploadStatus,
)
from .validation import normalize_upload_id, validate_file_name, validate_sha256

_DEFAULT_CHUNK_BYTES = 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat()


def upload_chunk_bytes() -> int:
    raw = os.getenv("FILE_UPLOAD_CHUNK_BYTES", str(_DEFAULT_CHUNK_BYTES)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise FileError("FILE_UPLOAD_CHUNK_BYTES must be an integer") from exc
    if value < 64 * 1024 or value > 8 * 1024 * 1024:
        raise FileError(
            "FILE_UPLOAD_CHUNK_BYTES must be between 65536 and 8388608"
        )
    return value


class FileUploadManager:
    """Durable resumable binary ingress for autonomous MCP agents."""

    def __init__(self, store: FileStore | None = None) -> None:
        self.store = store or FileStore()
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
                    state TEXT NOT NULL CHECK (state IN ('open', 'completed')),
                    file_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_upload_state_updated_at
                    ON upload_sessions(state, updated_at);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.store.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 30000")
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()
        finally:
            db.close()

    def _part_path(self, upload_id: str) -> Path:
        normalized = normalize_upload_id(upload_id)
        raw = normalized.removeprefix("upload:")
        return self.directory / f"{raw}.part"

    def _row(self, upload_id: str) -> sqlite3.Row:
        normalized = normalize_upload_id(upload_id)
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise FileError("upload session does not exist")
        return cast(sqlite3.Row, row)

    def _public_status(self, row: sqlite3.Row) -> JsonObject:
        expected = int(row["expected_size"])
        received = int(row["bytes_received"])
        state = str(row["state"])
        file_id = str(row["file_id"])
        return UploadStatus(
            upload_id=str(row["upload_id"]),
            name=str(row["name"]),
            mime_type=str(row["mime_type"]),
            expected_size=expected,
            expected_sha256=str(row["expected_sha256"]),
            bytes_received=received,
            next_offset=received,
            remaining_bytes=max(0, expected - received),
            complete=received == expected,
            committed=state == "completed",
            file_id=file_id or None,
            chunk_bytes=upload_chunk_bytes(),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=str(row["completed_at"]) or None,
        ).to_json()

    def _reconcile_open_row(
        self,
        db: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> sqlite3.Row:
        if str(row["state"]) != "open":
            return row
        upload_id = str(row["upload_id"])
        part = self._part_path(upload_id)
        if not part.is_file():
            raise FileError("upload staged bytes are missing")

        recorded = int(row["bytes_received"])
        actual = part.stat().st_size
        expected = int(row["expected_size"])
        if actual < recorded:
            raise FileError("upload staged bytes are shorter than committed metadata")
        if actual > expected:
            raise FileError("upload staged bytes exceed declared upload size")
        if actual > recorded:
            db.execute(
                """
                UPDATE upload_sessions
                SET bytes_received = ?, updated_at = ?
                WHERE upload_id = ?
                """,
                (actual, _now(), upload_id),
            )
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (upload_id,),
            ).fetchone()
            assert row is not None
        return row

    def begin(
        self,
        name: str,
        size_bytes: int,
        mime_type: str = "",
        expected_sha256: str = "",
    ) -> JsonObject:
        self.ensure()
        clean_name = validate_file_name(name)
        if size_bytes < 0 or size_bytes > upload_max_bytes():
            raise FileError(
                f"size_bytes must be between 0 and {upload_max_bytes()}"
            )
        expected = validate_sha256(expected_sha256)
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
                        state,
                        file_id,
                        created_at,
                        updated_at,
                        completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, 0, 'open', '', ?, ?, '')
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

    def status(self, upload_id: str) -> JsonObject:
        normalized = normalize_upload_id(upload_id)
        self.ensure()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise FileError("upload session does not exist")
            row = self._reconcile_open_row(db, row)
            return self._public_status(row)

    def list(
        self,
        state: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> JsonObject:
        if offset < 0:
            raise FileError("offset must be non-negative")
        if limit <= 0 or limit > 1000:
            raise FileError("limit must be between 1 and 1000")
        clean_state = state.strip().casefold()
        if clean_state not in {"", "open", "completed"}:
            raise FileError("state must be empty, open, or completed")

        self.ensure()
        where = ""
        params: list[str | int] = []
        if clean_state:
            where = "WHERE state = ?"
            params.append(clean_state)

        with self._connect() as db:
            total = int(
                db.execute(
                    f"SELECT COUNT(*) FROM upload_sessions {where}",
                    params,
                ).fetchone()[0]
            )
            rows = db.execute(
                f"""
                SELECT *
                FROM upload_sessions
                {where}
                ORDER BY updated_at DESC, upload_id
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()

        return UploadListResponse(
            sessions=[
                UploadStatus.model_validate(self._public_status(row))
                for row in rows
            ],
            offset=offset,
            limit=limit,
            total=total,
            truncated=offset + len(rows) < total,
        ).to_json()

    def write(
        self,
        upload_id: str,
        offset: int,
        data_base64: str,
    ) -> JsonObject:
        normalized = normalize_upload_id(upload_id)
        if offset < 0:
            raise FileError("offset must be non-negative")
        try:
            payload = base64.b64decode(data_base64, validate=True)
        except Exception as exc:
            raise FileError("data_base64 is not valid base64") from exc
        if not payload:
            raise FileError("upload chunk must not be empty")
        chunk_limit = upload_chunk_bytes()
        if len(payload) > chunk_limit:
            raise FileError(f"decoded chunk exceeds {chunk_limit} bytes")

        self.ensure()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise FileError("upload session does not exist")
            if str(row["state"]) != "open":
                raise FileError("upload session is already committed")
            row = self._reconcile_open_row(db, row)

            current = int(row["bytes_received"])
            expected = int(row["expected_size"])
            if offset != current:
                raise FileError(
                    f"offset mismatch: expected {current}, received {offset}"
                )
            if current + len(payload) > expected:
                raise FileError("chunk exceeds declared upload size")

            part = self._part_path(normalized)
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
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            assert row is not None
            return self._public_status(row)

    def finish(self, upload_id: str) -> JsonObject:
        normalized = normalize_upload_id(upload_id)
        current = self.status(normalized)
        if current["committed"]:
            file_id = str(current["file_id"])
            with suppress(FileNotFoundError):
                self._part_path(normalized).unlink()
            return UploadFinishResponse(
                upload_id=normalized,
                file=FileInfo.model_validate(self.store.info(file_id)),
                completed=True,
                already_committed=True,
            ).to_json()
        if not current["complete"]:
            raise FileError(
                "upload is incomplete: "
                f"received {current['bytes_received']} of {current['expected_size']} bytes"
            )

        row = self._row(normalized)
        part = self._part_path(normalized)
        if not part.is_file():
            raise FileError("upload staged bytes are missing")

        digest = hashlib.sha256()
        with part.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_sha256 = digest.hexdigest()
        expected_sha256 = str(row["expected_sha256"])
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise FileError(
                "upload SHA-256 mismatch: "
                f"expected {expected_sha256}, found {actual_sha256}"
            )

        # Copy, rather than move, before committing session metadata. If the
        # process dies between these operations, finish() can safely retry.
        file = self.store.put_file(
            part,
            name=str(row["name"]),
            mime_type=str(row["mime_type"]),
            source="agent-upload",
            consume=False,
        )
        if str(file["sha256"]) != actual_sha256:
            raise FileError("file store returned an unexpected SHA-256")

        completed_at = _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            if latest is None:
                raise FileError("upload session disappeared during commit")
            if str(latest["state"]) == "completed":
                committed_id = str(latest["file_id"])
                if committed_id != str(file["file_id"]):
                    raise FileError("upload session committed to a different file")
            else:
                latest = self._reconcile_open_row(db, latest)
                if int(latest["bytes_received"]) != int(latest["expected_size"]):
                    raise FileError("upload changed while it was being committed")
                db.execute(
                    """
                    UPDATE upload_sessions
                    SET state = 'completed',
                        file_id = ?,
                        updated_at = ?,
                        completed_at = ?
                    WHERE upload_id = ?
                    """,
                    (
                        file["file_id"],
                        completed_at,
                        completed_at,
                        normalized,
                    ),
                )

        with suppress(FileNotFoundError):
            part.unlink()

        return UploadFinishResponse(
            upload_id=normalized,
            file=FileInfo.model_validate(file),
            completed=True,
            already_committed=False,
        ).to_json()

    def cancel(self, upload_id: str) -> JsonObject:
        normalized = normalize_upload_id(upload_id)
        self.ensure()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                return UploadAlreadyAbsentResponse(
                    upload_id=normalized,
                    already_absent=True,
                ).to_json()
            if str(row["state"]) == "completed":
                return UploadAlreadyCommittedResponse(
                    upload_id=normalized,
                    already_committed=True,
                    file_id=str(row["file_id"]),
                ).to_json()
            bytes_received = int(row["bytes_received"])
            db.execute(
                "DELETE FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            )
        with suppress(FileNotFoundError):
            self._part_path(normalized).unlink()
        return UploadCancelResponse(
            upload_id=normalized,
            cancelled=True,
            discarded_bytes=bytes_received,
        ).to_json()

    def cleanup(
        self,
        older_than_hours: int = 24,
        dry_run: bool = True,
        limit: int = 1000,
    ) -> JsonObject:
        if older_than_hours < 1 or older_than_hours > 24 * 365:
            raise FileError("older_than_hours must be between 1 and 8760")
        if limit <= 0 or limit > 10_000:
            raise FileError("limit must be between 1 and 10000")

        self.ensure()
        cutoff = (datetime.now(UTC) - timedelta(hours=older_than_hours)).isoformat()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT *
                FROM upload_sessions
                WHERE updated_at < ?
                ORDER BY updated_at
                LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()

        sessions = []
        for row in rows:
            raw_state = str(row["state"])
            if raw_state not in {"open", "completed"}:
                raise FileError(f"invalid upload state: {raw_state}")
            state = cast(Literal["open", "completed"], raw_state)
            sessions.append(
                UploadCleanupItem(
                    upload_id=str(row["upload_id"]),
                    state=state,
                bytes_received=int(row["bytes_received"]),
                file_id=str(row["file_id"]) or None,
                    updated_at=str(row["updated_at"]),
                )
            )
        if dry_run:
            return UploadCleanupPreviewResponse(
                dry_run=True,
                older_than_hours=older_than_hours,
                sessions=sessions,
                count=len(sessions),
            ).to_json()

        removed: list[UploadCleanupItem] = []
        for item in sessions:
            upload_id = item.upload_id
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM upload_sessions WHERE upload_id = ?",
                    (upload_id,),
                ).fetchone()
                if row is None or str(row["updated_at"]) >= cutoff:
                    continue
                db.execute(
                    "DELETE FROM upload_sessions WHERE upload_id = ?",
                    (upload_id,),
                )
            with suppress(FileNotFoundError):
                self._part_path(upload_id).unlink()
            removed.append(item)

        return UploadCleanupResponse(
            dry_run=False,
            older_than_hours=older_than_hours,
            removed=removed,
            count=len(removed),
        ).to_json()

    def active_count(self) -> int:
        self.ensure()
        with self._connect() as db:
            return int(
                db.execute(
                    "SELECT COUNT(*) FROM upload_sessions WHERE state = 'open'"
                ).fetchone()[0]
            )
