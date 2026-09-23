from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import socket
import sqlite3
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from .file_store import FileError, FileStore, upload_max_bytes

_DEFAULT_CHUNK_BYTES = 1024 * 1024


class ClientFile(TypedDict):
    """ChatGPT/OpenAI file parameter payload."""

    download_url: str
    file_id: NotRequired[str]
    mime_type: NotRequired[str]
    file_name: NotRequired[str]


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


def _normalize_upload_id(upload_id: str) -> str:
    value = upload_id.strip().casefold()
    if not value.startswith("upload:"):
        raise FileError("upload_id must use the upload:<uuid> form")
    raw = value.removeprefix("upload:")
    try:
        parsed = uuid.UUID(raw)
    except ValueError as exc:
        raise FileError("upload_id contains an invalid UUID") from exc
    return f"upload:{parsed}"


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise FileError("name must not be empty")
    if len(value) > 255:
        raise FileError("name must not exceed 255 characters")
    if "/" in value or "\\" in value or any(ord(ch) < 32 for ch in value):
        raise FileError("name must be a plain file name without path separators")
    return value


def _validate_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if not digest:
        return ""
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise FileError("expected_sha256 must be a 64-character hexadecimal digest")
    return digest


def _validate_remote_file_url(file: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(file.strip())
    if parsed.scheme.casefold() != "https":
        raise FileError(
            "file must resolve to an HTTPS attachment URL; pass the client attachment/file "
            "argument directly instead of base64 or a server filesystem path"
        )
    if not parsed.hostname:
        raise FileError("attachment URL has no hostname")
    if parsed.username or parsed.password:
        raise FileError("attachment URL must not contain userinfo")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise FileError("attachment hostname cannot be resolved") from exc
    if not addresses:
        raise FileError("attachment hostname cannot be resolved")

    for item in addresses:
        raw_ip = str(item[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise FileError("attachment hostname resolved to an invalid address") from exc
        if not address.is_global:
            raise FileError("attachment URL resolves to a non-public address")
    return parsed


class _AttachmentRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        _validate_remote_file_url(str(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_remote_file(request: urllib.request.Request):
    opener = urllib.request.build_opener(_AttachmentRedirectHandler())
    return opener.open(request, timeout=60)


def _attachment_name(parsed: urllib.parse.SplitResult, requested_name: str) -> str:
    if requested_name.strip():
        return _validate_name(requested_name)
    candidate = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1]).strip()
    return _validate_name(candidate or "attachment.bin")


def ingest_file(
    file: ClientFile,
    name: str = "",
    mime_type: str = "",
    expected_size: int | None = None,
    expected_sha256: str = "",
) -> dict[str, Any]:
    """Stream one client-authorized attachment directly into canonical file storage."""
    store = FileStore()
    store.ensure()

    download_url = str(file.get("download_url", "")).strip()
    if not download_url:
        raise FileError("file.download_url is required")
    parsed = _validate_remote_file_url(download_url)

    file_name = str(file.get("file_name", "")).strip()
    clean_name = _attachment_name(parsed, name or file_name)
    expected_digest = _validate_sha256(expected_sha256)

    if (
        expected_size is not None
        and (expected_size < 0 or expected_size > upload_max_bytes())
    ):
        raise FileError(
            f"expected_size must be between 0 and {upload_max_bytes()}"
        )

    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "koba-mcp-bridge/0.1 file-ingress"},
    )
    temporary = store.tmp / f"attachment-{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    total = 0
    detected_mime = mime_type.strip() or str(file.get("mime_type", "")).strip()

    try:
        try:
            response = _open_remote_file(request)
        except Exception as exc:
            if isinstance(exc, FileError):
                raise
            raise FileError(
                f"attachment download failed: {type(exc).__name__}"
            ) from exc

        with response:
            final_url = str(response.geturl())
            _validate_remote_file_url(final_url)

            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise FileError("attachment returned invalid Content-Length") from exc
                if declared_size < 0:
                    raise FileError("attachment returned invalid Content-Length")
                if declared_size > upload_max_bytes():
                    raise FileError("attachment exceeds FILE_UPLOAD_MAX_BYTES")
                if expected_size is not None and declared_size != expected_size:
                    raise FileError(
                        "attachment Content-Length does not match expected_size"
                    )

            if not detected_mime:
                detected_mime = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                )

            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > upload_max_bytes():
                        raise FileError("attachment exceeds FILE_UPLOAD_MAX_BYTES")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        actual_digest = digest.hexdigest()
        if expected_size is not None and total != expected_size:
            raise FileError(
                f"attachment size mismatch: expected {expected_size}, received {total}"
            )
        if expected_digest and actual_digest != expected_digest:
            raise FileError(
                "attachment SHA-256 mismatch: "
                f"expected {expected_digest}, found {actual_digest}"
            )

        file = store.put_file(
            temporary,
            name=clean_name,
            mime_type=detected_mime,
            source="attachment-ingress",
            consume=True,
        )
        if str(file["sha256"]) != actual_digest:
            raise FileError("file store returned an unexpected SHA-256")
        return {
            "file": file,
            "completed": True,
            "transport": "client-file",
        }
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


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
    def _connect(self):
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
            raise FileError("upload session does not exist")
        return row

    def _public_status(self, row: sqlite3.Row) -> dict[str, Any]:
        expected = int(row["expected_size"])
        received = int(row["bytes_received"])
        state = str(row["state"])
        file_id = str(row["file_id"])
        return {
            "upload_id": str(row["upload_id"]),
            "name": str(row["name"]),
            "mime_type": str(row["mime_type"]),
            "expected_size": expected,
            "expected_sha256": str(row["expected_sha256"]),
            "bytes_received": received,
            "next_offset": received,
            "remaining_bytes": max(0, expected - received),
            "complete": received == expected,
            "committed": state == "completed",
            "file_id": file_id or None,
            "chunk_bytes": upload_chunk_bytes(),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "completed_at": str(row["completed_at"]) or None,
        }

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
    ) -> dict[str, Any]:
        self.ensure()
        clean_name = _validate_name(name)
        if size_bytes < 0 or size_bytes > upload_max_bytes():
            raise FileError(
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

    def status(self, upload_id: str) -> dict[str, Any]:
        normalized = _normalize_upload_id(upload_id)
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
    ) -> dict[str, Any]:
        if offset < 0:
            raise FileError("offset must be non-negative")
        if limit <= 0 or limit > 1000:
            raise FileError("limit must be between 1 and 1000")
        clean_state = state.strip().casefold()
        if clean_state not in {"", "open", "completed"}:
            raise FileError("state must be empty, open, or completed")

        self.ensure()
        where = ""
        params: list[Any] = []
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

        return {
            "sessions": [self._public_status(row) for row in rows],
            "offset": offset,
            "limit": limit,
            "total": total,
            "truncated": offset + len(rows) < total,
        }

    def write(
        self,
        upload_id: str,
        offset: int,
        data_base64: str,
    ) -> dict[str, Any]:
        normalized = _normalize_upload_id(upload_id)
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

    def finish(self, upload_id: str) -> dict[str, Any]:
        normalized = _normalize_upload_id(upload_id)
        current = self.status(normalized)
        if current["committed"]:
            file_id = str(current["file_id"])
            with suppress(FileNotFoundError):
                self._part_path(normalized).unlink()
            return {
                "upload_id": normalized,
                "file": self.store.info(file_id),
                "completed": True,
                "already_committed": True,
            }
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

        return {
            "upload_id": normalized,
            "file": file,
            "completed": True,
            "already_committed": False,
        }

    def cancel(self, upload_id: str) -> dict[str, Any]:
        normalized = _normalize_upload_id(upload_id)
        self.ensure()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM upload_sessions WHERE upload_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                return {"upload_id": normalized, "already_absent": True}
            if str(row["state"]) == "completed":
                return {
                    "upload_id": normalized,
                    "already_committed": True,
                    "file_id": str(row["file_id"]),
                }
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

    def cleanup(
        self,
        older_than_hours: int = 24,
        dry_run: bool = True,
        limit: int = 1000,
    ) -> dict[str, Any]:
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

        sessions = [
            {
                "upload_id": str(row["upload_id"]),
                "state": str(row["state"]),
                "bytes_received": int(row["bytes_received"]),
                "file_id": str(row["file_id"]) or None,
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
        if dry_run:
            return {
                "dry_run": True,
                "older_than_hours": older_than_hours,
                "sessions": sessions,
                "count": len(sessions),
            }

        removed: list[dict[str, Any]] = []
        for item in sessions:
            upload_id = str(item["upload_id"])
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

        return {
            "dry_run": False,
            "older_than_hours": older_than_hours,
            "removed": removed,
            "count": len(removed),
        }

    def active_count(self) -> int:
        self.ensure()
        with self._connect() as db:
            return int(
                db.execute(
                    "SELECT COUNT(*) FROM upload_sessions WHERE state = 'open'"
                ).fetchone()[0]
            )
