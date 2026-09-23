from __future__ import annotations

import builtins

from common.models import JsonObject

from .file_primitives import FileError, normalize_file_id, now_iso
from .models import FileReference, FileReferenceReleaseResponse
from .store_metadata import FileMetadataStore


class FileReferenceStore(FileMetadataStore):
    def add_reference(
        self,
        file_id: str,
        consumer_type: str,
        consumer_id: str,
        role: str = "source",
    ) -> JsonObject:
        normalized, _ = normalize_file_id(file_id)
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
                    now_iso(),
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
        normalized, _ = normalize_file_id(file_id)
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
        params: list[str | int] = []
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
