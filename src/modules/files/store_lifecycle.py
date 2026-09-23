from __future__ import annotations

import shutil
from contextlib import suppress

from common.models import JsonObject

from .file_primitives import FileError
from .models import FileDeleteResponse, FileGcResponse, FileInfo, FileStoreStatus
from .store_collections import FileCollectionStore


class FileLifecycleStore(FileCollectionStore):
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
            upload_max_bytes=self.settings.upload_max_bytes,
            max_extract_files=self.settings.max_extract_files,
            max_extract_bytes=self.settings.max_extract_bytes,
            free_bytes=usage.free,
        ).to_json()
