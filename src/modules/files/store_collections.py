from __future__ import annotations

import builtins
import hashlib
import json
import stat
import tarfile
import zipfile

from common.models import JsonObject

from .file_primitives import (
    FileError,
    max_extract_bytes,
    max_extract_files,
    now_iso,
    safe_collection_path,
)
from .models import (
    CollectionDeleteResponse,
    CollectionExtractResponse,
    CollectionItem,
    CollectionListResponse,
    CollectionResolveResponse,
    FileInfo,
)
from .store_references import FileReferenceStore


class FileCollectionStore(FileReferenceStore):
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
                zip_regular = [member for member in zip_members if not member.is_dir()]
                if len(zip_regular) > file_limit:
                    raise FileError("archive exceeds configured file-count limit")
                for zip_member in zip_regular:
                    mode = (zip_member.external_attr >> 16) & 0o170000
                    if mode and not stat.S_ISREG(mode):
                        raise FileError(
                            f"unsupported archive member type: {zip_member.filename}"
                        )
                    path = safe_collection_path(zip_member.filename)
                    total_bytes += int(zip_member.file_size)
                    if total_bytes > byte_limit:
                        raise FileError("archive exceeds configured extraction size limit")
                    with archive.open(zip_member, "r") as zip_stream:
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
                tar_regular = [member for member in tar_members if member.isfile()]
                for tar_member in tar_members:
                    if tar_member.isdir() or tar_member.isfile():
                        continue
                    raise FileError(f"unsupported archive member type: {tar_member.name}")
                if len(tar_regular) > file_limit:
                    raise FileError("archive exceeds configured file-count limit")
                for tar_member in tar_regular:
                    path = safe_collection_path(tar_member.name)
                    total_bytes += int(tar_member.size)
                    if total_bytes > byte_limit:
                        raise FileError("archive exceeds configured extraction size limit")
                    tar_stream = archive.extractfile(tar_member)
                    if tar_stream is None:
                        raise FileError(f"unable to read archive member: {tar_member.name}")
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
                (collection_id, source.file_id, now_iso()),
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
        params: list[str | int] = [collection_id]
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
        safe = safe_collection_path(path)
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
