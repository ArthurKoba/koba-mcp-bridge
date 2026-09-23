from __future__ import annotations

import base64
import builtins
import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO

from common.models import JsonObject

from .models import (
    CollectionDeleteResponse,
    CollectionExtractResponse,
    CollectionItem,
    CollectionListResponse,
    CollectionResolveResponse,
    FileAlias,
    FileCollectionMembership,
    FileDeleteResponse,
    FileGcResponse,
    FileInfo,
    FileListItem,
    FileListResponse,
    FileReadResponse,
    FileReference,
    FileReferenceReleaseResponse,
    FileStoreStatus,
)

_DEFAULT_ROOT = "/files"
_DEFAULT_READ_CHUNK = 1024 * 1024
_DEFAULT_MAX_EXTRACT_FILES = 20_000
_DEFAULT_MAX_EXTRACT_BYTES = 16 * 1024 * 1024 * 1024


class FileError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _root() -> Path:
    value = os.getenv("FILE_ROOT", _DEFAULT_ROOT).strip() or _DEFAULT_ROOT
    root = Path(value)
    if not root.is_absolute():
        raise FileError("FILE_ROOT must be absolute")
    return root.resolve(strict=False)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise FileError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise FileError(f"{name} must be between {minimum} and {maximum}")
    return value


def upload_max_bytes() -> int:
    return _env_int(
        "FILE_UPLOAD_MAX_BYTES",
        8 * 1024 * 1024 * 1024,
        1024 * 1024,
        64 * 1024 * 1024 * 1024,
    )


def max_extract_files() -> int:
    return _env_int(
        "FILE_MAX_EXTRACT_FILES",
        _DEFAULT_MAX_EXTRACT_FILES,
        1,
        100_000,
    )


def max_extract_bytes() -> int:
    return _env_int(
        "FILE_MAX_EXTRACT_BYTES",
        _DEFAULT_MAX_EXTRACT_BYTES,
        1024 * 1024,
        128 * 1024 * 1024 * 1024,
    )


def _normalize_file_id(file_id: str) -> tuple[str, str]:
    value = file_id.strip().casefold()
    if not value.startswith("sha256:"):
        raise FileError("file_id must use the sha256:<digest> form")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise FileError("file_id contains an invalid SHA-256 digest")
    return value, digest


def _safe_collection_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise FileError(f"unsafe archive path: {path}")
    cleaned = PurePosixPath(*(part for part in candidate.parts if part not in {"", "."}))
    if not cleaned.parts:
        raise FileError("archive member path is empty")
    return cleaned.as_posix()


