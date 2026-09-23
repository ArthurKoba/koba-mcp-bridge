from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Protocol, cast

from common.models import JsonObject
from common.settings import FileSettings

from .file_primitives import (
    FileError,
    guess_mime,
    normalize_file_id,
    now_iso,
)


class _MetadataLookup(Protocol):
    def info(self, file_id: str) -> JsonObject: ...


class FileStoreCore:
    def __init__(self, settings: FileSettings) -> None:
        self.settings = settings
        self.root = settings.root.resolve(strict=False)
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
        _, digest = normalize_file_id(file_id)
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
        created_at = now_iso()
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
        return cast(_MetadataLookup, self).info(file_id)

    def put_bytes(
        self,
        data: bytes,
        name: str,
        mime_type: str = "",
        source: str = "upload",
    ) -> JsonObject:
        self.ensure()
        if len(data) > self.settings.upload_max_bytes:
            raise FileError("file exceeds the configured upload size limit")
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
            mime_type=guess_mime(name, mime_type),
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
        limit = max_bytes or self.settings.upload_max_bytes
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
                mime_type=guess_mime(name, mime_type),
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
        if size > self.settings.upload_max_bytes:
            raise FileError("file exceeds the configured upload size limit")
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
            mime_type=guess_mime(name or path.name, mime_type),
            size_bytes=size,
            source=source,
        )
