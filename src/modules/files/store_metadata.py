from __future__ import annotations

import base64

from common.models import JsonObject

from .file_primitives import (
    _DEFAULT_READ_CHUNK,
    FileError,
    normalize_file_id,
    size_display,
)
from .models import (
    FileAlias,
    FileCollectionMembership,
    FileInfo,
    FileListItem,
    FileListResponse,
    FileReadResponse,
    FileReference,
)
from .store_core import FileStoreCore


class FileMetadataStore(FileStoreCore):
    def info(self, file_id: str) -> JsonObject:
        normalized, _ = normalize_file_id(file_id)
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
            size_display=size_display(int(row["size_bytes"])),
            present=self.path_for(normalized).is_file(),
        ).to_json()

    def stats(self) -> JsonObject:
        self.ensure()
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS file_count, COALESCE(SUM(size_bytes), 0) AS total_bytes FROM files"
            ).fetchone()
            reference_count = int(
                db.execute("SELECT COUNT(*) FROM file_refs").fetchone()[0]
            )
        file_count = int(row["file_count"])
        total_bytes = int(row["total_bytes"])
        return {
            "files": file_count,
            "size_bytes": total_bytes,
            "size_display": size_display(total_bytes),
            "references": reference_count,
        }

    def list(
        self,
        query: str = "",
        offset: int = 0,
        limit: int = 100,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> JsonObject:
        if offset < 0:
            raise FileError("offset must be non-negative")
        if limit <= 0 or limit > 1000:
            raise FileError("limit must be between 1 and 1000")
        sort_columns = {
            "name": "a.name COLLATE NOCASE",
            "mime_type": "a.mime_type COLLATE NOCASE",
            "size_bytes": "a.size_bytes",
            "created_at": "a.created_at",
            "reference_count": "reference_count",
        }
        if sort_by not in sort_columns:
            raise FileError("unsupported file sort column")
        normalized_order = sort_order.casefold()
        if normalized_order not in {"asc", "desc"}:
            raise FileError("sort_order must be asc or desc")
        order_by = f"{sort_columns[sort_by]} {normalized_order.upper()}, a.file_id"
        self.ensure()
        params: list[str | int] = []
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
                ORDER BY {order_by}
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
                size_display=size_display(int(row["size_bytes"])),
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