def _guess_mime(name: str, supplied: str = "") -> str:
    if supplied.strip():
        return supplied.strip()
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def _size_display(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class FileStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or _root()).resolve(strict=False)
        self.objects = self.root / "objects" / "sha256"
        self.tmp = self.root / "tmp"
        self.database = self.root / "files.sqlite3"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects.mkdir(parents=True, exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS aliases (
                    file_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (file_id, name, source),
                    FOREIGN KEY (file_id) REFERENCES files(file_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS collections (
                    collection_id TEXT PRIMARY KEY,
                    source_file_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_file_id) REFERENCES files(file_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS collection_items (
                    collection_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    PRIMARY KEY (collection_id, path),
                    FOREIGN KEY (collection_id) REFERENCES collections(collection_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (file_id) REFERENCES files(file_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS file_refs (
                    file_id TEXT NOT NULL,
                    consumer_type TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (file_id, consumer_type, consumer_id, role),
                    FOREIGN KEY (file_id) REFERENCES files(file_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_alias_name ON aliases(name);
                CREATE INDEX IF NOT EXISTS idx_ref_consumer
                    ON file_refs(consumer_type, consumer_id);
                CREATE INDEX IF NOT EXISTS idx_collection_file
                    ON collection_items(file_id);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()
        finally:
            db.close()

    def _object_path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest

    def path_for(self, file_id: str) -> Path:
        _, digest = _normalize_file_id(file_id)
        target = self._object_path(digest)
        if not target.is_file():
            raise FileError("file bytes are missing from object storage")
        return target

    def _register(
        self,
        digest: str,
        name: str,
        mime_type: str,
        size_bytes: int,
        source: str,
    ) -> JsonObject:
        file_id = f"sha256:{digest}"
        created_at = _now()
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO files
                    (file_id, sha256, name, mime_type, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (file_id, digest, name, mime_type, size_bytes, created_at),
            )
            db.execute(
                """
                INSERT OR IGNORE INTO aliases
                    (file_id, name, source, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (file_id, name, source, created_at),
            )
        return self.info(file_id)

    def put_bytes(
        self,
        data: bytes,
        name: str,
        mime_type: str = "",
        source: str = "upload",
    ) -> JsonObject:
        self.ensure()
        if len(data) > upload_max_bytes():
            raise FileError("file exceeds FILE_UPLOAD_MAX_BYTES")
        digest = hashlib.sha256(data).hexdigest()
        target = self._object_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd, temporary = tempfile.mkstemp(prefix="upload-", dir=self.tmp)
            temp_path = Path(temporary)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, target)
            finally:
                if temp_path.exists():
                    temp_path.unlink()
        return self._register(
            digest,
            name=name,
            mime_type=_guess_mime(name, mime_type),
            size_bytes=len(data),
            source=source,
        )

    def put_stream(
        self,
        source_stream: IO[bytes],
        name: str,
        mime_type: str = "",
        source: str = "generated",
        max_bytes: int | None = None,
    ) -> JsonObject:
        self.ensure()
        limit = max_bytes or upload_max_bytes()
        digest = hashlib.sha256()
        total = 0
        fd, temporary = tempfile.mkstemp(prefix="stream-", dir=self.tmp)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as handle:
                while True:
                    chunk = source_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise FileError("stream exceeds configured size limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

            hexdigest = digest.hexdigest()
            target = self._object_path(hexdigest)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                temp_path.unlink()
            else:
                os.replace(temp_path, target)
            return self._register(
                hexdigest,
                name=name,
                mime_type=_guess_mime(name, mime_type),
                size_bytes=total,
                source=source,
            )
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def put_file(
        self,
        path: Path,
        name: str | None = None,
        mime_type: str = "",
        source: str = "generated",
        consume: bool = False,
    ) -> JsonObject:
        self.ensure()
        if not path.is_file():
            raise FileError("source file does not exist")
        size = path.stat().st_size
        if size > upload_max_bytes():
            raise FileError("file exceeds FILE_UPLOAD_MAX_BYTES")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        hexdigest = digest.hexdigest()
        target = self._object_path(hexdigest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            if consume:
                os.replace(path, target)
            else:
                temporary = self.tmp / f"copy-{uuid.uuid4().hex}"
                shutil.copyfile(path, temporary)
                os.replace(temporary, target)
        elif consume:
            path.unlink()
        return self._register(
            hexdigest,
            name=name or path.name,
            mime_type=_guess_mime(name or path.name, mime_type),
            size_bytes=size,
            source=source,
        )

    def info(self, file_id: str) -> JsonObject:
        normalized, _ = _normalize_file_id(file_id)
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM files WHERE file_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise FileError("file does not exist")
            aliases = [
                FileAlias(
                    name=str(item["name"]),
                    source=str(item["source"]),
                    created_at=str(item["created_at"]),
                )
                for item in db.execute(
                    """
                    SELECT name, source, created_at
                    FROM aliases
                    WHERE file_id = ?
                    ORDER BY created_at DESC
                    """,
                    (normalized,),
                ).fetchall()
            ]
            refs = [
                FileReference(
                    consumer_type=str(item["consumer_type"]),
                    consumer_id=str(item["consumer_id"]),
                    role=str(item["role"]),
                    created_at=str(item["created_at"]),
                )
                for item in db.execute(
                    """
                    SELECT consumer_type, consumer_id, role, created_at
                    FROM file_refs
                    WHERE file_id = ?
                    ORDER BY consumer_type, consumer_id, role
                    """,
                    (normalized,),
                ).fetchall()
            ]
            collections = [
                FileCollectionMembership(
                    collection_id=str(item["collection_id"]),
                    path=str(item["path"]),
                )
                for item in db.execute(
                    """
                    SELECT collection_id, path
                    FROM collection_items
                    WHERE file_id = ?
                    ORDER BY collection_id, path
                    """,
                    (normalized,),
                ).fetchall()
            ]
        return FileInfo(
            file_id=str(row["file_id"]),
            sha256=str(row["sha256"]),
            name=str(row["name"]),
            mime_type=str(row["mime_type"]),
            size_bytes=int(row["size_bytes"]),
            created_at=str(row["created_at"]),
            aliases=aliases,
            references=refs,
            collections=collections,
            size_display=_size_display(int(row["size_bytes"])),
            present=self.path_for(normalized).is_file(),
        ).to_json()

    def list(self, query: str = "", offset: int = 0, limit: int = 100) -> JsonObject:
        if offset < 0:
            raise FileError("offset must be non-negative")
        if limit <= 0 or limit > 1000:
            raise FileError("limit must be between 1 and 1000")
        self.ensure()
        params: list[object] = []
        where = ""
        if query.strip():
            where = """
                WHERE a.file_id LIKE ?
                   OR a.name LIKE ?
                   OR EXISTS (
                       SELECT 1 FROM aliases x
                       WHERE x.file_id = a.file_id AND x.name LIKE ?
                   )
            """
            pattern = f"%{query.strip()}%"
            params.extend([pattern, pattern, pattern])
        with self._connect() as db:
            total = int(
                db.execute(
                    f"SELECT COUNT(*) FROM files a {where}",
                    params,
                ).fetchone()[0]
            )
            rows = db.execute(
                f"""
                SELECT a.*,
                       (SELECT COUNT(*) FROM file_refs r
                        WHERE r.file_id = a.file_id) AS reference_count
                FROM files a
                {where}
                ORDER BY a.created_at DESC, a.file_id
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        items = [
            FileListItem(
                file_id=str(row["file_id"]),
                sha256=str(row["sha256"]),
                name=str(row["name"]),
                mime_type=str(row["mime_type"]),
                size_bytes=int(row["size_bytes"]),
                created_at=str(row["created_at"]),
                reference_count=int(row["reference_count"]),
                size_display=_size_display(int(row["size_bytes"])),
            )
            for row in rows
        ]
        return FileListResponse(
            items=items,
            offset=offset,
            limit=limit,
            total=total,
            truncated=offset + len(items) < total,
        ).to_json()

    def find_by_name(self, name: str) -> JsonObject:
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT a.file_id
                FROM aliases x
                JOIN files a ON a.file_id = x.file_id
                WHERE x.name = ?
                ORDER BY x.created_at DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        if row is None:
            raise FileError(f"file name not found: {name}")
        return self.info(str(row["file_id"]))

    def read(
        self,
        file_id: str,
        offset: int = 0,
        length: int = _DEFAULT_READ_CHUNK,
    ) -> JsonObject:
        if offset < 0:
            raise FileError("offset must be non-negative")
        if length <= 0 or length > 16 * 1024 * 1024:
            raise FileError("length must be between 1 and 16777216")
        info = FileInfo.model_validate(self.info(file_id))
        path = self.path_for(file_id)
        size = info.size_bytes
        if offset > size:
            raise FileError("offset exceeds file size")
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
        next_offset = offset + len(data)
        return FileReadResponse(
            file_id=info.file_id,
            offset=offset,
            bytes_read=len(data),
            next_offset=next_offset,
            size_bytes=size,
            eof=next_offset >= size,
            data_base64=base64.b64encode(data).decode("ascii"),
        ).to_json()

    def put_text(
        self,
        name: str,
        content: str,
        mime_type: str = "text/plain; charset=utf-8",
    ) -> JsonObject:
        return self.put_bytes(
            content.encode("utf-8"),
            name=name,
            mime_type=mime_type,
            source="generated-text",
        )

    def add_reference(
        self,
        file_id: str,
        consumer_type: str,
        consumer_id: str,
        role: str = "source",
    ) -> JsonObject:
        normalized, _ = _normalize_file_id(file_id)
        self.info(normalized)
        if not consumer_type.strip() or not consumer_id.strip() or not role.strip():
            raise FileError("reference fields must not be empty")
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO file_refs
                    (file_id, consumer_type, consumer_id, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    consumer_type.strip(),
                    consumer_id.strip(),
                    role.strip(),
                    _now(),
                ),
            )
        return self.info(normalized)

    def release_reference(
        self,
        file_id: str,
        consumer_type: str,
        consumer_id: str,
        role: str = "source",
    ) -> JsonObject:
        normalized, _ = _normalize_file_id(file_id)
        self.info(normalized)
        with self._connect() as db:
            cursor = db.execute(
                """
                DELETE FROM file_refs
                WHERE file_id = ?
                  AND consumer_type = ?
                  AND consumer_id = ?
                  AND role = ?
                """,
                (normalized, consumer_type, consumer_id, role),
            )
        return FileReferenceReleaseResponse(
            file_id=normalized,
            released=cursor.rowcount > 0,
        ).to_json()

    def references(
        self,
        consumer_type: str = "",
        consumer_id: str = "",
    ) -> builtins.list[JsonObject]:
        self.ensure()
        clauses = []
        params: list[object] = []
        if consumer_type.strip():
            clauses.append("consumer_type = ?")
            params.append(consumer_type.strip())
        if consumer_id.strip():
            clauses.append("consumer_id = ?")
            params.append(consumer_id.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT file_id, consumer_type, consumer_id, role, created_at
                FROM file_refs
                {where}
                ORDER BY consumer_type, consumer_id, role, file_id
                """,
                params,
            ).fetchall()
        return [
            FileReference(
                file_id=str(row["file_id"]),
                consumer_type=str(row["consumer_type"]),
                consumer_id=str(row["consumer_id"]),
                role=str(row["role"]),
                created_at=str(row["created_at"]),
            ).to_json()
            for row in rows
        ]

    def extract(self, file_id: str) -> JsonObject:
        source = FileInfo.model_validate(self.info(file_id))
        archive_path = self.path_for(file_id)
        file_limit = max_extract_files()
        byte_limit = max_extract_bytes()
        entries: builtins.list[CollectionItem] = []
        total_bytes = 0

        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path) as archive:
                zip_members = archive.infolist()
                regular = [member for member in zip_members if not member.is_dir()]
                if len(regular) > file_limit:
                    raise FileError("archive exceeds configured file-count limit")
                for member in regular:
                    mode = (member.external_attr >> 16) & 0o170000
                    if mode and not stat.S_ISREG(mode):
                        raise FileError(
                            f"unsupported archive member type: {member.filename}"
                        )
                    path = _safe_collection_path(member.filename)
                    total_bytes += int(member.file_size)
                    if total_bytes > byte_limit:
                        raise FileError("archive exceeds configured extraction size limit")
                    with archive.open(member, "r") as zip_stream:
                        stored = self.put_stream(
                            zip_stream,
                            name=path,
                            source=f"collection:{source.file_id}",
                            max_bytes=byte_limit,
                        )
                    stored_info = FileInfo.model_validate(stored)
                    entries.append(
                        CollectionItem(
                            path=path,
                            file_id=stored_info.file_id,
                            size_bytes=stored_info.size_bytes,
                        )
                    )
        elif tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, mode="r:*") as archive:
                tar_members = archive.getmembers()
                regular = [member for member in tar_members if member.isfile()]
                for member in tar_members:
                    if member.isdir() or member.isfile():
                        continue
                    raise FileError(f"unsupported archive member type: {member.name}")
                if len(regular) > file_limit:
                    raise FileError("archive exceeds configured file-count limit")
                for member in regular:
                    path = _safe_collection_path(member.name)
                    total_bytes += int(member.size)
                    if total_bytes > byte_limit:
                        raise FileError("archive exceeds configured extraction size limit")
                    tar_stream = archive.extractfile(member)
                    if tar_stream is None:
                        raise FileError(f"unable to read archive member: {member.name}")
                    with tar_stream:
                        stored = self.put_stream(
                            tar_stream,
                            name=path,
                            source=f"collection:{source.file_id}",
                            max_bytes=byte_limit,
                        )
                    stored_info = FileInfo.model_validate(stored)
                    entries.append(
                        CollectionItem(
                            path=path,
                            file_id=stored_info.file_id,
                            size_bytes=stored_info.size_bytes,
                        )
                    )
        else:
            raise FileError("file is not a supported tar or zip archive")

        manifest = json.dumps(
            sorted(
                [
                    {"path": entry.path, "file_id": entry.file_id}
                    for entry in entries
                ],
                key=lambda item: item["path"],
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        collection_identity = source.file_id.encode("utf-8") + b"\0" + manifest
        collection_id = f"collection:{hashlib.sha256(collection_identity).hexdigest()}"

        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO collections
                    (collection_id, source_file_id, created_at)
                VALUES (?, ?, ?)
                """,
                (collection_id, source.file_id, _now()),
            )
            for entry in entries:
                db.execute(
                    """
                    INSERT OR IGNORE INTO collection_items
                        (collection_id, path, file_id)
                    VALUES (?, ?, ?)
                    """,
                    (collection_id, entry.path, entry.file_id),
                )

        return CollectionExtractResponse(
            collection_id=collection_id,
            source_file_id=source.file_id,
            files=len(entries),
            total_bytes=total_bytes,
            items=entries[:100],
            items_truncated=len(entries) > 100,
        ).to_json()

    def collection_list(
        self,
        collection_id: str,
        prefix: str = "",
        offset: int = 0,
        limit: int = 200,
    ) -> JsonObject:
        if not collection_id.startswith("collection:"):
            raise FileError("invalid collection_id")
        if offset < 0 or limit <= 0 or limit > 1000:
            raise FileError("invalid collection pagination")
        self.ensure()
        where = "collection_id = ?"
        params: list[object] = [collection_id]
        if prefix.strip():
            where += " AND path LIKE ?"
            params.append(f"{prefix.strip()}%")
        with self._connect() as db:
            exists = db.execute(
                "SELECT source_file_id FROM collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if exists is None:
                raise FileError("collection does not exist")
            total = int(
                db.execute(
                    f"SELECT COUNT(*) FROM collection_items WHERE {where}",
                    params,
                ).fetchone()[0]
            )
            rows = db.execute(
                f"""
                SELECT path, file_id
                FROM collection_items
                WHERE {where}
                ORDER BY path
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return CollectionListResponse(
            collection_id=collection_id,
            source_file_id=str(exists["source_file_id"]),
            items=[
                CollectionItem(
                    path=str(row["path"]),
                    file_id=str(row["file_id"]),
                )
                for row in rows
            ],
            offset=offset,
            limit=limit,
            total=total,
            truncated=offset + len(rows) < total,
        ).to_json()

    def collection_delete(self, collection_id: str) -> JsonObject:
        if not collection_id.startswith("collection:"):
            raise FileError("invalid collection_id")
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT source_file_id
                FROM collections
                WHERE collection_id = ?
                """,
                (collection_id,),
            ).fetchone()
            if row is None:
                return CollectionDeleteResponse(
                    collection_id=collection_id,
                    already_absent=True,
                ).to_json()
            item_count = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM collection_items
                    WHERE collection_id = ?
                    """,
                    (collection_id,),
                ).fetchone()[0]
            )
            source_file_id = str(row["source_file_id"])
            db.execute(
                "DELETE FROM collection_items WHERE collection_id = ?",
                (collection_id,),
            )
            db.execute(
                "DELETE FROM collections WHERE collection_id = ?",
                (collection_id,),
            )
        return CollectionDeleteResponse(
            collection_id=collection_id,
            source_file_id=source_file_id,
            released_items=item_count,
            deleted=True,
        ).to_json()

    def collection_resolve(self, collection_id: str, path: str) -> JsonObject:
        safe = _safe_collection_path(path)
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                """
                SELECT file_id
                FROM collection_items
                WHERE collection_id = ? AND path = ?
                """,
                (collection_id, safe),
            ).fetchone()
        if row is None:
            raise FileError("collection item does not exist")
        info = FileInfo.model_validate(self.info(str(row["file_id"])))
        return CollectionResolveResponse(
            **info.model_dump(),
            collection_id=collection_id,
            collection_path=safe,
        ).to_json()

    def delete(self, file_id: str, force: bool = False) -> JsonObject:
        info = FileInfo.model_validate(self.info(file_id))
        normalized = info.file_id
        refs = info.references
        collections = info.collections
        with self._connect() as db:
            source_collections = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT collection_id
                    FROM collections
                    WHERE source_file_id = ?
                    """,
                    (normalized,),
                ).fetchall()
            ]
            blockers = {
                "references": refs,
                "collection_items": collections,
                "source_collections": source_collections,
            }
            has_blockers = any(blockers.values())
            if has_blockers and not force:
                raise FileError(
                    "file is referenced; release references or use force=true"
                )
            if force:
                db.execute(
                    "DELETE FROM file_refs WHERE file_id = ?",
                    (normalized,),
                )
                collection_ids = [
                    row["collection_id"]
                    for row in db.execute(
                        """
                        SELECT DISTINCT collection_id
                        FROM collection_items
                        WHERE file_id = ?
                        UNION
                        SELECT collection_id
                        FROM collections
                        WHERE source_file_id = ?
                        """,
                        (normalized, normalized),
                    ).fetchall()
                ]
                for collection_id in collection_ids:
                    db.execute(
                        "DELETE FROM collection_items WHERE collection_id = ?",
                        (collection_id,),
                    )
                    db.execute(
                        "DELETE FROM collections WHERE collection_id = ?",
                        (collection_id,),
                    )
            db.execute("DELETE FROM aliases WHERE file_id = ?", (normalized,))
            db.execute("DELETE FROM files WHERE file_id = ?", (normalized,))

        path = self.path_for(normalized) if self._object_path(info.sha256).exists() else None
        if path is not None and path.exists():
            path.unlink()
            with suppress(OSError):
                path.parent.rmdir()
        return FileDeleteResponse(
            file_id=normalized,
            deleted=True,
            forced=force,
        ).to_json()

    def gc(self, dry_run: bool = True, limit: int = 1000) -> JsonObject:
        if limit <= 0 or limit > 10_000:
            raise FileError("limit must be between 1 and 10000")
        self.ensure()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT a.file_id
                FROM files a
                WHERE NOT EXISTS (
                    SELECT 1 FROM file_refs r
                    WHERE r.file_id = a.file_id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM collection_items i
                    WHERE i.file_id = a.file_id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM collections c
                    WHERE c.source_file_id = a.file_id
                )
                ORDER BY a.created_at
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        candidates = [str(row["file_id"]) for row in rows]
        if dry_run:
            return FileGcResponse(
                dry_run=True,
                candidates=candidates,
                count=len(candidates),
            ).to_json()
        deleted = []
        for file_id in candidates:
            self.delete(file_id)
            deleted.append(file_id)
        return FileGcResponse(
            dry_run=False,
            deleted=deleted,
            count=len(deleted),
        ).to_json()

    def status(self) -> JsonObject:
        self.ensure()
        usage = shutil.disk_usage(self.root)
        with self._connect() as db:
            file_count = int(db.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            collection_count = int(db.execute("SELECT COUNT(*) FROM collections").fetchone()[0])
            reference_count = int(db.execute("SELECT COUNT(*) FROM file_refs").fetchone()[0])
        return FileStoreStatus(
            status="ok",
            file_count=file_count,
            collection_count=collection_count,
            reference_count=reference_count,
            upload_max_bytes=upload_max_bytes(),
            max_extract_files=max_extract_files(),
            max_extract_bytes=max_extract_bytes(),
            free_bytes=usage.free,
        ).to_json()
