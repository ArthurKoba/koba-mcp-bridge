from __future__ import annotations

from pydantic import Field

from common.models import JsonObject, JsonValue, ProviderModel, StrictModel
from modules.files.models import FileId, FileInfo


class BackendStatus(ProviderModel):
    success: bool | None = None
    error: str | None = None


class StageBeginResponse(BackendStatus):
    stage_id: str = Field(min_length=1)
    chunk_bytes: int = Field(gt=0, le=8 * 1024 * 1024)


class StageWriteResponse(BackendStatus):
    next_offset: int = Field(ge=0)


class StageFinishResponse(BackendStatus):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class ProjectInfo(BackendStatus):
    has_project: bool
    project_name: str = Field(min_length=1)


class ImportDryRunResponse(StrictModel):
    success: bool
    dry_run: bool
    project_id: str = Field(min_length=1)
    file_id: FileId
    name: str
    project_folder: str
    language: str | None
    compiler_spec: str | None
    auto_analyze: bool


class ImportFileResponse(StrictModel):
    success: bool
    project_id: str = Field(min_length=1)
    file_id: FileId
    name: str
    project_name: str = Field(min_length=1)
    ghidra_result: JsonObject


class ProjectSource(StrictModel):
    file_id: FileId
    name: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    role: str


class ProjectSourcesResponse(StrictModel):
    project_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    sources: list[ProjectSource]
    count: int = Field(ge=0)


class ExportFileResponse(StrictModel):
    success: bool
    project_id: str = Field(min_length=1)
    file: FileInfo
    project_name: str = Field(min_length=1)
    ghidra_result: JsonValue | None
