from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from common.models import JsonObject, StrictModel

FileId = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
UploadId = Annotated[
    str,
    StringConstraints(
        pattern=r"^upload:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
CollectionId = Annotated[str, StringConstraints(pattern=r"^collection:[0-9a-f]{64}$")]


class ClientFile(StrictModel):
    download_url: str
    file_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None

    @field_validator("download_url")
    @classmethod
    def require_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("download_url must use HTTPS")
        return value


class FileAlias(StrictModel):
    name: str
    source: str
    created_at: str


class FileReference(StrictModel):
    file_id: FileId | None = None
    consumer_type: str
    consumer_id: str
    role: str
    created_at: str | None = None


class FileCollectionMembership(StrictModel):
    collection_id: CollectionId
    path: str


class FileInfo(StrictModel):
    file_id: FileId
    sha256: Sha256
    name: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    created_at: str
    aliases: list[FileAlias]
    references: list[FileReference]
    collections: list[FileCollectionMembership]
    size_display: str
    present: bool


class FileListItem(StrictModel):
    file_id: FileId
    sha256: Sha256
    name: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    created_at: str
    reference_count: int = Field(ge=0)
    size_display: str


class FileListResponse(StrictModel):
    items: list[FileListItem]
    offset: int = Field(ge=0)
    limit: int = Field(gt=0)
    total: int = Field(ge=0)
    truncated: bool


class FileReadResponse(StrictModel):
    file_id: FileId
    offset: int = Field(ge=0)
    bytes_read: int = Field(ge=0)
    next_offset: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    eof: bool
    data_base64: str


class FileReferenceListResponse(StrictModel):
    references: list[FileReference]
    count: int = Field(ge=0)


class FileReferenceReleaseResponse(StrictModel):
    file_id: FileId
    released: bool


class CollectionItem(StrictModel):
    path: str
    file_id: FileId
    size_bytes: int | None = Field(default=None, ge=0)


class CollectionExtractResponse(StrictModel):
    collection_id: CollectionId
    source_file_id: FileId
    files: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    items: list[CollectionItem]
    items_truncated: bool


class CollectionListResponse(StrictModel):
    collection_id: CollectionId
    source_file_id: FileId
    items: list[CollectionItem]
    offset: int = Field(ge=0)
    limit: int = Field(gt=0)
    total: int = Field(ge=0)
    truncated: bool


class CollectionDeleteResponse(StrictModel):
    collection_id: CollectionId
    source_file_id: FileId | None = None
    released_items: int | None = Field(default=None, ge=0)
    deleted: bool = False
    already_absent: bool = False


class CollectionResolveResponse(FileInfo):
    collection_id: CollectionId
    collection_path: str


class FileDeleteResponse(StrictModel):
    file_id: FileId
    deleted: bool
    forced: bool


class FileGcResponse(StrictModel):
    dry_run: bool
    count: int = Field(ge=0)
    candidates: list[FileId] | None = None
    deleted: list[FileId] | None = None


class FileStoreStatus(StrictModel):
    status: Literal["ok"]
    file_count: int = Field(ge=0)
    collection_count: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    upload_max_bytes: int = Field(gt=0)
    max_extract_files: int = Field(gt=0)
    max_extract_bytes: int = Field(gt=0)
    free_bytes: int = Field(ge=0)


class UploadStatus(StrictModel):
    upload_id: UploadId
    name: str
    mime_type: str
    expected_size: int = Field(ge=0)
    expected_sha256: str
    bytes_received: int = Field(ge=0)
    next_offset: int = Field(ge=0)
    remaining_bytes: int = Field(ge=0)
    complete: bool
    committed: bool
    file_id: FileId | None
    chunk_bytes: int = Field(gt=0)
    created_at: str
    updated_at: str
    completed_at: str | None


class UploadListResponse(StrictModel):
    sessions: list[UploadStatus]
    offset: int = Field(ge=0)
    limit: int = Field(gt=0)
    total: int = Field(ge=0)
    truncated: bool


class UploadFinishResponse(StrictModel):
    upload_id: UploadId
    file: FileInfo
    completed: bool
    already_committed: bool = False


class UploadCancelResponse(StrictModel):
    upload_id: UploadId
    cancelled: bool
    already_completed: bool = False


class UploadCleanupItem(StrictModel):
    upload_id: UploadId
    name: str
    state: Literal["open", "completed"]
    updated_at: str


class UploadCleanupResponse(StrictModel):
    dry_run: bool
    older_than_hours: int = Field(ge=0)
    matched: int = Field(ge=0)
    removed: list[UploadCleanupItem]
    truncated: bool


class FileToolResult(StrictModel):
    payload: JsonObject
